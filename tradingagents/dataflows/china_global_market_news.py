"""A-share-relevant global market and geopolitical news.

Combines two complementary sources:
  1. East Money keyword search with A-share-relevant global keywords
  2. yfinance Search with expanded queries (US-China, commodities, EM)

Both are free, no API key required.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from .config import get_config
from .rate_limiter import get_rate_limiter
from .registry import register_vendor

logger = logging.getLogger(__name__)

_rate_limiter = get_rate_limiter()
_rate_limiter.configure("china_global_market_news", max_calls=5, period=1.0)

_GLOBAL_KEYWORDS_EM = [
    "美联储 加息 人民币汇率",
    "美股 中概股 行情",
    "港股 恒生指数",
    "中美关系 地缘政治 贸易摩擦",
    "大宗商品 原油 铜 铁矿石 价格",
    "人民币汇率 美元指数",
    "全球经济衰退 通胀",
    "亚太市场 日经 韩国综指",
]

_GLOBAL_QUERIES_YF = [
    "US China trade tariff relations",
    "China ADR Hong Kong stock market",
    "emerging market Asia Pacific economy",
    "commodity prices oil copper iron ore",
    "yuan renminbi exchange rate policy",
    "global economic outlook 2025",
    "Asia stock market today",
]


def _fetch_eastmoney_global(start_date: str, end_date: str, limit: int) -> str:
    """Fetch A-share-relevant global news via East Money keyword search."""
    try:
        from .eastmoney_news import search_news_eastmoney

        return search_news_eastmoney(
            _GLOBAL_KEYWORDS_EM, start_date, end_date, limit=limit,
        )
    except Exception as exc:
        logger.debug("eastmoney global market search failed: %s", exc)
        return ""


def _fetch_yfinance_global(
    curr_date: str, look_back_days: int, limit: int,
) -> str:
    """Fetch global market news via yfinance Search with A-share-relevant queries."""
    try:
        import yfinance as yf
    except ImportError:
        logger.debug("yfinance not available for global market search")
        return ""

    all_news = []
    seen_titles = set()

    for query in _GLOBAL_QUERIES_YF:
        _rate_limiter.wait_if_needed("china_global_market_news")
        try:
            search = yf.Search(
                query=query,
                news_count=limit,
                enable_fuzzy_query=True,
            )
        except Exception as exc:
            logger.debug("yfinance Search failed for '%s': %s", query, exc)
            continue

        if not search.news:
            continue

        for article in search.news:
            if "content" in article:
                content = article["content"]
                title = content.get("title", "")
            else:
                title = article.get("title", "")

            if title and title not in seen_titles:
                seen_titles.add(title)
                all_news.append(article)

        if len(all_news) >= limit:
            break

    if not all_news:
        return ""

    # Calculate date range for header
    try:
        curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    except (ValueError, TypeError):
        curr_dt = datetime.now()
    start_dt = curr_dt - timedelta(days=look_back_days)
    start_date_str = start_dt.strftime("%Y-%m-%d")

    lines = [
        f"## Global Market News (Yahoo Finance), from {start_date_str} to {curr_date}:",
        "",
    ]
    for article in all_news[:limit]:
        if "content" in article:
            content = article["content"]
            title = content.get("title", "No title")
            publisher = (content.get("provider", {}) or {}).get(
                "displayName", "Unknown"
            )
            url_obj = content.get("canonicalUrl") or content.get(
                "clickThroughUrl"
            ) or {}
            link = url_obj.get("url", "")
            summary = content.get("summary", "")
        else:
            title = article.get("title", "No title")
            publisher = article.get("publisher", "Unknown")
            link = article.get("link", "")
            summary = ""

        lines.append(f"### {title} (source: {publisher})")
        if summary:
            lines.append(summary)
        if link:
            lines.append(f"Link: {link}")
        lines.append("")

    return "\n".join(lines)


def get_china_global_market_news(
    start_date: str = "",
    end_date: str = "",
    limit: int = 10,
) -> str:
    """Fetch global market and geopolitical news filtered for A-share relevance.

    Covers: US/HK markets, commodities (oil, copper, iron ore), foreign
    exchange (USD/CNY), geopolitics (US-China relations, trade frictions),
    and Asia-Pacific market trends.

    Args:
        start_date: Start date in ``YYYY-MM-DD`` format.
        end_date: End date in ``YYYY-MM-DD`` format.
        limit: Max articles to return.

    Returns:
        Formatted string or a placeholder.
    """
    look_back_days = get_config().get("global_news_lookback_days", 7)
    article_limit = get_config().get("global_news_article_limit", limit)

    em_block = _fetch_eastmoney_global(start_date, end_date, limit)
    yf_block = _fetch_yfinance_global(
        end_date, look_back_days, article_limit,
    )

    parts = []
    if em_block and not em_block.startswith("<no"):
        parts.append(em_block)
    if yf_block:
        parts.append(yf_block)

    if not parts:
        return "<no global market news data available for the requested period>"

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

register_vendor(
    "get_china_global_market_news",
    "eastmoney+yfinance",
    get_china_global_market_news,
    category="china_global_market_news",
    category_description="A-share relevant global market and geopolitical news",
)
