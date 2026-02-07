"""DNS cache implementation with TTL support."""
import time
from .config import logger, CACHE_ENABLED


class DNSCache:
    """In-Memory Cache with TTL."""
    
    def __init__(self):
        self._cache = {}

    def get(self, key):
        """Retrieve a cached DNS response if still valid."""
        if not CACHE_ENABLED:
            return None
        entry = self._cache.get(key)
        if entry:
            data, expiry = entry
            if time.time() < expiry:
                return data
            else:
                del self._cache[key]  # Lazy cleanup
        return None

    def set(self, key, data, ttl):
        """Cache a DNS response with TTL."""
        if not CACHE_ENABLED:
            return
        # Cap TTL to sane limits (e.g., min 60s, max 1h) to prevent thrashing
        ttl = max(60, min(ttl, 3600))
        self._cache[key] = (data, time.time() + ttl)

    def prune(self):
        """Cleanup expired keys periodically."""
        now = time.time()
        keys_to_remove = [k for k, v in self._cache.items() if now > v[1]]
        for k in keys_to_remove:
            del self._cache[k]
        if keys_to_remove:
            logger.debug(f"Pruned {len(keys_to_remove)} expired cache entries")
