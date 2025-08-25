# cache_manager.py
"""
Cache management for FutureScorer bot.
Implements intelligent caching to reduce API calls and improve performance.
"""
import time
from typing import Any, Dict, Optional, Callable
from dataclasses import dataclass
from threading import Lock
import pickle
import os
import gvars

@dataclass
class CacheEntry:
    value: Any
    timestamp: float
    ttl: float  # time to live in seconds
    
    def is_expired(self) -> bool:
        return time.time() - self.timestamp > self.ttl

class CacheManager:
    def __init__(self):
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = Lock()
        self._persistent_cache_file = os.path.join(gvars.configFolder, 'cache.pkl')
        self._load_persistent_cache()
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache if not expired."""
        with self._lock:
            if key in self._cache:
                entry = self._cache[key]
                if not entry.is_expired():
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
    
    def cleanup_expired(self) -> None:
        """Remove all expired entries."""
        with self._lock:
            expired_keys = [
                key for key, entry in self._cache.items() 
                if entry.is_expired()
            ]
            for key in expired_keys:
                del self._cache[key]
    
    def cached_call(self, key: str, func: Callable, ttl: float = 300, *args, **kwargs) -> Any:
        """Execute function and cache result, or return cached result if available."""
        cached_value = self.get(key)
        if cached_value is not None:
            return cached_value
        
        result = func(*args, **kwargs)
        self.set(key, result, ttl)
        return result
    
    def _load_persistent_cache(self) -> None:
        """Load persistent cache from disk."""
        try:
            if os.path.exists(self._persistent_cache_file):
                with open(self._persistent_cache_file, 'rb') as f:
                    persistent_data = pickle.load(f)
                    # Only load non-expired entries
                    current_time = time.time()
                    for key, entry in persistent_data.items():
                        if not entry.is_expired():
                            self._cache[key] = entry
        except Exception:
            # If loading fails, start with empty cache
            pass
    
    def save_persistent_cache(self) -> None:
        """Save cache to disk for persistence."""
        try:
            os.makedirs(os.path.dirname(self._persistent_cache_file), exist_ok=True)
            with open(self._persistent_cache_file, 'wb') as f:
                # Only save entries with long TTL (> 1 hour)
                long_term_cache = {
                    key: entry for key, entry in self._cache.items()
                    if entry.ttl > 3600 and not entry.is_expired()
                }
                pickle.dump(long_term_cache, f)
        except Exception:
            pass

# Global cache instance
cache_manager = CacheManager()

# Convenience functions
def get_cached(key: str) -> Optional[Any]:
    return cache_manager.get(key)

def set_cached(key: str, value: Any, ttl: float = 300) -> None:
    cache_manager.set(key, value, ttl)

def cached_call(key: str, func: Callable, ttl: float = 300, *args, **kwargs) -> Any:
    return cache_manager.cached_call(key, func, ttl, *args, **kwargs)
