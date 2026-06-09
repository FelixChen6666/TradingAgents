"""Pydantic schemas used by agents that produce structured output.

The framework's primary artifact is still prose: each agent's natural-language
reasoning is what users read in the saved markdown reports and what the
downstream agents read as context.  Structured output is layered onto the
three decision-making agents (Research Manager, Trader, Portfolio Manager)
so that:

- Their outputs follow consistent section headers across runs and providers
- Each provider's native structured-output mode is used (json_schema for
  OpenAI/xAI, response_schema for Gemini, tool-use for Anthropic)
- Schema field descriptions become the model's output instructions, freeing
  the prompt body to focus on context and the rating-scale guidance
- A render helper turns the parsed Pydantic instance back into the same
  markdown shape the rest of the system already consumes, so display,
  memory log, and saved reports keep working unchanged
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared rating types
# ---------------------------------------------------------------------------


class PortfolioRating(str, Enum):
    """5-tier rating used by the Research Manager and Portfolio Manager."""

    BUY = "Buy"
    OVERWEIGHT = "Overweight"
    HOLD = "Hold"
    UNDERWEIGHT = "Underweight"
    SELL = "Sell"


class TraderAction(str, Enum):
    """3-tier transaction direction used by the Trader.

    The Trader's job is to translate the Research Manager's investment plan
    into a concrete transaction proposal: should the desk execute a Buy, a
    Sell, or sit on Hold this round.  Position sizing and the nuanced
    Overweight / Underweight calls happen later at the Portfolio Manager.
    """

    BUY = "Buy"
    HOLD = "Hold"
    SELL = "Sell"


# ---------------------------------------------------------------------------
# Research Manager
# ---------------------------------------------------------------------------


class ResearchPlan(BaseModel):
    """Structured investment plan produced by the Research Manager.

    Hand-off to the Trader: the recommendation pins the directional view,
    the rationale captures which side of the bull/bear debate carried the
    argument, and the strategic actions translate that into concrete
    instructions the trader can execute against.
    """

    recommendation: PortfolioRating = Field(
        description=(
            "The investment recommendation. Exactly one of Buy / Overweight / "
            "Hold / Underweight / Sell. Reserve Hold for situations where the "
            "evidence on both sides is genuinely balanced; otherwise commit to "
            "the side with the stronger arguments."
        ),
    )
    rationale: str = Field(
        description=(
            "Conversational summary of the key points from both sides of the "
            "debate, ending with which arguments led to the recommendation. "
            "Speak naturally, as if to a teammate."
        ),
    )
    strategic_actions: str = Field(
        description=(
            "Concrete steps for the trader to implement the recommendation, "
            "including position sizing guidance consistent with the rating."
        ),
    )


def render_research_plan(plan: ResearchPlan) -> str:
    """Render a ResearchPlan to markdown for storage and the trader's prompt context."""
    return "\n".join([
        f"**Recommendation**: {plan.recommendation.value}",
        "",
        f"**Rationale**: {plan.rationale}",
        "",
        f"**Strategic Actions**: {plan.strategic_actions}",
    ])


# ---------------------------------------------------------------------------
# Trader
# ---------------------------------------------------------------------------


class TraderProposal(BaseModel):
    """Structured transaction proposal produced by the Trader.

    The trader reads the Research Manager's investment plan and the analyst
    reports, then turns them into a concrete transaction: what action to
    take, the reasoning that justifies it, and the practical levels for
    entry, stop-loss, and sizing.
    """

    action: TraderAction = Field(
        description="The transaction direction. Exactly one of Buy / Hold / Sell.",
    )
    reasoning: str = Field(
        description=(
            "The case for this action, anchored in the analysts' reports and "
            "the research plan. Two to four sentences."
        ),
    )
    entry_price: Optional[float] = Field(
        default=None,
        description="Optional entry price target in the instrument's quote currency.",
    )
    stop_loss: Optional[float] = Field(
        default=None,
        description="Optional stop-loss price in the instrument's quote currency.",
    )
    position_sizing: Optional[str] = Field(
        default=None,
        description="Optional sizing guidance, e.g. '5% of portfolio'.",
    )


def render_trader_proposal(proposal: TraderProposal) -> str:
    """Render a TraderProposal to markdown.

    The trailing ``FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**`` line is
    preserved for backward compatibility with the analyst stop-signal text
    and any external code that greps for it.
    """
    parts = [
        f"**Action**: {proposal.action.value}",
        "",
        f"**Reasoning**: {proposal.reasoning}",
    ]
    if proposal.entry_price is not None:
        parts.extend(["", f"**Entry Price**: {proposal.entry_price}"])
    if proposal.stop_loss is not None:
        parts.extend(["", f"**Stop Loss**: {proposal.stop_loss}"])
    if proposal.position_sizing:
        parts.extend(["", f"**Position Sizing**: {proposal.position_sizing}"])
    parts.extend([
        "",
        f"FINAL TRANSACTION PROPOSAL: **{proposal.action.value.upper()}**",
    ])
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Portfolio Manager
# ---------------------------------------------------------------------------


class HoldingAction(str, Enum):
    """Position-aware action recommendation based on analysis + current holdings.

    Maps the analytical rating to a concrete action given whether the user
    already holds the instrument and how large their position is.
    """

    OPEN_NEW = "开仓买入"
    ADD_TO = "加仓"
    HOLD = "持有不动"
    REDUCE = "减仓"
    CLOSE = "清仓卖出"
    WAIT = "观望等待"


class PortfolioDecision(BaseModel):
    """Structured output produced by the Portfolio Manager.

    The model fills every field as part of its primary LLM call; no separate
    extraction pass is required. Field descriptions double as the model's
    output instructions, so the prompt body only needs to convey context and
    the rating-scale guidance.
    """

    rating: PortfolioRating = Field(
        description=(
            "The final position rating. Exactly one of Buy / Overweight / Hold / "
            "Underweight / Sell, picked based on the analysts' debate."
        ),
    )
    executive_summary: str = Field(
        description=(
            "A concise action plan covering entry strategy, position sizing, "
            "key risk levels, and time horizon. Two to four sentences."
        ),
    )
    investment_thesis: str = Field(
        description=(
            "Detailed reasoning anchored in specific evidence from the analysts' "
            "debate. If prior lessons are referenced in the prompt context, "
            "incorporate them; otherwise rely solely on the current analysis."
        ),
    )
    current_position_summary: Optional[str] = Field(
        default=None,
        description=(
            "Summary of the user's current position in this instrument, "
            "e.g. 'Not holding' or 'Holding 100 shares at $150 avg cost'. "
            "Reflect what was provided; do not invent holdings."
        ),
    )
    holding_action: Optional[str] = Field(
        default=None,
        description=(
            "Concrete action recommendation informed by both the analysis "
            "rating and the user's current position. Choose from: "
            "开仓买入 (open new position when not holding + bullish), "
            "加仓 (add to existing position when holding + bullish), "
            "持有不动 (hold when holding + neutral/bullish), "
            "减仓 (reduce when holding + bearish), "
            "清仓卖出 (close entirely when holding + strongly bearish), "
            "观望等待 (wait when not holding + neutral/bearish)."
        ),
    )
    price_target: Optional[float] = Field(
        default=None,
        description="Optional target price in the instrument's quote currency.",
    )
    time_horizon: Optional[str] = Field(
        default=None,
        description="Optional recommended holding period, e.g. '3-6 months'.",
    )


def render_pm_decision(decision: PortfolioDecision) -> str:
    """Render a PortfolioDecision back to the markdown shape the rest of the system expects.

    Memory log, CLI display, and saved report files all read this markdown,
    so the rendered output preserves the exact section headers (``**Rating**``,
    ``**Executive Summary**``, ``**Investment Thesis**``) that downstream
    parsers and the report writers already handle.
    """
    parts = [
        f"**Rating**: {decision.rating.value}",
        "",
        f"**Executive Summary**: {decision.executive_summary}",
        "",
        f"**Investment Thesis**: {decision.investment_thesis}",
    ]
    if decision.current_position_summary:
        parts.extend(["", f"**Current Position**: {decision.current_position_summary}"])
    if decision.holding_action:
        parts.extend(["", f"**Holding Action**: {decision.holding_action}"])
    if decision.price_target is not None:
        parts.extend(["", f"**Price Target**: {decision.price_target}"])
    if decision.time_horizon:
        parts.extend(["", f"**Time Horizon**: {decision.time_horizon}"])
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Sentiment Analyst
# ---------------------------------------------------------------------------


class SentimentBand(str, Enum):
    """Discrete sentiment direction produced by the Sentiment Analyst.

    Six tiers keep the signal granular enough to be actionable while remaining
    small enough for every provider to map reliably from its JSON output.
    """

    BULLISH = "Bullish"
    MILDLY_BULLISH = "Mildly Bullish"
    NEUTRAL = "Neutral"
    MIXED = "Mixed"
    MILDLY_BEARISH = "Mildly Bearish"
    BEARISH = "Bearish"


class SentimentReport(BaseModel):
    """Structured sentiment report produced by the Sentiment Analyst.

    Replaces the previous free-form prose output so downstream consumers
    (dashboards, audit logs, PDF renderers, other agents) can read
    ``overall_band`` and ``overall_score`` without maintaining fragile regex
    fallbacks that drift with every model release. ``narrative`` preserves the
    rich source-by-source analysis; ``render_sentiment_report`` prepends a
    deterministic header so the saved report stays human-readable.
    """

    overall_band: SentimentBand = Field(
        description=(
            "Overall sentiment direction. Exactly one of: "
            "Bullish / Mildly Bullish / Neutral / Mixed / Mildly Bearish / Bearish. "
            "Use Mixed when sources point in clearly different directions. "
            "Use Neutral only when all sources are genuinely silent or non-committal."
        ),
    )
    overall_score: float = Field(
        ge=0.0,
        le=10.0,
        description=(
            "Numeric sentiment intensity on a 0–10 scale. "
            "0 = maximally bearish, 5 = neutral, 10 = maximally bullish. "
            "Guideline for consistency with overall_band: "
            "Bullish ~6.5–10, Mildly Bullish ~5.5–6.4, Neutral/Mixed ~4.5–5.5, "
            "Mildly Bearish ~3.5–4.4, Bearish ~0–3.4. "
            "Only the 0–10 bounds are enforced."
        ),
    )
    confidence: Literal["low", "medium", "high"] = Field(
        description=(
            "Confidence in the assessment based on data quality and sample size. "
            "Use 'low' when one or more sources returned a placeholder or fewer "
            "than 5 data points; 'medium' when data is present but sparse; "
            "'high' when all three sources returned substantive data."
        ),
    )
    narrative: str = Field(
        description=(
            "Full sentiment report covering, in order: "
            "(1) source-by-source breakdown with specific evidence (cite message "
            "counts, ratios, notable posts); "
            "(2) cross-source divergences and alignments; "
            "(3) dominant narrative themes; "
            "(4) catalysts and risks surfaced by the data; "
            "(5) a markdown table summarising key sentiment signals, their "
            "direction, source, and supporting evidence."
        ),
    )


def render_sentiment_report(report: SentimentReport) -> str:
    """Render a SentimentReport to the markdown shape the rest of the system expects.

    The structured header (band + score + confidence) is prepended to the
    narrative so the saved report is both human-readable and machine-parseable
    without regex.
    """
    return "\n".join([
        f"**Overall Sentiment:** **{report.overall_band.value}** "
        f"(Score: {report.overall_score:.1f}/10)",
        f"**Confidence:** {report.confidence.capitalize()}",
        "",
        report.narrative,
    ])


# ---------------------------------------------------------------------------
# Multi-Stock Comparison & Ranking
# ---------------------------------------------------------------------------


class MomentumFactors(BaseModel):
    """Momentum-related factors for short-term ranking."""

    return_12m: Optional[float] = Field(
        default=None,
        description="12-month price return excluding the most recent month",
    )
    return_5d: Optional[float] = Field(
        default=None,
        description="5-trading-day price return",
    )
    proximity_to_52w_high: Optional[float] = Field(
        default=None,
        description="Current price proximity to 52-week high, 0-1 scale",
    )
    rps_percentile: Optional[float] = Field(
        default=None,
        description="Relative Price Strength percentile vs full market, 0-100",
    )


class VolumeFactors(BaseModel):
    """Volume and accumulation factors."""

    relative_volume_ratio: Optional[float] = Field(
        default=None,
        description="Current volume / 20-day average volume",
    )
    chaikin_money_flow: Optional[float] = Field(
        default=None,
        description="20-day Chaikin Money Flow value, -1 to 1",
    )
    up_down_volume_ratio: Optional[float] = Field(
        default=None,
        description="Ratio of up-day volume to down-day volume over 10 days",
    )


class TechnicalFactors(BaseModel):
    """Technical indicator signals."""

    rsi_14: Optional[float] = Field(
        default=None,
        description="14-day RSI value, 0-100",
    )
    macd_signal: Optional[str] = Field(
        default=None,
        description="MACD signal direction: bullish_cross, bearish_cross, positive, negative",
    )
    bb_position: Optional[float] = Field(
        default=None,
        description="Price position within Bollinger Bands, 0 (lower) to 1 (upper)",
    )
    ma_alignment: Optional[str] = Field(
        default=None,
        description="Moving average alignment: bullish, bearish, mixed",
    )


class CapitalFlowFactors(BaseModel):
    """Capital flow factors (A-share specific)."""

    main_force_net_inflow_5d: Optional[float] = Field(
        default=None,
        description="Aggregated main force net capital inflow over 5 trading days",
    )
    northbound_change: Optional[float] = Field(
        default=None,
        description="Northbound (沪深港通) position change, if available",
    )


class StockRankingFactors(BaseModel):
    """Aggregated ranking factors for a single stock."""

    momentum: MomentumFactors = Field(
        default_factory=MomentumFactors,
        description="Momentum-related factors",
    )
    volume: VolumeFactors = Field(
        default_factory=VolumeFactors,
        description="Volume and accumulation factors",
    )
    technical: TechnicalFactors = Field(
        default_factory=TechnicalFactors,
        description="Technical indicator signals",
    )
    capital_flow: CapitalFlowFactors = Field(
        default_factory=CapitalFlowFactors,
        description="Capital flow factors",
    )
    short_term_score: Optional[float] = Field(
        default=None,
        description="Composite short-term score, 0-100",
    )


class ThemeTag(BaseModel):
    """A single theme/concept tag identified for a stock."""

    theme_name: str = Field(
        description="Theme or concept name, e.g. '人工智能', '新能源', '券商'",
    )
    relevance: float = Field(
        ge=0.0,
        le=1.0,
        description="Relevance score 0-1",
    )
    evidence: str = Field(
        description="Evidence supporting why this stock belongs to this theme",
    )


class LeaderPerception(BaseModel):
    """Perception of whether the stock is a sector leader (龙头)."""

    is_leader: bool = Field(
        description="Whether this stock is perceived as a sector leader",
    )
    sector: str = Field(
        description="The sector or industry this stock operates in",
    )
    confidence: str = Field(
        description="Confidence level: 高 / 中 / 低",
    )
    reasoning: str = Field(
        description="Reasoning for leader perception judgment",
    )


class IndividualStockRanking(BaseModel):
    """Ranked entry for a single stock in the comparison report."""

    ticker: str = Field(
        description="Stock ticker symbol",
    )
    company_name: str = Field(
        description="Company name",
    )
    short_term_score: float = Field(
        ge=0,
        le=100,
        description="Composite short-term score, 0-100",
    )
    pm_rating: str = Field(
        description="Portfolio Manager rating: Buy/Overweight/Hold/Underweight/Sell",
    )
    themes: list[ThemeTag] = Field(
        description="Identified theme/concept tags for this stock",
    )
    leader_perception: LeaderPerception = Field(
        description="Leader stock perception",
    )
    report_summary: str = Field(
        description="Concise summary of the full analyst report, ~300 chars",
    )


class ComparisonReport(BaseModel):
    """Top-level output for the multi-stock comparison and ranking feature."""

    generated_at: str = Field(
        description="Timestamp when the report was generated",
    )
    analysis_date: str = Field(
        description="The analysis date in YYYY-MM-DD format",
    )
    total_stocks: int = Field(
        description="Number of stocks analyzed",
    )
    ranked_stocks: list[IndividualStockRanking] = Field(
        description="Stocks ranked by short_term_score in descending order",
    )
    market_context: str = Field(
        description="Brief description of the A-share market context on analysis date",
    )
    key_themes: list[str] = Field(
        description="Top 3-5 most important themes identified across all stocks",
    )


def render_comparison_report(report: ComparisonReport) -> str:
    """Render a ComparisonReport to markdown for display and saving."""
    lines = [
        "# Multi-Stock Comparison Report",
        "",
        f"**Generated at**: {report.generated_at}",
        f"**Analysis Date**: {report.analysis_date}",
        f"**Total Stocks**: {report.total_stocks}",
        "",
        "---",
        "",
        "## Market Context",
        "",
        report.market_context,
        "",
        "---",
        "",
        "## Ranking Table",
        "",
        "| Rank | Ticker | Company | Short-Term Score | PM Rating | Themes | Leader |",
        "|------|--------|---------|-----------------|-----------|--------|--------|",
    ]
    for i, stock in enumerate(report.ranked_stocks, 1):
        theme_str = ", ".join(t.theme_name for t in stock.themes[:3])
        leader_str = "✓" if stock.leader_perception.is_leader else "✗"
        lines.append(
            f"| {i} | {stock.ticker} | {stock.company_name} | "
            f"{stock.short_term_score:.1f}/100 | {stock.pm_rating} | "
            f"{theme_str} | {leader_str} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## Key Themes",
        "",
    ])
    for theme in report.key_themes:
        lines.append(f"- **{theme}**")

    lines.extend([
        "",
        "---",
        "",
        "## Detailed Stock Analysis",
        "",
    ])
    for i, stock in enumerate(report.ranked_stocks, 1):
        lines.extend([
            f"### {i}. {stock.ticker} — {stock.company_name}",
            "",
            f"**Short-Term Score**: {stock.short_term_score:.1f}/100",
            f"**PM Rating**: {stock.pm_rating}",
            "",
            "**Themes:**",
        ])
        for theme in stock.themes:
            lines.append(f"- {theme.theme_name} (relevance: {theme.relevance:.2f}) — {theme.evidence}")
        lines.extend([
            "",
            f"**Leader Perception**: {'Yes' if stock.leader_perception.is_leader else 'No'} "
            f"(confidence: {stock.leader_perception.confidence})",
            f"**Sector**: {stock.leader_perception.sector}",
            f"**Reasoning**: {stock.leader_perception.reasoning}",
            "",
            "**Report Summary:**",
            "",
            stock.report_summary,
            "",
            "---",
            "",
        ])

    return "\n".join(lines)


def render_ranking_table(stocks: list[IndividualStockRanking]) -> str:
    """Render just the ranking table portion for quick display."""
    lines = [
        "| Rank | Ticker | Company | Score | PM Rating | Top Theme | Leader |",
        "|------|--------|---------|-------|-----------|-----------|--------|",
    ]
    for i, stock in enumerate(stocks, 1):
        top_theme = stock.themes[0].theme_name if stock.themes else "-"
        leader_str = "✓" if stock.leader_perception.is_leader else "✗"
        lines.append(
            f"| {i} | {stock.ticker} | {stock.company_name} | "
            f"{stock.short_term_score:.1f} | {stock.pm_rating} | "
            f"{top_theme} | {leader_str} |"
        )
    return "\n".join(lines)
