"""Unit tests for the bootstrap module."""
import pytest
from unittest.mock import Mock, patch, MagicMock
import socket
from dnslib import DNSRecord, QTYPE, RR, A
from jadnet_dns_proxy.bootstrap import get_upstream_ip


def test_get_upstream_ip_already_ip():
    """Test that IP addresses are returned unchanged."""
    # IPv4 address should be returned as-is
    result = get_upstream_ip("https://1.1.1.1/dns-query")
    assert result == "https://1.1.1.1/dns-query"


def test_get_upstream_ip_ipv6_literal():
    """Test that IPv6 addresses are returned unchanged."""
    # IPv6 address should be returned as-is
    result = get_upstream_ip("https://[2606:4700:4700::1111]/dns-query")
    assert result == "https://[2606:4700:4700::1111]/dns-query"
    
    # Compressed IPv6 address
    result = get_upstream_ip("https://[::1]/dns-query")
    assert result == "https://[::1]/dns-query"


def test_get_upstream_ip_non_canonical_ipv4_triggers_resolution():
    """Test that non-canonical IPv4 forms are treated as hostnames and trigger DNS resolution."""
    # Non-canonical forms like '1' should NOT be treated as IP addresses
    # They should trigger DNS resolution instead
    upstream_url = "https://1/dns-query"
    
    # Create a mock DNS response for hostname "1"
    dns_query = DNSRecord.question("1", "A")
    dns_response = dns_query.reply()
    dns_response.add_answer(RR("1", QTYPE.A, rdata=A("192.0.2.1"), ttl=300))
    response_bytes = dns_response.pack()
    
    # Mock socket operations
    mock_socket = MagicMock()
    mock_socket.__enter__.return_value = mock_socket
    mock_socket.recvfrom.return_value = (response_bytes, ("8.8.8.8", 53))
    
    with patch('socket.socket', return_value=mock_socket):
        result = get_upstream_ip(upstream_url)
    
    # Should have attempted DNS resolution, not returned the URL as-is
    mock_socket.sendto.assert_called_once()
    assert result == "https://192.0.2.1/dns-query"


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
    mock_socket.__enter__.return_value = mock_socket
    mock_socket.recvfrom.return_value = (response_bytes, ("8.8.8.8", 53))
    
    with patch('socket.socket', return_value=mock_socket):
        result = get_upstream_ip(upstream_url)
    
    # Should replace hostname with IP
    assert result == "https://104.16.248.249/dns-query"
    
    # Verify socket operations
    mock_socket.settimeout.assert_called_once_with(5.0)
    mock_socket.sendto.assert_called_once()
    mock_socket.recvfrom.assert_called_once_with(512)
    mock_socket.__exit__.assert_called_once()


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
    mock_socket.__enter__.return_value = mock_socket
    mock_socket.recvfrom.return_value = (response_bytes, ("8.8.8.8", 53))
    
    with patch('socket.socket', return_value=mock_socket):
        result = get_upstream_ip(upstream_url)
    
    # Should return original URL when no answers found
    assert result == upstream_url
    mock_socket.__exit__.assert_called_once()


def test_get_upstream_ip_socket_timeout():
    """Test handling of socket timeout during bootstrap."""
    upstream_url = "https://timeout.example.com/dns-query"
    
    # Mock socket to raise timeout
    mock_socket = MagicMock()
    mock_socket.__enter__.return_value = mock_socket
    mock_socket.recvfrom.side_effect = socket.timeout("Timeout")
    
    with patch('socket.socket', return_value=mock_socket):
        result = get_upstream_ip(upstream_url)
    
    # Should return original URL on timeout
    assert result == upstream_url
    mock_socket.__exit__.assert_called_once()


def test_get_upstream_ip_socket_error():
    """Test handling of socket errors during bootstrap."""
    upstream_url = "https://error.example.com/dns-query"
    
    # Mock socket to raise error
    mock_socket = MagicMock()
    mock_socket.__enter__.return_value = mock_socket
    mock_socket.sendto.side_effect = OSError("Network error")
    
    with patch('socket.socket', return_value=mock_socket):
        result = get_upstream_ip(upstream_url)
    
    # Should return original URL on error
    assert result == upstream_url
    mock_socket.__exit__.assert_called_once()


def test_get_upstream_ip_parse_error():
    """Test handling of invalid DNS response."""
    upstream_url = "https://invalid.example.com/dns-query"
    
    # Mock socket to return invalid data
    mock_socket = MagicMock()
    mock_socket.__enter__.return_value = mock_socket
    mock_socket.recvfrom.return_value = (b"invalid_dns_data", ("8.8.8.8", 53))
    
    with patch('socket.socket', return_value=mock_socket):
        result = get_upstream_ip(upstream_url)
    
    # Should return original URL when parsing fails
    assert result == upstream_url
    mock_socket.__exit__.assert_called_once()


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
    mock_socket.__enter__.return_value = mock_socket
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
    mock_socket.__enter__.return_value = mock_socket
    mock_socket.recvfrom.return_value = (response_bytes, ("8.8.8.8", 53))
    
    with patch('socket.socket', return_value=mock_socket):
        result = get_upstream_ip(upstream_url)
    
    # Should use first A record
    assert result == "https://1.1.1.1/dns-query"
