"""DoH (DNS over HTTPS) resolver implementation."""
import httpx
from dnslib import DNSRecord
from .config import logger


async def resolve_doh(client: httpx.AsyncClient, data: bytes, upstream_url: str) -> tuple[bytes, int]:
    """
    Resolve DNS query via DoH.
    
    Args:
        client: The HTTP client to use for the request
        data: Raw DNS query bytes
        upstream_url: The resolved URL of the DoH provider
        
    Returns:
        Tuple of (raw_response_bytes, ttl_in_seconds)
    """
    headers = {
        "Content-Type": "application/dns-message",
        "Accept": "application/dns-message"
    }
    
    try:
        resp = await client.post(upstream_url, content=data, headers=headers, timeout=4.0)
        resp.raise_for_status()
        
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
        logger.error(f"DoH Request failed: {e}")
        return None, 0
