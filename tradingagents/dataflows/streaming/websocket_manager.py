"""WebSocket connection lifecycle manager for streaming market data.

Maintains persistent WebSocket connections to data providers, dispatches
incoming messages to registered callbacks, and transparently reconnects
on failure.

Not imported by default — consumer modules that want streaming data
must call ``start()`` with the desired symbol list.

Design
------
- Runs a single ``asyncio`` event loop in a background daemon thread.
- Each vendor/symbol subscription creates an ``asyncio.Task`` that
  manages its own connection.
- Reconnection uses exponential backoff capped at 30 seconds.
- All callbacks are invoked on the background thread — consumer code
  must be thread-safe.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class StreamConfig:
    """Per-stream subscription configuration.

    Attributes:
        vendor: Vendor identifier (``"polygon"``, etc.).
        symbols: List of ticker symbols to subscribe to.
        on_trade: Optional callback for trade ticks.
        on_quote: Optional callback for quote updates.
        on_aggregate: Optional callback for minute aggregates.
        auto_reconnect: Whether to reconnect on disconnect.
        reconnect_delay: Initial reconnect delay in seconds.
    """

    vendor: str
    symbols: list[str]
    on_trade: Optional[Callable[[dict[str, Any]], None]] = None
    on_quote: Optional[Callable[[dict[str, Any]], None]] = None
    on_aggregate: Optional[Callable[[dict[str, Any]], None]] = None
    auto_reconnect: bool = True
    reconnect_delay: float = 5.0


class WebSocketManager:
    """Manages persistent WebSocket connections in a background thread.

    Usage::

        manager = WebSocketManager()

        def on_price(data: dict):
            print(f"{data['symbol']}: {data['price']}")

        manager.subscribe(StreamConfig(
            vendor="polygon",
            symbols=["AAPL", "MSFT"],
            on_trade=on_price,
        ))

        manager.start()
    """

    def __init__(self):
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._tasks: dict[str, asyncio.Task] = {}
        self._configs: list[StreamConfig] = []
        self._running = threading.Event()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background event loop.

        This method returns immediately; the loop runs in a daemon thread.
        """
        if self._thread is not None and self._thread.is_alive():
            logger.debug("WebSocketManager already running")
            return

        self._running.set()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="ws-manager",
            daemon=True,
        )
        self._thread.start()
        logger.info("WebSocketManager started")

    def stop(self) -> None:
        """Gracefully stop all connections and the event loop."""
        self._running.clear()
        if self._loop and not self._loop.is_closed():
            for task in self._tasks.values():
                task.cancel()
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("WebSocketManager stopped")

    def subscribe(self, config: StreamConfig) -> None:
        """Register a streaming subscription.

        If the manager is already running, the subscription is started
        immediately.
        """
        self._configs.append(config)
        if self._loop and self._loop.is_running():
            for symbol in config.symbols:
                key = f"{config.vendor}:{symbol}"
                if key not in self._tasks:
                    self._tasks[key] = asyncio.run_coroutine_threadsafe(
                        self._run_symbol_stream(config, symbol),
                        self._loop,
                    )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        """Entry point for the background thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        # Start all pending subscriptions.
        for config in self._configs:
            for symbol in config.symbols:
                key = f"{config.vendor}:{symbol}"
                self._tasks[key] = self._loop.create_task(
                    self._run_symbol_stream(config, symbol)
                )

        self._loop.run_forever()
        self._loop.close()

    async def _run_symbol_stream(
        self,
        config: StreamConfig,
        symbol: str,
    ) -> None:
        """Maintain a streaming connection for a single symbol.

        Implements exponential backoff reconnection.
        """
        delay = config.reconnect_delay
        max_delay = 30.0

        while self._running.is_set():
            try:
                await self._connect_and_stream(config, symbol)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning(
                    "Stream disconnected for %s:%s (%s), reconnecting in %.1fs",
                    config.vendor,
                    symbol,
                    exc,
                    delay,
                )

            if not config.auto_reconnect:
                break

            await asyncio.sleep(delay)
            delay = min(delay * 2, max_delay)

    async def _connect_and_stream(
        self,
        config: StreamConfig,
        symbol: str,
    ) -> None:
        """Connect to the vendor's streaming endpoint and dispatch messages.

        This is a placeholder for vendor-specific implementations.
        Each vendor (Polygon, Twelve Data, etc.) subclasses or patches
        this method.

        The default implementation simply waits — real vendors override
        this to open WebSocket connections.
        """
        # Vendor-specific WebSocket logic goes here (see polygon_io.py).
        # For now, the pattern is:
        #
        #   async with connect(f"wss://{vendor_host}/{symbol}") as ws:
        #       async for msg in ws:
        #           data = json.loads(msg)
        #           if data["type"] == "trade" and config.on_trade:
        #               config.on_trade(data)
        #
        await asyncio.Event().wait()  # sleep forever (no-op placeholder)
