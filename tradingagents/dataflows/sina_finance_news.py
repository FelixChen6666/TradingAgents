"""新浪财经 (Sina Finance) news data — free, no API key required.

Uses the public JSON API and web pages at ``finance.sina.com.cn``.
No registration or API key is needed.

Data sources
------------
- **Rolling news JSON API**: ``https://finance.sina.com.cn/api/roll.php``
  returns pure JSON (no JSONP wrapper).  Uses category IDs:
  - ``cid=56957`` — 国内财经 (domestic)
  - ``cid=332976`` — 国际财经 (international)
- **Individual stock news**: scrapes the news list page at
  ``finance.sina.com.cn/realstock/company/{exchange}{code}/nc.shtml``
"""

from __future__ import annotations

import logging
import re

import requests
from bs4 import BeautifulSoup

from .config import get_config
from .rate_limiter import get_rate_limiter
from .registry import register_vendor
from .symbol_utils import is_a_share, NoMarketDataError, strip_exchange_suffix

logger = logging.getLogger(__name__)

_rate_limiter = get_rate_limiter()
_rate_limiter.configure("sina_finance", max_calls=5, period=1.0)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/127.0.0.0 Safari/537.36"
    ),
    "Referer": "https://finance.sina.com.cn/",
}

# Sina Finance news category IDs
_CATEGORIES = {
    "domestic": "56957",
    "international": "332976",
    "industry": "56958",
    "stock": "56959",
}


def _exchange_prefix(symbol: str) -> str:
    """Return the Sina exchange prefix: ``sh`` for Shanghai, ``sz`` for Shenzhen."""
    raw = strip_exchange_suffix(symbol)
    if raw.startswith(("6", "9", "68")):
        return "sh"
    return "sz"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_news_sina(
    symbol: str,
    start_date: str,
    end_date: str,
    limit: int = 20,
) -> str:
    """Fetch新浪财经 news for a specific A-share stock ticker.

    Args:
        symbol: Stock ticker (e.g. ``"600519"``, ``"000001.SZ"``).
        start_date: Start date in ``YYYY-MM-DD`` format.
        end_date: End date in ``YYYY-MM-DD`` format.
        limit: Maximum number of articles.

    Returns:
        Formatted news text.
    """
    # Only applicable for A-share stocks — fall through to next vendor
    if not is_a_share(symbol):
        raise NoMarketDataError(
            symbol=symbol,
            canonical=symbol,
            detail="sina_finance only covers A-share stocks",
        )

    code = strip_exchange_suffix(symbol)
    prefix = _exchange_prefix(symbol)
    url = (
        f"https://vip.stock.finance.sina.com.cn/corp/go.php/vCB_AllNewsStock/"
        f"symbol/{prefix}{code}.phtml"
    )

    _rate_limiter.wait_if_needed("sina_finance")
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        resp.encoding = "gbk"  # Sina uses GBK encoding
    except Exception as exc:
        logger.debug("sina_finance news request failed for %s: %s", symbol, exc)
        return f"<sina_finance unavailable: {exc}>"

    try:
        soup = BeautifulSoup(resp.text, "html.parser")
        items = soup.select("ul.list li")
        if not items:
            return f"<no news found for {symbol} from sina_finance>"

        news_limit = get_config().get("news_article_limit", limit)
        lines = [f"## {symbol} News (新浪财经), from {start_date} to {end_date}:\n"]
        count = 0
        for item in items:
            if count >= news_limit:
                break
            link_tag = item.find("a")
            span_tag = item.find("span")
            if not link_tag:
                continue
            title = link_tag.get_text(strip=True)
            href = link_tag.get("href", "")
            pub_time = span_tag.get_text(strip=True) if span_tag else ""

            if not title:
                continue

            lines.append(f"### {title}")
            if pub_time:
                lines.append(f"Published: {pub_time}")
            if href and href.startswith("http"):
                lines.append(f"Link: {href}")
            lines.append("")
            count += 1

        if count == 0:
            return f"<no news found for {symbol} from sina_finance>"
        return "\n".join(lines)
    except Exception as exc:
        logger.debug("sina_finance parse failed for %s: %s", symbol, exc)
        return f"<sina_finance parse error: {exc}>"


def get_global_news_sina(
    queries: list[str] | None = None,
    start_date: str = "",
    end_date: str = "",
    limit: int = 10,
) -> str:
    """Fetch global/macro news from sina finance rolling news API.

    Args:
        queries: Optional search queries (used as category hints).
        start_date: Ignored (Sina API returns current news).
        end_date: Ignored.
        limit: Maximum articles.

    Returns:
        Formatted news text.
    """
    # Use the international category for "global" news
    cid = _CATEGORIES.get("international", "332976")
    url = "https://finance.sina.com.cn/api/roll.php"
    params = {"cid": cid, "page": 1}

    _rate_limiter.wait_if_needed("sina_finance")
    try:
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=10)
        resp.encoding = "utf-8"
        data = resp.json()
    except Exception as exc:
        logger.debug("sina_finance global news request failed: %s", exc)
        return f"<sina_finance global news unavailable: {exc}>"

    articles = []
    if isinstance(data, dict):
        # Try different response structures
        items = (
            data.get("result", {})
            .get("data", {})
            .get("list", data.get("list", []))
        )
        if isinstance(items, list):
            articles = items
        elif isinstance(items, dict):
            articles = list(items.values())

    if not articles:
        return "<no global news from sina_finance>"

    lines = ["## Global Finance News (新浪财经):\n"]
    for art in articles[:limit]:
        title = art.get("title", "No title")
        pub_time = art.get("date", art.get("ctime", ""))
        link = art.get("url", art.get("link", ""))

        lines.append(f"### {title}")
        if pub_time:
            lines.append(f"Published: {pub_time}")
        if link:
            lines.append(f"Link: {link}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

register_vendor("get_news", "sina_finance", get_news_sina,
                category="news_data",
                category_description="News and insider data")
register_vendor("get_global_news", "sina_finance", get_global_news_sina,
                category="news_data")
