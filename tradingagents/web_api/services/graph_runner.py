"""Runs the TradingAgents graph in a background thread and pushes typed
events to an ``asyncio.Queue`` for WebSocket delivery.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from tradingagents.web_api.models.ws_messages import StartAnalysisPayload
from tradingagents.web_api.services.state_buffer import StateBuffer


class GraphRunner:
    """Orchestrates graph execution in a thread pool and bridges events
    to the async world via an ``asyncio.Queue``.

    Usage::

        runner = GraphRunner()
        queue = await runner.start(payload)
        while True:
            event = await queue.get()
            if event is None:   # sentinel → analysis complete
                break
            await websocket.send_json(event)
    """

    def __init__(self):
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._cancelled = False
        self._stats_handler: Any = None
        self._start_time: float = 0.0

    async def start(self, payload: StartAnalysisPayload) -> asyncio.Queue:
        """Begin graph execution in a background thread.

        Returns the event queue. Consumer must read until ``None``.
        """
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()
        self._cancelled = False
        self._start_time = time.time()

        state_buffer = StateBuffer(event_callback=self._push_event)

        self._task = asyncio.create_task(
            asyncio.to_thread(self._run_sync, payload, state_buffer)
        )
        return self._queue

    async def cancel(self) -> None:
        """Request cancellation of the running graph."""
        self._cancelled = True
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    # ── Internal ───────────────────────────────────────────────────────

    async def _push_event(self, event: dict[str, Any]) -> None:
        """Called by StateBuffer (from the background thread)."""
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._queue.put_nowait, event)

    def _run_sync(self, payload: StartAnalysisPayload, state_buffer: StateBuffer) -> None:
        """Execute the graph synchronously in a thread."""
        try:
            self._sync_run(payload, state_buffer)
        except Exception as exc:
            self._loop.call_soon_threadsafe(
                self._queue.put_nowait,
                {"type": "error", "payload": {"message": str(exc)}}
            )
        finally:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, None)

    def _sync_run(self, payload: StartAnalysisPayload, buffer: StateBuffer) -> None:
        from tradingagents.default_config import DEFAULT_CONFIG
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        from cli.stats_handler import StatsCallbackHandler

        if self._cancelled:
            return

        # ── Build config ───────────────────────────────────────────────
        config = dict(DEFAULT_CONFIG)
        config["llm_provider"] = payload.llm_provider
        config["output_language"] = payload.output_language
        config["checkpoint_enabled"] = payload.checkpoint_enabled
        config["max_debate_rounds"] = payload.research_depth
        config["max_risk_discuss_rounds"] = payload.research_depth
        if payload.backend_url:
            config["backend_url"] = payload.backend_url
        if payload.shallow_thinker:
            config["quick_think_llm"] = payload.shallow_thinker
        if payload.deep_thinker:
            config["deep_think_llm"] = payload.deep_thinker
        if payload.google_thinking_level is not None:
            config["google_thinking_level"] = payload.google_thinking_level
        if payload.openai_reasoning_effort is not None:
            config["openai_reasoning_effort"] = payload.openai_reasoning_effort
        if payload.anthropic_effort is not None:
            config["anthropic_effort"] = payload.anthropic_effort
        if payload.data_vendors:
            config["data_vendors"].update(payload.data_vendors)
        if payload.api_keys:
            config.setdefault("api_keys", {}).update(payload.api_keys)

        asset_type = payload.asset_type

        # ── Stats handler ──────────────────────────────────────────────
        self._stats_handler = StatsCallbackHandler()

        # ── Analyst execution plan ─────────────────────────────────────
        analyst_keys = payload.analysts
        selected_analyst_names = []
        for key in analyst_keys:
            name = buffer.ANALYST_MAPPING.get(key.lower())
            if name:
                selected_analyst_names.append(name)

        from tradingagents.graph.analyst_execution import AnalystExecutionPlan, AnalystNodeSpec

        analyst_specs = []
        for key in analyst_keys:
            node_name = buffer.ANALYST_MAPPING.get(key.lower(), key)
            analyst_specs.append(
                AnalystNodeSpec(
                    key=key,
                    agent_node=node_name,
                    clear_node=f"Msg Clear {node_name}",
                    tool_node=f"tools_{key}",
                    report_key=f"{key}_report",
                )
            )
        analyst_execution_plan = AnalystExecutionPlan(
            specs=analyst_specs,
            concurrency_limit=config.get("analyst_concurrency_limit", 1),
        )

        # ── Build graph BEFORE sending analysis_started ────────────────
        # If graph creation fails (missing API key, invalid config, etc.)
        # we must NOT have sent analysis_started yet — otherwise the
        # frontend transitions to the "running" UI and immediately
        # loses the connection.
        graph = TradingAgentsGraph(
            analyst_keys,
            config=config,
            debug=True,
            callbacks=[self._stats_handler],
        )

        instrument_context = graph.resolve_instrument_context(payload.ticker, asset_type)

        # Build current_position string from payload fields
        current_position = ""
        if payload.holds_stock:
            parts = [f"Holding {payload.position_quantity or 0} shares"]
            if payload.position_avg_cost is not None:
                parts.append(f"avg cost ${payload.position_avg_cost}")
            current_position = ", ".join(parts)
        else:
            current_position = "Not holding"

        init_agent_state = graph.propagator.create_initial_state(
            payload.ticker,
            payload.analysis_date,
            asset_type=asset_type,
            instrument_context=instrument_context,
            current_position=current_position,
        )
        args = graph.propagator.get_graph_args(callbacks=[self._stats_handler])

        # ── Checkpoint cleanup ─────────────────────────────────────────
        if config.get("checkpoint_enabled"):
            try:
                import shutil
                from pathlib import Path
                ckpt_dir = Path(config["project_dir"]) / ".checkpoints"
                if ckpt_dir.exists():
                    shutil.rmtree(ckpt_dir)
            except Exception:
                pass

        # ── Graph ready → send analysis_started ────────────────────────
        self._loop.call_soon_threadsafe(
            self._queue.put_nowait,
            {
                "type": "analysis_started",
                "payload": {
                    "ticker": payload.ticker,
                    "date": payload.analysis_date,
                    "analysts": selected_analyst_names,
                    "asset_type": asset_type,
                },
            }
        )

        # ── Initialize buffer & set first analyst ──────────────────────
        fut = asyncio.run_coroutine_threadsafe(
            buffer.init_for_analysis(analyst_keys), self._loop
        )
        fut.result()

        if analyst_specs:
            first = analyst_specs[0].agent_node
            fut = asyncio.run_coroutine_threadsafe(
                buffer.update_agent_status(first, "in_progress"), self._loop
            )
            fut.result()

        # ── System messages ────────────────────────────────────────────
        self._loop.call_soon_threadsafe(
            self._queue.put_nowait,
            {"type": "message", "payload": {"timestamp": time.strftime("%H:%M:%S"), "type": "System", "content": f"Selected ticker: {payload.ticker}"}}
        )
        if asset_type != "stock":
            self._loop.call_soon_threadsafe(
                self._queue.put_nowait,
                {"type": "message", "payload": {"timestamp": time.strftime("%H:%M:%S"), "type": "System", "content": f"Detected asset type: {asset_type}"}}
            )
        self._loop.call_soon_threadsafe(
            self._queue.put_nowait,
            {"type": "message", "payload": {"timestamp": time.strftime("%H:%M:%S"), "type": "System", "content": f"Analysis date: {payload.analysis_date}"}}
        )

        # ── Stream loop ────────────────────────────────────────────────
        trace = []
        for chunk in graph.graph.stream(init_agent_state, **args):
            if self._cancelled:
                return

            try:
                fut = asyncio.run_coroutine_threadsafe(
                    buffer.process_chunk(chunk), self._loop
                )
                fut.result(timeout=30)
            except Exception:
                pass  # chunk error → skip and continue

            try:
                elapsed = time.time() - self._start_time
                stats = self._stats_handler.get_stats()
                fut = asyncio.run_coroutine_threadsafe(
                    buffer.push_stats(
                        stats.get("llm_calls", 0),
                        stats.get("tool_calls", 0),
                        stats.get("tokens_in", 0),
                        stats.get("tokens_out", 0),
                        elapsed,
                    ),
                    self._loop,
                )
                fut.result(timeout=10)
            except Exception:
                pass

            trace.append(chunk)
            time.sleep(0.001)

        # ── Post-processing ────────────────────────────────────────────
        final_state: dict[str, Any] = {}
        for chunk in trace:
            for key, value in chunk.items():
                final_state[key] = value

        report_map = {
            "market_report": "market_report",
            "sentiment_report": "sentiment_report",
            "news_report": "news_report",
            "fundamentals_report": "fundamentals_report",
            "investment_plan": "investment_plan",
            "trader_investment_plan": "trader_investment_plan",
            "final_trade_decision": "final_trade_decision",
        }
        for section, state_key in report_map.items():
            if state_key in final_state and final_state[state_key]:
                fut = asyncio.run_coroutine_threadsafe(
                    buffer.update_report_section(section, str(final_state[state_key])),
                    self._loop,
                )
                fut.result()

        all_agents = list(buffer.agent_status.keys())
        for agent in all_agents:
            fut = asyncio.run_coroutine_threadsafe(
                buffer.update_agent_status(agent, "completed"), self._loop
            )
            fut.result()

        elapsed = time.time() - self._start_time
        stats = self._stats_handler.get_stats()
        fut = asyncio.run_coroutine_threadsafe(
            buffer.push_stats(
                stats.get("llm_calls", 0),
                stats.get("tool_calls", 0),
                stats.get("tokens_in", 0),
                stats.get("tokens_out", 0),
                elapsed,
            ),
            self._loop,
        )
        fut.result()

        self._loop.call_soon_threadsafe(
            self._queue.put_nowait,
            {
                "type": "analysis_complete",
                "payload": {
                    "summary": buffer.final_report or "",
                    "wall_times": {},
                },
            }
        )
