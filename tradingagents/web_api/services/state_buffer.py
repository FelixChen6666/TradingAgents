"""Server-side state buffer — replicates the CLI's MessageBuffer logic
but pushes typed events to an async callback instead of rendering Rich panels.
"""

from __future__ import annotations

import datetime
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

from tradingagents.web_api.config import settings


class StateBuffer:
    """Server-side equivalent of ``cli.main.MessageBuffer``.

    Processes graph chunks, accumulates state, and pushes typed event dicts
    to an *async* callback so the WebSocket handler can forward them.
    """

    FIXED_AGENTS: ClassVar[dict[str, list[str]]] = {
        "Research Team": ["Bull Researcher", "Bear Researcher", "Research Manager"],
        "Trading Team": ["Trader"],
        "Risk Management": ["Aggressive Analyst", "Neutral Analyst", "Conservative Analyst"],
        "Portfolio Management": ["Portfolio Manager"],
    }

    ANALYST_MAPPING: ClassVar[dict[str, str]] = {
        "market": "Market Analyst",
        "social": "Sentiment Analyst",
        "news": "News Analyst",
        "fundamentals": "Fundamentals Analyst",
    }

    REPORT_SECTIONS: ClassVar[dict[str, tuple[str | None, str]]] = {
        "market_report": ("market", "Market Analyst"),
        "sentiment_report": ("social", "Sentiment Analyst"),
        "news_report": ("news", "News Analyst"),
        "fundamentals_report": ("fundamentals", "Fundamentals Analyst"),
        "investment_plan": (None, "Research Manager"),
        "trader_investment_plan": (None, "Trader"),
        "final_trade_decision": (None, "Portfolio Manager"),
    }

    SECTION_TITLES: ClassVar[dict[str, str]] = {
        "market_report": "Market Analysis",
        "sentiment_report": "Social Sentiment",
        "news_report": "News Analysis",
        "fundamentals_report": "Fundamentals Analysis",
        "investment_plan": "Research Team Decision",
        "trader_investment_plan": "Trading Team Plan",
        "final_trade_decision": "Portfolio Management Decision",
    }

    ANALYST_ORDER: ClassVar[list[str]] = ["market", "social", "news", "fundamentals"]

    def __init__(self, event_callback: Callable[[dict[str, Any]], Awaitable[None]]):
        self._callback = event_callback
        self.messages: deque[tuple[str, str, str]] = deque(maxlen=settings.buffer_max_length)
        self.tool_calls: deque[tuple[str, str, dict[str, Any]]] = deque(maxlen=settings.buffer_max_length)
        self.agent_status: dict[str, str] = {}
        self.report_sections: dict[str, str | None] = {}
        self.selected_analysts: list[str] = []
        self.current_report: str | None = None
        self.final_report: str | None = None
        self.current_agent: str | None = None
        self._processed_message_ids: set[str] = set()
        self._completed_analysts: set[str] = set()
        self._start_time: float = 0.0

    # ── Lifecycle ──────────────────────────────────────────────────────

    async def init_for_analysis(self, selected_analysts: list[str]) -> None:
        self.selected_analysts = [a.lower() for a in selected_analysts]
        self.agent_status = {}
        self._completed_analysts.clear()

        # Selected analysts
        for analyst_key in self.selected_analysts:
            if analyst_key in self.ANALYST_MAPPING:
                name = self.ANALYST_MAPPING[analyst_key]
                self.agent_status[name] = "pending"
                await self._push("agent_status_update", {"agent_name": name, "status": "pending"})

        # Fixed teams
        for team_agents in self.FIXED_AGENTS.values():
            for agent in team_agents:
                self.agent_status[agent] = "pending"
                await self._push("agent_status_update", {"agent_name": agent, "status": "pending"})

        # Report sections
        self.report_sections = {}
        for section, (analyst_key, _) in self.REPORT_SECTIONS.items():
            if analyst_key is None or analyst_key in self.selected_analysts:
                self.report_sections[section] = None

        self.current_report = None
        self.final_report = None
        self.current_agent = None
        self.messages.clear()
        self.tool_calls.clear()
        self._processed_message_ids.clear()

    # ── Chunk processing ───────────────────────────────────────────────

    async def process_chunk(self, chunk: dict[str, Any]) -> None:
        """Process one graph stream chunk and push events."""
        try:
            # 1 — messages (dedup)
            for message in chunk.get("messages", []):
                try:
                    msg_id = self._get_message_id(message)
                    if msg_id is not None:
                        if msg_id in self._processed_message_ids:
                            continue
                        self._processed_message_ids.add(msg_id)

                    msg_type, content = self._classify_message(message)
                    if content:
                        await self.add_message(msg_type, content)

                    # Tool calls from AI messages
                    msg_type_lower = getattr(message, "type", "") if hasattr(message, "type") else ""
                    if msg_type_lower == "ai" and hasattr(message, "tool_calls"):
                        for tc in (message.tool_calls or []):
                            tc_name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
                            tc_args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
                            await self.add_tool_call(tc_name, tc_args)
                except Exception:
                    pass  # skip bad messages, continue processing

            # 2 — analyst statuses
            try:
                await self._update_analyst_statuses(chunk)
            except Exception:
                pass

            # 3 — investment debate state
            if "investment_debate_state" in chunk:
                try:
                    await self._handle_investment_debate(chunk["investment_debate_state"])
                except Exception:
                    pass

            # 4 — trader plan
            if "trader_investment_plan" in chunk:
                try:
                    content = chunk["trader_investment_plan"]
                    if content:
                        await self.update_report_section("trader_investment_plan", content)
                        await self.update_agent_status("Trader", "completed")
                        await self.update_agent_status("Aggressive Analyst", "in_progress")
                except Exception:
                    pass

            # 5 — risk debate state
            if "risk_debate_state" in chunk:
                try:
                    await self._handle_risk_debate(chunk["risk_debate_state"])
                except Exception:
                    pass
        except Exception:
            pass  # outermost guard — never crash on a bad chunk

    # ── Mutations (each pushes an event) ───────────────────────────────

    async def add_message(self, message_type: str, content: str) -> None:
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.messages.append((timestamp, message_type, content))
        await self._push("message", {"timestamp": timestamp, "type": message_type, "content": content})

    async def add_tool_call(self, tool_name: str, args: dict[str, Any]) -> None:
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.tool_calls.append((timestamp, tool_name, args))
        await self._push("tool_call", {"timestamp": timestamp, "name": tool_name, "args": args})

    async def update_agent_status(self, agent: str, status: str) -> None:
        if agent in self.agent_status:
            self.agent_status[agent] = status
            self.current_agent = agent
            await self._push("agent_status_update", {"agent_name": agent, "status": status})

    async def update_report_section(self, section_name: str, content: str) -> None:
        if section_name in self.report_sections:
            self.report_sections[section_name] = content
            self._update_current_report()
            section_title = self.SECTION_TITLES.get(section_name, section_name)
            await self._push("report_section_update", {"section": section_title, "content": content})

    async def push_stats(self, llm_calls: int, tool_calls: int, tokens_in: int, tokens_out: int, elapsed: float) -> None:
        await self._push("stats_update", {
            "llm_calls": llm_calls,
            "tool_calls": tool_calls,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "elapsed_seconds": elapsed,
        })

    # ── Queries ────────────────────────────────────────────────────────

    def get_completed_reports_count(self) -> int:
        count = 0
        for section in self.report_sections:
            if section not in self.REPORT_SECTIONS:
                continue
            _, finalizing_agent = self.REPORT_SECTIONS[section]
            has_content = self.report_sections.get(section) is not None
            agent_done = self.agent_status.get(finalizing_agent) == "completed"
            if has_content and agent_done:
                count += 1
        return count

    def get_total_reports_count(self) -> int:
        return len(self.report_sections)

    # ── Internal ───────────────────────────────────────────────────────

    async def _push(self, type_: str, payload: dict[str, Any]) -> None:
        await self._callback({"type": type_, "payload": payload})

    def _get_message_id(self, message: Any) -> str | None:
        try:
            if hasattr(message, "id"):
                return message.id
            if isinstance(message, dict):
                return message.get("id")
        except Exception:
            return None
        return None

    def _classify_message(self, message: Any) -> tuple[str, str | None]:
        """Classify a LangChain message → (display_type, content)."""
        try:
            msg_type = getattr(message, "type", "") if hasattr(message, "type") else ""
        except Exception:
            msg_type = ""

        content = None
        try:
            raw = message.content if hasattr(message, "content") else ""
            content = self._extract_content(raw) if raw else None
        except Exception:
            pass

        if msg_type == "human":
            if content and content.strip() == "Continue":
                return "Control", content
            return "User", content
        elif msg_type == "ai":
            return "Agent", content
        elif msg_type == "tool":
            return "Data", content

        return "System", content

    def _extract_content(self, content: Any) -> str | None:
        if content is None:
            return None
        if isinstance(content, str):
            return content if content.strip() else None
        if isinstance(content, dict):
            return content.get("text") or None
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(item.get("text", ""))
            text = " ".join(parts)
            return text if text.strip() else None
        return str(content) if content else None

    def _update_current_report(self) -> None:
        latest_section = None
        latest_content = None
        for section, content in self.report_sections.items():
            if content is not None:
                latest_section = section
                latest_content = content

        if latest_section and latest_content:
            title = self.SECTION_TITLES.get(latest_section, latest_section)
            self.current_report = f"### {title}\n{latest_content}"

        self._update_final_report()

    def _update_final_report(self) -> None:
        parts: list[str] = []

        analyst_sections = ["market_report", "sentiment_report", "news_report", "fundamentals_report"]
        if any(self.report_sections.get(s) for s in analyst_sections):
            parts.append("## Analyst Team Reports")
            for section in analyst_sections:
                content = self.report_sections.get(section)
                if content:
                    title = self.SECTION_TITLES.get(section, section)
                    parts.append(f"### {title}\n{content}")

        for section, title_key in [("investment_plan", "Research Team Decision"),
                                    ("trader_investment_plan", "Trading Team Plan"),
                                    ("final_trade_decision", "Portfolio Management Decision")]:
            content = self.report_sections.get(section)
            if content:
                parts.append(f"## {title_key}")
                parts.append(str(content))

        self.final_report = "\n\n".join(parts) if parts else None

    async def _update_analyst_statuses(self, chunk: dict[str, Any]) -> None:
        """Mirrors ``cli.main.update_analyst_statuses``."""
        if not self.selected_analysts:
            return

        # Check which analysts have provided their report in this chunk
        analyst_report_map = {
            "market": "market_report",
            "social": "sentiment_report",
            "news": "news_report",
            "fundamentals": "fundamentals_report",
        }

        for analyst_key in self.ANALYST_ORDER:
            if analyst_key not in self.selected_analysts:
                continue
            report_key = analyst_report_map.get(analyst_key)
            if report_key and chunk.get(report_key):
                self._completed_analysts.add(analyst_key)
                await self.update_report_section(report_key, chunk[report_key])

        # Set statuses based on completion order
        found_current = False
        for analyst_key in self.ANALYST_ORDER:
            if analyst_key not in self.selected_analysts:
                continue
            name = self.ANALYST_MAPPING[analyst_key]

            if analyst_key in self._completed_analysts:
                if self.agent_status.get(name) != "completed":
                    await self.update_agent_status(name, "completed")
                continue

            if not found_current:
                if self.agent_status.get(name) != "in_progress":
                    await self.update_agent_status(name, "in_progress")
                found_current = True
            else:
                if self.agent_status.get(name) != "pending":
                    await self.update_agent_status(name, "pending")

        # All analysts done → start research
        if len(self._completed_analysts) == len(self.selected_analysts):
            await self.update_agent_status("Bull Researcher", "in_progress")

    async def _handle_investment_debate(self, state: dict[str, Any]) -> None:
        if not state:
            return
        judge = state.get("judge_decision", "")
        history = state.get("history", [])
        bull_hist = state.get("bull_history", [])
        bear_hist = state.get("bear_history", [])

        # Let the frontend know research is in progress
        if bull_hist or bear_hist:
            await self.update_agent_status("Bull Researcher", "in_progress")
            await self.update_agent_status("Bear Researcher", "in_progress")

        if judge:
            content = str(judge)
            await self.update_report_section("investment_plan", content)
            await self.update_agent_status("Bull Researcher", "completed")
            await self.update_agent_status("Bear Researcher", "completed")
            await self.update_agent_status("Research Manager", "completed")
            await self.update_agent_status("Trader", "in_progress")

    async def _handle_risk_debate(self, state: dict[str, Any]) -> None:
        if not state:
            return
        judge = state.get("judge_decision", "")
        agg_hist = state.get("aggressive_history", [])
        con_hist = state.get("conservative_history", [])
        neu_hist = state.get("neutral_history", [])

        if agg_hist or con_hist or neu_hist:
            await self.update_agent_status("Aggressive Analyst", "in_progress")

        if judge:
            await self.update_report_section("final_trade_decision", str(judge))
            await self.update_agent_status("Aggressive Analyst", "completed")
            await self.update_agent_status("Neutral Analyst", "completed")
            await self.update_agent_status("Conservative Analyst", "completed")
            await self.update_agent_status("Portfolio Manager", "completed")
