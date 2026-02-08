"""Main server implementation with worker pool."""
import asyncio
import signal
import httpx
from dnslib import DNSRecord, QTYPE
from .bootstrap import get_upstream_ip
from .config import logger, LISTEN_HOST, LISTEN_PORT, WORKER_COUNT, QUEUE_SIZE, DOH_UPSTREAMS
from .protocol import DNSProtocol
from .cache import DNSCache
from .resolver import resolve_doh
from .upstream_manager import UpstreamManager


async def worker(name, queue, client, cache, upstream_manager):
    """
    Worker that consumes packets from queue and processes them.
    
    Args:
        name: Worker identifier for logging
        queue: Asyncio queue containing DNS requests
        client: HTTP client for DoH requests
        cache: DNS cache instance
        upstream_manager: Manager for upstream servers
    """
    logger.debug(f"Worker {name} started")
    while True:
        # Get a "work item" out of the queue.
        data, addr, transport = await queue.get()
        
        try:
            # 1. Parse Request
            request = DNSRecord.parse(data)
            qname = str(request.q.qname)
            qtype = QTYPE[request.q.qtype]
            qid = request.header.id
            cache_key = (qname, qtype)

            # 2. Check Cache
            cached_data = cache.get(cache_key)
            
            if cached_data:
                # We must patch the ID of the cached response to match the current request ID
                cached_record = DNSRecord.parse(cached_data)
                cached_record.header.id = qid
                response_bytes = cached_record.pack()
                
                transport.sendto(response_bytes, addr)
                logger.info(f"[CACHE] {qname} ({qtype}) -> {addr[0]}")
            
            else:
                # 3. Fetch from DoH
                response_bytes, ttl = await resolve_doh(client, data, upstream_manager)
                
                if response_bytes:
                    transport.sendto(response_bytes, addr)
                    cache.set(cache_key, response_bytes, ttl)
                    logger.info(f"[UPSTREAM] {qname} ({qtype}) TTL:{ttl} -> {addr[0]}")
                
        except Exception as e:
            logger.error(f"Worker processing error: {e}")
        finally:
            # Notify the queue that the "work item" has been processed.
            queue.task_done()


async def stats_task(upstream_manager):
    """
    Periodically logs statistics about upstream servers.
    
    Args:
        upstream_manager: Manager for upstream servers
    """
    while True:
        await asyncio.sleep(300)  # Log stats every 5 minutes
        upstream_manager.log_stats()



async def cleaner_task(cache):
    """
    Runs periodically to clean up the cache.
    
    Args:
        cache: DNS cache instance
    """
    while True:
        await asyncio.sleep(60)
        cache.prune()


async def bootstrap_retry_task(upstream_manager):
    """
    Periodically retries failed bootstrap resolutions.
    
    This task checks every 60 seconds if any bootstrap resolutions have expired.
    If a failed resolution has expired, it will retry the bootstrap process.
    If successful, it updates the upstream manager with the new resolved URL.
    
    Args:
        upstream_manager: Manager for upstream servers
    """
    while True:
        await asyncio.sleep(60)  # Check every minute
        
        # Retry bootstrap for each server using its original URL
        for server in upstream_manager.servers:
            new_url = get_upstream_ip(server.original_url, use_cache=True)
            
            # Update the URL if it changed (successful bootstrap resolution)
            if server.url != new_url and new_url != server.original_url:
                logger.info(f"Bootstrap retry succeeded: {server.original_url} -> {new_url}")
                server.url = new_url


async def main():
    """Main server entry point."""
    # Bootstrap upstream URLs (resolve hostnames to IPs to avoid DNS loops)
    logger.info("Bootstrapping upstream URLs...")
    bootstrapped_upstreams = [get_upstream_ip(url) for url in DOH_UPSTREAMS]
    logger.info(f"Using Upstreams: {bootstrapped_upstreams}")
    
    # Create a Queue
    queue = asyncio.Queue(maxsize=QUEUE_SIZE)
    
    # Instantiate cache
    cache = DNSCache()
    
    # Initialize upstream manager with bootstrapped URLs and original URLs
    upstream_manager = UpstreamManager(bootstrapped_upstreams, DOH_UPSTREAMS)

    # Setup Loop and Transport
    loop = asyncio.get_running_loop()
    
    # Create persistent HTTP/2 client
    limits = httpx.Limits(max_keepalive_connections=20, max_connections=WORKER_COUNT + 5)
    async with httpx.AsyncClient(http2=True, limits=limits) as client:
        
        # Start UDP Server
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: DNSProtocol(queue),
            local_addr=(LISTEN_HOST, LISTEN_PORT)
        )

        # Start Workers
        tasks = []
        for i in range(WORKER_COUNT):
            # Pass upstream_manager to worker
            task = asyncio.create_task(worker(f"w-{i}", queue, client, cache, upstream_manager))
            tasks.append(task)
            
        # Start Cache Cleaner and pass cache
        tasks.append(asyncio.create_task(cleaner_task(cache)))
        
        # Start Stats Logger
        tasks.append(asyncio.create_task(stats_task(upstream_manager)))
        
        # Start Bootstrap Retry Task
        tasks.append(asyncio.create_task(bootstrap_retry_task(upstream_manager)))

        # Graceful Shutdown handling
        stop_event = asyncio.Event()
        def signal_handler():
            logger.info("Shutdown signal received.")
            stop_event.set()
            
        loop.add_signal_handler(signal.SIGTERM, signal_handler)
        loop.add_signal_handler(signal.SIGINT, signal_handler)

        await stop_event.wait()
        
        logger.info("Stopping transport...")
        transport.close()
        
        logger.info("Cancelling workers...")
        for task in tasks:
            task.cancel()
            
        await asyncio.gather(*tasks, return_exceptions=True)
