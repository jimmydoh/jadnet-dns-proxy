"""Upstream DoH server manager with load balancing and health tracking."""
import asyncio
import time
from dataclasses import dataclass, field
from typing import List, Optional
import httpx
from .config import logger


@dataclass
class UpstreamServer:
    """Represents a DoH upstream server with health metrics."""
    url: str
    is_up: bool = True
    total_requests: int = 0
    failed_requests: int = 0
    response_times: List[float] = field(default_factory=list)
    last_check: float = field(default_factory=time.time)
    
    @property
    def avg_response_time(self) -> float:
        """Calculate average response time."""
        if not self.response_times:
            return 0.0
        # Keep only last 100 response times to avoid unbounded growth
        recent_times = self.response_times[-100:]
        return sum(recent_times) / len(recent_times)
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate as a percentage."""
        if self.total_requests == 0:
            return 100.0
        return ((self.total_requests - self.failed_requests) / self.total_requests) * 100
    
    def record_success(self, response_time: float):
        """Record a successful request."""
        self.total_requests += 1
        self.response_times.append(response_time)
        # Keep list bounded
        if len(self.response_times) > 100:
            self.response_times = self.response_times[-100:]
        self.is_up = True
        self.last_check = time.time()
    
    def record_failure(self):
        """Record a failed request."""
        self.total_requests += 1
        self.failed_requests += 1
        self.last_check = time.time()
        
        # Mark as down if failure rate is too high
        if self.total_requests >= 5 and self.success_rate < 50:
            self.is_up = False
            logger.warning(f"Upstream {self.url} marked as DOWN (success rate: {self.success_rate:.1f}%)")


class UpstreamManager:
    """Manages multiple DoH upstream servers with load balancing."""
    
    def __init__(self, upstream_urls: List[str]):
        """
        Initialize the upstream manager.
        
        Args:
            upstream_urls: List of DoH server URLs
        """
        if not upstream_urls:
            raise ValueError("At least one upstream URL must be provided")
        
        self.servers = [UpstreamServer(url=url) for url in upstream_urls]
        self.current_index = 0
        logger.info(f"Initialized upstream manager with {len(self.servers)} servers: {upstream_urls}")
    
    async def get_next_server(self) -> Optional[UpstreamServer]:
        """
        Get the next available server using round-robin load balancing.
        Prioritizes servers that are up.
        
        Returns:
            UpstreamServer instance or None if all servers are down
        """
        # First, try to find an "up" server
        up_servers = [s for s in self.servers if s.is_up]
        
        if up_servers:
            # Round-robin through up servers
            server = up_servers[self.current_index % len(up_servers)]
            self.current_index = (self.current_index + 1) % len(up_servers)
            return server
        
        # If all servers are down, try to recover by returning the least bad one
        if self.servers:
            # Sort by success rate and return the best one
            best_server = max(self.servers, key=lambda s: s.success_rate)
            logger.warning(f"All servers down, attempting recovery with {best_server.url}")
            return best_server
        
        return None
    
    def get_stats(self) -> List[dict]:
        """
        Get statistics for all upstream servers.
        
        Returns:
            List of dictionaries containing server statistics
        """
        stats = []
        for server in self.servers:
            stats.append({
                'url': server.url,
                'is_up': server.is_up,
                'total_requests': server.total_requests,
                'failed_requests': server.failed_requests,
                'success_rate': f"{server.success_rate:.1f}%",
                'avg_response_time': f"{server.avg_response_time:.3f}s",
            })
        return stats
    
    def log_stats(self):
        """Log statistics for all upstream servers."""
        logger.info("=== Upstream Server Statistics ===")
        for stat in self.get_stats():
            status = "UP" if stat['is_up'] else "DOWN"
            logger.info(
                f"[{status}] {stat['url']} - "
                f"Requests: {stat['total_requests']}, "
                f"Success Rate: {stat['success_rate']}, "
                f"Avg Response Time: {stat['avg_response_time']}"
            )
