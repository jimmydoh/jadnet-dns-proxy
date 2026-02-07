import asyncio
import os
import time
import logging
import signal
import httpx
from dnslib import DNSRecord, DNSHeader, QTYPE

# --- Configuration ---
LISTEN_PORT = int(os.getenv('LISTEN_PORT', 5053))
LISTEN_HOST = os.getenv('LISTEN_HOST', '0.0.0.0')
DOH_UPSTREAM = os.getenv('DOH_UPSTREAM', 'https://cloudflare-dns.com/dns-query')
WORKER_COUNT = int(os.getenv('WORKER_COUNT', 10))
QUEUE_SIZE = int(os.getenv('QUEUE_SIZE', 1000))
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
CACHE_ENABLED = os.getenv('CACHE_ENABLED', 'true').lower() == 'true'

# --- Logging Setup ---
logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("async-doh")

# --- In-Memory Cache with TTL ---
class DNSCache:
    def __init__(self):
        self._cache = {}

    def get(self, key):
        if not CACHE_ENABLED: return None
        entry = self._cache.get(key)
        if entry:
            data, expiry = entry
            if time.time() < expiry:
                return data
            else:
                del self._cache[key] # Lazy cleanup
        return None

    def set(self, key, data, ttl):
        if not CACHE_ENABLED: return
        # Cap TTL to sane limits (e.g., min 60s, max 1h) to prevent thrashing
        ttl = max(60, min(ttl, 3600))
        self._cache[key] = (data, time.time() + ttl)

    def prune(self):
        """Cleanup expired keys periodically"""
        now = time.time()
        keys_to_remove = [k for k, v in self._cache.items() if now > v[1]]
        for k in keys_to_remove:
            del self._cache[k]
        if keys_to_remove:
            logger.debug(f"Pruned {len(keys_to_remove)} expired cache entries")

# --- UDP Protocol ---
class DNSProtocol(asyncio.DatagramProtocol):
    def __init__(self, queue):
        self.queue = queue
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport
        logger.info(f"UDP Server listening on {LISTEN_HOST}:{LISTEN_PORT}")

    def datagram_received(self, data, addr):
        try:
            # Non-blocking put. If queue is full, we drop packet to save memory.
            self.queue.put_nowait((data, addr, self.transport))
        except asyncio.QueueFull:
            logger.warning("Queue full! Dropping DNS packet.")

# --- Core Logic ---
async def resolve_doh(client: httpx.AsyncClient, data: bytes) -> tuple[bytes, int]:
    """
    Returns: (raw_response_bytes, ttl_in_seconds)
    """
    headers = {
        "Content-Type": "application/dns-message",
        "Accept": "application/dns-message"
    }
    
    try:
        resp = await client.post(DOH_UPSTREAM, content=data, headers=headers, timeout=4.0)
        resp.raise_for_status()
        
        # Parse response to find TTL
        parsed = DNSRecord.parse(resp.content)
        
        # Find minimum TTL in the answer section to be safe
        ttl = 300 # Default fallback
        if parsed.rr:
            # Standard Answer TTL
            ttl = min(r.ttl for r in parsed.rr)
        elif parsed.auth and len(parsed.auth) > 0:
            # Negative Caching (use SOA TTL if available per RFC 2308)
            ttl = min(r.ttl for r in parsed.auth)
            
        return resp.content, ttl
        
    except Exception as e:
        logger.error(f"DoH Request failed: {e}")
        return None, 0

async def worker(name, queue, client, cache):
    """
    Consumes packets from queue and processes them.
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
                response_bytes, ttl = await resolve_doh(client, data)
                
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
    """Runs periodically to clean up the cache"""
    while True:
        await asyncio.sleep(60)
        cache.prune()

async def main():
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
            task = asyncio.create_task(worker(f"w-{i}", queue, client, cache))
            tasks.append(task)
            
        # Start Cache Cleaner
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

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
