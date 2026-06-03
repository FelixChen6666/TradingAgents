"""Streaming market data package.

Provides WebSocket-based real-time data feeds as an optional enhancement
layer on top of the existing request-response vendor system.

All components are **opt-in** — the main pipeline works without any
streaming configuration.

Design
------
The streaming layer uses a producer-consumer pattern:
  - WebSocket clients (producers) run in a background thread and push
    ticks into a shared ring buffer.
  - Vendor implementations (consumers) read from the ring buffer to
    enrich historical REST responses with the most recent data.
  - The ``RingBuffer`` is thread-safe and maintains a time-windowed view.

To enable streaming, set ``streaming.enabled = True`` in the config and
configure a streaming vendor.
"""

from .ring_buffer import MarketDataRingBuffer
from .websocket_manager import StreamConfig, WebSocketManager
