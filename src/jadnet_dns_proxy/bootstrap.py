"""Bootstrap DNS resolution logic."""
import socket
import time
from urllib.parse import urlparse, urlunparse
from dnslib import DNSRecord, QTYPE
from .config import logger, BOOTSTRAP_DNS

# Cache for bootstrap resolutions: {hostname: (resolved_url, expiration_time, is_success)}
_bootstrap_cache = {}

# TTL for successful bootstrap resolutions (1 hour)
SUCCESS_TTL = 3600

# TTL for failed bootstrap resolutions (30 seconds - short to allow retries)
FAILURE_TTL = 30


def get_upstream_ip(upstream_url: str, use_cache: bool = True) -> str:
    """
    Resolves the hostname of the DoH upstream using the bootstrap DNS server.
    
    If the upstream is already an IP, returns it as-is.
    If it's a hostname, queries BOOTSTRAP_DNS directly via UDP.
    
    Successful resolutions are cached for 1 hour to reduce bootstrap queries.
    Failed resolutions are cached for only 30 seconds to allow quick retries
    on transient failures.
    
    Args:
        upstream_url: The DoH upstream URL (e.g., https://cloudflare-dns.com/dns-query)
        use_cache: Whether to use cached results (default: True)
        
    Returns:
        The upstream URL with hostname replaced by IP if resolution succeeded,
        otherwise returns the original URL
    """
    parsed = urlparse(upstream_url)
    hostname = parsed.hostname
    
    # 1. Check if it's already an IP
    try:
        socket.inet_aton(hostname)
        return upstream_url  # It is an IPv4
    except socket.error:
        pass  # It is a hostname
    
    # 2. Check cache if enabled
    current_time = time.time()
    if use_cache and hostname in _bootstrap_cache:
        cached_url, expiration_time, is_success = _bootstrap_cache[hostname]
        if current_time < expiration_time:
            status = "SUCCESS" if is_success else "FAILURE"
            logger.debug(f"Using cached bootstrap result for {hostname} (cached {status}, expires in {int(expiration_time - current_time)}s)")
            return cached_url
        else:
            logger.debug(f"Bootstrap cache expired for {hostname}, retrying resolution")

    logger.info(f"Bootstrapping upstream '{hostname}' via {BOOTSTRAP_DNS}...")

    # 3. Build Query
    q = DNSRecord.question(hostname, "A")
    data = q.pack()

    # 4. Send raw UDP packet
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(5.0)
    
    try:
        sock.sendto(data, (BOOTSTRAP_DNS, 53))
        response_data, _ = sock.recvfrom(512)
        
        # 5. Parse Response
        response = DNSRecord.parse(response_data)
        for rr in response.rr:
            if rr.rtype == QTYPE.A:
                ip = str(rr.rdata)
                logger.info(f"Resolved {hostname} -> {ip}")
                
                # Replace hostname with IP in the URL using urlunparse for safety
                # This ensures only the netloc (hostname:port) is replaced
                new_url = urlunparse(parsed._replace(netloc=ip if not parsed.port else f"{ip}:{parsed.port}"))
                
                # Cache successful resolution with long TTL (1 hour)
                _bootstrap_cache[hostname] = (new_url, current_time + SUCCESS_TTL, True)
                return new_url
                
        logger.warning(f"Could not resolve {hostname} via bootstrap. Using original URL.")
        # Cache failure with short TTL (30 seconds) to allow retry
        _bootstrap_cache[hostname] = (upstream_url, current_time + FAILURE_TTL, False)
        return upstream_url

    except Exception as e:
        logger.error(f"Bootstrap failed: {e}. Fallback to system resolver.")
        # Cache failure with short TTL (30 seconds) to allow retry
        _bootstrap_cache[hostname] = (upstream_url, current_time + FAILURE_TTL, False)
        return upstream_url
    finally:
        sock.close()


def get_bootstrap_cache():
    """Get the current bootstrap cache for inspection/testing."""
    return _bootstrap_cache.copy()


def clear_bootstrap_cache():
    """Clear the bootstrap cache. Useful for testing."""
    _bootstrap_cache.clear()

