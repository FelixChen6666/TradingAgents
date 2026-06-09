"""Chinese A-share social sentiment via AKShare — East Money 千股千评.

No API key required (AKShare wraps public APIs).  Three complementary views:

  1. **East Money 千股千评** — comprehensive scoring (综合得分, 机构参与度,
     关注指数) for a stock.
  2. **East Money detail scores** — historical score trend (历史评分) and
     institutional participation (机构参与度) time series.
  3. **Aggregate** (``"chinese"``) — combines all available sources into a
     single report block.

Each function follows the same graceful-degradation contract as StockTwits
and Reddit: returns a formatted string or a ``<placeholder>`` rather than
raising, so the calling sentiment analyst never has to handle exceptions.

NOTE: The former Baidu stock vote (百度股评投票) source has been replaced
because the upstream Baidu API no longer returns data.  The replacement
uses East Money historical score and institutional participation data which
provides richer and more reliable sentiment signals.
"""

from __future__ import annotations

import logging
from datetime import datetime

from .placeholders import no_data_found, source_unavailable
from .rate_limiter import get_rate_limiter
from .registry import register_vendor
from .symbol_utils import get_pure_code, is_a_share

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
# 1. East Money detail scores — 历史评分 + 机构参与度
# ---------------------------------------------------------------------------

def get_em_detail_scores(
    ticker: str,
    start_date: str = "",
    end_date: str = "",
    limit: int = 30,
) -> str:
    """Fetch historical score trend and institutional participation from East Money.

    Uses ``stock_comment_detail_zhpj_lspf_em`` (历史评分) and
    ``stock_comment_detail_zlkp_jgcyd_em`` (机构参与度) to provide
    time-series sentiment signals — more reliable than the deprecated
    Baidu vote API.
    """
    if not _AKSHARE_AVAILABLE:
        return "<akshare not available: install with 'pip install akshare'>"
    if not is_a_share(ticker):
        return f"<em detail scores not applicable for non-A-share ticker: {ticker}>"

    code = get_pure_code(ticker)
    _rate_limiter.wait_if_needed("chinese_sentiment")

    blocks: list[str] = [f"## East Money Detail Scores — {ticker}", ""]

    # -- Historical score trend --
    try:
        df = ak.stock_comment_detail_zhpj_lspf_em(symbol=code)
        if df is not None and not df.empty:
            blocks.append("**历史评分 (Historical Score — recent 5):**")
            for _, row in df.head(5).iterrows():
                date = row.get("交易日", row.get("交易日期", ""))
                score = row.get("评分", "")
                blocks.append(f"  {date}: Score={score}")
            blocks.append("")
    except Exception as exc:
        logger.debug("Historical score failed for %s: %s", ticker, exc)

    # -- Institutional participation --
    try:
        df = ak.stock_comment_detail_zlkp_jgcyd_em(symbol=code)
        if df is not None and not df.empty:
            blocks.append("**机构参与度 (Institutional Participation — recent 5):**")
            for _, row in df.head(5).iterrows():
                date = row.get("交易日", row.get("交易日期", ""))
                val = row.get("机构参与度", "")
                blocks.append(f"  {date}: Participation={val}")
            blocks.append("")
    except Exception as exc:
        logger.debug("Institutional participation failed for %s: %s", ticker, exc)

    if len(blocks) == 2:
        return no_data_found("em_detail_scores", ticker, "score data")

    return "\n".join(blocks)


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
    if not is_a_share(ticker):
        return f"<em_comment not applicable for non-A-share ticker: {ticker}>"

    code = get_pure_code(ticker)
    _rate_limiter.wait_if_needed("chinese_sentiment")

    try:
        stock_comment_em = ak.stock_comment_em
        stock_comment_detail_scrd_focus_em = ak.stock_comment_detail_scrd_focus_em
        stock_comment_detail_scrd_desire_em = ak.stock_comment_detail_scrd_desire_em
    except AttributeError as exc:
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
                date = row.get("交易日", row.get("交易日期", ""))
                val = row.get("用户关注指数", row.get("关注指数", ""))
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
    if not is_a_share(ticker):
        return f"<chinese sentiment sources not applicable for {ticker}>"

    parts = [
        f"# Chinese Social Sentiment for {ticker}\n",
    ]

    detail = get_em_detail_scores(ticker, start_date, end_date, limit)
    if not detail.startswith("<") and "no_data" not in detail.lower():
        parts.append(detail)
    else:
        parts.append(f"  (EM detail scores: {detail})")

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
    "get_social_sentiment", "em_detail_scores", get_em_detail_scores,
)
register_vendor(
    "get_social_sentiment", "em_comment", get_em_comment,
)
register_vendor(
    "get_social_sentiment", "chinese", get_chinese_sentiment_aggregate,
)
