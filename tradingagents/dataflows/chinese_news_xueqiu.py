"""Xueqiu (雪球) discussion posts — free, no API key required.

Hits the public status-search endpoint at
``https://xueqiu.com/query/v1/symbol/search/status`` to fetch per-symbol
discussion threads. Xueqiu is the largest 中文 value-investing community;
its discussion skews toward fundamental analysis, valuations, and
long-term theses, complementing 东方财富股吧 (which skews toward 短线
retail/打板/游资 sentiment).

No API key, no registration, but the platform's anti-crawling is much
tighter than East Money's:

* a valid cookie (``xq_a_token``/``xq_r_token``) is set on first visit to
  ``xueqiu.com``; without it the JSON endpoint returns 400.
* newer (2024+) versions add a ``md5__1038`` signature parameter to
  comment-fetch endpoints. We don't hit the comment endpoint — we only
  read the public status-search feed, which still works with the cookie
  approach as of mid-2025.

Graceful-degradation contract: this module **never raises**. When Xueqiu
returns 403/empty/anti-crawling blocks, the function returns a
``<placeholder>`` string so the calling sentiment analyst always has a
uniform interface.
"""

from __future__ import annotations

import json
import logging
from typing import List, Optional

import requests

from .placeholders import no_data_found, source_unavailable
from .rate_limiter import get_rate_limiter
from .registry import register_vendor
from .symbol_utils import (
    is_a_share,
    to_a_share_code,
)

logger = logging.getLogger(__name__)

_rate_limiter = get_rate_limiter()
_rate_limiter.configure("chinese_xueqiu", max_calls=2, period=1.0)

_HOME_URL = "https://xueqiu.com/"
_STATUS_API = "https://xueqiu.com/query/v1/symbol/search/status"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/127.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "X-Requested-With": "XMLHttpRequest",
}

_TIMEOUT = 10.0
_DEFAULT_SIZE = 10
_MAX_PAGES = 3


def _to_xueqiu_symbol(symbol: str) -> str:
    """Convert ``600519`` / ``600519.SH`` / ``SH600519`` to ``SH600519``.

    Xueqiu's API requires the exchange prefix on A-share codes:
      - 60xxxx, 68xxxx, 90xxxx → ``SH``
      - 00xxxx, 30xxxx          → ``SZ``
      - 8xxxxx, 92xxxx          → ``BJ``
    """
    code = to_a_share_code(symbol)
    if not code.isdigit() or len(code) != 6:
        return ""
    if code.startswith(("60", "68", "90")):
        return f"SH{code}"
    if code.startswith(("00", "30")):
        return f"SZ{code}"
    if code.startswith(("8", "92")):
        return f"BJ{code}"
    return f"SH{code}"


def _bootstrap_cookie(session: requests.Session, timeout: float) -> bool:
    """Visit ``xueqiu.com`` once to obtain the ``xq_a_token``/``xq_r_token``
    cookies. Returns ``True`` if at least one Xueqiu cookie was captured.
    """
    try:
        resp = session.get(_HOME_URL, headers=_HEADERS, timeout=timeout)
    except requests.RequestException as exc:
        logger.debug("Xueqiu cookie bootstrap failed: %s", exc)
        return False
    cookies = session.cookies.get_dict()
    has_token = any(k in cookies for k in ("xq_a_token", "xq_r_token", "u"))
    if resp.status_code != 200 or not has_token:
        logger.debug(
            "Xueqiu cookie bootstrap: status=%d, cookies=%s",
            resp.status_code, list(cookies.keys()),
        )
        return has_token
    return True


def _parse_statuses(payload: dict) -> List[dict]:
    """Extract a normalised list of status dicts from a Xueqiu JSON response."""
    rows: List[dict] = []
    if not isinstance(payload, dict):
        return rows
    for item in payload.get("list", []) or []:
        if not isinstance(item, dict):
            continue
        text = item.get("text", "")
        if not text:
            continue
        user = item.get("user") or {}
        rows.append({
            "id": item.get("id"),
            "text": _strip_html(text),
            "user_id": user.get("id"),
            "user_name": user.get("screen_name", "?"),
            "time_before": item.get("timeBefore", ""),
            "created_at": item.get("created_at"),
            "retweet_count": item.get("retweet_count", 0) or 0,
            "reply_count": item.get("reply_count", 0) or 0,
            "fav_count": item.get("fav_count", 0) or 0,
        })
    return rows


def _strip_html(text: str) -> str:
    """Remove ``<em>`` highlight tags and excess whitespace from Xueqiu HTML."""
    if not text:
        return ""
    out = text.replace("<em>", "").replace("</em>", "")
    return " ".join(out.split())


def _fetch_page(
    session: requests.Session,
    xq_symbol: str,
    page: int,
    size: int,
    timeout: float,
) -> Optional[dict]:
    """Fetch one page of status-search results; return parsed JSON or None."""
    params = {
        "symbol": xq_symbol,
        "page": page,
        "size": size,
    }
    headers = {**_HEADERS, "Referer": f"https://xueqiu.com/S/{xq_symbol}"}
    _rate_limiter.wait_if_needed("chinese_xueqiu")
    try:
        resp = session.get(
            _STATUS_API, params=params, headers=headers, timeout=timeout,
        )
    except requests.RequestException as exc:
        logger.warning("Xueqiu fetch failed for %s page %d: %s", xq_symbol, page, exc)
        return None
    if resp.status_code != 200:
        logger.warning(
            "Xueqiu returned %d for %s page %d",
            resp.status_code, xq_symbol, page,
        )
        return None
    try:
        return resp.json()
    except json.JSONDecodeError as exc:
        logger.debug("Xueqiu JSON decode error: %s", exc)
        return None


def get_xueqiu_posts(
    ticker: str,
    start_date: str = "",
    end_date: str = "",
    limit: int = 20,
    timeout: float = _TIMEOUT,
) -> str:
    """Fetch recent Xueqiu discussion posts for *ticker* (A-share only).

    Args:
        ticker: A-share code like ``600519`` or ``600519.SH`` / ``SH600519``.
        start_date: Reserved for future filtering (Xueqiu's status-search
            API does not expose query-by-date parameters in the public
            feed).
        end_date: Same reserved-for-future note.
        limit: Maximum number of posts to return.

    Returns:
        A markdown-formatted string of recent discussion posts, or a
        ``<placeholder>`` when the request fails or the symbol is not an
        A-share.
    """
    if not is_a_share(ticker):
        return f"<xueqiu not applicable for non-A-share ticker: {ticker}>"

    xq_symbol = _to_xueqiu_symbol(ticker)
    if not xq_symbol:
        return f"<xueqiu could not derive symbol for: {ticker}>"

    target = max(1, limit)
    pages = min(_MAX_PAGES, (target + _DEFAULT_SIZE - 1) // _DEFAULT_SIZE)
    size = _DEFAULT_SIZE

    session = requests.Session()
    session.headers.update(_HEADERS)

    if not _bootstrap_cookie(session, timeout):
        return source_unavailable(
            "xueqiu",
            "could not obtain session cookies (anti-crawling block or network error)",
        )

    all_statuses: List[dict] = []
    parse_failure = False
    for page in range(1, pages + 1):
        payload = _fetch_page(session, xq_symbol, page, size, timeout)
        if payload is None:
            parse_failure = True
            continue
        statuses = _parse_statuses(payload)
        if not statuses and page == 1:
            parse_failure = True
        all_statuses.extend(statuses)
        if len(all_statuses) >= target:
            break

    all_statuses = all_statuses[:target]

    if not all_statuses:
        if parse_failure:
            return source_unavailable(
                "xueqiu",
                f"failed to fetch or parse statuses for {xq_symbol}",
            )
        return no_data_found("xueqiu", ticker, "discussion posts")

    lines = [f"## Xueqiu (雪球) Posts — {ticker}", ""]
    lines.append(
        f"Recent {len(all_statuses)} discussion threads from Xueqiu "
        f"(value-investing community):"
    )
    lines.append("")
    for i, s in enumerate(all_statuses, 1):
        snippet = s["text"]
        if len(snippet) > 200:
            snippet = snippet[:200] + "…"
        stats_parts = []
        if s["reply_count"]:
            stats_parts.append(f"reply={s['reply_count']}")
        if s["retweet_count"]:
            stats_parts.append(f"retweet={s['retweet_count']}")
        if s["fav_count"]:
            stats_parts.append(f"fav={s['fav_count']}")
        stats = " · ".join(stats_parts)
        line = f"{i}. {snippet}"
        if stats:
            line += f"  ({stats})"
        line += f"  — @{s['user_name']} · {s['time_before'] or '?'}"
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
    "get_social_sentiment", "xueqiu_posts", get_xueqiu_posts,
)
