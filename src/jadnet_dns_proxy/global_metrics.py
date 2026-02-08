"""Global metrics tracking for DNS proxy."""
import time
from dataclasses import dataclass, field
from typing import List
from .config import logger


@dataclass
class GlobalMetrics:
    """Tracks global metrics for the DNS proxy."""
    
    total_queries: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    response_times: List[float] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)
    last_log_time: float = field(default_factory=time.time)
    
    def record_cache_hit(self):
        """Record a cache hit."""
        self.total_queries += 1
        self.cache_hits += 1
    
    def record_cache_miss(self, response_time: float):
        """Record a cache miss with response time."""
        self.total_queries += 1
        self.cache_misses += 1
        self.response_times.append(response_time)
        # Keep list bounded to last 1000 entries
        if len(self.response_times) > 1000:
            self.response_times = self.response_times[-1000:]
    
    def get_queries_per_minute(self) -> float:
        """Calculate queries per minute since last log."""
        current_time = time.time()
        elapsed_minutes = (current_time - self.last_log_time) / 60.0
        if elapsed_minutes == 0:
            return 0.0
        return self.total_queries / elapsed_minutes
    
    def get_cache_hit_rate(self) -> float:
        """Calculate cache hit rate as a percentage."""
        if self.total_queries == 0:
            return 0.0
        return (self.cache_hits / self.total_queries) * 100
    
    def get_min_response_time(self) -> float:
        """Get minimum response time."""
        if not self.response_times:
            return 0.0
        return min(self.response_times)
    
    def get_mean_response_time(self) -> float:
        """Get mean response time."""
        if not self.response_times:
            return 0.0
        return sum(self.response_times) / len(self.response_times)
    
    def get_max_response_time(self) -> float:
        """Get maximum response time."""
        if not self.response_times:
            return 0.0
        return max(self.response_times)
    
    def log_stats(self):
        """Log global statistics."""
        qpm = self.get_queries_per_minute()
        hit_rate = self.get_cache_hit_rate()
        
        logger.info("=== Global Metrics ===")
        
        # Format cache stats
        cache_stats = f"Cache: {self.cache_hits} hits / {self.cache_misses} misses ({hit_rate:.1f}% hit rate)"
        
        # Format response time stats if we have data
        if self.response_times:
            min_time = self.get_min_response_time()
            mean_time = self.get_mean_response_time()
            max_time = self.get_max_response_time()
            response_stats = f", Response times: min={min_time:.3f}s, mean={mean_time:.3f}s, max={max_time:.3f}s"
        else:
            response_stats = ""
        
        logger.info(
            f"Queries/min: {qpm:.1f}, {cache_stats}{response_stats}"
        )
        
        # Reset counters for next interval
        self.total_queries = 0
        self.cache_hits = 0
        self.cache_misses = 0
        self.response_times = []
        self.last_log_time = time.time()
