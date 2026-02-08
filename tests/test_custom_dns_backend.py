"""Unit tests for the CustomDNSNetworkBackend."""
import pytest
from unittest.mock import Mock, patch, AsyncMock, MagicMock
import socket
from dnslib import DNSRecord, QTYPE, RR, A
import httpcore
from jadnet_dns_proxy.bootstrap import (
    resolve_hostname_to_ip,
    CustomDNSNetworkBackend,
    SNIPreservingStream
)


def test_resolve_hostname_to_ip_already_ip():
    """Test that IP addresses are returned unchanged."""
    result = resolve_hostname_to_ip("1.1.1.1")
    assert result == "1.1.1.1"


def test_resolve_hostname_to_ip_success():
    """Test successful hostname resolution."""
    # Create a mock DNS response
    dns_query = DNSRecord.question("example.com", "A")
    dns_response = dns_query.reply()
    dns_response.add_answer(RR("example.com", QTYPE.A, rdata=A("93.184.216.34"), ttl=300))
    response_bytes = dns_response.pack()
    
    # Mock socket operations
    mock_socket = MagicMock()
    mock_socket.__enter__.return_value = mock_socket
    mock_socket.recvfrom.return_value = (response_bytes, ("8.8.8.8", 53))
    
    with patch('socket.socket', return_value=mock_socket):
        result = resolve_hostname_to_ip("example.com", "8.8.8.8")
    
    assert result == "93.184.216.34"
    mock_socket.settimeout.assert_called_once_with(5.0)
    mock_socket.sendto.assert_called_once()
    mock_socket.__exit__.assert_called_once()


def test_resolve_hostname_to_ip_failure():
    """Test handling of resolution failure."""
    # Create a mock DNS response with no answers
    dns_query = DNSRecord.question("nonexistent.example.com", "A")
    dns_response = dns_query.reply()
    response_bytes = dns_response.pack()
    
    # Mock socket operations
    mock_socket = MagicMock()
    mock_socket.__enter__.return_value = mock_socket
    mock_socket.recvfrom.return_value = (response_bytes, ("8.8.8.8", 53))
    
    with patch('socket.socket', return_value=mock_socket):
        result = resolve_hostname_to_ip("nonexistent.example.com", "8.8.8.8")
    
    assert result is None
    mock_socket.__exit__.assert_called_once()


def test_resolve_hostname_to_ip_timeout():
    """Test handling of socket timeout."""
    mock_socket = MagicMock()
    mock_socket.__enter__.return_value = mock_socket
    mock_socket.recvfrom.side_effect = socket.timeout("Timeout")
    
    with patch('socket.socket', return_value=mock_socket):
        result = resolve_hostname_to_ip("timeout.example.com", "8.8.8.8")
    
    assert result is None
    mock_socket.__exit__.assert_called_once()


@pytest.mark.asyncio
async def test_custom_dns_backend_caches_resolution():
    """Test that the custom backend caches DNS resolutions."""
    backend = CustomDNSNetworkBackend(bootstrap_dns="8.8.8.8")
    
    # Create a mock DNS response
    dns_query = DNSRecord.question("example.com", "A")
    dns_response = dns_query.reply()
    dns_response.add_answer(RR("example.com", QTYPE.A, rdata=A("93.184.216.34"), ttl=300))
    response_bytes = dns_response.pack()
    
    # Mock socket operations
    mock_socket = MagicMock()
    mock_socket.__enter__.return_value = mock_socket
    mock_socket.recvfrom.return_value = (response_bytes, ("8.8.8.8", 53))
    
    # Mock the default backend's connect_tcp
    mock_stream = AsyncMock(spec=httpcore.AsyncNetworkStream)
    backend._default_backend.connect_tcp = AsyncMock(return_value=mock_stream)
    
    with patch('socket.socket', return_value=mock_socket):
        # First call should resolve and cache
        stream1 = await backend.connect_tcp("example.com", 443)
        
        # Second call should use cache (socket.socket should not be called again)
        stream2 = await backend.connect_tcp("example.com", 443)
    
    # Verify caching works
    assert "example.com" in backend._dns_cache
    assert backend._dns_cache["example.com"] == ("93.184.216.34", "example.com")
    
    # Verify connect_tcp was called with the resolved IP both times
    assert backend._default_backend.connect_tcp.call_count == 2
    backend._default_backend.connect_tcp.assert_any_call(
        host="93.184.216.34",
        port=443,
        timeout=None,
        local_address=None,
        socket_options=None
    )
    
    # Verify both calls returned SNIPreservingStream instances
    assert isinstance(stream1, SNIPreservingStream)
    assert isinstance(stream2, SNIPreservingStream)
    assert stream1._original_hostname == "example.com"
    assert stream2._original_hostname == "example.com"


@pytest.mark.asyncio
async def test_custom_dns_backend_handles_ip_directly():
    """Test that the backend handles IP addresses directly without resolution."""
    backend = CustomDNSNetworkBackend(bootstrap_dns="8.8.8.8")
    
    # Mock the default backend's connect_tcp
    mock_stream = AsyncMock(spec=httpcore.AsyncNetworkStream)
    backend._default_backend.connect_tcp = AsyncMock(return_value=mock_stream)
    
    # Connect using an IP address directly
    stream = await backend.connect_tcp("1.1.1.1", 443)
    
    # Verify no DNS resolution was attempted (would require socket.socket)
    # and connect_tcp was called with the same IP
    backend._default_backend.connect_tcp.assert_called_once_with(
        host="1.1.1.1",
        port=443,
        timeout=None,
        local_address=None,
        socket_options=None
    )
    
    # Verify SNIPreservingStream is returned
    assert isinstance(stream, SNIPreservingStream)
    assert stream._original_hostname == "1.1.1.1"


@pytest.mark.asyncio
async def test_sni_preserving_stream_delegates_methods():
    """Test that SNIPreservingStream properly delegates to underlying stream."""
    mock_stream = AsyncMock(spec=httpcore.AsyncNetworkStream)
    mock_stream.read = AsyncMock(return_value=b"test data")
    mock_stream.write = AsyncMock()
    mock_stream.aclose = AsyncMock()
    mock_stream.get_extra_info = Mock(return_value="extra_info")
    
    wrapped_stream = SNIPreservingStream(mock_stream, "example.com")
    
    # Test read
    data = await wrapped_stream.read(1024, timeout=5.0)
    assert data == b"test data"
    mock_stream.read.assert_called_once_with(1024, 5.0)
    
    # Test write
    await wrapped_stream.write(b"test", timeout=5.0)
    mock_stream.write.assert_called_once_with(b"test", 5.0)
    
    # Test aclose
    await wrapped_stream.aclose()
    mock_stream.aclose.assert_called_once()
    
    # Test get_extra_info
    info = wrapped_stream.get_extra_info("test")
    assert info == "extra_info"
    mock_stream.get_extra_info.assert_called_once_with("test")


@pytest.mark.asyncio
async def test_sni_preserving_stream_preserves_hostname_in_start_tls():
    """Test that SNIPreservingStream uses original hostname for SNI."""
    mock_stream = AsyncMock(spec=httpcore.AsyncNetworkStream)
    mock_tls_stream = AsyncMock(spec=httpcore.AsyncNetworkStream)
    mock_stream.start_tls = AsyncMock(return_value=mock_tls_stream)
    
    wrapped_stream = SNIPreservingStream(mock_stream, "example.com")
    
    # Call start_tls without providing server_hostname
    import ssl
    ssl_context = ssl.create_default_context()
    result = await wrapped_stream.start_tls(ssl_context, timeout=5.0)
    
    # Verify start_tls was called with the original hostname
    mock_stream.start_tls.assert_called_once_with(
        ssl_context, server_hostname="example.com", timeout=5.0
    )
    
    # Verify the result is wrapped
    assert isinstance(result, SNIPreservingStream)
    assert result._original_hostname == "example.com"


@pytest.mark.asyncio
async def test_sni_preserving_stream_respects_explicit_server_hostname():
    """Test that SNIPreservingStream respects explicitly provided server_hostname."""
    mock_stream = AsyncMock(spec=httpcore.AsyncNetworkStream)
    mock_tls_stream = AsyncMock(spec=httpcore.AsyncNetworkStream)
    mock_stream.start_tls = AsyncMock(return_value=mock_tls_stream)
    
    wrapped_stream = SNIPreservingStream(mock_stream, "example.com")
    
    # Call start_tls with explicit server_hostname
    import ssl
    ssl_context = ssl.create_default_context()
    result = await wrapped_stream.start_tls(ssl_context, server_hostname="other.com", timeout=5.0)
    
    # Verify start_tls was called with the explicit hostname, not the cached one
    mock_stream.start_tls.assert_called_once_with(
        ssl_context, server_hostname="other.com", timeout=5.0
    )


@pytest.mark.asyncio
async def test_custom_async_stream_aclose():
    """Test that CustomAsyncStream properly closes the underlying response."""
    from jadnet_dns_proxy.bootstrap import CustomDNSTransport
    import httpx
    
    # Create a transport
    transport = CustomDNSTransport(bootstrap_dns="8.8.8.8")
    
    # Mock the connection pool to return a mock response
    mock_response = AsyncMock(spec=httpcore.Response)
    mock_response.status = 200
    mock_response.headers = []
    mock_response.stream = AsyncMock()
    mock_response.stream.__aiter__ = AsyncMock(return_value=iter([b"test data"]))
    mock_response.extensions = {}
    mock_response.aclose = AsyncMock()
    
    transport._pool.handle_async_request = AsyncMock(return_value=mock_response)
    
    # Create a request
    request = httpx.Request("GET", "https://example.com/test")
    
    # Handle the request
    response = await transport.handle_async_request(request)
    
    # Verify the response is created
    assert response.status_code == 200
    
    # Close the response (this should call aclose on the stream)
    await response.aclose()
    
    # Verify that the underlying httpcore response's aclose was called
    mock_response.aclose.assert_called_once()
    
    # Clean up
    await transport.aclose()


@pytest.mark.asyncio
async def test_custom_dns_backend_does_not_cache_failed_resolutions():
    """Test that failed DNS resolutions are not cached, allowing retries."""
    backend = CustomDNSNetworkBackend(bootstrap_dns="8.8.8.8")
    
    HOSTNAME = "transient-failure.example.com"
    MOCK_RESOLVED_IP = "93.184.216.34"
    
    # Create a mock DNS response with no answers (resolution failure)
    dns_question = DNSRecord.question(HOSTNAME, "A")
    dns_response = dns_question.reply()
    # No answers added - simulates resolution failure
    response_bytes = dns_response.pack()
    
    # Mock socket operations for the first call (failure)
    mock_socket_fail = MagicMock()
    mock_socket_fail.__enter__.return_value = mock_socket_fail
    mock_socket_fail.recvfrom.return_value = (response_bytes, ("8.8.8.8", 53))
    
    # Mock the default backend's connect_tcp
    mock_stream = AsyncMock(spec=httpcore.AsyncNetworkStream)
    backend._default_backend.connect_tcp = AsyncMock(return_value=mock_stream)
    
    # Capture log warnings to verify the warning message
    with patch('socket.socket', return_value=mock_socket_fail), \
         patch('jadnet_dns_proxy.bootstrap.logger') as mock_logger:
        # First call should fail to resolve
        stream1 = await backend.connect_tcp(HOSTNAME, 443)
        
        # Verify warning log message was generated
        mock_logger.warning.assert_called_with(
            f"Bootstrap resolution failed for {HOSTNAME}, will retry on next connection"
        )
    
    # Verify the hostname is NOT in the cache (failed resolutions should not be cached)
    assert HOSTNAME not in backend._dns_cache
    
    # Verify connect_tcp was called with the original hostname (fallback to system DNS)
    assert backend._default_backend.connect_tcp.call_count == 1
    backend._default_backend.connect_tcp.assert_called_with(
        host=HOSTNAME,
        port=443,
        timeout=None,
        local_address=None,
        socket_options=None
    )
    
    # Now create a successful DNS response for the second attempt
    dns_response_success = dns_question.reply()
    dns_response_success.add_answer(RR(HOSTNAME, QTYPE.A, rdata=A(MOCK_RESOLVED_IP), ttl=300))
    response_bytes_success = dns_response_success.pack()
    
    # Mock socket operations for the second call (success)
    mock_socket_success = MagicMock()
    mock_socket_success.__enter__.return_value = mock_socket_success
    mock_socket_success.recvfrom.return_value = (response_bytes_success, ("8.8.8.8", 53))
    
    with patch('socket.socket', return_value=mock_socket_success):
        # Second call should retry resolution and succeed
        stream2 = await backend.connect_tcp(HOSTNAME, 443)
    
    # Verify the hostname IS NOW in the cache (successful resolution should be cached)
    assert HOSTNAME in backend._dns_cache
    assert backend._dns_cache[HOSTNAME] == (MOCK_RESOLVED_IP, HOSTNAME)
    
    # Verify connect_tcp was called twice total
    assert backend._default_backend.connect_tcp.call_count == 2
    
    # Verify the second call specifically used the resolved IP
    second_call_kwargs = backend._default_backend.connect_tcp.call_args_list[1].kwargs
    assert second_call_kwargs['host'] == MOCK_RESOLVED_IP
    assert second_call_kwargs['port'] == 443
    
    # Verify both calls returned SNIPreservingStream instances
    assert isinstance(stream1, SNIPreservingStream)
    assert isinstance(stream2, SNIPreservingStream)
    assert stream1._original_hostname == HOSTNAME
    assert stream2._original_hostname == HOSTNAME
