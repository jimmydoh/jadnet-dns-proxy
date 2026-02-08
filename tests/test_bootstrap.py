"""Unit tests for the bootstrap module."""
import pytest
import time
from unittest.mock import Mock, patch, MagicMock
import socket
from dnslib import DNSRecord, QTYPE, RR, A
from jadnet_dns_proxy.bootstrap import (
    get_upstream_ip, 
    clear_bootstrap_cache, 
    get_bootstrap_cache, 
    SUCCESS_TTL, 
    FAILURE_TTL
)


def test_get_upstream_ip_already_ip():
    """Test that IP addresses are returned unchanged."""
    # IPv4 address should be returned as-is
    result = get_upstream_ip("https://1.1.1.1/dns-query")
    assert result == "https://1.1.1.1/dns-query"


def test_get_upstream_ip_hostname_success():
    """Test successful hostname resolution via bootstrap."""
    upstream_url = "https://cloudflare-dns.com/dns-query"
    
    # Create a mock DNS response
    dns_query = DNSRecord.question("cloudflare-dns.com", "A")
    dns_response = dns_query.reply()
    dns_response.add_answer(RR("cloudflare-dns.com", QTYPE.A, rdata=A("104.16.248.249"), ttl=300))
    response_bytes = dns_response.pack()
    
    # Mock socket operations
    mock_socket = MagicMock()
    mock_socket.recvfrom.return_value = (response_bytes, ("8.8.8.8", 53))
    
    with patch('socket.socket', return_value=mock_socket):
        result = get_upstream_ip(upstream_url)
    
    # Should replace hostname with IP
    assert result == "https://104.16.248.249/dns-query"
    
    # Verify socket operations
    mock_socket.settimeout.assert_called_once_with(5.0)
    mock_socket.sendto.assert_called_once()
    mock_socket.recvfrom.assert_called_once_with(512)
    mock_socket.close.assert_called_once()


def test_get_upstream_ip_no_answers():
    """Test handling of DNS response with no answers."""
    upstream_url = "https://nonexistent.example.com/dns-query"
    
    # Create a mock DNS response with no answers
    dns_query = DNSRecord.question("nonexistent.example.com", "A")
    dns_response = dns_query.reply()
    # No answers added
    response_bytes = dns_response.pack()
    
    # Mock socket operations
    mock_socket = MagicMock()
    mock_socket.recvfrom.return_value = (response_bytes, ("8.8.8.8", 53))
    
    with patch('socket.socket', return_value=mock_socket):
        result = get_upstream_ip(upstream_url)
    
    # Should return original URL when no answers found
    assert result == upstream_url
    mock_socket.close.assert_called_once()


def test_get_upstream_ip_socket_timeout():
    """Test handling of socket timeout during bootstrap."""
    upstream_url = "https://timeout.example.com/dns-query"
    
    # Mock socket to raise timeout
    mock_socket = MagicMock()
    mock_socket.recvfrom.side_effect = socket.timeout("Timeout")
    
    with patch('socket.socket', return_value=mock_socket):
        result = get_upstream_ip(upstream_url)
    
    # Should return original URL on timeout
    assert result == upstream_url
    mock_socket.close.assert_called_once()


def test_get_upstream_ip_socket_error():
    """Test handling of socket errors during bootstrap."""
    upstream_url = "https://error.example.com/dns-query"
    
    # Mock socket to raise error
    mock_socket = MagicMock()
    mock_socket.sendto.side_effect = OSError("Network error")
    
    with patch('socket.socket', return_value=mock_socket):
        result = get_upstream_ip(upstream_url)
    
    # Should return original URL on error
    assert result == upstream_url
    mock_socket.close.assert_called_once()


def test_get_upstream_ip_parse_error():
    """Test handling of invalid DNS response."""
    upstream_url = "https://invalid.example.com/dns-query"
    
    # Mock socket to return invalid data
    mock_socket = MagicMock()
    mock_socket.recvfrom.return_value = (b"invalid_dns_data", ("8.8.8.8", 53))
    
    with patch('socket.socket', return_value=mock_socket):
        result = get_upstream_ip(upstream_url)
    
    # Should return original URL when parsing fails
    assert result == upstream_url
    mock_socket.close.assert_called_once()


def test_get_upstream_ip_custom_bootstrap_dns():
    """Test that bootstrap uses the configured BOOTSTRAP_DNS."""
    upstream_url = "https://dns.google/dns-query"
    
    # Create a mock DNS response
    dns_query = DNSRecord.question("dns.google", "A")
    dns_response = dns_query.reply()
    dns_response.add_answer(RR("dns.google", QTYPE.A, rdata=A("8.8.8.8"), ttl=300))
    response_bytes = dns_response.pack()
    
    # Mock socket operations
    mock_socket = MagicMock()
    mock_socket.recvfrom.return_value = (response_bytes, ("1.1.1.1", 53))
    
    with patch('socket.socket', return_value=mock_socket):
        with patch('jadnet_dns_proxy.bootstrap.BOOTSTRAP_DNS', '1.1.1.1'):
            result = get_upstream_ip(upstream_url)
    
    # Should use custom bootstrap DNS
    call_args = mock_socket.sendto.call_args[0]
    assert call_args[1] == ('1.1.1.1', 53)
    
    # Should replace hostname with IP
    assert result == "https://8.8.8.8/dns-query"


def test_get_upstream_ip_multiple_answers():
    """Test handling of multiple A records (should use first one)."""
    upstream_url = "https://multi.example.com/dns-query"
    
    # Create a mock DNS response with multiple answers
    dns_query = DNSRecord.question("multi.example.com", "A")
    dns_response = dns_query.reply()
    dns_response.add_answer(RR("multi.example.com", QTYPE.A, rdata=A("1.1.1.1"), ttl=300))
    dns_response.add_answer(RR("multi.example.com", QTYPE.A, rdata=A("2.2.2.2"), ttl=300))
    response_bytes = dns_response.pack()
    
    # Mock socket operations
    mock_socket = MagicMock()
    mock_socket.recvfrom.return_value = (response_bytes, ("8.8.8.8", 53))
    
    with patch('socket.socket', return_value=mock_socket):
        result = get_upstream_ip(upstream_url)
    
    # Should use first A record
    assert result == "https://1.1.1.1/dns-query"


def test_bootstrap_cache_success():
    """Test that successful resolutions are cached with long TTL."""
    # Clear cache before test
    clear_bootstrap_cache()
    
    upstream_url = "https://cache-test.example.com/dns-query"
    
    # Create a mock DNS response
    dns_query = DNSRecord.question("cache-test.example.com", "A")
    dns_response = dns_query.reply()
    dns_response.add_answer(RR("cache-test.example.com", QTYPE.A, rdata=A("10.0.0.1"), ttl=300))
    response_bytes = dns_response.pack()
    
    # Mock socket operations
    mock_socket = MagicMock()
    mock_socket.recvfrom.return_value = (response_bytes, ("8.8.8.8", 53))
    
    with patch('socket.socket', return_value=mock_socket):
        with patch('time.time', return_value=1000.0):
            result = get_upstream_ip(upstream_url)
    
    # Should resolve successfully
    assert result == "https://10.0.0.1/dns-query"
    
    # Check cache - should have entry with long TTL
    cache = get_bootstrap_cache()
    assert "cache-test.example.com" in cache
    cached_url, expiration, is_success = cache["cache-test.example.com"]
    assert cached_url == "https://10.0.0.1/dns-query"
    assert is_success is True
    assert expiration == 1000.0 + SUCCESS_TTL  # 1 hour from now
    
    # Second call should use cache (no socket call)
    with patch('socket.socket') as mock_socket_2:
        with patch('time.time', return_value=1001.0):  # 1 second later
            result2 = get_upstream_ip(upstream_url)
    
    assert result2 == "https://10.0.0.1/dns-query"
    mock_socket_2.assert_not_called()  # Cache was used, no socket call
    
    # Clean up
    clear_bootstrap_cache()


def test_bootstrap_cache_failure_short_ttl():
    """Test that failures are cached with short TTL to allow retry."""
    # Clear cache before test
    clear_bootstrap_cache()
    
    upstream_url = "https://fail-test.example.com/dns-query"
    
    # Mock socket to raise timeout
    mock_socket = MagicMock()
    mock_socket.recvfrom.side_effect = socket.timeout("Timeout")
    
    with patch('socket.socket', return_value=mock_socket):
        with patch('time.time', return_value=2000.0):
            result = get_upstream_ip(upstream_url)
    
    # Should return original URL on failure
    assert result == upstream_url
    
    # Check cache - should have entry with short TTL
    cache = get_bootstrap_cache()
    assert "fail-test.example.com" in cache
    cached_url, expiration, is_success = cache["fail-test.example.com"]
    assert cached_url == upstream_url
    assert is_success is False
    assert expiration == 2000.0 + FAILURE_TTL  # 30 seconds from now
    
    # Second call within TTL should use cache (no retry)
    with patch('socket.socket') as mock_socket_2:
        with patch('time.time', return_value=2010.0):  # 10 seconds later, still within 30s TTL
            result2 = get_upstream_ip(upstream_url)
    
    assert result2 == upstream_url
    mock_socket_2.assert_not_called()  # Cache was used
    
    # Clean up
    clear_bootstrap_cache()


def test_bootstrap_cache_expiration_retry():
    """Test that expired cache entries trigger a retry."""
    # Clear cache before test
    clear_bootstrap_cache()
    
    upstream_url = "https://retry-test.example.com/dns-query"
    
    # First call - timeout (failure)
    mock_socket_fail = MagicMock()
    mock_socket_fail.recvfrom.side_effect = socket.timeout("Timeout")
    
    with patch('socket.socket', return_value=mock_socket_fail):
        with patch('time.time', return_value=3000.0):
            result1 = get_upstream_ip(upstream_url)
    
    assert result1 == upstream_url
    
    # Cache should have failed entry
    cache = get_bootstrap_cache()
    assert "retry-test.example.com" in cache
    _, expiration, is_success = cache["retry-test.example.com"]
    assert is_success is False
    
    # Second call after TTL expires - now succeeds
    dns_query = DNSRecord.question("retry-test.example.com", "A")
    dns_response = dns_query.reply()
    dns_response.add_answer(RR("retry-test.example.com", QTYPE.A, rdata=A("10.0.0.2"), ttl=300))
    response_bytes = dns_response.pack()
    
    mock_socket_success = MagicMock()
    mock_socket_success.recvfrom.return_value = (response_bytes, ("8.8.8.8", 53))
    
    # After TTL expires (30 seconds + 1)
    with patch('socket.socket', return_value=mock_socket_success):
        with patch('time.time', return_value=3000.0 + FAILURE_TTL + 1):
            result2 = get_upstream_ip(upstream_url)
    
    # Should resolve successfully now
    assert result2 == "https://10.0.0.2/dns-query"
    
    # Cache should now have successful entry
    cache = get_bootstrap_cache()
    cached_url, _, is_success = cache["retry-test.example.com"]
    assert cached_url == "https://10.0.0.2/dns-query"
    assert is_success is True
    
    # Clean up
    clear_bootstrap_cache()


def test_bootstrap_cache_bypass():
    """Test that cache can be bypassed with use_cache=False."""
    # Clear cache before test
    clear_bootstrap_cache()
    
    upstream_url = "https://bypass-test.example.com/dns-query"
    
    # Create a mock DNS response
    dns_query = DNSRecord.question("bypass-test.example.com", "A")
    dns_response = dns_query.reply()
    dns_response.add_answer(RR("bypass-test.example.com", QTYPE.A, rdata=A("10.0.0.3"), ttl=300))
    response_bytes = dns_response.pack()
    
    # Mock socket operations
    mock_socket = MagicMock()
    mock_socket.recvfrom.return_value = (response_bytes, ("8.8.8.8", 53))
    
    # First call with caching
    with patch('socket.socket', return_value=mock_socket):
        result1 = get_upstream_ip(upstream_url, use_cache=True)
    
    assert result1 == "https://10.0.0.3/dns-query"
    assert mock_socket.sendto.call_count == 1
    
    # Second call with cache bypass should make another DNS query
    mock_socket.reset_mock()
    with patch('socket.socket', return_value=mock_socket):
        result2 = get_upstream_ip(upstream_url, use_cache=False)
    
    assert result2 == "https://10.0.0.3/dns-query"
    assert mock_socket.sendto.call_count == 1  # Made another query despite cache
    
    # Clean up
    clear_bootstrap_cache()

