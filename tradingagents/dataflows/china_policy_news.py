"""China policy and regulatory news.

Combines two complementary sources:
  1. East Money keyword search with policy-related keywords
  2. Sina Finance domestic news feed (category 国内财经), post-filtered
     for policy-related headlines

Both are free, no API key required.
"""

from __future__ import annotations

import logging
import re

import requests

from .config import get_config
from .rate_limiter import get_rate_limiter
from .registry import register_vendor

logger = logging.getLogger(__name__)

_rate_limiter = get_rate_limiter()
_rate_limiter.configure("china_policy_news", max_calls=5, period=1.0)

_POLICY_KEYWORDS_EM = [
    "产业政策",
    "数字经济 发展规划",
    "双碳 碳中和 碳达峰",
    "设备更新 以旧换新",
    "反垄断 平台经济",
    "印花税 资本市场改革",
    "减持新规 注册制",
    "房地产政策 调控",
    "新能源 光伏 风电 政策",
    "人工智能 产业发展 政策",
]

_POLICY_FILTER_TERMS = [
    "政策", "监管", "改革", "法规", "通知", "意见",
    "规划", "方案", "措施", "印发", "发布", "实施",
    "印花税", "注册制", "减持", "退市",
    "反垄断", "房地产", "新能源",
    "碳达峰", "碳中和", "数字经济",
    "产业", "行业", "发展",
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/127.0.0.0 Safari/537.36"
    ),
    "Referer": "https://finance.sina.com.cn/",
}

_SINA_DOMESTIC_CID = "56957"


def _is_policy_relevant(title: str) -> bool:
    """Check if a news headline is likely policy/regulatory related."""
    title_lower = title.lower()
    return any(term.lower() in title_lower for term in _POLICY_FILTER_TERMS)


def _fetch_eastmoney_policy(start_date: str, end_date: str, limit: int) -> str:
    """Fetch policy news via East Money keyword search."""
    try:
        from .eastmoney_news import search_news_eastmoney

        return search_news_eastmoney(
            _POLICY_KEYWORDS_EM, start_date, end_date, limit=limit,
        )
    except Exception as exc:
        logger.debug("eastmoney policy search failed: %s", exc)
        return ""


def _fetch_sina_domestic(limit: int) -> str:
    """Fetch domestic financial news from Sina Finance, filtered for policy relevance."""
    url = "https://finance.sina.com.cn/api/roll.php"
    params = {"cid": _SINA_DOMESTIC_CID, "page": 1}

    _rate_limiter.wait_if_needed("china_policy_news")
    try:
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=10)
        resp.encoding = "utf-8"
        data = resp.json()
    except Exception as exc:
        logger.debug("sina domestic news failed: %s", exc)
        return ""

    articles = []
    if isinstance(data, dict):
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
        return ""

    lines = ["## 国内政策财经新闻 (新浪财经):\n"]
    count = 0
    for art in articles:
        if count >= limit:
            break
        title = art.get("title", "")
        if not title or not _is_policy_relevant(title):
            continue
        pub_time = art.get("date", art.get("ctime", ""))
        link = art.get("url", art.get("link", ""))
        lines.append(f"### {title}")
        if pub_time:
            lines.append(f"Published: {pub_time}")
        if link:
            lines.append(f"Link: {link}")
        lines.append("")
        count += 1

    if count == 0:
        return ""

    return "\n".join(lines)


def get_china_policy_news(
    start_date: str = "",
    end_date: str = "",
    limit: int = 15,
) -> str:
    """Fetch China policy and regulatory news.

    Args:
        start_date: Start date in ``YYYY-MM-DD`` format.
        end_date: End date in ``YYYY-MM-DD`` format.
        limit: Max articles to return.

    Returns:
        Formatted string with policy news, or a placeholder.
    """
    em_block = _fetch_eastmoney_policy(start_date, end_date, limit)
    sina_block = _fetch_sina_domestic(limit)

    parts = []
    if em_block and not em_block.startswith("<no"):
        parts.append(em_block)
    if sina_block:
        parts.append(sina_block)

    if not parts:
        return "<no policy news data available for the requested period>"

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

register_vendor(
    "get_china_policy_news",
    "eastmoney+sina",
    get_china_policy_news,
    category="china_policy_news",
    category_description="China policy and regulatory news",
)
