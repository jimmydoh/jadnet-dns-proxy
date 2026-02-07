"""UDP DNS protocol implementation."""
import asyncio
from .config import logger, LISTEN_HOST, LISTEN_PORT


class DNSProtocol(asyncio.DatagramProtocol):
    """UDP Protocol handler for DNS requests."""
    
    def __init__(self, queue):
        self.queue = queue
        self.transport = None

    def connection_made(self, transport):
        """Called when connection is established."""
        self.transport = transport
        logger.info(f"UDP Server listening on {LISTEN_HOST}:{LISTEN_PORT}")

    def datagram_received(self, data, addr):
        """Called when a UDP datagram is received."""
        try:
            # Non-blocking put. If queue is full, we drop packet to save memory.
            self.queue.put_nowait((data, addr, self.transport))
        except asyncio.QueueFull:
            logger.warning("Queue full! Dropping DNS packet.")
