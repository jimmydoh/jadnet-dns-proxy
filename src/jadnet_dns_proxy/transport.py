"""Custom HTTP transport with DNS resolution mapping."""
import httpx
import httpcore
from typing import Dict, Optional


class CustomDNSTransport(httpx.AsyncHTTPTransport):
    """
    Custom HTTP transport that maps hostnames to specific IP addresses.
    
    This transport allows overriding DNS resolution by providing a mapping
    of hostnames to IP addresses, while still using the original hostname
    for SNI and Host headers.
    
    Example:
        dns_mapping = {"example.com": "93.184.216.34"}
        transport = CustomDNSTransport(dns_mapping=dns_mapping)
        async with httpx.AsyncClient(transport=transport) as client:
            resp = await client.get("https://example.com")
    """
    
    def __init__(
        self,
        dns_mapping: Optional[Dict[str, str]] = None,
        **kwargs
    ):
        """
        Initialize the custom DNS transport.
        
        Args:
            dns_mapping: Dictionary mapping hostnames to IP addresses
            **kwargs: Additional arguments passed to AsyncHTTPTransport
        """
        super().__init__(**kwargs)
        self.dns_mapping = dns_mapping or {}
    
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """
        Handle an async HTTP request with custom DNS resolution.
        
        This method maps the request hostname to a configured IP address
        while preserving the original hostname for SNI and Host headers.
        
        Args:
            request: The HTTP request to handle
            
        Returns:
            The HTTP response with properly populated request attribute
        """
        # Save the original URL for response population
        original_url = request.url
        
        # Check if we have a DNS mapping for this host
        original_host = request.url.host
        if original_host in self.dns_mapping:
            # Create a new URL with the mapped IP but preserve the original host for SNI
            mapped_ip = self.dns_mapping[original_host]
            
            # Build new URL with IP
            new_url = request.url.copy_with(host=mapped_ip)
            
            # Modify the request URL directly
            request.url = new_url
            
            # Preserve the original hostname in extensions for SNI
            if 'sni_hostname' not in request.extensions:
                request.extensions['sni_hostname'] = original_host.encode('ascii')
        
        # Call parent implementation
        response = await super().handle_async_request(request)
        
        # Restore the original URL and populate the response.request attribute
        # This is important for httpx's raise_for_status() and other features
        request.url = original_url
        response._request = request
        
        return response
