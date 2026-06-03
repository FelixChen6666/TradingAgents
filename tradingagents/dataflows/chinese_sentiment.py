"""Chinese A-share social sentiment via AKShare — Baidu vote + East Money 千股千评.

No API key required (AKShare wraps public APIs).  Three complementary views:

  1. **Baidu stock vote** (百度股评投票) — bullish/bearish ratio per period,
     directly analogous to the Bullish/Bearish labels on StockTwits.
  2. **East Money 千股千评** — comprehensive scoring (综合得分, 机构参与度,
     关注指数) for a stock.
  3. **Aggregate** (``"chinese"``) — combines all available sources into a
     single report block.

Each function follows the same graceful-degradation contract as StockTwits
and Reddit: returns a formatted string or a ``<placeholder>`` rather than
raising, so the calling sentiment analyst never has to handle exceptions.
"""

from __future__ import annotations

import logging
from datetime import datetime

from .placeholders import no_data_found, source_unavailable
from .rate_limiter import get_rate_limiter
from .registry import register_vendor
from .symbol_utils import strip_exchange_suffix

logger = logging.getLogger(__name__)

_rate_limiter = get_rate_limiter()
_rate_limiter.configure("chinese_sentiment", max_calls=10, period=1.0)

try:
    import akshare as ak
except ImportError:
    ak = None  # type: ignore[assignment]
    _AKSHARE_AVAILABLE = False
else:
    _AKSHARE_AVAILABLE = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_code(symbol: str) -> str:
    """Strip exchange suffix and return the pure A-share numeric code."""
    return strip_exchange_suffix(symbol.upper())


def _is_a_share(symbol: str) -> bool:
    """Rough check: starts with 6, 0, 3 (after stripping suffix)."""
    code = _to_code(symbol)
    return code.isdigit() and len(code) == 6


# ---------------------------------------------------------------------------
# 1. Baidu stock vote  —  百度股评投票 (bullish/bearish ratio)
# ---------------------------------------------------------------------------

def get_baidu_vote(
    ticker: str,
    start_date: str = "",
    end_date: str = "",
    limit: int = 30,
) -> str:
    """Fetch bullish/bearish voting data from Baidu stock review.

    ``stock_zh_vote_baidu`` returns vote counts and ratios per period
    (day/week/month/year) — directly analogous to StockTwits sentiment tags.
    """
    if not _AKSHARE_AVAILABLE:
        return "<akshare not available: install with 'pip install akshare'>"
    if not _is_a_share(ticker):
        return f"<baidu vote not applicable for non-A-share ticker: {ticker}>"

    code = _to_code(ticker)
    _rate_limiter.wait_if_needed("chinese_sentiment")

    try:
        from akshare.stock_feature.stock_zh_vote_baidu import stock_zh_vote_baidu
        df = stock_zh_vote_baidu(symbol=code, indicator="股票")
    except Exception as exc:
        logger.debug("Baidu vote failed for %s: %s", ticker, exc)
        return source_unavailable("baidu_vote", str(exc))

    if df is None or df.empty:
        return no_data_found("baidu_vote", ticker, "vote data")

    lines = [f"## Baidu Stock Vote — {ticker}", ""]
    for _, row in df.iterrows():
        period = row.get("周期", "")
        bullish = row.get("看涨", 0)
        bearish = row.get("看跌", 0)
        bull_pct = row.get("看涨比例", "")
        bear_pct = row.get("看跌比例", "")
        lines.append(f"  {period}: Bullish {bullish} ({bull_pct}) / Bearish {bearish} ({bear_pct})")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 2. East Money 千股千评 — comprehensive stock evaluation
# ---------------------------------------------------------------------------

def get_em_comment(
    ticker: str,
    start_date: str = "",
    end_date: str = "",
    limit: int = 30,
) -> str:
    """Fetch comprehensive stock evaluation from East Money 千股千评.

    Includes 综合得分 (composite score), 机构参与度 (institutional
    participation), 关注指数 (attention index), and ranking.
    """
    if not _AKSHARE_AVAILABLE:
        return "<akshare not available: install with 'pip install akshare'>"
    if not _is_a_share(ticker):
        return f"<em_comment not applicable for non-A-share ticker: {ticker}>"

    code = _to_code(ticker)
    _rate_limiter.wait_if_needed("chinese_sentiment")

    try:
        from akshare.stock_feature.stock_comment_em import (
            stock_comment_em,
            stock_comment_detail_scrd_focus_em,
            stock_comment_detail_scrd_desire_em,
        )
    except Exception as exc:
        return source_unavailable("em_comment", str(exc))

    blocks: list[str] = [f"## East Money 千股千评 — {ticker}", ""]

    # -- Overall evaluation (full-market, filter by code) --
    try:
        overview = stock_comment_em()
        if overview is not None and not overview.empty:
            match = overview[overview["代码"].astype(str).str.contains(code)]
            if not match.empty:
                row = match.iloc[0]
                blocks.append("**综合评估 (Comprehensive Evaluation):**")
                for col in ["综合得分", "上升", "目前排名", "关注指数"]:
                    if col in row:
                        blocks.append(f"  {col}: {row[col]}")
                blocks.append("")
    except Exception as exc:
        logger.debug("EM comment overview failed for %s: %s", ticker, exc)

    # -- User attention index history --
    try:
        focus = stock_comment_detail_scrd_focus_em(symbol=code)
        if focus is not None and not focus.empty:
            blocks.append("**关注指数 (Attention Index — recent 5):**")
            for _, row in focus.head(5).iterrows():
                date = row.get("交易日期", "")
                val = row.get("关注指数", "")
                blocks.append(f"  {date}: {val}")
            blocks.append("")
    except Exception as exc:
        logger.debug("Focus index failed for %s: %s", ticker, exc)

    # -- Market participation willingness --
    try:
        desire = stock_comment_detail_scrd_desire_em(symbol=code)
        if desire is not None and not desire.empty:
            blocks.append("**市场参与意愿 (Market Participation Willingness — recent 5):**")
            for _, row in desire.head(5).iterrows():
                date = row.get("交易日期", "")
                will = row.get("参与意愿", "")
                will_chg = row.get("参与意愿变化", "")
                blocks.append(f"  {date}: Willingness={will} Change={will_chg}")
            blocks.append("")
    except Exception as exc:
        logger.debug("Participation desire failed for %s: %s", ticker, exc)

    if len(blocks) == 2:  # nothing was added beyond the header
        return no_data_found("em_comment", ticker, "evaluation data")

    return "\n".join(blocks)


# ---------------------------------------------------------------------------
# 3. Aggregate — all Chinese sources combined
# ---------------------------------------------------------------------------

def get_chinese_sentiment_aggregate(
    ticker: str,
    start_date: str = "",
    end_date: str = "",
    limit: int = 30,
) -> str:
    """Aggregate all Chinese sentiment sources for *ticker*."""
    if not _is_a_share(ticker):
        return f"<chinese sentiment sources not applicable for {ticker}>"

    parts = [
        f"# Chinese Social Sentiment for {ticker}\n",
    ]

    baidu = get_baidu_vote(ticker, start_date, end_date, limit)
    if not baidu.startswith("<") and "no_data" not in baidu.lower():
        parts.append(baidu)
    else:
        parts.append(f"  (Baidu vote: {baidu})")

    em = get_em_comment(ticker, start_date, end_date, limit)
    if not em.startswith("<") and "no_data" not in em.lower():
        parts.append(em)
    else:
        parts.append(f"  (East Money comment: {em})")

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# 4. Fallback stub for non-A-share tickers
# ---------------------------------------------------------------------------

def get_chinese_sentiment_placeholder(
    ticker: str,
    start_date: str = "",
    end_date: str = "",
    limit: int = 30,
) -> str:
    """Return a placeholder — this vendor only supports A-share tickers."""
    return f"<chinese sentiment: {ticker} is not an A-share ticker, skipping>"


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

register_vendor(
    "get_social_sentiment", "baidu_vote", get_baidu_vote,
)
register_vendor(
    "get_social_sentiment", "em_comment", get_em_comment,
)
register_vendor(
    "get_social_sentiment", "chinese", get_chinese_sentiment_aggregate,
)
