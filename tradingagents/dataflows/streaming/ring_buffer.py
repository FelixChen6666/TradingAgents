"""In-memory ring buffer for streaming market data.

Thread-safe, fixed-size buffer per symbol that stores the most recent
N seconds of tick/minute data. Vendor implementations read from this
to enrich historical REST responses with the latest streaming data.
"""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock
from typing import Any, Optional


class MarketDataRingBuffer:
    """Time-windowed, thread-safe buffer for streaming market data.

    Each symbol gets an independent buffer.  Data points older than
    *window_seconds* are pruned on every write.

    Usage::

        buf = MarketDataRingBuffer(window_seconds=1800)

        buf.push("AAPL", {"price": 150.0, "volume": 1000, "timestamp": ...})
        latest = buf.get_latest("AAPL")
        recent = buf.get_recent("AAPL")
    """

    def __init__(self, window_seconds: int = 1800):
        self._window = window_seconds
        self._data: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._lock = Lock()

    def push(self, symbol: str, record: dict[str, Any]) -> None:
        """Insert a streaming data point.

        Args:
            symbol: Ticker symbol (e.g. ``"AAPL"``).
            record: A dict with at minimum a ``"timestamp"`` key (float,
                Unix epoch seconds).  Typical fields: ``price``,
                ``volume``, ``bid``, ``ask``.
        """
        now = time.time()
        cutoff = now - self._window
        ts = record.get("timestamp", now)

        with self._lock:
            # Prune old entries for this symbol.
            self._data[symbol] = [
                r
                for r in self._data[symbol]
                if r.get("timestamp", cutoff) >= cutoff
            ]
            self._data[symbol].append({**record, "timestamp": ts})

    def get_recent(self, symbol: str) -> list[dict[str, Any]]:
        """Return all buffered data points for *symbol*.

        Returns a shallow copy so callers cannot mutate the buffer.
        """
        with self._lock:
            return list(self._data.get(symbol, []))

    def get_latest(self, symbol: str) -> Optional[dict[str, Any]]:
        """Return the single most recent data point, or ``None``."""
        with self._lock:
            records = self._data.get(symbol, [])
            return records[-1] if records else None

    def clear(self, symbol: str | None = None) -> None:
        """Clear the buffer for one symbol, or all symbols if ``None``."""
        with self._lock:
            if symbol is None:
                self._data.clear()
            else:
                self._data.pop(symbol, None)

    @property
    def symbols(self) -> list[str]:
        """Return all symbols that have buffered data."""
        with self._lock:
            return list(self._data.keys())
