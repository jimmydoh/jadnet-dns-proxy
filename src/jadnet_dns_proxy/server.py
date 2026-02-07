"""Main server implementation with worker pool."""
import asyncio
import signal
import httpx
from dnslib import DNSRecord, QTYPE
from .config import logger, LISTEN_HOST, LISTEN_PORT, WORKER_COUNT, QUEUE_SIZE, DOH_UPSTREAM
from .protocol import DNSProtocol
from .cache import DNSCache
from .resolver import resolve_doh
from .bootstrap import get_upstream_ip


async def worker(name, queue, client, cache, upstream_url):
    """
    Worker that consumes packets from queue and processes them.
    
    Args:
        name: Worker identifier for logging
        queue: Asyncio queue containing DNS requests
        client: HTTP client for DoH requests
        cache: DNS cache instance
        upstream_url: The resolved URL of the DoH provider
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
                response_bytes, ttl = await resolve_doh(client, data, upstream_url)
                
                if response_bytes:
                    transport.sendto(response_bytes, addr)
                    cache.set(cache_key, response_bytes, ttl)
                    logger.info(f"[UPSTREAM] {qname} ({qtype}) TTL:{ttl} -> {addr[0]}")
                
        except Exception as e:
            logger.error(f"Worker processing error: {e}")
        finally:
            # Notify the queue that the "work item" has been processed.
            queue.task_done()


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
    # 1. Run Bootstrap BEFORE starting the loop
    # This resolves the URL to an IP-based URL to avoid system resolver loops
    final_upstream_url = get_upstream_ip(DOH_UPSTREAM)
    logger.info(f"Using Upstream: {final_upstream_url}")
    
    # Create a Queue
    queue = asyncio.Queue(maxsize=QUEUE_SIZE)
    
    # Instantiate cache
    cache = DNSCache()

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
            # Pass final_upstream_url to workers
            task = asyncio.create_task(worker(f"w-{i}", queue, client, cache, final_upstream_url))
            tasks.append(task)
            
        # Start Cache Cleaner and pass cache
        tasks.append(asyncio.create_task(cleaner_task(cache)))

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
