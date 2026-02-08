"""Unit tests for the server module."""
import asyncio
import signal
from unittest.mock import Mock, AsyncMock, patch
from dnslib import DNSRecord, QTYPE, RR, A
from jadnet_dns_proxy.server import worker, cleaner_task, stats_task, main
from jadnet_dns_proxy.cache import DNSCache
from jadnet_dns_proxy.upstream_manager import UpstreamManager
from jadnet_dns_proxy.global_metrics import GlobalMetrics

import pytest


@pytest.mark.asyncio
async def test_worker_cache_hit():
    """Test worker handling a cache hit."""
    queue = asyncio.Queue()
    
    # Create a DNS request
    request = DNSRecord.question("cached.example.com", "A")
    request_bytes = request.pack()
    
    # Create a cached response
    response = request.reply()
    response.add_answer(RR("cached.example.com", QTYPE.A, rdata=A("1.2.3.4"), ttl=300))
    cached_bytes = response.pack()
    
    # Create mock cache that returns data
    mock_cache = Mock()
    mock_cache.get = Mock(return_value=cached_bytes)
    
    # Setup queue item
    transport = Mock()
    transport.sendto = Mock()
    addr = ("127.0.0.1", 12345)
    await queue.put((request_bytes, addr, transport))
    
    # Setup mock client (should not be called for cache hit)
    mock_client = AsyncMock()
    
    # Setup mock upstream manager (should not be called for cache hit)
    mock_upstream_manager = Mock()
    
    # Setup mock global metrics
    mock_global_metrics = Mock()
    mock_global_metrics.record_cache_hit = Mock()
    
    # Create worker task with cache, upstream_manager, and global_metrics parameters
    worker_task = asyncio.create_task(worker("test-worker", queue, mock_client, mock_cache, mock_upstream_manager, mock_global_metrics))
    
    # Wait for the queued item to be processed
    await queue.join()
    
    # Cancel worker
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        # Expected when shutting down the worker task during the test.
        pass
    
    # Verify sendto was called with response
    transport.sendto.assert_called_once()
    sent_data = transport.sendto.call_args[0][0]
    sent_addr = transport.sendto.call_args[0][1]
    assert sent_addr == addr
    
    # Verify cache.get was called with the expected key
    mock_cache.get.assert_called_once_with(("cached.example.com.", "A"))
    
    # Verify global_metrics.record_cache_hit was called
    mock_global_metrics.record_cache_hit.assert_called_once()
    
    # Parse and verify the response
    sent_response = DNSRecord.parse(sent_data)
    assert sent_response.header.id == request.header.id


@pytest.mark.asyncio
async def test_worker_cache_miss():
    """Test worker handling a cache miss."""
    queue = asyncio.Queue()
    
    # Create a DNS request
    request = DNSRecord.question("uncached.example.com", "A")
    request_bytes = request.pack()
    
    # Create a DoH response
    response = request.reply()
    response.add_answer(RR("uncached.example.com", QTYPE.A, rdata=A("5.6.7.8"), ttl=600))
    response_bytes = response.pack()
    
    # Create mock cache that returns None (cache miss)
    mock_cache = Mock()
    mock_cache.get = Mock(return_value=None)
    mock_cache.set = Mock()
    
    # Setup queue item
    transport = Mock()
    transport.sendto = Mock()
    addr = ("192.168.1.1", 54321)
    await queue.put((request_bytes, addr, transport))
    
    # Setup mock client to return response
    mock_client = AsyncMock()
    
    # Setup mock upstream manager
    mock_upstream_manager = Mock()
    
    # Setup mock global metrics
    mock_global_metrics = Mock()
    mock_global_metrics.record_cache_miss = Mock()
    
    with patch('jadnet_dns_proxy.server.resolve_doh', 
               return_value=(response_bytes, 600)) as mock_resolve:
        
        # Create worker task with cache, upstream_manager, and global_metrics parameters
        worker_task = asyncio.create_task(worker("test-worker", queue, mock_client, mock_cache, mock_upstream_manager, mock_global_metrics))
        
        # Wait for the queued item to be processed
        await queue.join()
        
        # Cancel worker
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        
        # Verify resolve_doh was called with upstream_manager
        mock_resolve.assert_called_once()
        call_args = mock_resolve.call_args[0]
        assert call_args[2] == mock_upstream_manager
        
        # Verify sendto was called
        transport.sendto.assert_called_once_with(response_bytes, addr)
        
        # Verify cache.set was called
        mock_cache.set.assert_called_once()
        call_args = mock_cache.set.call_args[0]
        assert call_args[0] == ("uncached.example.com.", "A")
        assert call_args[1] == response_bytes
        assert call_args[2] == 600
        
        # Verify global_metrics.record_cache_miss was called
        mock_global_metrics.record_cache_miss.assert_called_once()


@pytest.mark.asyncio
async def test_worker_resolve_error():
    """Test worker handling a resolution error."""
    queue = asyncio.Queue()
    
    request = DNSRecord.question("error.example.com", "A")
    request_bytes = request.pack()
    
    # Create mock cache that returns None (cache miss)
    mock_cache = Mock()
    mock_cache.get = Mock(return_value=None)
    
    transport = Mock()
    transport.sendto = Mock()
    addr = ("10.0.0.1", 9999)
    await queue.put((request_bytes, addr, transport))
    
    mock_client = AsyncMock()
    mock_upstream_manager = Mock()
    
    # Setup mock global metrics
    mock_global_metrics = Mock()
    mock_global_metrics.record_cache_miss = Mock()
    
    # Mock resolve_doh to return None (error case)
    with patch('jadnet_dns_proxy.server.resolve_doh', return_value=(None, 0)):
        worker_task = asyncio.create_task(worker("test-worker", queue, mock_client, mock_cache, mock_upstream_manager, mock_global_metrics))
        
        # Wait for the queued item to be processed
        await queue.join()
        
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        
        # Verify sendto was NOT called (no response to send)
        transport.sendto.assert_not_called()


@pytest.mark.asyncio
async def test_worker_invalid_dns_packet():
    """Test worker handling an invalid DNS packet."""
    queue = asyncio.Queue()
    
    # Invalid DNS data
    invalid_data = b"not_a_valid_dns_packet"
    
    # Create mock cache (won't be used due to parsing error)
    mock_cache = Mock()
    
    transport = Mock()
    transport.sendto = Mock()
    addr = ("10.0.0.1", 8888)
    await queue.put((invalid_data, addr, transport))
    
    mock_client = AsyncMock()
    mock_upstream_manager = Mock()
    
    # Setup mock global metrics
    mock_global_metrics = Mock()
    
    worker_task = asyncio.create_task(worker("test-worker", queue, mock_client, mock_cache, mock_upstream_manager, mock_global_metrics))
    
    # Wait for the queued item to be processed
    await queue.join()
    
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    
    # Should not crash, just handle the error gracefully
    transport.sendto.assert_not_called()


@pytest.mark.asyncio
async def test_cleaner_task():
    """Test that cleaner_task calls prune periodically."""
    # Create mock cache
    mock_cache = Mock()
    mock_cache.prune = Mock()
    
    # Mock sleep to avoid actually waiting
    with patch('asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
        # Make sleep raise CancelledError after first call to stop the loop
        mock_sleep.side_effect = [None, asyncio.CancelledError()]
        
        cleaner = asyncio.create_task(cleaner_task(mock_cache))
        
        try:
            await cleaner
        except asyncio.CancelledError:
            pass
        
        # Verify prune was called
        assert mock_cache.prune.call_count >= 1
        # Verify sleep was called with 60 seconds
        mock_sleep.assert_called_with(60)


@pytest.mark.asyncio
async def test_stats_task():
    """Test that stats_task calls log_stats periodically."""
    # Create mock upstream manager
    mock_upstream_manager = Mock()
    mock_upstream_manager.log_stats = Mock()
    
    # Create mock global metrics
    mock_global_metrics = Mock()
    mock_global_metrics.log_stats = Mock()
    
    # Mock sleep to avoid actually waiting
    with patch('asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
        # Make sleep raise CancelledError after first call to stop the loop
        mock_sleep.side_effect = [None, asyncio.CancelledError()]
        
        stats = asyncio.create_task(stats_task(mock_upstream_manager, mock_global_metrics))
        
        try:
            await stats
        except asyncio.CancelledError:
            pass
        
        # Verify log_stats was called on both managers
        assert mock_upstream_manager.log_stats.call_count >= 1
        assert mock_global_metrics.log_stats.call_count >= 1
        # Verify sleep was called with 300 seconds
        mock_sleep.assert_called_with(300)


@pytest.mark.asyncio
async def test_worker_task_done_called():
    """Test that worker calls task_done on the queue."""
    queue = asyncio.Queue()
    
    request = DNSRecord.question("test.example.com", "A")
    request_bytes = request.pack()
    
    # Create mock cache that returns None (cache miss)
    mock_cache = Mock()
    mock_cache.get = Mock(return_value=None)
    
    transport = Mock()
    addr = ("127.0.0.1", 12345)
    await queue.put((request_bytes, addr, transport))
    
    mock_client = AsyncMock()
    mock_upstream_manager = Mock()
    
    # Setup mock global metrics
    mock_global_metrics = Mock()
    mock_global_metrics.record_cache_miss = Mock()
    
    with patch('jadnet_dns_proxy.server.resolve_doh', return_value=(b"response", 300)):
        # Track task_done calls
        original_task_done = queue.task_done
        task_done_called = False
        
        def tracked_task_done():
            nonlocal task_done_called
            task_done_called = True
            original_task_done()
        
        queue.task_done = tracked_task_done
        
        worker_task = asyncio.create_task(worker("test-worker", queue, mock_client, mock_cache, mock_upstream_manager, mock_global_metrics))
        
        # Wait for the queued item to be processed
        await queue.join()
        
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        
        # Verify task_done was called
        assert task_done_called


@pytest.mark.asyncio
async def test_worker_cache_hit_debug_logging(caplog):
    """Test that cache hit logs at DEBUG level."""
    import logging
    caplog.set_level(logging.DEBUG)
    
    queue = asyncio.Queue()
    
    # Create a DNS request
    request = DNSRecord.question("cached.example.com", "A")
    request_bytes = request.pack()
    
    # Create a cached response
    response = request.reply()
    response.add_answer(RR("cached.example.com", QTYPE.A, rdata=A("1.2.3.4"), ttl=300))
    cached_bytes = response.pack()
    
    # Create mock cache that returns data
    mock_cache = Mock()
    mock_cache.get = Mock(return_value=cached_bytes)
    
    # Setup queue item
    transport = Mock()
    transport.sendto = Mock()
    addr = ("127.0.0.1", 12345)
    await queue.put((request_bytes, addr, transport))
    
    # Setup mock client
    mock_client = AsyncMock()
    mock_upstream_manager = Mock()
    
    # Setup mock global metrics
    mock_global_metrics = Mock()
    mock_global_metrics.record_cache_hit = Mock()
    
    # Create worker task
    worker_task = asyncio.create_task(worker("test-worker", queue, mock_client, mock_cache, mock_upstream_manager, mock_global_metrics))
    
    # Wait for the queued item to be processed
    await queue.join()
    
    # Cancel worker
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    
    # Verify that cache hit was logged at DEBUG level
    assert any("[CACHE] cached.example.com." in record.message for record in caplog.records if record.levelname == "DEBUG")


@pytest.mark.asyncio
async def test_worker_upstream_request_debug_logging(caplog):
    """Test that upstream request logs at DEBUG level."""
    import logging
    caplog.set_level(logging.DEBUG)
    
    queue = asyncio.Queue()
    
    # Create a DNS request
    request = DNSRecord.question("uncached.example.com", "A")
    request_bytes = request.pack()
    
    # Create a DoH response
    response = request.reply()
    response.add_answer(RR("uncached.example.com", QTYPE.A, rdata=A("5.6.7.8"), ttl=600))
    response_bytes = response.pack()
    
    # Create mock cache that returns None (cache miss)
    mock_cache = Mock()
    mock_cache.get = Mock(return_value=None)
    mock_cache.set = Mock()
    
    # Setup queue item
    transport = Mock()
    transport.sendto = Mock()
    addr = ("192.168.1.1", 54321)
    await queue.put((request_bytes, addr, transport))
    
    # Setup mock client
    mock_client = AsyncMock()
    mock_upstream_manager = Mock()
    
    # Setup mock global metrics
    mock_global_metrics = Mock()
    mock_global_metrics.record_cache_miss = Mock()
    
    with patch('jadnet_dns_proxy.server.resolve_doh', 
               return_value=(response_bytes, 600)):
        
        # Create worker task
        worker_task = asyncio.create_task(worker("test-worker", queue, mock_client, mock_cache, mock_upstream_manager, mock_global_metrics))
        
        # Wait for the queued item to be processed
        await queue.join()
        
        # Cancel worker
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        
        # Verify that upstream request was logged at DEBUG level
        assert any("[UPSTREAM] uncached.example.com." in record.message for record in caplog.records if record.levelname == "DEBUG")


@pytest.mark.asyncio
async def test_worker_no_verbose_logging_at_info_level(caplog):
    """Test that per-request logs don't appear at INFO level."""
    import logging
    caplog.set_level(logging.INFO)
    
    queue = asyncio.Queue()
    
    # Create a DNS request
    request = DNSRecord.question("test.example.com", "A")
    request_bytes = request.pack()
    
    # Create a cached response
    response = request.reply()
    response.add_answer(RR("test.example.com", QTYPE.A, rdata=A("1.2.3.4"), ttl=300))
    cached_bytes = response.pack()
    
    # Create mock cache that returns data
    mock_cache = Mock()
    mock_cache.get = Mock(return_value=cached_bytes)
    
    # Setup queue item
    transport = Mock()
    transport.sendto = Mock()
    addr = ("127.0.0.1", 12345)
    await queue.put((request_bytes, addr, transport))
    
    # Setup mock client
    mock_client = AsyncMock()
    mock_upstream_manager = Mock()
    
    # Setup mock global metrics
    mock_global_metrics = Mock()
    mock_global_metrics.record_cache_hit = Mock()
    
    # Create worker task
    worker_task = asyncio.create_task(worker("test-worker", queue, mock_client, mock_cache, mock_upstream_manager, mock_global_metrics))
    
    # Wait for the queued item to be processed
    await queue.join()
    
    # Cancel worker
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    
    # Verify that per-request logs don't appear at INFO level
    info_records = [record for record in caplog.records if record.levelname == "INFO"]
    assert not any("[CACHE]" in record.message for record in info_records)
    assert not any("[UPSTREAM]" in record.message for record in info_records)
async def test_main_signal_handler_not_implemented():
    """Test that main() handles NotImplementedError for signal handlers (Windows compatibility)."""
    # Mock all the dependencies
    with patch('jadnet_dns_proxy.server.CustomDNSTransport') as mock_transport_class, \
         patch('jadnet_dns_proxy.server.httpx.AsyncClient') as mock_client_class, \
         patch('jadnet_dns_proxy.server.asyncio.get_running_loop') as mock_get_loop, \
         patch('jadnet_dns_proxy.server.asyncio.create_task') as mock_create_task, \
         patch('jadnet_dns_proxy.server.asyncio.Event') as mock_event_class, \
         patch('jadnet_dns_proxy.server.logger') as mock_logger:
        
        # Setup CustomDNSTransport mock
        mock_transport = AsyncMock()
        mock_transport.__aenter__ = AsyncMock(return_value=mock_transport)
        mock_transport.__aexit__ = AsyncMock(return_value=None)
        mock_transport_class.return_value = mock_transport
        
        # Setup mock loop
        mock_loop = Mock()
        mock_get_loop.return_value = mock_loop
        
        # Mock the loop.create_datagram_endpoint to return transport and protocol
        mock_transport = Mock()
        mock_protocol = Mock()
        mock_loop.create_datagram_endpoint = AsyncMock(return_value=(mock_transport, mock_protocol))
        
        # Make add_signal_handler raise NotImplementedError (simulating Windows)
        mock_loop.add_signal_handler = Mock(side_effect=NotImplementedError("Signal handlers not supported"))
        
        # Setup mock event
        mock_event = Mock()
        mock_event_class.return_value = mock_event
        
        # Make the event.wait() return immediately to avoid blocking
        mock_event.wait = AsyncMock()
        
        # Setup mock client context manager
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_class.return_value = mock_client
        
        # Setup mock tasks
        mock_task = Mock()
        mock_task.cancel = Mock()
        mock_create_task.return_value = mock_task
        
        # Mock asyncio.gather to return immediately
        with patch('jadnet_dns_proxy.server.asyncio.gather', new_callable=AsyncMock):
            # Run main
            await main()
        
        # Verify that add_signal_handler was called (and raised NotImplementedError)
        assert mock_loop.add_signal_handler.called
        
        # Verify that the warning was logged about signal handlers not being supported
        warning_calls = [call for call in mock_logger.warning.call_args_list 
                         if "Signal handlers not supported" in str(call)]
        assert len(warning_calls) == 1
        assert "Windows systems" in str(warning_calls[0])

