"""东方财富 (East Money) news data — free, no API key required.

Uses the public JSON API that powers the East Money web frontend at
``push2.eastmoney.com``.  No registration or API key is needed.

Implementation notes
--------------------
- The API returns JSONP by default; passing ``_`` (timestamp) or omitting
  the callback parameter returns plain JSON on some endpoints.
- Rate limiting is handled by the module-level :class:`RateLimiter`
  (10 calls/second max, 1s inter-request delay).
- Anti-scraping: set ``Referer: https://www.eastmoney.com/`` and a
  desktop User-Agent.
"""

from __future__ import annotations

import json
import logging
import re
import time

import requests

from .config import get_config
from .rate_limiter import get_rate_limiter
from .registry import register_vendor
from .symbol_utils import (
    get_eastmoney_secid,
    is_a_share,
    NoMarketDataError,
)

logger = logging.getLogger(__name__)

_rate_limiter = get_rate_limiter()
_rate_limiter.configure("eastmoney", max_calls=5, period=1.0)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/127.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.eastmoney.com/",
    "Accept": "application/json, text/plain, */*",
}


def _strip_jsonp(text: str) -> str:
    """Remove JSONP wrapper if present and return the inner JSON string."""
    if text.startswith("jQuery") or text.startswith("jsonp"):
        m = re.search(r"\((\{.*\})\)", text, re.DOTALL)
        if m:
            return m.group(1)
        m = re.search(r"\((\[.*\])\)", text, re.DOTALL)
        if m:
            return m.group(1)
    return text


def _parse_articles(data: dict) -> list[dict]:
    """Extract article list from the East Money API response."""
    # Response structure: { "data": { "list": [...] } } or { "list": [...] }
    d = data.get("data", data)
    if not isinstance(d, dict):
        return []
    articles = d.get("list", d.get("articles", []))
    if isinstance(articles, dict):
        articles = list(articles.values())
    return articles if isinstance(articles, list) else []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_news_eastmoney(
    symbol: str,
    start_date: str,
    end_date: str,
    limit: int = 20,
) -> str:
    """Fetch East Money news for a specific stock ticker.

    Args:
        symbol: Stock ticker (e.g. ``"600519"``, ``"000001.SZ"``).
        start_date: Start date in ``YYYY-MM-DD`` format.
        end_date: End date in ``YYYY-MM-DD`` format.
        limit: Maximum number of articles.

    Returns:
        Formatted news text, or a ``<no news found>`` / ``<unavailable>``
        placeholder.
    """
    # Only applicable for A-share stocks — fall through to next vendor
    if not is_a_share(symbol):
        raise NoMarketDataError(
            symbol=symbol,
            canonical=symbol,
            detail="eastmoney only covers A-share stocks",
        )

    secid = get_eastmoney_secid(symbol)
    url = "https://push2.eastmoney.com/api/qt/stock_news_em/get"
    params = {
        "secid": secid,
        "pn": 1,
        "pz": min(limit, 50),
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fields": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
    }

    _rate_limiter.wait_if_needed("eastmoney")
    try:
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=10)
        resp.encoding = "utf-8"
        raw = _strip_jsonp(resp.text)
        data = json.loads(raw) if raw else {}
    except Exception as exc:
        logger.debug("eastmoney news request failed for %s: %s", symbol, exc)
        return f"<eastmoney unavailable: {exc}>"

    articles = _parse_articles(data)
    if not articles:
        return f"<no news found for {symbol} from eastmoney>"

    news_limit = get_config().get("news_article_limit", limit)
    articles = articles[:news_limit]

    lines = [f"## {symbol} News (东方财富), from {start_date} to {end_date}:\n"]
    for art in articles:
        title = art.get("art_Title", art.get("title", "No title"))
        pub_time = art.get("art_PubDate", art.get("date", ""))
        content = art.get("art_Content", art.get("content", ""))
        link = art.get("art_Url", art.get("url", ""))
        source = art.get("art_Source", art.get("source", "东方财富"))

        lines.append(f"### {title}")
        if pub_time:
            lines.append(f"Published: {pub_time}")
        if content:
            # Truncate very long content
            snippet = content[:300] + "..." if len(content) > 300 else content
            lines.append(snippet)
        if link:
            lines.append(f"Link: {link}")
        lines.append("")

    return "\n".join(lines)


def get_global_news_eastmoney(
    queries: list[str] | None = None,
    start_date: str = "",
    end_date: str = "",
    limit: int = 10,
) -> str:
    """Fetch global financial news from East Money.

    Args:
        queries: Ignored for East Money (uses its own global feed).
        start_date: Optional start date filter.
        end_date: Optional end date filter.
        limit: Maximum articles to return.

    Returns:
        Formatted news text.
    """
    url = "https://push2.eastmoney.com/api/qt/stock_news/get"
    params = {
        "type": "1",
        "page": 1,
        "pageSize": min(limit, 50),
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
    }

    _rate_limiter.wait_if_needed("eastmoney")
    try:
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=10)
        resp.encoding = "utf-8"
        raw = _strip_jsonp(resp.text)
        data = json.loads(raw) if raw else {}
    except Exception as exc:
        logger.debug("eastmoney global news request failed: %s", exc)
        return f"<eastmoney global news unavailable: {exc}>"

    articles = _parse_articles(data)
    if not articles:
        return "<no global news from eastmoney>"

    lines = ["## Global Finance News (东方财富):\n"]
    for art in articles[:limit]:
        title = art.get("art_Title", art.get("title", "No title"))
        pub_time = art.get("art_PubDate", art.get("date", ""))
        content = art.get("art_Content", art.get("content", ""))
        link = art.get("art_Url", art.get("url", ""))

        lines.append(f"### {title}")
        if pub_time:
            lines.append(f"Published: {pub_time}")
        if content:
            snippet = content[:300] + "..." if len(content) > 300 else content
            lines.append(snippet)
        if link:
            lines.append(f"Link: {link}")
        lines.append("")

    return "\n".join(lines)


def search_news_eastmoney(
    keywords: list[str],
    start_date: str = "",
    end_date: str = "",
    limit: int = 15,
) -> str:
    """Search East Money news by keyword (company name, industry, sector, etc.).

    Useful when per-ticker news APIs return no results — a broader keyword
    search still finds relevant industry / company coverage.

    Args:
        keywords: Search terms (e.g. ``["贵州茅台", "白酒"]``).
        start_date: Start date in ``YYYY-MM-DD`` format (used as hint).
        end_date: End date in ``YYYY-MM-DD`` format.
        limit: Max articles to return.

    Returns:
        Formatted news text, or a ``<no results>`` placeholder.
    """
    url = "https://search-api-web.eastmoney.com/search/jsonp"
    headers = {
        **dict(_HEADERS),
        "Referer": "https://www.eastmoney.com/",
    }

    all_articles: list[dict] = []
    seen_urls: set[str] = set()
    per_query = max(1, limit // max(len(keywords), 1))

    for kw in keywords:
        params = {
            "param": json.dumps({
                "uid": "",
                "keyword": kw,
                "type": ["cmsArticleWebOld"],
                "client": "web",
                "clientType": "web",
                "clientVersion": "curr",
            }, ensure_ascii=False),
            "cb": "jQuery",
        }

        _rate_limiter.wait_if_needed("eastmoney")
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            resp.encoding = "utf-8"
            raw = _strip_jsonp(resp.text)
            data = json.loads(raw) if raw else {}
        except Exception as exc:
            logger.debug("eastmoney search failed for '%s': %s", kw, exc)
            continue

        result = data.get("result", {})
        articles = result.get("cmsArticleWebOld", [])
        if not isinstance(articles, list):
            continue

        for art in articles:
            art_url = art.get("url", "") or art.get("art_Url", "")
            if art_url and art_url in seen_urls:
                continue
            if art_url:
                seen_urls.add(art_url)
            all_articles.append(art)

        if len(all_articles) >= limit:
            break

    if not all_articles:
        return f"<no keyword search results from eastmoney for: {keywords}>"

    lines = [
        f"## Industry / Sector News (东方财富关键词搜索):",
        f"   Keywords: {', '.join(keywords)}",
        "",
    ]
    for art in all_articles[:limit]:
        title = art.get("title", "")
        # Strip <em> tags from title (search highlighting)
        title = re.sub(r"</?em>", "", title) if title else "No title"
        pub_time = art.get("date", art.get("art_PubDate", ""))
        content = art.get("content", art.get("art_Content", ""))
        content = re.sub(r"</?em>", "", content) if content else ""
        link = art.get("url", art.get("art_Url", ""))
        media = art.get("mediaName", art.get("art_Source", "东方财富"))

        lines.append(f"### {title}")
        if pub_time:
            lines.append(f"Published: {pub_time}")
        if media:
            lines.append(f"Source: {media}")
        if content:
            snippet = content[:300] + "..." if len(content) > 300 else content
            lines.append(snippet)
        if link:
            lines.append(f"Link: {link}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

register_vendor("get_news", "eastmoney", get_news_eastmoney,
                category="news_data",
                category_description="News and insider data")
register_vendor("get_global_news", "eastmoney", get_global_news_eastmoney,
                category="news_data")
register_vendor("search_news", "eastmoney", search_news_eastmoney,
                category="news_data",
                category_description="Keyword-based news search")
