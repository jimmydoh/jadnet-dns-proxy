"""Unit tests for the DNS cache module."""
import time
import pytest
from unittest.mock import patch
from jadnet_dns_proxy.cache import DNSCache


class TestDNSCache:
    """Tests for the DNSCache class."""
    
    def test_cache_initialization(self):
        """Test that cache initializes correctly."""
        cache = DNSCache()
        assert cache._cache == {}
    
    @patch('jadnet_dns_proxy.cache.CACHE_ENABLED', True)
    def test_set_and_get_valid_entry(self):
        """Test setting and getting a valid cache entry."""
        cache = DNSCache()
        key = ("example.com.", "A")
        data = b"test_dns_response"
        ttl = 300
        
        cache.set(key, data, ttl)
        result = cache.get(key)
        
        assert result == data
    
    @patch('jadnet_dns_proxy.cache.CACHE_ENABLED', True)
    def test_get_expired_entry(self):
        """Test that expired entries are not returned."""
        cache = DNSCache()
        key = ("example.com.", "A")
        data = b"test_dns_response"
        
        # Manually insert an expired entry (bypassing the set method which clamps TTL)
        cache._cache[key] = (data, time.time() - 1)  # Already expired
        
        result = cache.get(key)
        assert result is None
        assert key not in cache._cache  # Should be removed lazily
    
    @patch('jadnet_dns_proxy.cache.CACHE_ENABLED', True)
    def test_get_nonexistent_entry(self):
        """Test getting a non-existent entry returns None."""
        cache = DNSCache()
        result = cache.get(("nonexistent.com.", "A"))
        assert result is None
    
    @patch('jadnet_dns_proxy.cache.CACHE_ENABLED', False)
    def test_cache_disabled_get(self):
        """Test that get returns None when caching is disabled."""
        cache = DNSCache()
        cache._cache[("example.com.", "A")] = (b"data", time.time() + 300)
        
        result = cache.get(("example.com.", "A"))
        assert result is None
    
    @patch('jadnet_dns_proxy.cache.CACHE_ENABLED', False)
    def test_cache_disabled_set(self):
        """Test that set doesn't cache when caching is disabled."""
        cache = DNSCache()
        cache.set(("example.com.", "A"), b"data", 300)
        
        assert cache._cache == {}
    
    @patch('jadnet_dns_proxy.cache.CACHE_ENABLED', True)
    def test_ttl_clamping_min(self):
        """Test that TTL is clamped to minimum of 60 seconds."""
        cache = DNSCache()
        key = ("example.com.", "A")
        data = b"test_dns_response"
        
        # Try to set with TTL less than 60
        cache.set(key, data, 30)
        
        # Verify entry exists
        assert cache.get(key) == data
        
        # Check that TTL was adjusted to at least 60 seconds
        entry = cache._cache[key]
        expiry_time = entry[1]
        # Should expire in at least 59 seconds (accounting for execution time)
        assert expiry_time > time.time() + 59
    
    @patch('jadnet_dns_proxy.cache.CACHE_ENABLED', True)
    def test_ttl_clamping_max(self):
        """Test that TTL is clamped to maximum of 3600 seconds."""
        cache = DNSCache()
        key = ("example.com.", "A")
        data = b"test_dns_response"
        
        # Try to set with TTL more than 3600
        cache.set(key, data, 7200)
        
        # Check that TTL was adjusted to at most 3600 seconds
        entry = cache._cache[key]
        expiry_time = entry[1]
        # Should expire in at most 3601 seconds (accounting for execution time)
        assert expiry_time < time.time() + 3601
    
    @patch('jadnet_dns_proxy.cache.CACHE_ENABLED', True)
    def test_prune_expired_entries(self):
        """Test that prune removes expired entries."""
        cache = DNSCache()
        
        # Add some entries with very short TTL
        cache._cache[("expired1.com.", "A")] = (b"data1", time.time() - 1)
        cache._cache[("expired2.com.", "A")] = (b"data2", time.time() - 1)
        cache._cache[("valid.com.", "A")] = (b"data3", time.time() + 300)
        
        cache.prune()
        
        # Expired entries should be removed
        assert ("expired1.com.", "A") not in cache._cache
        assert ("expired2.com.", "A") not in cache._cache
        # Valid entry should remain
        assert ("valid.com.", "A") in cache._cache
    
    @patch('jadnet_dns_proxy.cache.CACHE_ENABLED', True)
    def test_prune_no_expired_entries(self):
        """Test that prune doesn't affect valid entries."""
        cache = DNSCache()
        
        # Add only valid entries
        cache._cache[("valid1.com.", "A")] = (b"data1", time.time() + 300)
        cache._cache[("valid2.com.", "A")] = (b"data2", time.time() + 300)
        
        cache.prune()
        
        # All entries should remain
        assert len(cache._cache) == 2
    
    @patch('jadnet_dns_proxy.cache.CACHE_ENABLED', True)
    def test_multiple_keys(self):
        """Test cache with multiple different keys."""
        cache = DNSCache()
        
        keys = [
            ("example.com.", "A"),
            ("example.com.", "AAAA"),
            ("google.com.", "A"),
        ]
        
        for i, key in enumerate(keys):
            cache.set(key, f"data{i}".encode(), 300)
        
        # All keys should be retrievable
        for i, key in enumerate(keys):
            assert cache.get(key) == f"data{i}".encode()
