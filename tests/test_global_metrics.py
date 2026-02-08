"""Unit tests for the global_metrics module."""
import time
from unittest.mock import patch
from jadnet_dns_proxy.global_metrics import GlobalMetrics

import pytest


def test_global_metrics_initialization():
    """Test GlobalMetrics initialization."""
    metrics = GlobalMetrics()
    
    assert metrics.total_queries == 0
    assert metrics.cache_hits == 0
    assert metrics.cache_misses == 0
    assert metrics.response_times == []
    assert metrics.start_time > 0
    assert metrics.last_log_time > 0


def test_record_cache_hit():
    """Test recording a cache hit."""
    metrics = GlobalMetrics()
    
    metrics.record_cache_hit()
    
    assert metrics.total_queries == 1
    assert metrics.cache_hits == 1
    assert metrics.cache_misses == 0
    assert len(metrics.response_times) == 0


def test_record_multiple_cache_hits():
    """Test recording multiple cache hits."""
    metrics = GlobalMetrics()
    
    metrics.record_cache_hit()
    metrics.record_cache_hit()
    metrics.record_cache_hit()
    
    assert metrics.total_queries == 3
    assert metrics.cache_hits == 3
    assert metrics.cache_misses == 0


def test_record_cache_miss():
    """Test recording a cache miss with response time."""
    metrics = GlobalMetrics()
    
    metrics.record_cache_miss(0.123)
    
    assert metrics.total_queries == 1
    assert metrics.cache_hits == 0
    assert metrics.cache_misses == 1
    assert len(metrics.response_times) == 1
    assert metrics.response_times[0] == 0.123


def test_record_multiple_cache_misses():
    """Test recording multiple cache misses."""
    metrics = GlobalMetrics()
    
    metrics.record_cache_miss(0.1)
    metrics.record_cache_miss(0.2)
    metrics.record_cache_miss(0.3)
    
    assert metrics.total_queries == 3
    assert metrics.cache_hits == 0
    assert metrics.cache_misses == 3
    assert len(metrics.response_times) == 3
    assert metrics.response_times == [0.1, 0.2, 0.3]


def test_record_mixed_hits_and_misses():
    """Test recording a mix of cache hits and misses."""
    metrics = GlobalMetrics()
    
    metrics.record_cache_hit()
    metrics.record_cache_miss(0.15)
    metrics.record_cache_hit()
    metrics.record_cache_miss(0.25)
    
    assert metrics.total_queries == 4
    assert metrics.cache_hits == 2
    assert metrics.cache_misses == 2
    assert len(metrics.response_times) == 2
    assert metrics.response_times == [0.15, 0.25]


def test_response_times_bounded():
    """Test that response_times list is bounded to 1000 entries."""
    metrics = GlobalMetrics()
    
    # Add 1100 cache misses
    for i in range(1100):
        metrics.record_cache_miss(float(i))
    
    # Should only keep the last 1000
    assert len(metrics.response_times) == 1000
    assert metrics.response_times[0] == 100.0  # First kept entry
    assert metrics.response_times[-1] == 1099.0  # Last entry


def test_get_queries_per_minute():
    """Test calculating queries per minute."""
    with patch('jadnet_dns_proxy.global_metrics.time.time') as mock_time:
        # Start at time 0
        mock_time.return_value = 0.0
        metrics = GlobalMetrics()
        metrics.last_log_time = 0.0  # Ensure consistent test behavior
        
        # Record some queries
        metrics.record_cache_hit()
        metrics.record_cache_hit()
        metrics.record_cache_miss(0.1)
        
        # Advance time by 1 minute (60 seconds)
        mock_time.return_value = 60.0
        
        qpm = metrics.get_queries_per_minute()
        assert qpm == 3.0  # 3 queries in 1 minute


def test_get_queries_per_minute_zero_elapsed():
    """Test queries per minute when no time has elapsed."""
    metrics = GlobalMetrics()
    
    metrics.record_cache_hit()
    
    # Immediately check (no time elapsed)
    qpm = metrics.get_queries_per_minute()
    assert qpm >= 0.0  # Should not crash


def test_get_cache_hit_rate():
    """Test calculating cache hit rate."""
    metrics = GlobalMetrics()
    
    metrics.record_cache_hit()
    metrics.record_cache_hit()
    metrics.record_cache_hit()
    metrics.record_cache_miss(0.1)
    
    hit_rate = metrics.get_cache_hit_rate()
    assert hit_rate == 75.0  # 3 hits out of 4 total


def test_get_cache_hit_rate_no_queries():
    """Test cache hit rate when no queries have been made."""
    metrics = GlobalMetrics()
    
    hit_rate = metrics.get_cache_hit_rate()
    assert hit_rate == 0.0


def test_get_cache_hit_rate_all_hits():
    """Test cache hit rate when all queries are hits."""
    metrics = GlobalMetrics()
    
    metrics.record_cache_hit()
    metrics.record_cache_hit()
    
    hit_rate = metrics.get_cache_hit_rate()
    assert hit_rate == 100.0


def test_get_cache_hit_rate_all_misses():
    """Test cache hit rate when all queries are misses."""
    metrics = GlobalMetrics()
    
    metrics.record_cache_miss(0.1)
    metrics.record_cache_miss(0.2)
    
    hit_rate = metrics.get_cache_hit_rate()
    assert hit_rate == 0.0


def test_get_min_response_time():
    """Test getting minimum response time."""
    metrics = GlobalMetrics()
    
    metrics.record_cache_miss(0.3)
    metrics.record_cache_miss(0.1)
    metrics.record_cache_miss(0.5)
    
    min_time = metrics.get_min_response_time()
    assert min_time == 0.1


def test_get_min_response_time_no_data():
    """Test minimum response time with no data."""
    metrics = GlobalMetrics()
    
    min_time = metrics.get_min_response_time()
    assert min_time == 0.0


def test_get_mean_response_time():
    """Test getting mean response time."""
    metrics = GlobalMetrics()
    
    metrics.record_cache_miss(0.1)
    metrics.record_cache_miss(0.2)
    metrics.record_cache_miss(0.3)
    
    mean_time = metrics.get_mean_response_time()
    assert abs(mean_time - 0.2) < 0.001  # Use approximate comparison


def test_get_mean_response_time_no_data():
    """Test mean response time with no data."""
    metrics = GlobalMetrics()
    
    mean_time = metrics.get_mean_response_time()
    assert mean_time == 0.0


def test_get_max_response_time():
    """Test getting maximum response time."""
    metrics = GlobalMetrics()
    
    metrics.record_cache_miss(0.1)
    metrics.record_cache_miss(0.5)
    metrics.record_cache_miss(0.3)
    
    max_time = metrics.get_max_response_time()
    assert max_time == 0.5


def test_get_max_response_time_no_data():
    """Test maximum response time with no data."""
    metrics = GlobalMetrics()
    
    max_time = metrics.get_max_response_time()
    assert max_time == 0.0


def test_log_stats(caplog):
    """Test logging statistics."""
    import logging
    caplog.set_level(logging.INFO)
    
    with patch('jadnet_dns_proxy.global_metrics.time.time') as mock_time:
        # Start at time 0
        mock_time.return_value = 0.0
        metrics = GlobalMetrics()
        metrics.last_log_time = 0.0  # Ensure consistent test behavior
        
        # Record some metrics
        metrics.record_cache_hit()
        metrics.record_cache_hit()
        metrics.record_cache_miss(0.1)
        metrics.record_cache_miss(0.3)
        
        # Advance time by 2 minutes (120 seconds)
        mock_time.return_value = 120.0
        
        metrics.log_stats()
        
        # Check that stats were logged
        assert any("Global Metrics" in record.message for record in caplog.records)
        assert any("Queries/min: 2.0" in record.message for record in caplog.records)
        assert any("Cache: 2 hits / 2 misses (50.0% hit rate)" in record.message for record in caplog.records)
        assert any("min=0.100s, mean=0.200s, max=0.300s" in record.message for record in caplog.records)


def test_log_stats_resets_counters():
    """Test that log_stats resets counters for next interval."""
    with patch('jadnet_dns_proxy.global_metrics.time.time') as mock_time:
        # Start at time 0
        mock_time.return_value = 0.0
        metrics = GlobalMetrics()
        
        # Record some metrics
        metrics.record_cache_hit()
        metrics.record_cache_miss(0.1)
        
        # Advance time
        mock_time.return_value = 60.0
        
        # Log stats (this should reset counters)
        metrics.log_stats()
        
        # Verify counters were reset
        assert metrics.total_queries == 0
        assert metrics.cache_hits == 0
        assert metrics.cache_misses == 0
        assert metrics.response_times == []
        assert metrics.last_log_time == 60.0


def test_log_stats_with_no_data(caplog):
    """Test logging statistics when no data has been recorded."""
    import logging
    caplog.set_level(logging.INFO)
    
    metrics = GlobalMetrics()
    
    # Log stats without recording any data
    metrics.log_stats()
    
    # Should still log without crashing and without response time stats
    assert any("Global Metrics" in record.message for record in caplog.records)
    assert any("Queries/min:" in record.message for record in caplog.records)
    # Response time stats should not be present when there's no data
    info_messages = [record.message for record in caplog.records if record.levelname == "INFO"]
    response_time_msg = [msg for msg in info_messages if "Queries/min:" in msg][0]
    assert "Response times:" not in response_time_msg


def test_log_stats_with_only_cache_hits(caplog):
    """Test logging statistics when only cache hits are recorded (no response times)."""
    import logging
    caplog.set_level(logging.INFO)
    
    with patch('jadnet_dns_proxy.global_metrics.time.time') as mock_time:
        # Start at time 0
        mock_time.return_value = 0.0
        metrics = GlobalMetrics()
        metrics.last_log_time = 0.0  # Ensure consistent test behavior
        
        # Record only cache hits (no cache misses, so no response times)
        metrics.record_cache_hit()
        metrics.record_cache_hit()
        metrics.record_cache_hit()
        
        # Advance time by 1 minute
        mock_time.return_value = 60.0
        
        metrics.log_stats()
        
        # Check that stats were logged
        assert any("Global Metrics" in record.message for record in caplog.records)
        assert any("Queries/min: 3.0" in record.message for record in caplog.records)
        assert any("Cache: 3 hits / 0 misses (100.0% hit rate)" in record.message for record in caplog.records)
        
        # Response time stats should not be present when there are only cache hits
        info_messages = [record.message for record in caplog.records if record.levelname == "INFO"]
        response_time_msg = [msg for msg in info_messages if "Queries/min:" in msg][0]
        assert "Response times:" not in response_time_msg
