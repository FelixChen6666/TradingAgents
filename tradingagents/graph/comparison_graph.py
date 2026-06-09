"""Comparison Orchestrator: parallel multi-stock analysis + LLM synthesis.

Architecture:
  Phase 1 — Run ``TradingAgentsGraph.propagate()`` for each stock in
             parallel via ``ThreadPoolExecutor``.
  Phase 2 — Compute data-driven ranking factors (``RankingCalculator``).
  Phase 3 — Synthesise into a ``ComparisonReport`` (``ComparisonManager``).

Each stock gets its own isolated graph instance — this avoids concurrency
issues in LangGraph's single-ticker ``StateGraph``.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Optional

from tradingagents.agents.managers.comparison_manager import create_comparison_manager
from tradingagents.agents.schemas import ComparisonReport, IndividualStockRanking
from tradingagents.agents.utils.ranking_calculator import RankingCalculator
from tradingagents.dataflows.interface import route_to_vendor
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

logger = logging.getLogger(__name__)


class ComparisonOrchestrator:
    """Top-level orchestrator for multi-stock comparison and ranking.

    Usage::

        orch = ComparisonOrchestrator(config)
        report = orch.run_comparison(
            tickers=["600519", "300750", "000858"],
            trade_date="2026-06-03",
            selected_analysts=["market", "news", "sentiment", "fundamentals"],
        )
    """

    def __init__(
        self,
        config: dict | None = None,
    ):
        self.config = config or DEFAULT_CONFIG
        self.calculator = RankingCalculator()

    def run_comparison(
        self,
        tickers: list[str],
        trade_date: str,
        selected_analysts: list[str] | None = None,
        max_workers: int = 5,
        callbacks: Optional[list] = None,
    ) -> tuple[ComparisonReport, dict[str, Any]]:
        """Run the full comparison pipeline.

        Args:
            tickers: Stock tickers to compare (max 10).
            trade_date: Analysis date (YYYY-MM-DD).
            selected_analysts: Analyst types to run (default: all).
            max_workers: Parallelism limit.
            callbacks: Optional callback handlers.

        Returns:
            A tuple of ``(ComparisonReport, per_stock_data)`` where
            ``per_stock_data`` maps ticker -> ``{"state": dict, "factors": StockRankingFactors}``.
        """
        if len(tickers) > 10:
            logger.warning("More than 10 tickers provided; truncating to 10.")
            tickers = tickers[:10]

        analysts = selected_analysts or ["market", "social", "news", "fundamentals"]
        callbacks = callbacks or []

        # Phase 1: Parallel per-stock analysis
        logger.info("Phase 1: Running parallel analysis for %d stocks...", len(tickers))
        results = self._run_parallel_analysis(tickers, trade_date, analysts, max_workers, callbacks)

        # Phase 2: Compute ranking factors (data-driven)
        logger.info("Phase 2: Computing ranking factors...")
        factor_results = self._compute_factors(tickers, trade_date)

        # Phase 2b: Fetch auxiliary data
        market_breadth = self._fetch_market_breadth(trade_date)
        concept_tags = self._fetch_concept_tags(tickers)
        news_snippets = self._fetch_news_snippets(tickers, trade_date)

        # Phase 3: LLM synthesis
        logger.info("Phase 3: Running LLM comparison synthesis...")
        report = self._run_synthesis(
            tickers, trade_date, results, factor_results,
            market_breadth, concept_tags, news_snippets,
        )

        # Build per-stock detail dict for downstream save/display
        per_stock_data: dict[str, Any] = {}
        for ticker in tickers:
            state = results.get(ticker, {})
            factors = factor_results.get(ticker)
            per_stock_data[ticker] = {"state": state, "factors": factors}

        return report, per_stock_data

    # ------------------------------------------------------------------
    # Phase 1
    # ------------------------------------------------------------------

    def _run_parallel_analysis(
        self,
        tickers: list[str],
        trade_date: str,
        selected_analysts: list[str],
        max_workers: int,
        callbacks: list,
    ) -> dict[str, dict]:
        """Run TradingAgentsGraph.propagate() for each ticker in parallel."""
        results: dict[str, dict] = {}

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(
                    self._analyze_single_stock,
                    ticker, trade_date, selected_analysts, callbacks,
                ): ticker
                for ticker in tickers
            }
            for future in as_completed(futures):
                ticker = futures[future]
                try:
                    results[ticker] = future.result()
                    logger.info("  ✓ %s analysis completed", ticker)
                except Exception as exc:
                    logger.error("  ✗ %s analysis failed: %s", ticker, exc)
                    # Add a minimal placeholder so downstream doesn't crash
                    results[ticker] = self._make_placeholder_state(ticker, trade_date, str(exc))

        return results

    def _analyze_single_stock(
        self,
        ticker: str,
        trade_date: str,
        selected_analysts: list[str],
        callbacks: list,
    ) -> dict:
        """Run the full trading agents pipeline for a single stock."""
        graph = TradingAgentsGraph(
            selected_analysts=selected_analysts,
            config=self.config,
            debug=False,
            callbacks=callbacks,
        )
        final_state, signal = graph.propagate(ticker, trade_date)
        return final_state

    def _make_placeholder_state(self, ticker: str, trade_date: str, error: str) -> dict:
        """Create a minimal state dict for a failed analysis."""
        return {
            "company_of_interest": ticker,
            "trade_date": trade_date,
            "instrument_context": ticker,
            "final_trade_decision": "**Rating**: Hold\n\n**Error**: " + error,
            "market_report": "",
            "sentiment_report": "",
            "news_report": "",
            "fundamentals_report": "",
            "investment_plan": "",
            "trader_investment_plan": "",
        }

    # ------------------------------------------------------------------
    # Phase 2
    # ------------------------------------------------------------------

    def _compute_factors(
        self,
        tickers: list[str],
        trade_date: str,
    ) -> dict[str, Any]:
        """Compute ranking factors for all tickers."""
        factors = {}
        for ticker in tickers:
            try:
                factors[ticker] = self.calculator.compute_all_factors(ticker, trade_date)
            except Exception as exc:
                logger.warning("Factor computation failed for %s: %s", ticker, exc)
                from tradingagents.agents.schemas import StockRankingFactors
                factors[ticker] = StockRankingFactors()
        return factors

    def _fetch_market_breadth(self, trade_date: str) -> dict | None:
        """Fetch full-market breadth data."""
        try:
            return route_to_vendor("get_market_breadth", trade_date)
        except Exception as exc:
            logger.warning("Market breadth fetch failed: %s", exc)
            return None

    def _fetch_concept_tags(self, tickers: list[str]) -> dict[str, list[dict]]:
        """Fetch concept/industry board tags for all tickers."""
        tags = {}
        for ticker in tickers:
            try:
                data = route_to_vendor("get_stock_concept_tags", ticker)
                if data and isinstance(data, list):
                    tags[ticker] = data
            except Exception as exc:
                logger.debug("Concept tags failed for %s: %s", ticker, exc)
        return tags

    def _fetch_news_snippets(self, tickers: list[str], trade_date: str) -> dict[str, str]:
        """Fetch recent news snippets for all tickers."""
        snippets = {}
        for ticker in tickers:
            try:
                news = route_to_vendor("get_news", ticker, end_date=trade_date)
                if isinstance(news, str):
                    snippets[ticker] = news[:500]
            except Exception as exc:
                logger.debug("News fetch failed for %s: %s", ticker, exc)
        return snippets

    # ------------------------------------------------------------------
    # Phase 3
    # ------------------------------------------------------------------

    def _run_synthesis(
        self,
        tickers: list[str],
        trade_date: str,
        analysis_results: dict[str, dict],
        factor_results: dict[str, Any],
        market_breadth: dict | None,
        concept_tags: dict[str, list[dict]],
        news_snippets: dict[str, str],
    ) -> ComparisonReport:
        """Run the LLM Comparison Manager to produce the final report."""
        # Ensure global config (language, etc.) is set for get_language_instruction()
        from tradingagents.dataflows.config import set_config
        set_config(self.config)

        try:
            from tradingagents.llm_clients import create_llm_client

            llm_kwargs = self._get_provider_kwargs()
            deep_client = create_llm_client(
                provider=self.config.get("llm_provider", "openai"),
                model=self.config.get("deep_think_llm", "gpt-4o"),
                base_url=self.config.get("backend_url"),
                **llm_kwargs,
            )
            comparison_llm = deep_client.get_llm()
            manager = create_comparison_manager(comparison_llm)

            report = manager(
                tickers=tickers,
                trade_date=trade_date,
                analysis_results=analysis_results,
                factor_results=factor_results,
                market_breadth=market_breadth,
                concept_tags=concept_tags,
                news_snippets=news_snippets,
            )
        except Exception as exc:
            logger.error("LLM synthesis failed: %s — using fallback ranking", exc)
            report = ComparisonReport(
                generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                analysis_date=trade_date,
                total_stocks=len(tickers),
                ranked_stocks=self._fallback_ranking(tickers, analysis_results, factor_results),
                market_context=str(market_breadth) if market_breadth else "N/A",
                key_themes=["See full report"],
            )

        return report

    def _fallback_ranking(
        self,
        tickers: list[str],
        analysis_results: dict[str, dict],
        factor_results: dict[str, Any],
    ) -> list[IndividualStockRanking]:
        """Fallback ranking when LLM synthesis fails."""
        from tradingagents.agents.managers.comparison_manager import _extract_pm_rating, _extract_report_summary, _extract_company_name

        ranked = []
        for ticker in tickers:
            factors = factor_results.get(ticker)
            result = analysis_results.get(ticker)
            score = factors.short_term_score if factors and factors.short_term_score is not None else 50.0
            pm_rating = _extract_pm_rating(result) if result else "Hold"
            summary = _extract_report_summary(result) if result else "Analysis unavailable"
            company = _extract_company_name(result, ticker) if result else ticker
            from tradingagents.agents.schemas import LeaderPerception
            ranked.append(IndividualStockRanking(
                ticker=ticker,
                company_name=company,
                short_term_score=score,
                pm_rating=pm_rating,
                themes=[],
                leader_perception=LeaderPerception(
                    is_leader=False,
                    sector="未知",
                    confidence="低",
                    reasoning="Synthesis unavailable; data-driven fallback",
                ),
                report_summary=summary,
            ))
        ranked.sort(key=lambda x: x.short_term_score, reverse=True)
        return ranked

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    def _get_provider_kwargs(self) -> dict:
        """Get provider-specific kwargs for LLM client creation."""
        kwargs = {}
        provider = self.config.get("llm_provider", "").lower()

        if provider == "google":
            thinking_level = self.config.get("google_thinking_level")
            if thinking_level:
                kwargs["thinking_level"] = thinking_level
        elif provider == "openai":
            reasoning_effort = self.config.get("openai_reasoning_effort")
            if reasoning_effort:
                kwargs["reasoning_effort"] = reasoning_effort
        elif provider == "anthropic":
            effort = self.config.get("anthropic_effort")
            if effort:
                kwargs["effort"] = effort

        temperature = self.config.get("temperature")
        if temperature is not None and temperature != "":
            kwargs["temperature"] = float(temperature)

        return kwargs
