"""
LRU Cache implementation using OrderedDict for memory-efficient caching with automatic eviction.

This module provides a Least Recently Used (LRU) cache implementation that automatically
manages memory by evicting the least recently used items when the cache exceeds its
maximum size limit. It maintains O(1) access time and provides a dict-like interface.
Thread-safe for concurrent access.
"""

import threading
from collections import OrderedDict
from typing import Any, Dict, Optional


class LRUCache:
    """
    A Least Recently Used (LRU) cache implementation using OrderedDict.

    Automatically evicts the least recently used items when the cache exceeds
    the maximum size limit. Provides dict-like interface with O(1) operations.
    Thread-safe for concurrent access using RLock.

    Args:
        max_size: Maximum number of items to store in cache (default: 1000)
    """

    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self.cache = OrderedDict()
        self._lock = threading.RLock()

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Get item from cache, moving it to end (most recent) if found."""
        with self._lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                return self.cache[key]
            return None

    def set(self, key: str, value: Dict[str, Any]) -> None:
        """Set item in cache, evicting oldest if at capacity."""
        with self._lock:
            if key in self.cache:
                self.cache.move_to_end(key)
            else:
                if len(self.cache) >= self.max_size:
                    self.cache.popitem(last=False)  # Remove oldest
            self.cache[key] = value

    def clear(self) -> None:
        """Clear all items from cache."""
        with self._lock:
            self.cache.clear()

    def __contains__(self, key: str) -> bool:
        """Check if key exists in cache."""
        with self._lock:
            return key in self.cache

    def __len__(self) -> int:
        """Return number of items in cache."""
        with self._lock:
            return len(self.cache)

    def __getitem__(self, key: str) -> Dict[str, Any]:
        """Get item using bracket notation, moving to end if found."""
        with self._lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                return self.cache[key]
            raise KeyError(key)

    def __setitem__(self, key: str, value: Dict[str, Any]) -> None:
        """Set item using bracket notation."""
        self.set(key, value)

    def __getstate__(self) -> Dict[str, Any]:
        state = self.__dict__.copy()
        del state["_lock"]
        return state

    def __setstate__(self, state: Dict[str, Any]) -> None:
        self.__dict__.update(state)
        self._lock = threading.RLock()
