"""Bootstrap DNS resolution logic."""
import socket
from typing import Optional
from urllib.parse import urlparse, urlunparse
from dnslib import DNSRecord, QTYPE
import httpx
import httpcore
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
                
                # Replace hostname with IP in the URL using urlunparse for safety
                # This ensures only the netloc (hostname:port) is replaced
                new_url = urlunparse(parsed._replace(netloc=ip if not parsed.port else f"{ip}:{parsed.port}"))
                return new_url
                
        logger.warning(f"Could not resolve {hostname} via bootstrap. Using original URL.")
        return upstream_url

    except Exception as e:
        logger.error(f"Bootstrap failed: {e}. Fallback to system resolver.")
        return upstream_url
    finally:
        sock.close()


def resolve_hostname_to_ip(hostname: str, bootstrap_dns: str = BOOTSTRAP_DNS) -> Optional[str]:
    """
    Resolves a hostname to an IP address using the bootstrap DNS server.
    
    This function performs DNS resolution without modifying URLs, making it
    suitable for use in custom transports that need to preserve the original
    hostname for SNI.
    
    Args:
        hostname: The hostname to resolve (e.g., 'cloudflare-dns.com')
        bootstrap_dns: The DNS server to use for resolution
        
    Returns:
        The resolved IP address as a string, or None if resolution failed
    """
    # Check if it's already an IP
    try:
        socket.inet_aton(hostname)
        return hostname  # It is already an IPv4
    except socket.error:
        pass  # It is a hostname
    
    logger.debug(f"Resolving '{hostname}' via {bootstrap_dns}...")
    
    # Build Query
    q = DNSRecord.question(hostname, "A")
    data = q.pack()
    
    # Send raw UDP packet
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(5.0)
    
    try:
        sock.sendto(data, (bootstrap_dns, 53))
        response_data, _ = sock.recvfrom(512)
        
        # Parse Response
        response = DNSRecord.parse(response_data)
        for rr in response.rr:
            if rr.rtype == QTYPE.A:
                ip = str(rr.rdata)
                logger.debug(f"Resolved {hostname} -> {ip}")
                return ip
        
        logger.warning(f"Could not resolve {hostname} via bootstrap.")
        return None
        
    except Exception as e:
        logger.error(f"Bootstrap resolution failed for {hostname}: {e}")
        return None
    finally:
        sock.close()


class CustomDNSNetworkBackend(httpcore.AsyncNetworkBackend):
    """
    Custom network backend that performs manual DNS resolution while preserving
    the original hostname for SNI (Server Name Indication).
    
    This solves the SSL/SNI issue where DoH providers' certificates don't include
    IP addresses. By resolving the hostname to an IP at the socket level but 
    keeping the original hostname in the connection, we ensure the TLS handshake 
    includes the correct SNI extension.
    """
    
    def __init__(self, bootstrap_dns: str = BOOTSTRAP_DNS):
        """
        Initialize the custom DNS network backend.
        
        Args:
            bootstrap_dns: The DNS server to use for manual resolution
        """
        self.bootstrap_dns = bootstrap_dns
        self._dns_cache = {}  # Simple cache: hostname -> (IP, original_hostname)
        # Use the default backend for actual connections
        self._default_backend = httpcore.AsyncNetworkBackend()
    
    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: Optional[float] = None,
        local_address: Optional[str] = None,
        socket_options = None,
    ):
        """
        Connect to a TCP socket with custom DNS resolution.
        
        This method resolves the hostname to an IP address using bootstrap DNS,
        but preserves the original hostname for SNI in the TLS handshake.
        """
        original_host = host
        
        # Check if we already have a cached IP for this hostname
        if host not in self._dns_cache:
            # Perform DNS resolution using bootstrap DNS
            resolved_ip = resolve_hostname_to_ip(host, self.bootstrap_dns)
            
            if resolved_ip and resolved_ip != host:
                # Cache the resolved IP with the original hostname
                self._dns_cache[host] = (resolved_ip, host)
                logger.info(f"Cached DNS: {host} -> {resolved_ip}")
            else:
                # If resolution failed or it's already an IP, cache as-is
                self._dns_cache[host] = (host, host)
        
        # Get the resolved IP and original hostname from cache
        resolved_ip, original_host = self._dns_cache[host]
        
        # Connect to the resolved IP
        stream = await self._default_backend.connect_tcp(
            host=resolved_ip,
            port=port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )
        
        # Wrap the stream to preserve the original hostname for SNI
        return SNIPreservingStream(stream, original_host)
    
    async def connect_unix_socket(
        self,
        path: str,
        timeout: Optional[float] = None,
        socket_options = None,
    ):
        """Connect to a Unix socket (delegates to default backend)."""
        return await self._default_backend.connect_unix_socket(
            path=path,
            timeout=timeout,
            socket_options=socket_options,
        )
    
    async def sleep(self, seconds: float):
        """Sleep for a given duration (delegates to default backend)."""
        return await self._default_backend.sleep(seconds)


class SNIPreservingStream(httpcore.AsyncNetworkStream):
    """
    Wrapper around AsyncNetworkStream that preserves the original hostname for SNI.
    
    When start_tls is called without a server_hostname, this wrapper provides
    the original hostname to ensure correct SNI behavior.
    """
    
    def __init__(self, stream: httpcore.AsyncNetworkStream, original_hostname: str):
        """
        Initialize the SNI-preserving stream wrapper.
        
        Args:
            stream: The underlying network stream
            original_hostname: The original hostname to use for SNI
        """
        self._stream = stream
        self._original_hostname = original_hostname
    
    async def read(self, max_bytes: int, timeout: Optional[float] = None) -> bytes:
        """Read from the underlying stream."""
        return await self._stream.read(max_bytes, timeout)
    
    async def write(self, buffer: bytes, timeout: Optional[float] = None) -> None:
        """Write to the underlying stream."""
        return await self._stream.write(buffer, timeout)
    
    async def aclose(self) -> None:
        """Close the underlying stream."""
        return await self._stream.aclose()
    
    async def start_tls(
        self,
        ssl_context,
        server_hostname: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        """
        Start TLS with the original hostname for SNI.
        
        If server_hostname is not provided, uses the original hostname
        from the DNS resolution to ensure correct SNI.
        """
        # Use the original hostname for SNI if not explicitly provided
        if server_hostname is None:
            server_hostname = self._original_hostname
        
        # Call start_tls on the underlying stream with the correct server_hostname
        new_stream = await self._stream.start_tls(
            ssl_context, server_hostname=server_hostname, timeout=timeout
        )
        
        # Wrap the new stream to maintain the pattern
        return SNIPreservingStream(new_stream, self._original_hostname)
    
    def get_extra_info(self, info: str):
        """Get extra info from the underlying stream."""
        return self._stream.get_extra_info(info)
