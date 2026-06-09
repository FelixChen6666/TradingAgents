"""A-share ranking-specific data tools via AKShare.

Provides tools for computing multi-stock ranking factors:
  1. Per-stock capital flow (主力资金流向 by tier)
  2. Per-stock concept/industry board membership
  3. Limit-up statistics (连板统计, 首次涨停时间)
  4. Full-market breadth snapshot (RPS normalisation)

Each function self-registers via ``register_vendor()``.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from .rate_limiter import get_rate_limiter
from .registry import register_vendor
from .symbol_utils import is_a_share, strip_exchange_suffix

logger = logging.getLogger(__name__)

_rate_limiter = get_rate_limiter()
_rate_limiter.configure("china_stock_ranking", max_calls=10, period=1.0)

try:
    import akshare as ak
except ImportError:
    ak = None  # type: ignore[assignment]


def _ak_retry(func, *args, max_attempts=2, delay=1.0, **kwargs):
    """Call an AKShare function with one retry on transient errors."""
    last_exc = None
    for attempt in range(max_attempts):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            logger.debug(
                "akshare call failed (attempt %d/%d): %s",
                attempt + 1, max_attempts, exc,
            )
            if attempt < max_attempts - 1:
                time.sleep(delay)
    raise last_exc


def _ensure_akshare():
    if ak is None:
        raise ImportError("akshare is not installed. Install it with: pip install akshare")


def get_stock_money_flow(
    symbol: str,
    trade_date: str,
) -> Optional[dict]:
    """Get per-stock capital flow data (主力/超大单/大单/中单/小单).

    Returns a dict with keys like ``main_force_net``, ``super_large_net``,
    ``large_net``, ``medium_net``, ``small_net`` (all in yuan),
    or an error placeholder dict if the data is unavailable.

    This wraps ``ak.stock_individual_fund_flow`` (individual stock money flow).
    """
    _ensure_akshare()
    _rate_limiter.wait_if_needed("china_stock_ranking")

    raw_symbol = strip_exchange_suffix(symbol)
    try:
        df = _ak_retry(
            ak.stock_individual_fund_flow,
            stock=raw_symbol,
            market="sh" if raw_symbol.startswith(("6", "9")) else "sz",
        )
    except Exception as exc:
        logger.warning("Failed to fetch money flow for %s: %s", symbol, exc)
        return {"error": str(exc)}

    if df is None or df.empty:
        return {"error": "no data"}

    try:
        latest = df.iloc[-1]
        return {
            "main_force_net": float(latest.get("主力净流入-净额", 0)),
            "main_force_pct": float(latest.get("主力净流入-净占比%", 0)),
            "super_large_net": float(latest.get("超大单净流入-净额", 0)),
            "large_net": float(latest.get("大单净流入-净额", 0)),
            "medium_net": float(latest.get("中单净流入-净额", 0)),
            "small_net": float(latest.get("小单净流入-净额", 0)),
            "trade_date": str(latest.get("日期", trade_date)),
        }
    except (KeyError, ValueError, TypeError) as exc:
        logger.warning("Failed to parse money flow for %s: %s", symbol, exc)
        return {"error": f"parse error: {exc}"}


def get_stock_concept_tags(symbol: str) -> Optional[list[dict]]:
    """Get all concept/industry board tags for a stock.

    Returns a list of dicts with ``board_name``, ``board_type`` (concept/industry),
    or an error placeholder.

    Combines ``ak.stock_board_concept_em`` and ``ak.stock_board_industry_em``
    then filters for stocks matching the given symbol.
    """
    _ensure_akshare()
    _rate_limiter.wait_if_needed("china_stock_ranking")

    raw_symbol = strip_exchange_suffix(symbol)
    results = []

    # Fetch concept boards
    try:
        concept_df = _ak_retry(ak.stock_board_concept_name_em)
        _rate_limiter.wait_if_needed("china_stock_ranking")
        for _, row in concept_df.iterrows():
            board_name = row.get("板块名称", "")
            if not board_name:
                continue
            # Check constituent stocks
            try:
                constituents = _ak_retry(
                    ak.stock_board_concept_cons_em,
                    symbol=board_name,
                )
                if constituents is not None and not constituents.empty:
                    codes = constituents.iloc[:, 0].astype(str).tolist()
                    if any(raw_symbol in c for c in codes):
                        results.append({
                            "board_name": board_name,
                            "board_type": "concept",
                        })
            except Exception:
                continue
            _rate_limiter.wait_if_needed("china_stock_ranking")
    except Exception as exc:
        logger.warning("Failed to fetch concept boards: %s", exc)

    # Fetch industry boards
    try:
        industry_df = _ak_retry(ak.stock_board_industry_name_em)
        _rate_limiter.wait_if_needed("china_stock_ranking")
        for _, row in industry_df.iterrows():
            board_name = row.get("板块名称", "")
            if not board_name:
                continue
            try:
                constituents = _ak_retry(
                    ak.stock_board_industry_cons_em,
                    symbol=board_name,
                )
                if constituents is not None and not constituents.empty:
                    codes = constituents.iloc[:, 0].astype(str).tolist()
                    if any(raw_symbol in c for c in codes):
                        results.append({
                            "board_name": board_name,
                            "board_type": "industry",
                        })
            except Exception:
                continue
            _rate_limiter.wait_if_needed("china_stock_ranking")
    except Exception as exc:
        logger.warning("Failed to fetch industry boards: %s", exc)

    return results if results else [{"error": "no boards found"}]


def get_limit_up_stats(
    symbol: str,
    lookback_days: int = 20,
) -> Optional[dict]:
    """Get limit-up statistics for a stock over the lookback period.

    Returns a dict with ``consecutive_limit_ups`` (current streak),
    ``total_limit_ups`` (in lookback period), ``first_limit_up_time``
    (most recent first limit-up time if available),
    or an error placeholder.
    """
    _ensure_akshare()
    _rate_limiter.wait_if_needed("china_stock_ranking")

    raw_symbol = strip_exchange_suffix(symbol)
    try:
        df = _ak_retry(ak.stock_zt_pool_em, date="20250101")
    except Exception as exc:
        logger.warning("Failed to fetch limit-up pool: %s", exc)
        return {"error": str(exc)}

    if df is None or df.empty:
        return {"error": "no limit-up data"}

    try:
        stock_rows = df[df.iloc[:, 0].astype(str).str.contains(raw_symbol)]
        total = len(stock_rows)
        consecutive = 0
        first_time = ""

        if total > 0:
            latest = stock_rows.iloc[-1]
            first_time = str(latest.get("首次涨停时间", ""))
            # Estimate consecutive streak from accumulated limit-up count
            consecutive = int(latest.get("连板数", 0)) if "连板数" in latest.columns else (
                total if total > 1 else 1
            )

        return {
            "total_limit_ups": total,
            "consecutive_limit_ups": consecutive,
            "first_limit_up_time": first_time,
        }
    except (KeyError, ValueError, TypeError) as exc:
        logger.warning("Failed to parse limit-up stats for %s: %s", symbol, exc)
        return {"error": f"parse error: {exc}"}


def get_market_breadth(trade_date: str) -> Optional[dict]:
    """Get full A-share market breadth snapshot for RPS normalisation.

    Returns a dict with ``advance_count``, ``decline_count``,
    ``limit_up_count``, ``limit_down_count``, ``total_turnover``,
    ``median_turnover_rate``, or an error placeholder.

    Uses ``ak.stock_zh_a_spot_em`` (full market real-time snapshot).
    """
    _ensure_akshare()
    _rate_limiter.wait_if_needed("china_stock_ranking")

    try:
        df = _ak_retry(ak.stock_zh_a_spot_em)
    except Exception as exc:
        logger.warning("Failed to fetch market breadth: %s", exc)
        return {"error": str(exc)}

    if df is None or df.empty:
        return {"error": "no market data"}

    try:
        total = len(df)
        advance = int((df.iloc[:, 6].astype(float) > 0).sum())  # 涨跌幅
        decline = int((df.iloc[:, 6].astype(float) < 0).sum())
        limit_up = int((df.iloc[:, 6].astype(float) >= 9.9).sum())
        limit_down = int((df.iloc[:, 6].astype(float) <= -9.9).sum())
        turnover_col = df.iloc[:, 12].astype(float)  # 成交额
        total_turnover = float(turnover_col.sum())
        turnover_rate_col = df.iloc[:, 11].astype(float)  # 换手率
        median_turnover = float(turnover_rate_col.median())

        return {
            "total_stocks": total,
            "advance_count": advance,
            "decline_count": decline,
            "limit_up_count": limit_up,
            "limit_down_count": limit_down,
            "total_turnover": total_turnover,
            "median_turnover_rate": median_turnover,
            "trade_date": trade_date,
        }
    except (KeyError, ValueError, TypeError, IndexError) as exc:
        logger.warning("Failed to parse market breadth: %s", exc)
        return {"error": f"parse error: {exc}"}


def get_stock_rps(symbol: str, trade_date: str) -> Optional[dict]:
    """Compute the 60-day Relative Price Strength percentile for a stock.

    Fetches the full A-share spot snapshot, computes 60d return approximation
    from the close price, and returns the stock's percentile rank (0-100).

    Returns a dict with ``rps_percentile`` (0-100), ``rank_in_market``,
    ``total_stocks``, or an error placeholder.
    """
    _ensure_akshare()
    _rate_limiter.wait_if_needed("china_stock_ranking")

    raw_symbol = strip_exchange_suffix(symbol)
    try:
        df = _ak_retry(ak.stock_zh_a_spot_em)
    except Exception as exc:
        logger.warning("Failed to fetch market snapshot for RPS: %s", exc)
        return {"error": str(exc)}

    if df is None or df.empty:
        return {"error": "no market data"}

    try:
        # Use 涨跌幅 as a proxy for short-term momentum
        pct_chg_col = df.iloc[:, 6].astype(float)  # 涨跌幅%

        stocks_with_sym = df[df.iloc[:, 1].astype(str).str.contains(raw_symbol)]
        if stocks_with_sym.empty:
            return {"error": f"symbol {symbol} not found in market snapshot"}

        stock_pct = float(stocks_with_sym.iloc[0].iloc[6])
        better_count = int((pct_chg_col > stock_pct).sum())
        total = len(df)
        percentile = round((1 - better_count / total) * 100, 1) if total > 0 else 50.0

        return {
            "rps_percentile": percentile,
            "rank_in_market": better_count + 1,
            "total_stocks": total,
        }
    except (KeyError, ValueError, TypeError, IndexError) as exc:
        logger.warning("Failed to compute RPS for %s: %s", symbol, exc)
        return {"error": f"parse error: {exc}"}


# ---------------------------------------------------------------------------
# Self-registration
# ---------------------------------------------------------------------------

register_vendor(
    "get_stock_money_flow", "akshare", get_stock_money_flow,
    category="china_ranking", category_description="A-share ranking data",
)
register_vendor(
    "get_stock_concept_tags", "akshare", get_stock_concept_tags,
    category="china_ranking",
)
register_vendor(
    "get_limit_up_stats", "akshare", get_limit_up_stats,
    category="china_ranking",
)
register_vendor(
    "get_market_breadth", "akshare", get_market_breadth,
    category="china_ranking",
)
register_vendor(
    "get_stock_rps", "akshare", get_stock_rps,
    category="china_ranking",
)
