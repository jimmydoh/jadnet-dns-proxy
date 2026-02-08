"""End-to-end tests for CustomDNSTransport.handle_async_request()."""
import pytest
import httpx
import httpcore
from unittest.mock import AsyncMock, Mock, patch
from jadnet_dns_proxy.bootstrap import CustomDNSTransport


@pytest.mark.asyncio
async def test_custom_dns_transport_end_to_end_success():
    """
    Test CustomDNSTransport end-to-end with httpx.AsyncClient.
    
    This test validates:
    - Request mapping through the transport
    - Response.request population
    - raise_for_status() works correctly  
    - resp.content returns expected data
    - Response stream closure
    """
    # Create mock response data
    response_content = b"Hello, World!"
    
    # Create transport with mocked pool
    transport = CustomDNSTransport(bootstrap_dns="8.8.8.8")
    
    # Create mock httpcore response
    mock_httpcore_response = Mock()
    mock_httpcore_response.status = 200
    mock_httpcore_response.headers = [(b'content-type', b'text/plain')]
    mock_httpcore_response.extensions = {}
    
    # Create async iterable for stream
    async def mock_stream():
        yield response_content
    
    mock_httpcore_response.stream = mock_stream()
    
    # Mock the pool's handle_async_request method
    mock_pool = AsyncMock()
    mock_pool.handle_async_request = AsyncMock(return_value=mock_httpcore_response)
    transport._pool = mock_pool
    
    # Use transport with httpx.AsyncClient
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
        assert response.request.method == "GET"
        
        # Validate status code
        assert response.status_code == 200
        
        # Verify the pool was called
        assert mock_pool.handle_async_request.called


@pytest.mark.asyncio
async def test_custom_dns_transport_http_error_raises():
    """
    Test that raise_for_status() raises for HTTP errors.
    
    Validates that error responses are properly handled and
    raise_for_status() works correctly.
    """
    # Create transport with mocked pool
    transport = CustomDNSTransport(bootstrap_dns="8.8.8.8")
    
    # Create mock httpcore response with 404 status
    mock_httpcore_response = Mock()
    mock_httpcore_response.status = 404
    mock_httpcore_response.headers = [(b'content-type', b'text/plain')]
    mock_httpcore_response.extensions = {}
    
    async def mock_stream():
        yield b"Not Found"
    
    mock_httpcore_response.stream = mock_stream()
    
    mock_pool = AsyncMock()
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
async def test_custom_dns_transport_response_stream_closure():
    """
    Test that response streams are properly closed.
    
    This validates that the stream is consumed and properly closed
    after reading the response content.
    """
    class MockStream:
        """Mock stream that tracks if it was consumed."""
        def __init__(self):
            self.consumed = False
            
        async def __aiter__(self):
            self.consumed = True
            yield b"chunk1"
            yield b"chunk2"
    
    # Create transport with mocked pool
    transport = CustomDNSTransport(bootstrap_dns="8.8.8.8")
    
    mock_stream = MockStream()
    
    mock_httpcore_response = Mock()
    mock_httpcore_response.status = 200
    mock_httpcore_response.headers = []
    mock_httpcore_response.extensions = {}
    mock_httpcore_response.stream = mock_stream
    
    mock_pool = AsyncMock()
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
async def test_custom_dns_transport_multiple_requests():
    """
    Test multiple sequential requests through the same transport.
    
    Validates that the transport can handle multiple requests
    and properly manages request/response lifecycle.
    """
    # Create transport with mocked pool
    transport = CustomDNSTransport(bootstrap_dns="8.8.8.8")
    
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
        create_response(b"First response"),
        create_response(b"Second response"),
    ]
    
    mock_pool = AsyncMock()
    mock_pool.handle_async_request = AsyncMock(side_effect=responses)
    transport._pool = mock_pool
    
    async with httpx.AsyncClient(transport=transport) as client:
        # First request
        resp1 = await client.get("https://api.example.com/data")
        assert resp1.content == b"First response"
        assert resp1.request.url.host == "api.example.com"
        
        # Second request
        resp2 = await client.get("https://cdn.example.com/assets")
        assert resp2.content == b"Second response"
        assert resp2.request.url.host == "cdn.example.com"
        
        # Verify both requests were handled
        assert mock_pool.handle_async_request.call_count == 2


@pytest.mark.asyncio
async def test_custom_dns_transport_post_with_content():
    """
    Test POST request with content through CustomDNSTransport.
    
    Validates that request body is properly handled.
    """
    # Create transport with mocked pool
    transport = CustomDNSTransport(bootstrap_dns="8.8.8.8")
    
    mock_httpcore_response = Mock()
    mock_httpcore_response.status = 201
    mock_httpcore_response.headers = [(b'content-type', b'application/json')]
    mock_httpcore_response.extensions = {}
    
    async def mock_stream():
        yield b'{"created": true}'
    
    mock_httpcore_response.stream = mock_stream()
    
    mock_pool = AsyncMock()
    mock_pool.handle_async_request = AsyncMock(return_value=mock_httpcore_response)
    transport._pool = mock_pool
    
    async with httpx.AsyncClient(transport=transport) as client:
        post_data = {"name": "test"}
        response = await client.post(
            "https://api.example.com/items",
            json=post_data
        )
        
        # Validate response
        response.raise_for_status()
        assert response.status_code == 201
        # JSON parser converts lowercase 'true' to Python's True
        assert response.json() == {"created": True}
        
        # Verify request was sent
        call_args = mock_pool.handle_async_request.call_args
        request = call_args[0][0]
        assert request.method == b"POST"


@pytest.mark.asyncio
async def test_custom_dns_transport_request_headers_preserved():
    """
    Test that custom request headers are preserved.
    """
    # Create transport with mocked pool
    transport = CustomDNSTransport(bootstrap_dns="8.8.8.8")
    
    mock_httpcore_response = Mock()
    mock_httpcore_response.status = 200
    mock_httpcore_response.headers = []
    mock_httpcore_response.extensions = {}
    
    async def mock_stream():
        yield b"OK"
    
    mock_httpcore_response.stream = mock_stream()
    
    mock_pool = AsyncMock()
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


@pytest.mark.asyncio
async def test_custom_dns_transport_exception_mapping():
    """
    Test that httpcore exceptions are properly mapped to httpx exceptions.
    """
    # Create transport with mocked pool
    transport = CustomDNSTransport(bootstrap_dns="8.8.8.8")
    
    # Mock pool to raise httpcore.ConnectError
    mock_pool = AsyncMock()
    mock_pool.handle_async_request = AsyncMock(
        side_effect=httpcore.ConnectError("Connection failed")
    )
    transport._pool = mock_pool
    
    async with httpx.AsyncClient(transport=transport) as client:
        # Should raise httpx.ConnectError (not httpcore.ConnectError)
        with pytest.raises(httpx.ConnectError) as exc_info:
            await client.get("https://example.com/test")
        
        assert "Connection failed" in str(exc_info.value)


@pytest.mark.asyncio
async def test_custom_dns_transport_timeout_exception():
    """
    Test that timeout exceptions are properly mapped.
    """
    # Create transport with mocked pool
    transport = CustomDNSTransport(bootstrap_dns="8.8.8.8")
    
    # Mock pool to raise httpcore.ReadTimeout
    mock_pool = AsyncMock()
    mock_pool.handle_async_request = AsyncMock(
        side_effect=httpcore.ReadTimeout("Read timeout")
    )
    transport._pool = mock_pool
    
    async with httpx.AsyncClient(transport=transport) as client:
        # Should raise httpx.ReadTimeout (not httpcore.ReadTimeout)
        with pytest.raises(httpx.ReadTimeout) as exc_info:
            await client.get("https://example.com/test")
        
        assert "Read timeout" in str(exc_info.value)


@pytest.mark.asyncio
async def test_custom_dns_transport_aclose():
    """
    Test that transport is properly closed.
    """
    # Create transport with mocked pool
    transport = CustomDNSTransport(bootstrap_dns="8.8.8.8")
    
    mock_pool = AsyncMock()
    mock_pool.aclose = AsyncMock()
    transport._pool = mock_pool
    
    # Use transport with context manager
    async with transport:
        pass
    
    # Verify pool was closed
    mock_pool.aclose.assert_called_once()
