"""Bootstrap DNS resolution logic."""
import socket
from urllib.parse import urlparse
from dnslib import DNSRecord, QTYPE
from .config import logger, BOOTSTRAP_DNS


def get_upstream_ip(upstream_url: str) -> str:
    """
    Resolves the hostname of the DoH upstream using the bootstrap DNS server.
    
    If the upstream is already an IP, returns it as-is.
    If it's a hostname, queries BOOTSTRAP_DNS directly via UDP.
    
    Args:
        upstream_url: The DoH upstream URL (e.g., https://cloudflare-dns.com/dns-query)
        
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

    logger.info(f"Bootstrapping upstream '{hostname}' via {BOOTSTRAP_DNS}...")

    # 2. Build Query
    q = DNSRecord.question(hostname, "A")
    data = q.pack()

    # 3. Send raw UDP packet
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(5.0)
    
    try:
        sock.sendto(data, (BOOTSTRAP_DNS, 53))
        response_data, _ = sock.recvfrom(512)
        
        # 4. Parse Response
        response = DNSRecord.parse(response_data)
        for rr in response.rr:
            if rr.rtype == QTYPE.A:
                ip = str(rr.rdata)
                logger.info(f"Resolved {hostname} -> {ip}")
                
                # Replace hostname with IP in the URL
                # Note: This relies on the DoH provider having a valid cert for the IP 
                # (Cloudflare/Google/Quad9 all do).
                new_url = upstream_url.replace(hostname, ip)
                return new_url
                
        logger.warning(f"Could not resolve {hostname} via bootstrap. Using original URL.")
        return upstream_url

    except Exception as e:
        logger.error(f"Bootstrap failed: {e}. Fallback to system resolver.")
        return upstream_url
    finally:
        sock.close()
