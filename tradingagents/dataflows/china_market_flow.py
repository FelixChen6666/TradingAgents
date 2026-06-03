"""A-share market sentiment and capital flow statistics via AKShare.

Provides structured numerical data about the A-share market state:
  1. Market turnover / breadth overview (两市成交额, 涨跌家数)
  2. Main capital flow direction (主力资金流入流出)
  3. Northbound capital flow (北向资金净流入)
  4. Margin trading balances (融资融券余额)
  5. Limit-up / limit-down pool (涨停/跌停)

Each AKShare call is independently wrapped so one failing source
does not block the others.  Transient connection errors are retried
once.
"""

from __future__ import annotations

import logging
import time

from .rate_limiter import get_rate_limiter
from .registry import register_vendor

logger = logging.getLogger(__name__)

_rate_limiter = get_rate_limiter()
_rate_limiter.configure("china_market_flow", max_calls=10, period=1.0)

try:
    import akshare as ak
except ImportError:
    ak = None  # type: ignore[assignment]


def _ak_retry(func, *args, max_attempts=2, delay=1.0, **kwargs):
    """Call an AKShare function with one retry on transient errors.

    AKShare's underlying HTTP requests sometimes fail with
    RemoteDisconnected / ConnectionError.  One retry is usually
    enough to recover.
    """
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
    raise last_exc  # type: ignore[misc]


def _fetch_market_turnover_overview() -> str:
    """Fetch A-share market breadth and turnover from the spot table."""
    if ak is None:
        return ""

    _rate_limiter.wait_if_needed("china_market_flow")
    try:
        df = _ak_retry(ak.stock_zh_a_spot_em)
    except Exception as exc:
        logger.debug("akshare stock_zh_a_spot_em failed: %s", exc)
        return ""

    if df is None or df.empty:
        return ""

    lines = ["## 市场总览 (Market Turnover Overview):", ""]
    try:
        total_count = len(df)
        advancing = (df["涨跌幅"] > 0).sum() if "涨跌幅" in df.columns else 0
        declining = (df["涨跌幅"] < 0).sum() if "涨跌幅" in df.columns else 0
        turnover_col = "成交额" if "成交额" in df.columns else None

        lines.append(f"- Total listed A-shares: {total_count}")
        lines.append(f"- Advancing: {advancing}")
        lines.append(f"- Declining: {declining}")
        lines.append(f"- Flat: {total_count - advancing - declining}")

        if turnover_col:
            total_volume = df[turnover_col].sum()
            lines.append(f"- Total turnover (成交额): {total_volume / 1e8:.0f}亿元")

        lines.append("")
    except Exception as exc:
        logger.debug("market turnover calculation failed: %s", exc)

    return "\n".join(lines)


def _fetch_main_capital_flow() -> str:
    """Fetch main capital flow (主力资金流向) by sector."""
    if ak is None:
        return ""

    _rate_limiter.wait_if_needed("china_market_flow")
    try:
        df = _ak_retry(ak.stock_market_fund_flow)
    except Exception as exc:
        logger.debug("akshare stock_market_fund_flow failed: %s", exc)
        return ""

    if df is None or df.empty:
        return ""

    lines = ["## 主力资金流向 (Main Capital Flow by Sector):", ""]
    try:
        display = df.head(10).to_string(index=False)
        lines.append(display)
        lines.append("")
    except Exception as exc:
        logger.debug("main capital flow formatting failed: %s", exc)

    return "\n".join(lines)


def _fetch_northbound_flow() -> str:
    """Fetch northbound capital flow (北向资金) via Shanghai and Shenzhen HK Connect."""
    if ak is None:
        return ""

    lines = []

    for label, symbol in [("沪股通 (Shanghai Connect)", "沪股通"),
                          ("深股通 (Shenzhen Connect)", "深股通")]:
        _rate_limiter.wait_if_needed("china_market_flow")
        try:
            df = _ak_retry(ak.stock_hsgt_hist_em, symbol=symbol)
        except Exception as exc:
            logger.debug("akshare stock_hsgt_hist_em(%s) failed: %s", symbol, exc)
            continue

        if df is not None and not df.empty:
            lines.append(f"## {label} 北向资金历史数据:")
            lines.append(df.tail(10).to_string(index=False))
            lines.append("")

    return "\n".join(lines)


def _fetch_margin_trading() -> str:
    """Fetch margin trading balances (融资融券)."""
    if ak is None:
        return ""

    lines = []

    # Shenzhen margin
    _rate_limiter.wait_if_needed("china_market_flow")
    try:
        sz = _ak_retry(ak.macro_china_market_margin_sz)
        if sz is not None and not sz.empty:
            lines.append("## 深交所融资融券 (SZSE Margin Trading):")
            lines.append(sz.tail(5).to_string(index=False))
            lines.append("")
    except Exception as exc:
        logger.debug("akshare macro_china_market_margin_sz failed: %s", exc)

    # Shanghai margin
    _rate_limiter.wait_if_needed("china_market_flow")
    try:
        sh = _ak_retry(ak.macro_china_market_margin_sh)
        if sh is not None and not sh.empty:
            lines.append("## 上交所融资融券 (SSE Margin Trading):")
            lines.append(sh.tail(5).to_string(index=False))
            lines.append("")
    except Exception as exc:
        logger.debug("akshare macro_china_market_margin_sh failed: %s", exc)

    return "\n".join(lines)


def _fetch_limit_up_pool(trade_date: str) -> str:
    """Fetch limit-up/down board statistics (涨停/跌停)."""
    if ak is None:
        return ""

    _rate_limiter.wait_if_needed("china_market_flow")
    try:
        df = _ak_retry(ak.stock_zt_pool_em, date=trade_date)
    except Exception as exc:
        logger.debug("akshare stock_zt_pool_em failed for %s: %s", trade_date, exc)
        return ""

    if df is None or df.empty:
        return ""

    lines = ["## 涨停/跌停板 (Limit Up/Down Board):", ""]
    try:
        limit_up = len(df[df["pctChg"] >= 9.8]) if "pctChg" in df.columns else len(df)
        limit_down = len(df[df["pctChg"] <= -9.8]) if "pctChg" in df.columns else 0
        lines.append(f"- Limit-up stocks: {limit_up}")
        lines.append(f"- Limit-down stocks: {limit_down}")
        lines.append(f"- Total on board: {len(df)}")
        lines.append("")
        if "名称" in df.columns and "pctChg" in df.columns:
            top_up = (
                df[df["pctChg"] >= 9.8]
                .head(5)[["名称", "pctChg"]]
                .to_string(index=False)
            )
            lines.append(f"Top limit-up:\n{top_up}\n")
    except Exception as exc:
        logger.debug("limit-up pool formatting failed: %s", exc)

    return "\n".join(lines)


def get_china_market_flow(trade_date: str = "") -> str:
    """Fetch A-share market sentiment and capital flow statistics.

    Aggregates: market turnover/breadth, main capital flow by sector,
    northbound capital flow, margin trading balances, and limit-up/down
    board data.

    Args:
        trade_date: Trade date in ``YYYY-MM-DD`` format. Only used for
            the limit-up/down board query; if empty, that source is
            skipped.

    Returns:
        Formatted string with structured sections, or a placeholder.
    """
    parts = []

    turnover = _fetch_market_turnover_overview()
    if turnover:
        parts.append(turnover)

    capital_flow = _fetch_main_capital_flow()
    if capital_flow:
        parts.append(capital_flow)

    northbound = _fetch_northbound_flow()
    if northbound:
        parts.append(northbound)

    margin = _fetch_margin_trading()
    if margin:
        parts.append(margin)

    if trade_date:
        limit_pool = _fetch_limit_up_pool(trade_date)
        if limit_pool:
            parts.append(limit_pool)

    if not parts:
        return "<no market sentiment flow data available>"

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

register_vendor(
    "get_china_market_flow",
    "akshare",
    get_china_market_flow,
    category="china_market_flow",
    category_description="A-share market sentiment and capital flow statistics",
)
