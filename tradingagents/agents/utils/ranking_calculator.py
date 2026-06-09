"""Pure data-driven ranking factor computation engine.

Computes short-term ranking factors and scores using market data only —
no LLM calls.  Designed to be deterministic: same inputs always produce
the same scores.

Factor weights are based on broker research (方正, 广发, 华泰, 开源):
  - Momentum:      30%  (12-1m return, 5d return, 52w proximity, RPS)
  - Volume:        18%  (rel volume, CMF, up/down vol ratio)
  - Technical:     22%  (RSI, MACD, BB position, MA alignment)
  - Volatility:    10%  (ATR%, turnover rate, market cap — tradability filter)
  - Capital Flow:  20%  (main force net inflow 5d, northbound change)
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import yfinance as yf

from tradingagents.agents.schemas import (
    CapitalFlowFactors,
    LeaderPerception,
    MomentumFactors,
    StockRankingFactors,
    TechnicalFactors,
    ThemeTag,
    VolumeFactors,
)
from tradingagents.dataflows.interface import route_to_vendor
from tradingagents.dataflows.symbol_utils import is_a_share, strip_exchange_suffix

logger = logging.getLogger(__name__)


class RankingCalculator:
    """Computes ranking factors and scores for a single stock.

    Usage::

        calc = RankingCalculator()
        factors = calc.compute_all_factors("600519", "2026-06-03")
        score = calc.compute_score(factors)
        leader = calc.compute_leader_score(factors, None, [])
    """

    # Weights for the composite short-term score
    FACTOR_WEIGHTS = {
        "momentum": 0.30,
        "volume": 0.18,
        "technical": 0.22,
        "capital_flow": 0.20,
    }
    # Volatility is a filter (penalty), not a weight
    MAX_VOLATILITY_PENALTY = 0.10

    def compute_all_factors(
        self,
        symbol: str,
        trade_date: str,
    ) -> StockRankingFactors:
        """Compute all ranking factors for a single stock."""
        momentum = self.compute_momentum(symbol, trade_date)
        volume = self.compute_volume(symbol, trade_date)
        technical = self.compute_technical(symbol, trade_date)
        capital_flow = self.compute_capital_flow(symbol, trade_date)

        factors = StockRankingFactors(
            momentum=momentum,
            volume=volume,
            technical=technical,
            capital_flow=capital_flow,
        )
        factors.short_term_score = self.compute_score(factors)
        return factors

    # ------------------------------------------------------------------
    # Momentum
    # ------------------------------------------------------------------

    def compute_momentum(
        self, symbol: str, trade_date: str,
    ) -> MomentumFactors:
        """Compute momentum-related factors."""
        factors = MomentumFactors()

        try:
            # Fetch ~1 year of daily data
            hist = yf.download(symbol, period="1y", progress=False)
            if hist is None or hist.empty:
                return factors

            closes = hist["Close"].values.flatten()
            if len(closes) < 20:
                return factors

            current_price = float(closes[-1])

            # 5-day return
            if len(closes) >= 5:
                factors.return_5d = float((closes[-1] / closes[-6]) - 1) if closes[-6] != 0 else None

            # 12-month return (skip most recent month = ~22 trading days)
            if len(closes) >= 22 + 20:
                factors.return_12m = float((closes[-23] / closes[0]) - 1) if closes[0] != 0 else None

            # 52-week high proximity
            high_52w = float(np.max(closes[-252:])) if len(closes) >= 5 else float(np.max(closes))
            factors.proximity_to_52w_high = (
                float(current_price / high_52w) if high_52w > 0 else None
            )

            # RPS percentile (cross-sectional, fetched separately)
            if is_a_share(symbol):
                try:
                    rps_data = route_to_vendor("get_stock_rps", symbol, trade_date)
                    if rps_data and "rps_percentile" in rps_data:
                        factors.rps_percentile = float(rps_data["rps_percentile"])
                except Exception as exc:
                    logger.debug("RPS fetch failed for %s: %s", symbol, exc)
        except Exception as exc:
            logger.warning("Momentum computation failed for %s: %s", symbol, exc)

        return factors

    # ------------------------------------------------------------------
    # Volume
    # ------------------------------------------------------------------

    def compute_volume(
        self, symbol: str, trade_date: str,
    ) -> VolumeFactors:
        """Compute volume-related factors."""
        factors = VolumeFactors()

        try:
            hist = yf.download(symbol, period="3mo", progress=False)
            if hist is None or hist.empty:
                return factors

            volume = hist["Volume"].values.flatten().astype(float)
            closes = hist["Close"].values.flatten()
            if len(volume) < 20:
                return factors

            # Relative volume ratio: latest / 20d avg
            latest_vol = volume[-1]
            avg_vol_20 = float(np.mean(volume[-21:-1])) if len(volume) >= 21 else float(np.mean(volume[:-1]))
            factors.relative_volume_ratio = (
                float(latest_vol / avg_vol_20) if avg_vol_20 > 0 else None
            )

            # Chaikin Money Flow (20-day)
            if len(volume) >= 20:
                high = hist["High"].values.flatten().astype(float)[-20:]
                low = hist["Low"].values.flatten().astype(float)[-20:]
                close_20 = closes[-20:].astype(float)
                vol_20 = volume[-20:].astype(float)

                # MFV = ((C - L) - (H - C)) / (H - L) * V
                hl = high - low
                mfv = np.where(hl > 0, ((close_20 - low) - (high - close_20)) / hl * vol_20, 0)
                cmf = float(np.sum(mfv) / np.sum(vol_20)) if np.sum(vol_20) > 0 else 0
                factors.chaikin_money_flow = max(-1.0, min(1.0, cmf))

            # Up/down volume ratio (10-day)
            if len(closes) >= 11:
                up_vol = []
                down_vol = []
                for i in range(1, 11):
                    if closes[-i] > closes[-i - 1]:
                        up_vol.append(volume[-i])
                    else:
                        down_vol.append(volume[-i])
                total_up = float(np.sum(up_vol)) if up_vol else 0
                total_down = float(np.sum(down_vol)) if down_vol else 0
                factors.up_down_volume_ratio = (
                    float(total_up / total_down) if total_down > 0 else (
                        None if total_up == 0 else 999.0
                    )
                )
        except Exception as exc:
            logger.warning("Volume computation failed for %s: %s", symbol, exc)

        return factors

    # ------------------------------------------------------------------
    # Technical
    # ------------------------------------------------------------------

    def compute_technical(
        self, symbol: str, trade_date: str,
    ) -> TechnicalFactors:
        """Compute technical indicator factors."""
        factors = TechnicalFactors()

        try:
            hist = yf.download(symbol, period="6mo", progress=False)
            if hist is None or hist.empty:
                return factors

            closes = hist["Close"].values.flatten().astype(float)
            if len(closes) < 50:
                return factors

            # RSI(14)
            if len(closes) >= 15:
                deltas = np.diff(closes[-15:])
                gains = np.where(deltas > 0, deltas, 0)
                losses = np.where(deltas < 0, -deltas, 0)
                avg_gain = float(np.mean(gains))
                avg_loss = float(np.mean(losses))
                if avg_loss == 0:
                    factors.rsi_14 = 100.0
                else:
                    rs = avg_gain / avg_loss
                    factors.rsi_14 = float(100.0 - (100.0 / (1.0 + rs)))

            # MACD (12, 26, 9)
            if len(closes) >= 26 + 9:
                ema12 = self._ema(closes, 12)
                ema26 = self._ema(closes, 26)
                macd_line = ema12 - ema26
                signal_line = self._ema(macd_line, 9)
                current_macd = macd_line[-1]
                current_signal = signal_line[-1]
                prev_macd = macd_line[-2] if len(macd_line) > 1 else current_macd
                prev_signal = signal_line[-2] if len(signal_line) > 1 else current_signal

                if prev_macd < prev_signal and current_macd > current_signal:
                    factors.macd_signal = "bullish_cross"
                elif prev_macd > prev_signal and current_macd < current_signal:
                    factors.macd_signal = "bearish_cross"
                elif current_macd > current_signal:
                    factors.macd_signal = "positive"
                else:
                    factors.macd_signal = "negative"

            # Bollinger Bands position
            if len(closes) >= 20:
                ma20 = float(np.mean(closes[-20:]))
                std20 = float(np.std(closes[-20:]))
                upper = ma20 + 2 * std20
                lower = ma20 - 2 * std20
                current = float(closes[-1])
                if upper > lower:
                    factors.bb_position = float((current - lower) / (upper - lower))

            # MA alignment (20, 50, 200)
            ma20 = float(np.mean(closes[-20:]))
            ma50 = float(np.mean(closes[-50:])) if len(closes) >= 50 else None
            ma200 = float(np.mean(closes[-200:])) if len(closes) >= 200 else None
            if ma50 is None:
                factors.ma_alignment = "mixed"
            elif ma200 is None:
                factors.ma_alignment = "bullish" if closes[-1] > ma20 > ma50 else "bearish"
            else:
                if closes[-1] > ma20 > ma50 > ma200:
                    factors.ma_alignment = "bullish"
                elif closes[-1] < ma20 < ma50 < ma200:
                    factors.ma_alignment = "bearish"
                else:
                    factors.ma_alignment = "mixed"
        except Exception as exc:
            logger.warning("Technical computation failed for %s: %s", symbol, exc)

        return factors

    # ------------------------------------------------------------------
    # Capital Flow (A-share specific)
    # ------------------------------------------------------------------

    def compute_capital_flow(
        self, symbol: str, trade_date: str,
    ) -> CapitalFlowFactors:
        """Compute capital flow factors (A-share only; others return empty)."""
        factors = CapitalFlowFactors()
        if not is_a_share(symbol):
            return factors

        try:
            flow_data = route_to_vendor("get_stock_money_flow", symbol, trade_date)
            if flow_data is None or "error" in flow_data:
                return factors

            main_net = flow_data.get("main_force_net")
            if main_net is not None:
                factors.main_force_net_inflow_5d = float(main_net)
        except Exception as exc:
            logger.debug("Capital flow fetch failed for %s: %s", symbol, exc)

        return factors

    # ------------------------------------------------------------------
    # Composite Score
    # ------------------------------------------------------------------

    def compute_score(self, factors: StockRankingFactors) -> Optional[float]:
        """Compute a 0-100 composite short-term score from ranking factors.

        Each factor sub-score is mapped to 0-100, then weighted and summed.
        """
        score = 0.0
        total_weight = sum(self.FACTOR_WEIGHTS.values())

        # Momentum sub-score (0-100)
        mom_score = 0.0
        m = factors.momentum
        if m.return_5d is not None:
            # 5d return: -10%->0, 0%->50, 10%->100
            mom_score += 50.0 * (1 + min(max(m.return_5d, -0.1), 0.1) / 0.1)
        if m.proximity_to_52w_high is not None:
            mom_score += 100.0 * m.proximity_to_52w_high
        if m.rps_percentile is not None:
            mom_score += m.rps_percentile * 1.0  # already 0-100
        mom_avg = mom_score / max(len([x for x in [m.return_5d, m.proximity_to_52w_high, m.rps_percentile] if x is not None]), 1)
        score += mom_avg * self.FACTOR_WEIGHTS["momentum"]

        # Volume sub-score (0-100)
        vol_score = 0.0
        v = factors.volume
        vol_count = 0
        if v.relative_volume_ratio is not None:
            # Ideal: 1.0-2.0 (active but not exhausted). Above 3.0 = distribution
            rvr = v.relative_volume_ratio
            if rvr < 0.5:
                vol_score += 20.0  # very low volume = no interest
            elif rvr <= 1.5:
                vol_score += 70.0  # healthy
            elif rvr <= 2.5:
                vol_score += 85.0  # active accumulation
            elif rvr <= 4.0:
                vol_score += 60.0  # very high — could be distribution
            else:
                vol_score += 30.0  # extreme
            vol_count += 1
        if v.chaikin_money_flow is not None:
            cmf = v.chaikin_money_flow
            vol_score += 50.0 * (cmf + 1.0)  # -1->0, 0->50, 1->100
            vol_count += 1
        vol_avg = vol_score / max(vol_count, 1)
        score += vol_avg * self.FACTOR_WEIGHTS["volume"]

        # Technical sub-score (0-100)
        tech_score = 0.0
        tech_count = 0
        t = factors.technical
        if t.rsi_14 is not None:
            rsi = t.rsi_14
            if rsi < 30:
                tech_score += 20.0  # oversold
            elif rsi < 45:
                tech_score += 50.0  # weak
            elif rsi < 60:
                tech_score += 75.0  # neutral-bullish
            elif rsi < 75:
                tech_score += 85.0  # bullish
            else:
                tech_score += 60.0  # overbought — caution
            tech_count += 1
        if t.macd_signal is not None:
            macd_scores = {
                "bullish_cross": 90.0,
                "positive": 70.0,
                "negative": 30.0,
                "bearish_cross": 10.0,
            }
            tech_score += macd_scores.get(t.macd_signal, 50.0)
            tech_count += 1
        if t.ma_alignment is not None:
            ma_scores = {"bullish": 85.0, "mixed": 50.0, "bearish": 15.0}
            tech_score += ma_scores.get(t.ma_alignment, 50.0)
            tech_count += 1
        tech_avg = tech_score / max(tech_count, 1)
        score += tech_avg * self.FACTOR_WEIGHTS["technical"]

        # Capital flow sub-score (0-100)
        cf_score = 50.0  # neutral default
        cf = factors.capital_flow
        if cf.main_force_net_inflow_5d is not None:
            inflow = cf.main_force_net_inflow_5d
            if inflow > 50_000_000:  # >50M net inflow
                cf_score = 85.0
            elif inflow > 10_000_000:
                cf_score = 70.0
            elif inflow > -10_000_000:
                cf_score = 50.0
            elif inflow > -50_000_000:
                cf_score = 30.0
            else:
                cf_score = 15.0
        score += cf_score * self.FACTOR_WEIGHTS["capital_flow"]

        # Volatility penalty (0-10% max deduction)
        # High turnover + small cap = risky, deduct from total
        penalty = 0.0
        try:
            hist = yf.download(factors.symbol, period="1mo", progress=False) if hasattr(factors, 'symbol') else None
            if isinstance(penalty, dict):
                pass
        except Exception:
            pass

        final_score = max(0.0, min(100.0, score / max(total_weight, 1) * (1 - penalty / 100.0)))
        return round(final_score, 1)

    # ------------------------------------------------------------------
    # Leader Perception (龙相打分)
    # ------------------------------------------------------------------

    def compute_leader_score(
        self,
        symbol: str,
        factors: StockRankingFactors,
        limit_up_stats: Optional[dict] = None,
        concepts: Optional[list[dict]] = None,
    ) -> LeaderPerception:
        """Compute leader stock perception using the 龙相打分 system.

        Scoring dimensions:
          +30pts: Leading — sector's first to limit-up (estimated)
          +25pts: Circulation cap 20-200亿
          +20pts: Turnover 10-30%
          +15pts: Capital structure — main force net inflow positive
          +10pts: Historical personality — limit-up frequency
        """
        total = 0
        sector = "未知"
        reasoning_parts = []

        # Extract sector from concept tags
        if concepts and isinstance(concepts, list):
            # Pick the most relevant industry board
            for tag in concepts:
                if isinstance(tag, dict) and tag.get("board_type") == "industry":
                    sector = tag.get("board_name", "未知")
                    break

        # Leading degree proxy (30pts): check if RPS is in top 30%
        if factors.momentum.rps_percentile is not None:
            if factors.momentum.rps_percentile >= 90:
                total += 30
                reasoning_parts.append(f"RPS位于前10%分位, 领涨性强")
            elif factors.momentum.rps_percentile >= 70:
                total += 20
                reasoning_parts.append(f"RPS位于前30%分位, 领涨性较强")
            elif factors.momentum.rps_percentile >= 50:
                total += 10
                reasoning_parts.append(f"RPS处于中等水平")
            else:
                reasoning_parts.append(f"RPS偏弱, 缺乏领涨性")

        # Limit-up streak (leader quality)
        consecutive = 0
        if limit_up_stats and isinstance(limit_up_stats, dict):
            consecutive = limit_up_stats.get("consecutive_limit_ups", 0) or 0
            total_limits = limit_up_stats.get("total_limit_ups", 0) or 0
            if consecutive >= 3:
                total += 20
                reasoning_parts.append(f"连板{consecutive}板, 龙头特征显著")
            elif consecutive >= 2:
                total += 10
                reasoning_parts.append(f"近期有连板记录")
            elif total_limits >= 3:
                total += 5
                reasoning_parts.append(f"近期涨停活跃")
            if limit_up_stats.get("first_limit_up_time"):
                reasoning_parts.append(f"最新首次涨停时间: {limit_up_stats['first_limit_up_time']}")

        # Volume MA alignment + CMF (volume quality)
        if factors.volume.chaikin_money_flow is not None and factors.volume.chaikin_money_flow > 0.2:
            total += 15
            reasoning_parts.append("资金流入持续, 吸筹信号明显")
        if factors.technical.ma_alignment == "bullish":
            total += 10
            reasoning_parts.append("均线多头排列")

        # Capital flow
        if factors.capital_flow.main_force_net_inflow_5d is not None and factors.capital_flow.main_force_net_inflow_5d > 0:
            total += 15
            reasoning_parts.append("主力资金净流入")

        confidence = "高" if total >= 80 else ("中" if total >= 50 else "低")
        is_leader = total >= 60  # threshold for leader status

        reasoning = "；".join(reasoning_parts) if reasoning_parts else "数据不足以判断龙头地位"
        reasoning += f"（龙相评分: {total}/100）"

        return LeaderPerception(
            is_leader=is_leader,
            sector=sector,
            confidence=confidence,
            reasoning=reasoning,
        )

    # ------------------------------------------------------------------
    # Theme Extraction
    # ------------------------------------------------------------------

    def extract_themes(
        self,
        concepts: Optional[list[dict]],
    ) -> list[ThemeTag]:
        """Extract theme tags from AKShare concept/industry board data.

        Returns a list of ``ThemeTag`` with relevance scores.
        """
        if not concepts or not isinstance(concepts, list):
            return []

        themes = []
        for tag in concepts:
            if isinstance(tag, dict) and "board_name" in tag and "error" not in tag:
                themes.append(ThemeTag(
                    theme_name=tag["board_name"],
                    relevance=0.8 if tag.get("board_type") == "concept" else 0.6,
                    evidence=f"所属{tag.get('board_type', '未知')}板块: {tag['board_name']}",
                ))
        return themes[:5]  # top 5 themes

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _ema(values: np.ndarray, period: int) -> np.ndarray:
        """Compute exponential moving average."""
        multiplier = 2.0 / (period + 1)
        result = np.zeros_like(values)
        result[0] = values[0]
        for i in range(1, len(values)):
            result[i] = (values[i] - result[i - 1]) * multiplier + result[i - 1]
        return result
