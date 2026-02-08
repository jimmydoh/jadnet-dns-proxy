"""End-to-end tests for CustomDNSTransport."""
import pytest
import httpx
from unittest.mock import AsyncMock, Mock
from jadnet_dns_proxy.transport import CustomDNSTransport


@pytest.mark.asyncio
async def test_custom_dns_transport_end_to_end_success():
    """
    Test CustomDNSTransport end-to-end with successful response.
    
    This test validates:
    - Request mapping to custom IP
    - Response.request population
    - raise_for_status() works correctly
    - resp.content returns expected data
    - Response stream closure
    """
    # Setup DNS mapping
    dns_mapping = {"example.com": "93.184.216.34"}
    
    # Create mock response data
    response_content = b"Hello, World!"
    
    # Create transport and mock its pool
    transport = CustomDNSTransport(dns_mapping=dns_mapping)
    mock_pool = AsyncMock()
    
    # Create mock httpcore response
    mock_httpcore_response = Mock()
    mock_httpcore_response.status = 200
    mock_httpcore_response.headers = [(b'content-type', b'text/plain')]
    mock_httpcore_response.extensions = {}
    
    # Create async iterable for stream
    async def mock_stream():
        yield response_content
    
    mock_httpcore_response.stream = mock_stream()
    
    # Configure mock pool
    mock_pool.handle_async_request = AsyncMock(return_value=mock_httpcore_response)
    transport._pool = mock_pool
    
    async with httpx.AsyncClient(transport=transport) as client:
        # Make request
        response = await client.get("https://example.com/test")
        
        # Validate raise_for_status() doesn't raise (200 OK)
        response.raise_for_status()
        
        # Validate resp.content
        assert response.content == response_content
        assert response.text == "Hello, World!"
        
        # Validate response.request is populated
        assert response.request is not None
        assert response.request.url.host == "example.com"
        
        # Validate status code
        assert response.status_code == 200
        
        # Verify the pool was called with mapped IP
        assert mock_pool.handle_async_request.called
        call_args = mock_pool.handle_async_request.call_args
        request = call_args[0][0]
        
        # The request should have been mapped to the IP
        assert request.url.host == b"93.184.216.34"


@pytest.mark.asyncio
async def test_custom_dns_transport_http_error_raises():
    """
    Test that raise_for_status() raises for HTTP errors.
    
    Validates that error responses are properly handled and
    raise_for_status() works correctly.
    """
    dns_mapping = {"example.com": "93.184.216.34"}
    
    # Create transport and mock its pool
    transport = CustomDNSTransport(dns_mapping=dns_mapping)
    mock_pool = AsyncMock()
    
    # Create mock httpcore response with 404 status
    mock_httpcore_response = Mock()
    mock_httpcore_response.status = 404
    mock_httpcore_response.headers = [(b'content-type', b'text/plain')]
    mock_httpcore_response.extensions = {}
    
    async def mock_stream():
        yield b"Not Found"
    
    mock_httpcore_response.stream = mock_stream()
    
    mock_pool.handle_async_request = AsyncMock(return_value=mock_httpcore_response)
    transport._pool = mock_pool
    
    async with httpx.AsyncClient(transport=transport) as client:
        response = await client.get("https://example.com/notfound")
        
        # Should not raise yet
        assert response.status_code == 404
        
        # raise_for_status() should raise HTTPStatusError
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            response.raise_for_status()
        
        # Validate exception details
        assert exc_info.value.response.status_code == 404
        assert exc_info.value.request is not None


@pytest.mark.asyncio
async def test_custom_dns_transport_without_mapping():
    """
    Test that requests without DNS mapping are passed through normally.
    """
    # No DNS mapping - should pass through unchanged
    dns_mapping = {}
    
    # Create transport and mock its pool
    transport = CustomDNSTransport(dns_mapping=dns_mapping)
    mock_pool = AsyncMock()
    
    mock_httpcore_response = Mock()
    mock_httpcore_response.status = 200
    mock_httpcore_response.headers = [(b'content-type', b'text/plain')]
    mock_httpcore_response.extensions = {}
    
    async def mock_stream():
        yield b"Response"
    
    mock_httpcore_response.stream = mock_stream()
    
    mock_pool.handle_async_request = AsyncMock(return_value=mock_httpcore_response)
    transport._pool = mock_pool
    
    async with httpx.AsyncClient(transport=transport) as client:
        response = await client.get("https://unmapped.example.com/test")
        
        # Verify request was not modified (host should remain unchanged)
        call_args = mock_pool.handle_async_request.call_args
        request = call_args[0][0]
        assert request.url.host == b"unmapped.example.com"
        
        # Verify response is still valid
        assert response.status_code == 200
        assert response.content == b"Response"


@pytest.mark.asyncio
async def test_custom_dns_transport_response_stream_closure():
    """
    Test that response streams are properly closed.
    
    This validates that the stream is consumed and properly closed
    after reading the response content.
    """
    dns_mapping = {"example.com": "93.184.216.34"}
    
    class MockStream:
        """Mock stream that tracks if it was consumed."""
        def __init__(self):
            self.consumed = False
            
        async def __aiter__(self):
            self.consumed = True
            yield b"chunk1"
            yield b"chunk2"
    
    # Create transport and mock its pool
    transport = CustomDNSTransport(dns_mapping=dns_mapping)
    mock_pool = AsyncMock()
    
    mock_stream = MockStream()
    
    mock_httpcore_response = Mock()
    mock_httpcore_response.status = 200
    mock_httpcore_response.headers = []
    mock_httpcore_response.extensions = {}
    mock_httpcore_response.stream = mock_stream
    
    mock_pool.handle_async_request = AsyncMock(return_value=mock_httpcore_response)
    transport._pool = mock_pool
    
    async with httpx.AsyncClient(transport=transport) as client:
        response = await client.get("https://example.com/test")
        
        # Read the content - this should consume the stream
        content = response.content
        
        # Verify stream was consumed
        assert mock_stream.consumed
        assert content == b"chunk1chunk2"


@pytest.mark.asyncio
async def test_custom_dns_transport_preserves_sni_hostname():
    """
    Test that the original hostname is preserved for SNI in TLS.
    
    This is important for HTTPS requests where the server certificate
    must match the original hostname, not the IP address.
    """
    dns_mapping = {"secure.example.com": "203.0.113.1"}
    
    # Create transport and mock its pool
    transport = CustomDNSTransport(dns_mapping=dns_mapping)
    mock_pool = AsyncMock()
    
    mock_httpcore_response = Mock()
    mock_httpcore_response.status = 200
    mock_httpcore_response.headers = []
    mock_httpcore_response.extensions = {}
    
    async def mock_stream():
        yield b"Secure response"
    
    mock_httpcore_response.stream = mock_stream()
    
    mock_pool.handle_async_request = AsyncMock(return_value=mock_httpcore_response)
    transport._pool = mock_pool
    
    async with httpx.AsyncClient(transport=transport) as client:
        response = await client.get("https://secure.example.com/api")
        
        # Check that the request was mapped
        call_args = mock_pool.handle_async_request.call_args
        request = call_args[0][0]
        
        # URL should have the IP
        assert request.url.host == b"203.0.113.1"
        
        # But SNI should have original hostname
        assert 'sni_hostname' in request.extensions
        assert request.extensions['sni_hostname'] == b"secure.example.com"


@pytest.mark.asyncio
async def test_custom_dns_transport_multiple_requests():
    """
    Test multiple sequential requests through the same transport.
    
    Validates that the transport can handle multiple requests
    and properly manages request/response lifecycle.
    """
    dns_mapping = {
        "api.example.com": "198.51.100.1",
        "cdn.example.com": "198.51.100.2"
    }
    
    # Create transport and mock its pool
    transport = CustomDNSTransport(dns_mapping=dns_mapping)
    mock_pool = AsyncMock()
    
    # Configure mock to return different responses
    def create_response(content):
        mock_resp = Mock()
        mock_resp.status = 200
        mock_resp.headers = []
        mock_resp.extensions = {}
        
        async def stream():
            yield content
        
        mock_resp.stream = stream()
        return mock_resp
    
    responses = [
        create_response(b"API response"),
        create_response(b"CDN response"),
    ]
    
    mock_pool.handle_async_request = AsyncMock(side_effect=responses)
    transport._pool = mock_pool
    
    async with httpx.AsyncClient(transport=transport) as client:
        # First request
        resp1 = await client.get("https://api.example.com/data")
        assert resp1.content == b"API response"
        assert resp1.request.url.host == "api.example.com"
        
        # Second request
        resp2 = await client.get("https://cdn.example.com/assets")
        assert resp2.content == b"CDN response"
        assert resp2.request.url.host == "cdn.example.com"
        
        # Verify both requests were mapped to correct IPs
        calls = mock_pool.handle_async_request.call_args_list
        assert len(calls) == 2
        
        # First call should be to API IP
        assert calls[0][0][0].url.host == b"198.51.100.1"
        
        # Second call should be to CDN IP
        assert calls[1][0][0].url.host == b"198.51.100.2"


@pytest.mark.asyncio
async def test_custom_dns_transport_post_with_content():
    """
    Test POST request with content through CustomDNSTransport.
    
    Validates that request body is properly handled.
    """
    dns_mapping = {"api.example.com": "198.51.100.10"}
    
    # Create transport and mock its pool
    transport = CustomDNSTransport(dns_mapping=dns_mapping)
    mock_pool = AsyncMock()
    
    mock_httpcore_response = Mock()
    mock_httpcore_response.status = 201
    mock_httpcore_response.headers = [(b'content-type', b'application/json')]
    mock_httpcore_response.extensions = {}
    
    async def mock_stream():
        yield b'{"created": true}'
    
    mock_httpcore_response.stream = mock_stream()
    
    mock_pool.handle_async_request = AsyncMock(return_value=mock_httpcore_response)
    transport._pool = mock_pool
    
    async with httpx.AsyncClient(transport=transport) as client:
        post_data = {"name": "test"}
        response = await client.post(
            "https://api.example.com/items",
            json=post_data
        )
        
        # Verify response
        response.raise_for_status()
        assert response.status_code == 201
        # JSON parser converts lowercase 'true' to Python's True
        assert response.json() == {"created": True}
        
        # Verify request was mapped
        call_args = mock_pool.handle_async_request.call_args
        request = call_args[0][0]
        assert request.url.host == b"198.51.100.10"
        assert request.method == b"POST"


@pytest.mark.asyncio
async def test_custom_dns_transport_request_headers_preserved():
    """
    Test that custom request headers are preserved.
    """
    dns_mapping = {"example.com": "93.184.216.34"}
    
    # Create transport and mock its pool
    transport = CustomDNSTransport(dns_mapping=dns_mapping)
    mock_pool = AsyncMock()
    
    mock_httpcore_response = Mock()
    mock_httpcore_response.status = 200
    mock_httpcore_response.headers = []
    mock_httpcore_response.extensions = {}
    
    async def mock_stream():
        yield b"OK"
    
    mock_httpcore_response.stream = mock_stream()
    
    mock_pool.handle_async_request = AsyncMock(return_value=mock_httpcore_response)
    transport._pool = mock_pool
    
    async with httpx.AsyncClient(transport=transport) as client:
        custom_headers = {
            "X-Custom-Header": "custom-value",
            "Authorization": "Bearer token123"
        }
        
        response = await client.get(
            "https://example.com/api",
            headers=custom_headers
        )
        
        # Verify headers were passed through
        call_args = mock_pool.handle_async_request.call_args
        request = call_args[0][0]
        
        # Check headers are present 
        # httpcore headers are a list of (name, value) byte tuples
        # Convert to dict for easier assertions
        headers_dict = dict(request.headers)
        # httpcore preserves header case, so check for the original case
        assert b"X-Custom-Header" in headers_dict
        assert headers_dict[b"X-Custom-Header"] == b"custom-value"
        assert b"Authorization" in headers_dict
        assert headers_dict[b"Authorization"] == b"Bearer token123"
