"""Shared streaming protocol definitions.

Defines the type contracts that streaming vendors must implement so the
``WebSocketManager`` can dispatch normalized messages regardless of the
underlying provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class TradeTick:
    """A single trade tick from any streaming provider."""

    symbol: str
    price: float
    volume: int
    timestamp: float  # Unix epoch seconds
    exchange: str = ""
    conditions: Optional[list[str]] = None


@dataclass
class QuoteTick:
    """A top-of-book quote update."""

    symbol: str
    bid: float
    ask: float
    bid_size: int
    ask_size: int
    timestamp: float


@dataclass
class AggregateBar:
    """A time-aggregated OHLCV bar (typically 1-minute)."""

    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    timestamp: float  # Bar start time


def normalize_trade(data: dict[str, Any], vendor: str) -> Optional[TradeTick]:
    """Normalize a vendor-specific trade message to a ``TradeTick``.

    Returns ``None`` if the message cannot be parsed (vendor version
    mismatch, missing required fields, etc.).
    """
    if vendor == "polygon":
        return TradeTick(
            symbol=data.get("sym", ""),
            price=float(data.get("p", 0)),
            volume=int(data.get("s", 0)),
            timestamp=data.get("t", 0) / 1_000_000_000,  # nanos to seconds
            exchange=data.get("x", ""),
            conditions=data.get("c"),
        )
    # Add vendor-specific normalisers here.
    return None


def normalize_quote(data: dict[str, Any], vendor: str) -> Optional[QuoteTick]:
    """Normalise a vendor-specific quote message to a ``QuoteTick``."""
    if vendor == "polygon":
        return QuoteTick(
            symbol=data.get("sym", ""),
            bid=float(data.get("p", 0)),
            ask=float(data.get("P", 0)),
            bid_size=int(data.get("s", 0)),
            ask_size=int(data.get("S", 0)),
            timestamp=data.get("t", 0) / 1_000_000_000,
        )
    return None


def normalize_aggregate(data: dict[str, Any], vendor: str) -> Optional[AggregateBar]:
    """Normalise a vendor-specific aggregate message to an ``AggregateBar``."""
    if vendor == "polygon":
        return AggregateBar(
            symbol=data.get("sym", ""),
            open=float(data.get("o", 0)),
            high=float(data.get("h", 0)),
            low=float(data.get("l", 0)),
            close=float(data.get("c", 0)),
            volume=int(data.get("v", 0)),
            timestamp=data.get("s", 0) / 1_000_000_000,
        )
    return None
