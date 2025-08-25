# cacheManager.py
"""
Cache management for FutureScorer bot.
Implements intelligent caching to reduce API calls and improve performance.
"""
import time
import sys
from typing import Any, Dict, Optional, Callable
from dataclasses import dataclass
from threading import Lock
import pickle
import os
import os
import gvars

@dataclass
class CacheEntry:
    value: Any
    timestamp: float
    ttl: float  # time to live in seconds
    
    def isExpired(self) -> bool:
        return time.time() - self.timestamp > self.ttl

class CacheManager:
    def __init__(self):
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = Lock()
        self._persistent_cache_file = os.path.join(gvars.configFolder, 'cache.pkl')
        self.loadPersistentCache()
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache if not expired."""
        with self._lock:
            if key in self._cache:
                entry = self._cache[key]
                if not entry.isExpired():
                    return entry.value
                else:
                    # Remove expired entry
                    del self._cache[key]
            return None
    
    def set(self, key: str, value: Any, ttl: float = 300) -> None:
        """Set value in cache with TTL."""
        with self._lock:
            self._cache[key] = CacheEntry(value, time.time(), ttl)
    
    def delete(self, key: str) -> None:
        """Delete key from cache."""
        with self._lock:
            self._cache.pop(key, None)
    
    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            self._cache.clear()
    
    def cleanupExpired(self) -> None:
        """Remove all expired entries."""
        with self._lock:
            expired_keys = [
                key for key, entry in self._cache.items() 
                if entry.isExpired()
            ]
            for key in expired_keys:
                del self._cache[key]
    
    def cachedCall(self, key: str, func: Callable, ttl: float = 300, *args, **kwargs) -> Any:
        """Execute function and cache result, or return cached result if available."""
        cached_value = self.get(key)
        if cached_value is not None:
            return cached_value
        
        result = func(*args, **kwargs)
        self.set(key, result, ttl)
        return result
    
    def loadPersistentCache(self) -> None:
        """Load persistent cache from disk."""
        try:
            if os.path.exists(self._persistent_cache_file):
                with open(self._persistent_cache_file, 'rb') as f:
                    persistent_data = pickle.load(f)
                    # Only load non-expired entries
                    current_time = time.time()
                    for key, entry in persistent_data.items():
                        if not entry.isExpired():
                            self._cache[key] = entry
        except Exception:
            # If loading fails, start with empty cache
            pass
    
    def savePersistentCache(self) -> None:
        """Save cache to disk for persistence."""
        try:
            os.makedirs(os.path.dirname(self._persistent_cache_file), exist_ok=True)
            with open(self._persistent_cache_file, 'wb') as f:
                # Only save entries with long TTL (> 1 hour)
                long_term_cache = {
                    key: entry for key, entry in self._cache.items()
                    if entry.ttl > 3600 and not entry.isExpired()
                }
                pickle.dump(long_term_cache, f)
        except Exception:
            pass
    
    def getCacheStats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        current_time = time.time()
        expired_count = 0
        
        for entry in self._cache.values():
            if entry.isExpired():
                expired_count += 1
        
        return {
            'total_items': len(self._cache),
            'expired_items': expired_count,
            'active_items': len(self._cache) - expired_count,
            'memory_usage_mb': sys.getsizeof(self._cache) / 1024 / 1024
        }

# Global cache instance
cacheManager = CacheManager()

# Convenience functions
def getCached(key: str) -> Optional[Any]:
    return cacheManager.get(key)

def setCached(key: str, value: Any, ttl: float = 300) -> None:
    cacheManager.set(key, value, ttl)

def cachedCall(key: str, func: Callable, ttl: float = 300, *args, **kwargs) -> Any:
    return cacheManager.cachedCall(key, func, ttl, *args, **kwargs)
