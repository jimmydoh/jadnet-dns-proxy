"""Unit tests for the DoH resolver module."""
import pytest
from unittest.mock import Mock, AsyncMock, patch
from dnslib import DNSRecord, QTYPE, RR, A
from jadnet_dns_proxy.resolver import resolve_doh
from jadnet_dns_proxy.upstream_manager import UpstreamManager, UpstreamServer


@pytest.mark.asyncio
async def test_resolve_doh_success():
    """Test successful DoH resolution."""
    # Create a mock DNS response
    dns_request = DNSRecord.question("example.com", "A")
    dns_response = dns_request.reply()
    dns_response.add_answer(RR("example.com", QTYPE.A, rdata=A("93.184.216.34"), ttl=300))
    response_bytes = dns_response.pack()
    
    # Mock HTTP client
    mock_client = AsyncMock()
    mock_response = Mock()
    mock_response.content = response_bytes
    mock_response.raise_for_status = Mock()
    mock_client.post = AsyncMock(return_value=mock_response)
    
    # Mock upstream manager
    mock_upstream = UpstreamServer(url="https://1.1.1.1/dns-query")
    mock_manager = Mock()
    mock_manager.get_next_server = AsyncMock(return_value=mock_upstream)
    
    # Call resolve_doh
    result_bytes, ttl = await resolve_doh(mock_client, dns_request.pack(), mock_manager)
    
    # Verify result
    assert result_bytes == response_bytes
    assert ttl == 300
    
    # Verify client was called correctly
    mock_client.post.assert_called_once()
    call_kwargs = mock_client.post.call_args.kwargs
    assert call_kwargs['headers']['Content-Type'] == 'application/dns-message'
    assert call_kwargs['headers']['Accept'] == 'application/dns-message'
    assert call_kwargs['timeout'] == 4.0
    
    # Verify upstream recorded success
    assert mock_upstream.total_requests == 1
    assert mock_upstream.failed_requests == 0


@pytest.mark.asyncio
async def test_resolve_doh_multiple_answers():
    """Test DoH resolution with multiple answers (min TTL should be used)."""
    dns_request = DNSRecord.question("example.com", "A")
    dns_response = dns_request.reply()
    dns_response.add_answer(RR("example.com", QTYPE.A, rdata=A("1.1.1.1"), ttl=600))
    dns_response.add_answer(RR("example.com", QTYPE.A, rdata=A("2.2.2.2"), ttl=300))
    dns_response.add_answer(RR("example.com", QTYPE.A, rdata=A("3.3.3.3"), ttl=450))
    response_bytes = dns_response.pack()
    
    mock_client = AsyncMock()
    mock_response = Mock()
    mock_response.content = response_bytes
    mock_response.raise_for_status = Mock()
    mock_client.post = AsyncMock(return_value=mock_response)
    
    mock_upstream = UpstreamServer(url="https://1.1.1.1/dns-query")
    mock_manager = Mock()
    mock_manager.get_next_server = AsyncMock(return_value=mock_upstream)
    
    result_bytes, ttl = await resolve_doh(mock_client, dns_request.pack(), mock_manager)
    
    # Should use minimum TTL
    assert ttl == 300


@pytest.mark.asyncio
async def test_resolve_doh_no_answers():
    """Test DoH resolution with no answers (default TTL should be used)."""
    dns_request = DNSRecord.question("nonexistent.example.com", "A")
    dns_response = dns_request.reply()
    # No answers added
    response_bytes = dns_response.pack()
    
    mock_client = AsyncMock()
    mock_response = Mock()
    mock_response.content = response_bytes
    mock_response.raise_for_status = Mock()
    mock_client.post = AsyncMock(return_value=mock_response)
    
    mock_upstream = UpstreamServer(url="https://1.1.1.1/dns-query")
    mock_manager = Mock()
    mock_manager.get_next_server = AsyncMock(return_value=mock_upstream)
    
    result_bytes, ttl = await resolve_doh(mock_client, dns_request.pack(), mock_manager)
    
    # Should use default TTL
    assert ttl == 300


@pytest.mark.asyncio
async def test_resolve_doh_http_error():
    """Test DoH resolution with HTTP error."""
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=Exception("HTTP error"))
    
    mock_upstream = UpstreamServer(url="https://1.1.1.1/dns-query")
    mock_manager = Mock()
    mock_manager.get_next_server = AsyncMock(return_value=mock_upstream)
    
    result_bytes, ttl = await resolve_doh(mock_client, b"fake_query", mock_manager)
    
    # Should return None and 0 on error
    assert result_bytes is None
    assert ttl == 0
    
    # Verify upstream recorded failure
    assert mock_upstream.total_requests == 1
    assert mock_upstream.failed_requests == 1


@pytest.mark.asyncio
async def test_resolve_doh_timeout():
    """Test DoH resolution with timeout."""
    import httpx
    
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))
    
    mock_upstream = UpstreamServer(url="https://1.1.1.1/dns-query")
    mock_manager = Mock()
    mock_manager.get_next_server = AsyncMock(return_value=mock_upstream)
    
    result_bytes, ttl = await resolve_doh(mock_client, b"fake_query", mock_manager)
    
    assert result_bytes is None
    assert ttl == 0
    
    # Verify upstream recorded failure
    assert mock_upstream.failed_requests == 1


@pytest.mark.asyncio
async def test_resolve_doh_http_status_error():
    """Test DoH resolution with HTTP status error."""
    import httpx
    
    mock_client = AsyncMock()
    mock_response = Mock()
    mock_response.raise_for_status = Mock(side_effect=httpx.HTTPStatusError(
        "404", request=Mock(), response=Mock()
    ))
    mock_client.post = AsyncMock(return_value=mock_response)
    
    mock_upstream = UpstreamServer(url="https://1.1.1.1/dns-query")
    mock_manager = Mock()
    mock_manager.get_next_server = AsyncMock(return_value=mock_upstream)
    
    result_bytes, ttl = await resolve_doh(mock_client, b"fake_query", mock_manager)
    
    assert result_bytes is None
    assert ttl == 0
    
    # Verify upstream recorded failure
    assert mock_upstream.failed_requests == 1


@pytest.mark.asyncio
async def test_resolve_doh_uses_upstream_from_manager():
    """Test that resolve_doh uses the upstream from the manager."""
    dns_request = DNSRecord.question("example.com", "A")
    dns_response = dns_request.reply()
    response_bytes = dns_response.pack()
    
    mock_client = AsyncMock()
    mock_response = Mock()
    mock_response.content = response_bytes
    mock_response.raise_for_status = Mock()
    mock_client.post = AsyncMock(return_value=mock_response)
    
    mock_upstream = UpstreamServer(url="https://test.example.com/dns-query")
    mock_manager = Mock()
    mock_manager.get_next_server = AsyncMock(return_value=mock_upstream)
    
    await resolve_doh(mock_client, dns_request.pack(), mock_manager)
    
    # Verify the correct upstream URL was used
    call_args = mock_client.post.call_args
    assert call_args[0][0] == 'https://test.example.com/dns-query'


@pytest.mark.asyncio
async def test_resolve_doh_no_upstream_available():
    """Test DoH resolution when no upstream is available."""
    mock_client = AsyncMock()
    mock_manager = Mock()
    mock_manager.get_next_server = AsyncMock(return_value=None)
    
    result_bytes, ttl = await resolve_doh(mock_client, b"fake_query", mock_manager)
    
    assert result_bytes is None
    assert ttl == 0
    
    # Client should not have been called
    mock_client.post.assert_not_called()

