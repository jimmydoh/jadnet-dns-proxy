"""Unit tests for the server module."""
import asyncio
import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from dnslib import DNSRecord, QTYPE, RR, A
from jadnet_dns_proxy.server import worker, cleaner_task, dns_cache


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
    
    # Mock cache to return data
    cache_key = ("cached.example.com.", "A")
    with patch.object(dns_cache, 'get', return_value=cached_bytes):
        # Setup queue item
        transport = Mock()
        transport.sendto = Mock()
        addr = ("127.0.0.1", 12345)
        await queue.put((request_bytes, addr, transport))
        
        # Setup mock client (should not be called for cache hit)
        mock_client = AsyncMock()
        
        # Create worker task
        worker_task = asyncio.create_task(worker("test-worker", queue, mock_client))
        
        # Wait for the queued item to be processed
        await queue.join()
        
        # Cancel worker
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        
        # Verify sendto was called with response
        transport.sendto.assert_called_once()
        sent_data = transport.sendto.call_args[0][0]
        sent_addr = transport.sendto.call_args[0][1]
        assert sent_addr == addr
        
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
    
    # Mock cache miss
    with patch.object(dns_cache, 'get', return_value=None), \
         patch.object(dns_cache, 'set') as mock_set:
        
        # Setup queue item
        transport = Mock()
        transport.sendto = Mock()
        addr = ("192.168.1.1", 54321)
        await queue.put((request_bytes, addr, transport))
        
        # Setup mock client to return response
        mock_client = AsyncMock()
        with patch('jadnet_dns_proxy.server.resolve_doh', 
                   return_value=(response_bytes, 600)) as mock_resolve:
            
            # Create worker task
            worker_task = asyncio.create_task(worker("test-worker", queue, mock_client))
            
            # Wait for worker to process
            await asyncio.sleep(0.1)
            
            # Cancel worker
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass
            
            # Verify resolve_doh was called
            mock_resolve.assert_called_once()
            
            # Verify sendto was called
            transport.sendto.assert_called_once_with(response_bytes, addr)
            
            # Verify cache.set was called
            mock_set.assert_called_once()
            call_args = mock_set.call_args[0]
            assert call_args[0] == ("uncached.example.com.", "A")
            assert call_args[1] == response_bytes
            assert call_args[2] == 600


@pytest.mark.asyncio
async def test_worker_resolve_error():
    """Test worker handling a resolution error."""
    queue = asyncio.Queue()
    
    request = DNSRecord.question("error.example.com", "A")
    request_bytes = request.pack()
    
    with patch.object(dns_cache, 'get', return_value=None):
        transport = Mock()
        transport.sendto = Mock()
        addr = ("10.0.0.1", 9999)
        await queue.put((request_bytes, addr, transport))
        
        mock_client = AsyncMock()
        # Mock resolve_doh to return None (error case)
        with patch('jadnet_dns_proxy.server.resolve_doh', return_value=(None, 0)):
            worker_task = asyncio.create_task(worker("test-worker", queue, mock_client))
            
            await asyncio.sleep(0.1)
            
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
    
    transport = Mock()
    transport.sendto = Mock()
    addr = ("10.0.0.1", 8888)
    await queue.put((invalid_data, addr, transport))
    
    mock_client = AsyncMock()
    
    worker_task = asyncio.create_task(worker("test-worker", queue, mock_client))
    
    await asyncio.sleep(0.1)
    
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
    with patch.object(dns_cache, 'prune') as mock_prune:
        # Mock sleep to avoid actually waiting
        with patch('asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
            # Make sleep raise CancelledError after first call to stop the loop
            mock_sleep.side_effect = [None, asyncio.CancelledError()]
            
            cleaner = asyncio.create_task(cleaner_task())
            
            try:
                await cleaner
            except asyncio.CancelledError:
                pass
            
            # Verify prune was called
            assert mock_prune.call_count >= 1
            # Verify sleep was called with 60 seconds
            mock_sleep.assert_called_with(60)


@pytest.mark.asyncio
async def test_worker_task_done_called():
    """Test that worker calls task_done on the queue."""
    queue = asyncio.Queue()
    
    request = DNSRecord.question("test.example.com", "A")
    request_bytes = request.pack()
    
    with patch.object(dns_cache, 'get', return_value=None):
        transport = Mock()
        addr = ("127.0.0.1", 12345)
        await queue.put((request_bytes, addr, transport))
        
        mock_client = AsyncMock()
        with patch('jadnet_dns_proxy.server.resolve_doh', return_value=(b"response", 300)):
            # Track task_done calls
            original_task_done = queue.task_done
            task_done_called = False
            
            def tracked_task_done():
                nonlocal task_done_called
                task_done_called = True
                original_task_done()
            
            queue.task_done = tracked_task_done
            
            worker_task = asyncio.create_task(worker("test-worker", queue, mock_client))
            
            await asyncio.sleep(0.1)
            
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass
            
            # Verify task_done was called
            assert task_done_called
