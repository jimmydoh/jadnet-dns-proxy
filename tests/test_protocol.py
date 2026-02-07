"""Unit tests for the DNS protocol module."""
import asyncio
import pytest
from unittest.mock import Mock, MagicMock
from jadnet_dns_proxy.protocol import DNSProtocol


class TestDNSProtocol:
    """Tests for the DNSProtocol class."""
    
    def test_protocol_initialization(self):
        """Test that protocol initializes correctly."""
        queue = asyncio.Queue()
        protocol = DNSProtocol(queue)
        
        assert protocol.queue is queue
        assert protocol.transport is None
    
    def test_connection_made(self):
        """Test that connection_made sets transport."""
        queue = asyncio.Queue()
        protocol = DNSProtocol(queue)
        transport = Mock()
        
        protocol.connection_made(transport)
        
        assert protocol.transport is transport
    
    def test_datagram_received_success(self):
        """Test successful datagram reception."""
        queue = asyncio.Queue(maxsize=10)
        protocol = DNSProtocol(queue)
        transport = Mock()
        protocol.transport = transport
        
        data = b"test_dns_query"
        addr = ("127.0.0.1", 12345)
        
        protocol.datagram_received(data, addr)
        
        # Verify item was added to queue
        assert queue.qsize() == 1
        item = queue.get_nowait()
        assert item == (data, addr, transport)
    
    def test_datagram_received_queue_full(self):
        """Test that packet is dropped when queue is full."""
        queue = asyncio.Queue(maxsize=1)
        protocol = DNSProtocol(queue)
        transport = Mock()
        protocol.transport = transport
        
        # Fill the queue
        queue.put_nowait(("first", ("1.1.1.1", 1), transport))
        
        # Try to add another packet (should be dropped)
        data = b"test_dns_query"
        addr = ("127.0.0.1", 12345)
        
        # Should not raise an exception
        protocol.datagram_received(data, addr)
        
        # Queue should still have only 1 item
        assert queue.qsize() == 1
    
    def test_multiple_datagrams(self):
        """Test receiving multiple datagrams."""
        queue = asyncio.Queue(maxsize=10)
        protocol = DNSProtocol(queue)
        transport = Mock()
        protocol.transport = transport
        
        packets = [
            (b"query1", ("127.0.0.1", 1001)),
            (b"query2", ("127.0.0.1", 1002)),
            (b"query3", ("127.0.0.1", 1003)),
        ]
        
        for data, addr in packets:
            protocol.datagram_received(data, addr)
        
        assert queue.qsize() == 3
        
        # Verify all packets are in the queue
        for data, addr in packets:
            item = queue.get_nowait()
            assert item[0] == data
            assert item[1] == addr
            assert item[2] is transport
