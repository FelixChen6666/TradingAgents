"""East Money Guba (东方财富股吧) discussion posts — free, no API key required.

Scrapes public HTML pages at
``https://guba.eastmoney.com/list,<code>,f_<page>.html`` to fetch per-stock
discussion posts. This is the single most cited retail-trader sentiment
source for A-shares, with on-topic threads that often lead price moves
(intraday 涨停/跌停 discussions, board-meeting rumours, follow-on
情绪宣泄).

No API key, no registration. Eastern-money's anti-crawling is light: a
desktop User-Agent plus a 1 second inter-request delay is sufficient for
interactive use. Heavier scraping should add a proxy pool, which is out
of scope for this module.

Graceful-degradation contract (mirrors ``stocktwits`` and ``chinese_sentiment``):
the function returns a formatted string or a ``<placeholder>`` rather
than raising, so the calling sentiment analyst never has to special-case
exceptions.
"""

from __future__ import annotations

import logging
from html import unescape
from typing import List, Optional

import requests
from bs4 import BeautifulSoup

from .placeholders import no_data_found, source_unavailable
from .rate_limiter import get_rate_limiter
from .registry import register_vendor
from .symbol_utils import (
    is_a_share,
    to_a_share_code,
)

logger = logging.getLogger(__name__)

_rate_limiter = get_rate_limiter()
_rate_limiter.configure("chinese_guba", max_calls=3, period=1.0)

_GUBA_PAGE_URL = "https://guba.eastmoney.com/list,{code},f_{page}.html"
_POST_DETAIL_URL = "https://guba.eastmoney.com/news,{code},{post_id}.html"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/127.0.0.0 Safari/537.36"
    ),
    "Referer": "https://guba.eastmoney.com/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

_PAGE_SIZE = 30
_DEFAULT_PAGES = 3
_TIMEOUT = 10.0


def _parse_post_list(html_text: str, code: str) -> List[dict]:
    """Parse a single Guba list page into a list of post dicts.

    Each dict contains: post_id, title, author, post_time, read_count,
    reply_count. Fields that cannot be parsed are returned as empty
    strings (the formatter will still render the row, just with blanks).
    """
    soup = BeautifulSoup(html_text, "html.parser")
    items: List[dict] = []

    # Eastern Money's list page uses <tr class="listitem"> for each post;
    # older pages also use <div class="articleh">. Try both selectors.
    for tr in soup.select("tr.listitem"):
        title_a = tr.select_one("td.title a, .title a")
        if not title_a:
            continue
        post_id = _extract_post_id(title_a.get("href", ""))
        title = unescape(title_a.get_text(strip=True))
        if not title:
            continue
        author_cell = tr.select_one("td.author a, .author a")
        author = unescape(author_cell.get_text(strip=True)) if author_cell else ""
        time_cell = tr.select_one("td.update, .update")
        post_time = unescape(time_cell.get_text(strip=True)) if time_cell else ""
        read_cell = tr.select_one("td.read, .read")
        read_count = unescape(read_cell.get_text(strip=True)) if read_cell else ""
        reply_cell = tr.select_one("td.reply, .reply")
        reply_count = unescape(reply_cell.get_text(strip=True)) if reply_cell else ""
        items.append({
            "post_id": post_id,
            "title": title,
            "author": author,
            "post_time": post_time,
            "read_count": read_count,
            "reply_count": reply_count,
        })

    # Fallback: try the legacy <div class="articleh"> markup.
    if not items:
        for div in soup.select("div.articleh"):
            title_a = div.select_one("a.l3, a.title")
            if not title_a:
                continue
            post_id = _extract_post_id(title_a.get("href", ""))
            title = unescape(title_a.get_text(strip=True))
            if not title:
                continue
            author_a = div.select_one("a.l4, .author a")
            author = unescape(author_a.get_text(strip=True)) if author_a else ""
            time_span = div.select_one("span.l6, .update")
            post_time = unescape(time_span.get_text(strip=True)) if time_span else ""
            items.append({
                "post_id": post_id,
                "title": title,
                "author": author,
                "post_time": post_time,
                "read_count": "",
                "reply_count": "",
            })

    return items


def _extract_post_id(href: str) -> str:
    """Pull ``post_id`` from a Guba link such as ``/news,600519,123456789.html``.

    Guba list-page hrefs look like ``/news,<code>,<post_id>.html`` where
    ``post_id`` is a 9-12 digit number. The 6-digit stock code sits next
    to it, so we pick the *longest* purely-digit segment — that is always
    the post id.
    """
    if not href:
        return ""
    candidates = [p for p in href.replace(".html", "").split(",") if p.isdigit()]
    if not candidates:
        return ""
    return max(candidates, key=len)


def _fetch_page(code: str, page: int, timeout: float) -> Optional[str]:
    """Fetch one Guba list page; return HTML text or None on failure."""
    url = _GUBA_PAGE_URL.format(code=code, page=page)
    _rate_limiter.wait_if_needed("chinese_guba")
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
    except requests.RequestException as exc:
        logger.warning("Guba request failed for %s page %d: %s", code, page, exc)
        return None
    if resp.status_code != 200:
        logger.warning("Guba returned %d for %s page %d", resp.status_code, code, page)
        return None
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def get_guba_posts(
    ticker: str,
    start_date: str = "",
    end_date: str = "",
    limit: int = 30,
    pages: int = _DEFAULT_PAGES,
    timeout: float = _TIMEOUT,
) -> str:
    """Fetch recent Guba discussion posts for *ticker* (A-share only).

    Args:
        ticker: A-share code like ``600519`` or ``600519.SH`` / ``SH600519``.
        start_date: Reserved for future filtering (Guba does not expose
            query-by-date parameters in the public list page).
        end_date: Same reserved-for-future note.
        limit: Maximum number of posts to return (capped by the per-page
            fetch * ``pages``).
        pages: Number of list pages to crawl (each page = 30 posts).
        timeout: Per-request timeout in seconds.

    Returns:
        A markdown-formatted string of recent posts, or a ``<placeholder>``
        when the request fails or the symbol is not an A-share.
    """
    if not is_a_share(ticker):
        return f"<guba not applicable for non-A-share ticker: {ticker}>"

    code = to_a_share_code(ticker)
    pages = max(1, min(pages, 10))
    target = max(1, limit // _PAGE_SIZE + (1 if limit % _PAGE_SIZE else 0))
    pages = min(pages, target)

    all_posts: List[dict] = []
    parse_failure = False
    for page in range(1, pages + 1):
        html_text = _fetch_page(code, page, timeout)
        if html_text is None:
            parse_failure = True
            continue
        posts = _parse_post_list(html_text, code)
        if not posts and page == 1:
            parse_failure = True
        all_posts.extend(posts)
        if len(all_posts) >= limit:
            break

    all_posts = all_posts[:limit]

    if not all_posts:
        if parse_failure:
            return source_unavailable(
                "guba", f"failed to fetch or parse pages for {code}",
            )
        return no_data_found("guba", ticker, "discussion posts")

    lines = [f"## East Money Guba Posts — {ticker}", ""]
    lines.append(
        f"Recent {len(all_posts)} discussion threads from 东方财富股吧 "
        f"(retail-trader forum):"
    )
    lines.append("")
    for i, post in enumerate(all_posts, 1):
        title = post["title"]
        post_id = post["post_id"]
        author = post["author"] or "?"
        post_time = post["post_time"] or "?"
        stats_parts = []
        if post["read_count"]:
            stats_parts.append(f"read={post['read_count']}")
        if post["reply_count"]:
            stats_parts.append(f"reply={post['reply_count']}")
        stats = " · ".join(stats_parts)
        line = f"{i}. [{title}]({_POST_DETAIL_URL.format(code=code, post_id=post_id) if post_id else ''})"
        if stats:
            line += f"  ({stats})"
        line += f"  — @{author} · {post_time}"
        lines.append(line)

    if parse_failure:
        lines.append("")
        lines.append(
            "_(Note: some pages could not be fetched; results may be "
            "incomplete — likely an anti-crawling block or transient "
            "network error.)_"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

register_vendor(
    "get_social_sentiment", "guba_posts", get_guba_posts,
)
