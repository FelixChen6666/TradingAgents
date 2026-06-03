"""Multi-vendor, TTL-aware cache for dataflow results.

Extends the existing file-based caching pattern from ``stockstats_utils``
with vendor namespacing and configurable TTL.

Usage::

    cache = VendorCache(get_config()["data_cache_dir"])

    result = cache.get_or_fetch(
        vendor="akshare", key="600519-SH",
        ttl_seconds=3600,
        fetcher=lambda: fetch_from_api(),
    )
"""

from __future__ import annotations

import os
import time
from typing import Callable, Optional

from .utils import safe_ticker_component

_CACHE_EXT = ".csv"


class VendorCache:
    """File-based cache with vendor-namespaced keys and TTL."""

    def __init__(self, cache_dir: str):
        self._cache_dir = cache_dir

    def _cache_path(self, vendor: str, key: str) -> str:
        safe = safe_ticker_component(key) or "unknown"
        return os.path.join(self._cache_dir, vendor, f"{safe}{_CACHE_EXT}")

    def get(
        self, vendor: str, key: str, ttl_seconds: float = 3600
    ) -> Optional[str]:
        """Return cached content if it exists and is fresh, else None."""
        path = self._cache_path(vendor, key)
        if not os.path.isfile(path):
            return None
        if time.time() - os.path.getmtime(path) > ttl_seconds:
            return None
        content = _read_file(path)
        if content is None or not content.strip():
            return None
        return content

    def set(self, vendor: str, key: str, content: str) -> None:
        """Write *content* to the vendor-namespaced cache file."""
        path = self._cache_path(vendor, key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _write_file(path, content)

    def get_or_fetch(
        self,
        vendor: str,
        key: str,
        fetcher: Callable[[], str],
        ttl_seconds: float = 3600,
    ) -> str:
        """Return cached content or fetch, cache, and return.

        An empty result from *fetcher* is **not** cached (prevents
        caching transient failures).
        """
        cached = self.get(vendor, key, ttl_seconds)
        if cached is not None:
            return cached

        fresh = fetcher()
        if fresh and fresh.strip():
            self.set(vendor, key, fresh)
        return fresh

    def invalidate(self, vendor: str, key: str) -> None:
        """Remove a cached entry if it exists."""
        path = self._cache_path(vendor, key)
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


def _read_file(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return None


def _write_file(path: str, content: str) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError:
        pass
