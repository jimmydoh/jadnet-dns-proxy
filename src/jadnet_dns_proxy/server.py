"""Main server implementation with worker pool."""
import asyncio
import signal
import time
import httpx
from dnslib import DNSRecord, QTYPE
from .bootstrap import CustomDNSTransport
from .config import logger, LISTEN_HOST, LISTEN_PORT, WORKER_COUNT, QUEUE_SIZE, DOH_UPSTREAMS, BOOTSTRAP_DNS
from .protocol import DNSProtocol
from .cache import DNSCache
from .resolver import resolve_doh
from .upstream_manager import UpstreamManager
from .global_metrics import GlobalMetrics


async def worker(name, queue, client, cache, upstream_manager, global_metrics):
    """
    Worker that consumes packets from queue and processes them.
    
    Args:
        name: Worker identifier for logging
        queue: Asyncio queue containing DNS requests
        client: HTTP client for DoH requests
        cache: DNS cache instance
        upstream_manager: Manager for upstream servers
        global_metrics: Global metrics tracker
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
                logger.debug(f"[CACHE] {qname} ({qtype}) -> {addr[0]}")
                
                # Record cache hit
                global_metrics.record_cache_hit()
            
            else:
                # 3. Fetch from DoH
                start_time = time.time()
                response_bytes, ttl = await resolve_doh(client, data, upstream_manager)
                response_time = time.time() - start_time
                
                if response_bytes:
                    transport.sendto(response_bytes, addr)
                    cache.set(cache_key, response_bytes, ttl)
                    logger.debug(f"[UPSTREAM] {qname} ({qtype}) TTL:{ttl} -> {addr[0]}")
                    
                    # Record cache miss with response time
                    global_metrics.record_cache_miss(response_time)
                
        except Exception as e:
            logger.error(f"Worker processing error: {e}")
        finally:
            # Notify the queue that the "work item" has been processed.
            queue.task_done()


async def stats_task(upstream_manager, global_metrics):
    """
    Periodically logs statistics about upstream servers and global metrics.
    
    Args:
        upstream_manager: Manager for upstream servers
        global_metrics: Global metrics tracker
    """
    while True:
        await asyncio.sleep(300)  # Log stats every 5 minutes
        upstream_manager.log_stats()
        global_metrics.log_stats()



async def cleaner_task(cache):
    """
    Runs periodically to clean up the cache.
    
    Args:
        cache: DNS cache instance
    """
    while True:
        await asyncio.sleep(60)
        cache.prune()


async def main():
    """Main server entry point."""
    # Use original upstream URLs (no URL rewriting)
    # DNS resolution will be handled by CustomDNSTransport
    logger.info(f"Initializing with upstream URLs: {DOH_UPSTREAMS}")
    
    # Create a Queue
    queue = asyncio.Queue(maxsize=QUEUE_SIZE)
    
    # Instantiate cache
    cache = DNSCache()
    
    # Initialize upstream manager with original URLs (not bootstrapped)
    upstream_manager = UpstreamManager(DOH_UPSTREAMS)
    
    # Initialize global metrics
    global_metrics = GlobalMetrics()

    # Setup Loop and Transport
    loop = asyncio.get_running_loop()
    
    # Create persistent HTTP/2 client with custom DNS transport
    # This transport performs DNS resolution while preserving hostname for SNI
    limits = httpx.Limits(max_keepalive_connections=20, max_connections=WORKER_COUNT + 5)
    transport = CustomDNSTransport(
        bootstrap_dns=BOOTSTRAP_DNS,
        http2=True,
        limits=limits
    )
    async with httpx.AsyncClient(transport=transport) as client:
        
        # Start UDP Server
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: DNSProtocol(queue),
            local_addr=(LISTEN_HOST, LISTEN_PORT)
        )

        # Start Workers
        tasks = []
        for i in range(WORKER_COUNT):
            # Pass upstream_manager and global_metrics to worker
            task = asyncio.create_task(worker(f"w-{i}", queue, client, cache, upstream_manager, global_metrics))
            tasks.append(task)
            
        # Start Cache Cleaner and pass cache
        tasks.append(asyncio.create_task(cleaner_task(cache)))
        
        # Start Stats Logger
        tasks.append(asyncio.create_task(stats_task(upstream_manager, global_metrics)))

        # Graceful Shutdown handling
        stop_event = asyncio.Event()
        def signal_handler():
            logger.info("Shutdown signal received.")
            stop_event.set()
            
        try:
            loop.add_signal_handler(signal.SIGTERM, signal_handler)
            loop.add_signal_handler(signal.SIGINT, signal_handler)
        except NotImplementedError:
            logger.warning("Signal handlers not supported on this platform. This is expected on Windows systems.")

        await stop_event.wait()
        
        logger.info("Stopping transport...")
        transport.close()
        
        logger.info("Cancelling workers...")
        for task in tasks:
            task.cancel()
            
        await asyncio.gather(*tasks, return_exceptions=True)
