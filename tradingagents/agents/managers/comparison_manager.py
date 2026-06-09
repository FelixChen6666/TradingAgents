"""Comparison Manager: synthesises multi-stock analysis into a ranked comparison report.

This is the Phase-2 LLM agent that reads:
- Per-stock computed ranking factors (data-driven scores)
- Per-stock Portfolio Manager ratings
- Truncated per-stock report summaries
- Market context (breadth, turnover, limit-up counts)
- AKShare concept tags per stock
- Recent East Money news snippets

And produces a ``ComparisonReport`` with ranked stocks, themes, and leader perception.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from tradingagents.agents.schemas import (
    ComparisonReport,
    IndividualStockRanking,
    LeaderPerception,
    StockRankingFactors,
    ThemeTag,
    render_comparison_report,
)
from tradingagents.agents.utils.agent_utils import get_language_instruction
from tradingagents.agents.utils.structured import (
    bind_structured,
)


def create_comparison_manager(deep_thinking_llm):
    """Create the Comparison Manager LLM agent node.

    Args:
        deep_thinking_llm: The deep-thinking LLM instance (same as
            research_manager/portfolio_manager).

    Returns:
        A callable that takes analysis context and returns a ComparisonReport.
    """
    structured_llm = bind_structured(deep_thinking_llm, ComparisonReport, "Comparison Manager")

    def comparison_manager(
        *,
        tickers: list[str],
        trade_date: str,
        analysis_results: dict[str, Any],
        factor_results: dict[str, StockRankingFactors],
        market_breadth: dict | None = None,
        concept_tags: dict[str, list[dict]] | None = None,
        news_snippets: dict[str, str] | None = None,
    ) -> ComparisonReport:
        """Run the Comparison Manager: synthesise all per-stock results into a ranked report.

        Args:
            tickers: List of stock tickers.
            trade_date: Analysis date (YYYY-MM-DD).
            analysis_results: Dict mapping ticker -> final_state from TradingAgentsGraph.
            factor_results: Dict mapping ticker -> StockRankingFactors.
            market_breadth: Optional market breadth data from get_market_breadth().
            concept_tags: Optional dict mapping ticker -> list of concept board dicts.
            news_snippets: Optional dict mapping ticker -> recent news text snippet.

        Returns:
            A ComparisonReport with ranked stocks.
        """
        # Build the comparison table for the prompt
        table_rows = []
        for ticker in tickers:
            factors = factor_results.get(ticker)
            result = analysis_results.get(ticker)
            if factors is None or result is None:
                continue

            score = factors.short_term_score or 50.0
            pm_rating = _extract_pm_rating(result)
            summary = _extract_report_summary(result)

            concepts = (concept_tags or {}).get(ticker, [])
            concept_str = "; ".join(
                c.get("board_name", "") for c in concepts
                if isinstance(c, dict) and "error" not in c
            ) or "无"

            news = (news_snippets or {}).get(ticker, "")
            news_str = news[:200] if news else "无"

            m = factors.momentum
            v = factors.volume
            t = factors.technical
            cf = factors.capital_flow

            table_rows.append(f"""
=== {ticker} ===
Company: {result.get('instrument_context', ticker).split(chr(10))[0] if result.get('instrument_context') else ticker}
Short-Term Score: {score}/100
PM Rating: {pm_rating}
Concepts: {concept_str}

**Factors:**
- Momentum: 5d={_fmt_pct(m.return_5d)}, 52w prox={_fmt_num(m.proximity_to_52w_high, 2)}, RPS={_fmt_num(m.rps_percentile, 1)}%
- Volume: rel_vol={_fmt_num(v.relative_volume_ratio, 2)}, CMF={_fmt_num(v.chaikin_money_flow, 2)}, up/down vol ratio={_fmt_num(v.up_down_volume_ratio, 2)}
- Technical: RSI={_fmt_num(t.rsi_14, 1)}, MACD={t.macd_signal or "N/A"}, BB pos={_fmt_num(t.bb_position, 2)}, MA alignment={t.ma_alignment or "N/A"}
- Capital Flow: main_force_5d={_fmt_num(cf.main_force_net_inflow_5d, 0)}

**Report Summary:**
{summary}

**Recent News:**
{news_str}
""")

        comparison_table = "\n".join(table_rows)

        # Market context string
        market_str = _format_market_context(market_breadth)

        language_suffix = get_language_instruction()
        prompt = f"""You are a senior quantitative analyst. Your task is to compare and rank the following stocks, producing a comprehensive buy-recommendation ranking list.

{market_str}

---

**Instructions:**

For each stock, you have:
1. A computed **Short-Term Score** (0-100) based on momentum, volume, technical, and capital flow factors
2. A **PM Rating** (Buy/Overweight/Hold/Underweight/Sell) from the Portfolio Manager agent
3. **Factor breakdowns** for transparency
4. **Concept board tags** and **recent news** for theme identification

Your job is to:

### 1. Short-Term Score
- Use the provided score as the primary ranking criterion
- The score is already computed from data — do not recompute
- You may adjust the relative order based on qualitative factors (news quality, PM conviction)

### 2. Theme/Tag Identification
- Identify 1-3 concept themes per stock
- Use the AKShare concept tags as evidence
- Enrich with your understanding of current market themes
- Mark themes that show recent catalyst potential (from news)

### 3. Leader Stock Perception (龙头感知)
- Judge whether each stock is a leader in its sector
- Criteria: sector position, RPS percentile, limit-up potential, capital flow
- Distinguish between:
  - **板块龙头** (sector leader): strongest in its theme group
  - **中军** (core holding): stable, large-cap, trend-following
  - **跟风** (follower): moves with the sector but doesn't lead
- Provide clear reasoning for each judgment

### 4. Final Ranking
- Rank stocks from most to least recommended for short-term trading
- Identify the top 3-5 **key themes** across all stocks
- Provide concise but evidence-based summaries

---

**Stocks to Compare:**
{comparison_table}

---

Output your analysis as a structured ComparisonReport. Ensure every field is filled with careful, evidence-backed reasoning.
{language_suffix}"""

        # Try structured output first to get a typed ComparisonReport
        report = None
        if structured_llm is not None:
            try:
                report = structured_llm.invoke(prompt)
            except Exception as exc:
                logger.warning(
                    "Comparison Manager: structured-output invocation failed (%s); retrying once as free text",
                    exc,
                )

        # If structured output unavailable or failed, fall back to free text
        if report is None:
            try:
                response = deep_thinking_llm.invoke(prompt)
                free_text = response.content
                logger.info("Comparison Manager: using free-text fallback (%d chars)", len(free_text))
            except Exception as exc:
                logger.error("Comparison Manager: free-text fallback also failed (%s)", exc)
                free_text = ""

            if free_text:
                report = ComparisonReport(
                    generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                    analysis_date=trade_date,
                    total_stocks=len(tickers),
                    ranked_stocks=_fallback_ranking(tickers, analysis_results, factor_results),
                    market_context=market_str,
                    key_themes=["See full report"],
                )
                # Attach the free-text as a report summary on the first stock
                if report.ranked_stocks and free_text:
                    report.ranked_stocks[0].report_summary = (
                        free_text[:3000] + "..." if len(free_text) > 3000 else free_text
                    )
            else:
                report = ComparisonReport(
                    generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                    analysis_date=trade_date,
                    total_stocks=len(tickers),
                    ranked_stocks=_fallback_ranking(tickers, analysis_results, factor_results),
                    market_context=market_str,
                    key_themes=["See full report"],
                )

        return report

    return comparison_manager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_pm_rating(state: dict) -> str:
    """Extract PM rating from a final state dict."""
    decision = state.get("final_trade_decision", "")
    if not decision:
        return "Hold"
    for rating in ("Buy", "Overweight", "Hold", "Underweight", "Sell"):
        if f"**Rating**: {rating}" in decision:
            return rating
    return "Hold"


def _extract_report_summary(state: dict) -> str:
    """Extract a concise summary from all analyst reports in the state."""
    parts = []
    for key, label in [
        ("market_report", "Market"),
        ("sentiment_report", "Sentiment"),
        ("news_report", "News"),
        ("fundamentals_report", "Fundamentals"),
    ]:
        text = state.get(key, "")
        if text:
            # Take first 2 lines as summary
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            head = " ".join(lines[:3])[:200]
            parts.append(f"[{label}] {head}")
    return " | ".join(parts[:3]) if parts else "Analysis completed."


def _fmt_pct(val, default="N/A"):
    if val is not None:
        return f"{val * 100:.1f}%"
    return default


def _fmt_num(val, decimals=2):
    if val is not None:
        if isinstance(val, float):
            return f"{val:.{decimals}f}"
        return str(val)
    return "N/A"


def _format_market_context(market_breadth: dict | None) -> str:
    """Format market breadth data into a prompt-readable string."""
    if not market_breadth or "error" in market_breadth:
        return "### Market Context\nMarket breadth data unavailable."
    return f"""### Market Context
- Total A-shares tracked: {market_breadth.get('total_stocks', 'N/A')}
- Advancing / Declining: {market_breadth.get('advance_count', 'N/A')} / {market_breadth.get('decline_count', 'N/A')}
- Limit-up / Limit-down: {market_breadth.get('limit_up_count', 'N/A')} / {market_breadth.get('limit_down_count', 'N/A')}
- Total Turnover: {_fmt_num(market_breadth.get('total_turnover', 0) / 1e8, 0)} 亿
- Median Turnover Rate: {_fmt_num(market_breadth.get('median_turnover_rate', 0), 1)}%
"""


def _extract_company_name(result: dict, ticker: str) -> str:
    """Extract a clean company name from the analysis state."""
    ctx = result.get("instrument_context", "")
    if not ctx:
        return ticker
    # instrument_context format: "The instrument to analyze is `TICKER`. ...
    # Resolved identity: Company: NAME; ..."
    import re
    m = re.search(r"Company:\s*([^;.]+)", ctx)
    if m:
        return m.group(1).strip()
    return ticker


def _fallback_ranking(
    tickers: list[str],
    analysis_results: dict[str, dict],
    factor_results: dict[str, StockRankingFactors],
) -> list[IndividualStockRanking]:
    """Fallback: rank by computed score when structured LLM output fails."""
    ranked = []
    for ticker in tickers:
        factors = factor_results.get(ticker)
        result = analysis_results.get(ticker)
        if factors is None or result is None:
            continue
        score = factors.short_term_score or 50.0
        pm_rating = _extract_pm_rating(result)
        summary = _extract_report_summary(result)
        ranked.append(IndividualStockRanking(
            ticker=ticker,
            company_name=_extract_company_name(result, ticker),
            short_term_score=score,
            pm_rating=pm_rating,
            themes=[],
            leader_perception=LeaderPerception(
                is_leader=False,
                sector="未知",
                confidence="低",
                reasoning="LLM structured output unavailable; using data-driven fallback",
            ),
            report_summary=summary,
        ))
    ranked.sort(key=lambda x: x.short_term_score, reverse=True)
    return ranked
