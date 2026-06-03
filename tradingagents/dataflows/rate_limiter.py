"""Centralised rate limiter with per-vendor policies.

Usage::

    rate_limiter = RateLimiter()
    rate_limiter.configure("akshare", max_calls=10, period=1.0)

    def fetch():
        rate_limiter.wait_if_needed("akshare")
        return do_request()

Thread-safe.  Designed for the synchronous vendor-call path; no async
primitives are used.
"""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timedelta
from threading import Lock


class RateLimiter:
    """Simple sliding-window rate limiter.

    Each vendor gets a window of ``period`` seconds during which at most
    ``max_calls`` calls are allowed.  Calls beyond the limit block until
    the window slides.
    """

    def __init__(self):
        self._limits: dict[str, tuple[int, float]] = {}
        self._history: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def configure(self, vendor: str, max_calls: int, period: float = 1.0) -> None:
        """Set rate limit for *vendor*.

        Args:
            vendor: Vendor identifier (same string used in ``register_vendor``).
            max_calls: Maximum number of calls allowed in the window.
            period: Window length in seconds.
        """
        self._limits[vendor] = (max_calls, period)

    def acquire(self, vendor: str) -> bool:
        """Try to acquire a rate-limit slot.

        Returns:
            True if the call is within the limit, False if it should be
            deferred.
        """
        with self._lock:
            limit = self._limits.get(vendor)
            if limit is None:
                return True  # no limit configured

            max_calls, period = limit
            now = time.monotonic()
            cutoff = now - period

            # Prune entries outside the window.
            self._history[vendor] = [t for t in self._history[vendor] if t > cutoff]

            if len(self._history[vendor]) >= max_calls:
                return False

            self._history[vendor].append(now)
            return True

    def wait_if_needed(self, vendor: str, timeout: float = 30.0) -> None:
        """Block until a rate-limit slot is available.

        Args:
            vendor: Vendor identifier.
            timeout: Maximum time to wait in seconds.

        Raises:
            TimeoutError: If a slot does not become available within
                *timeout* seconds.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.acquire(vendor):
                return
            time.sleep(0.1)
        raise TimeoutError(
            f"Rate limit timeout for vendor '{vendor}' after {timeout}s"
        )


# Module-level singleton so all vendor modules share the same limiter.
_rate_limiter = RateLimiter()


def get_rate_limiter() -> RateLimiter:
    """Return the module-level :class:`RateLimiter` singleton."""
    return _rate_limiter
