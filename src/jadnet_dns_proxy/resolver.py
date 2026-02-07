"""DoH (DNS over HTTPS) resolver implementation."""
import time
import httpx
from dnslib import DNSRecord
from .config import logger
from .upstream_manager import UpstreamManager


async def resolve_doh(client: httpx.AsyncClient, data: bytes, upstream_manager: UpstreamManager) -> tuple[bytes, int]:
    """
    Resolve DNS query via DoH using the upstream manager.
    
    Args:
        client: The HTTP client to use for the request
        data: Raw DNS query bytes
        upstream_manager: Manager for upstream servers
        
    Returns:
        Tuple of (raw_response_bytes, ttl_in_seconds)
    """
    headers = {
        "Content-Type": "application/dns-message",
        "Accept": "application/dns-message"
    }
    
    # Get the next available upstream server
    upstream = await upstream_manager.get_next_server()
    if not upstream:
        logger.error("No upstream servers available")
        return None, 0
    
    start_time = time.time()
    
    try:
        resp = await client.post(upstream.url, content=data, headers=headers, timeout=4.0)
        resp.raise_for_status()
        
        # Record successful request
        response_time = time.time() - start_time
        upstream.record_success(response_time)
        
        # Parse response to find TTL
        parsed = DNSRecord.parse(resp.content)
        
        # Find minimum TTL in the answer section to be safe
        ttl = 300  # Default fallback
        if parsed.rr:
            # Standard Answer TTL
            ttl = min(r.ttl for r in parsed.rr)
        elif parsed.auth:
            # Negative Caching (use SOA TTL if available)
            ttl = min(r.ttl for r in parsed.auth)
            
        return resp.content, ttl
        
    except Exception as e:
        # Record failed request
        upstream.record_failure()
        logger.error(f"DoH Request to {upstream.url} failed: {e}")
        return None, 0

