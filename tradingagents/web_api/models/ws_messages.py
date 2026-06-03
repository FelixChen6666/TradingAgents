"""WebSocket message models — the protocol contract between frontend and backend.

Every message has a ``type`` discriminator string and a ``payload`` dict.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ── Inbound (client → server) ──────────────────────────────────────────

class StartAnalysisPayload(BaseModel):
    ticker: str
    analysis_date: str  # YYYY-MM-DD
    analysts: list[str] = Field(default_factory=list)  # e.g. ["market", "social"]
    research_depth: int = 1
    llm_provider: str = "openai"
    backend_url: str | None = None
    shallow_thinker: str = ""
    deep_thinker: str = ""
    google_thinking_level: str | None = None
    openai_reasoning_effort: str | None = None
    anthropic_effort: str | None = None
    output_language: str = "English"
    data_vendors: dict[str, str] = Field(default_factory=dict)
    asset_type: str = "stock"
    checkpoint_enabled: bool = False
    api_keys: dict[str, str] = Field(default_factory=dict)
    holds_stock: bool = False
    position_quantity: float | None = None
    position_avg_cost: float | None = None


class StartAnalysisMessage(BaseModel):
    type: Literal["start_analysis"] = "start_analysis"
    payload: StartAnalysisPayload


class CancelAnalysisMessage(BaseModel):
    type: Literal["cancel_analysis"] = "cancel_analysis"
    payload: dict[str, Any] = Field(default_factory=dict)


WebSocketInboundMessage = StartAnalysisMessage | CancelAnalysisMessage


# ── Outbound (server → client) ─────────────────────────────────────────

class ConnectionEstablished(BaseModel):
    type: Literal["connection_established"] = "connection_established"
    payload: dict[str, Any]  # { session_id: str }


class AnalysisStarted(BaseModel):
    type: Literal["analysis_started"] = "analysis_started"
    payload: dict[str, Any]  # { ticker, date, analysts }


class AgentStatusUpdate(BaseModel):
    type: Literal["agent_status_update"] = "agent_status_update"
    payload: dict[str, Any]  # { agent_name, status }


class MessageEvent(BaseModel):
    type: Literal["message"] = "message"
    payload: dict[str, Any]  # { timestamp, type, content }


class ToolCallEvent(BaseModel):
    type: Literal["tool_call"] = "tool_call"
    payload: dict[str, Any]  # { timestamp, name, args }


class ReportSectionUpdate(BaseModel):
    type: Literal["report_section_update"] = "report_section_update"
    payload: dict[str, Any]  # { section, content }


class StatsUpdate(BaseModel):
    type: Literal["stats_update"] = "stats_update"
    payload: dict[str, Any]  # { llm_calls, tool_calls, tokens_in, tokens_out, elapsed_seconds }


class AnalysisComplete(BaseModel):
    type: Literal["analysis_complete"] = "analysis_complete"
    payload: dict[str, Any]  # { summary, wall_times }


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    payload: dict[str, Any]  # { message }


WebSocketOutboundMessage = (
    ConnectionEstablished
    | AnalysisStarted
    | AgentStatusUpdate
    | MessageEvent
    | ToolCallEvent
    | ReportSectionUpdate
    | StatsUpdate
    | AnalysisComplete
    | ErrorEvent
)
