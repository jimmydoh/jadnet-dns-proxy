"""Unit tests for the upstream manager module."""
import pytest
import asyncio
from jadnet_dns_proxy.upstream_manager import UpstreamServer, UpstreamManager


class TestUpstreamServer:
    """Tests for UpstreamServer class."""
    
    def test_server_initialization(self):
        """Test that a server is initialized with correct defaults."""
        server = UpstreamServer(url="https://1.1.1.1/dns-query")
        
        assert server.url == "https://1.1.1.1/dns-query"
        assert server.is_up is True
        assert server.total_requests == 0
        assert server.failed_requests == 0
        assert len(server.response_times) == 0
        assert server.avg_response_time == 0.0
        assert server.success_rate == 100.0
    
    def test_record_success(self):
        """Test recording a successful request."""
        server = UpstreamServer(url="https://1.1.1.1/dns-query")
        
        server.record_success(0.150)
        
        assert server.total_requests == 1
        assert server.failed_requests == 0
        assert len(server.response_times) == 1
        assert server.response_times[0] == 0.150
        assert server.avg_response_time == pytest.approx(0.150)
        assert server.success_rate == 100.0
        assert server.is_up is True
    
    def test_record_multiple_successes(self):
        """Test recording multiple successful requests."""
        server = UpstreamServer(url="https://1.1.1.1/dns-query")
        
        server.record_success(0.100)
        server.record_success(0.200)
        server.record_success(0.150)
        
        assert server.total_requests == 3
        assert server.failed_requests == 0
        assert len(server.response_times) == 3
        assert server.avg_response_time == pytest.approx(0.150)
        assert server.success_rate == 100.0
    
    def test_record_failure(self):
        """Test recording a failed request."""
        server = UpstreamServer(url="https://1.1.1.1/dns-query")
        
        server.record_failure()
        
        assert server.total_requests == 1
        assert server.failed_requests == 1
        assert server.success_rate == 0.0
        # Server should still be up with only 1 failure
        assert server.is_up is True
    
    def test_server_marked_down_on_high_failure_rate(self):
        """Test that server is marked down when failure rate is too high."""
        server = UpstreamServer(url="https://1.1.1.1/dns-query")
        
        # Record enough failures to trigger down status
        for _ in range(5):
            server.record_failure()
        
        assert server.total_requests == 5
        assert server.failed_requests == 5
        assert server.success_rate == 0.0
        assert server.is_up is False
    
    def test_server_marked_down_on_partial_failure_rate(self):
        """Test that server is marked down when success rate drops below 50%."""
        server = UpstreamServer(url="https://1.1.1.1/dns-query")
        
        # 2 successes, 4 failures = 33% success rate
        server.record_success(0.100)
        server.record_success(0.150)
        server.record_failure()
        server.record_failure()
        server.record_failure()
        server.record_failure()
        
        assert server.total_requests == 6
        assert server.failed_requests == 4
        assert server.success_rate == pytest.approx(33.33, rel=0.1)
        assert server.is_up is False
    
    def test_server_recovery_after_success(self):
        """Test that server is marked up after a successful request."""
        server = UpstreamServer(url="https://1.1.1.1/dns-query")
        
        # Mark server down
        for _ in range(5):
            server.record_failure()
        assert server.is_up is False
        
        # Record success should mark it back up
        server.record_success(0.100)
        assert server.is_up is True
    
    def test_response_times_bounded(self):
        """Test that response times list is kept bounded at 100 entries."""
        server = UpstreamServer(url="https://1.1.1.1/dns-query")
        
        # Record 150 successes
        for i in range(150):
            server.record_success(0.100 + i * 0.001)
        
        # Should only keep last 100
        assert len(server.response_times) == 100
        assert server.total_requests == 150


class TestUpstreamManager:
    """Tests for UpstreamManager class."""
    
    def test_manager_initialization_single_upstream(self):
        """Test manager initialization with a single upstream."""
        manager = UpstreamManager(["https://1.1.1.1/dns-query"])
        
        assert len(manager.servers) == 1
        assert manager.servers[0].url == "https://1.1.1.1/dns-query"
        assert manager.current_index == 0
    
    def test_manager_initialization_multiple_upstreams(self):
        """Test manager initialization with multiple upstreams."""
        urls = [
            "https://1.1.1.1/dns-query",
            "https://1.0.0.1/dns-query",
            "https://dns.google/dns-query"
        ]
        manager = UpstreamManager(urls)
        
        assert len(manager.servers) == 3
        for i, url in enumerate(urls):
            assert manager.servers[i].url == url
    
    def test_manager_initialization_empty_list_raises_error(self):
        """Test that initializing with empty list raises an error."""
        with pytest.raises(ValueError, match="At least one upstream URL must be provided"):
            UpstreamManager([])
    
    @pytest.mark.asyncio
    async def test_get_next_server_single_upstream(self):
        """Test getting next server with single upstream."""
        manager = UpstreamManager(["https://1.1.1.1/dns-query"])
        
        server1 = await manager.get_next_server()
        server2 = await manager.get_next_server()
        
        assert server1 is not None
        assert server2 is not None
        assert server1.url == "https://1.1.1.1/dns-query"
        assert server2.url == "https://1.1.1.1/dns-query"
    
    @pytest.mark.asyncio
    async def test_get_next_server_round_robin(self):
        """Test that servers are returned in round-robin fashion."""
        urls = [
            "https://1.1.1.1/dns-query",
            "https://1.0.0.1/dns-query",
            "https://dns.google/dns-query"
        ]
        manager = UpstreamManager(urls)
        
        # Get servers in sequence
        servers = []
        for _ in range(6):
            server = await manager.get_next_server()
            servers.append(server.url)
        
        # Should cycle through all servers
        expected = [
            "https://1.1.1.1/dns-query",
            "https://1.0.0.1/dns-query",
            "https://dns.google/dns-query",
            "https://1.1.1.1/dns-query",
            "https://1.0.0.1/dns-query",
            "https://dns.google/dns-query"
        ]
        assert servers == expected
    
    @pytest.mark.asyncio
    async def test_get_next_server_skips_down_servers(self):
        """Test that down servers are skipped."""
        urls = [
            "https://1.1.1.1/dns-query",
            "https://1.0.0.1/dns-query",
            "https://dns.google/dns-query"
        ]
        manager = UpstreamManager(urls)
        
        # Mark second server as down
        manager.servers[1].is_up = False
        
        # Get servers
        servers = []
        for _ in range(4):
            server = await manager.get_next_server()
            servers.append(server.url)
        
        # Should only cycle through servers 0 and 2
        expected = [
            "https://1.1.1.1/dns-query",
            "https://dns.google/dns-query",
            "https://1.1.1.1/dns-query",
            "https://dns.google/dns-query"
        ]
        assert servers == expected
    
    @pytest.mark.asyncio
    async def test_get_next_server_all_down_returns_best(self):
        """Test that when all servers are down, the best one is returned."""
        urls = [
            "https://1.1.1.1/dns-query",
            "https://1.0.0.1/dns-query"
        ]
        manager = UpstreamManager(urls)
        
        # Mark all servers down with different success rates
        manager.servers[0].is_up = False
        manager.servers[0].total_requests = 10
        manager.servers[0].failed_requests = 8  # 20% success rate
        
        manager.servers[1].is_up = False
        manager.servers[1].total_requests = 10
        manager.servers[1].failed_requests = 5  # 50% success rate
        
        # Should return server with better success rate
        server = await manager.get_next_server()
        assert server.url == "https://1.0.0.1/dns-query"
    
    def test_get_stats(self):
        """Test getting statistics for all servers."""
        urls = [
            "https://1.1.1.1/dns-query",
            "https://1.0.0.1/dns-query"
        ]
        manager = UpstreamManager(urls)
        
        # Record some activity
        manager.servers[0].record_success(0.150)
        manager.servers[0].record_success(0.250)
        manager.servers[1].record_failure()
        
        stats = manager.get_stats()
        
        assert len(stats) == 2
        assert stats[0]['url'] == "https://1.1.1.1/dns-query"
        assert stats[0]['is_up'] is True
        assert stats[0]['total_requests'] == 2
        assert stats[0]['failed_requests'] == 0
        assert stats[0]['success_rate'] == "100.0%"
        
        assert stats[1]['url'] == "https://1.0.0.1/dns-query"
        assert stats[1]['is_up'] is True
        assert stats[1]['total_requests'] == 1
        assert stats[1]['failed_requests'] == 1
        assert stats[1]['success_rate'] == "0.0%"
    
    def test_log_stats(self, caplog):
        """Test logging statistics."""
        import logging
        
        # Set caplog to capture logs at INFO level
        caplog.set_level(logging.INFO, logger='async-doh')
        
        urls = ["https://1.1.1.1/dns-query"]
        manager = UpstreamManager(urls)
        
        manager.servers[0].record_success(0.100)
        
        manager.log_stats()
        
        # Check that log messages were created
        assert len(caplog.records) > 0
        # Verify that the stats message is in the logs
        log_messages = [record.message for record in caplog.records]
        assert any("Upstream Server Statistics" in msg for msg in log_messages)
