"""China macroeconomic news — financial news + numerical indicators.

Combines two complementary sources into one structured block:
  1. East Money keyword search for macro news headlines
  2. AKShare numerical macro indicators (GDP, CPI, PPI, PMI, 社融)

Each AKShare call is independently wrapped so one failing source
does not block the others.
"""

from __future__ import annotations

import logging

from .config import get_config
from .rate_limiter import get_rate_limiter
from .registry import register_vendor

logger = logging.getLogger(__name__)

_rate_limiter = get_rate_limiter()
_rate_limiter.configure("china_macro_news", max_calls=5, period=1.0)

# AKShare optional import — same pattern as akshare_stock.py
try:
    import akshare as ak
except ImportError:
    ak = None  # type: ignore[assignment]

_MACRO_KEYWORDS = [
    "GDP 中国经济",
    "CPI 居民消费价格",
    "PPI 工业生产者价格",
    "PMI 制造业采购经理指数",
    "社融 社会融资规模",
    "LPR 贷款市场报价利率",
    "降准 降息 货币政策",
]


def _fetch_eastmoney_news(start_date: str, end_date: str, limit: int) -> str:
    """Fetch macro news headlines via East Money keyword search."""
    try:
        from .eastmoney_news import search_news_eastmoney

        return search_news_eastmoney(
            _MACRO_KEYWORDS, start_date, end_date, limit=limit,
        )
    except Exception as exc:
        logger.debug("eastmoney macro search failed: %s", exc)
        return ""


def _fetch_akshare_indicators() -> str:
    """Fetch numerical macro indicators via AKShare.

    Each indicator call is independently wrapped so one failure
    (rate limit, removed API, network blip) does not block the others.
    """
    if ak is None:
        return ""

    lines: list[str] = []

    # — GDP —
    _rate_limiter.wait_if_needed("china_macro_news")
    try:
        gdp = ak.macro_china_gdp()
        if gdp is not None and not gdp.empty:
            lines.append("## GDP (国内生产总值)")
            lines.append(gdp.tail(5).to_string())
            lines.append("")
    except Exception as exc:
        logger.debug("akshare macro_china_gdp failed: %s", exc)

    # — CPI —
    _rate_limiter.wait_if_needed("china_macro_news")
    try:
        cpi = ak.macro_china_cpi_monthly()
        if cpi is not None and not cpi.empty:
            lines.append("## CPI (居民消费价格指数)")
            lines.append(cpi.tail(5).to_string())
            lines.append("")
    except Exception as exc:
        logger.debug("akshare macro_china_cpi_monthly failed: %s", exc)

    # — PPI —
    _rate_limiter.wait_if_needed("china_macro_news")
    try:
        ppi = ak.macro_china_ppi_monthly()
        if ppi is not None and not ppi.empty:
            lines.append("## PPI (工业生产者价格指数)")
            lines.append(ppi.tail(5).to_string())
            lines.append("")
    except Exception as exc:
        logger.debug("akshare macro_china_ppi_monthly failed: %s", exc)

    # — PMI —
    _rate_limiter.wait_if_needed("china_macro_news")
    try:
        pmi = ak.macro_china_pmi()
        if pmi is not None and not pmi.empty:
            lines.append("## PMI (采购经理指数)")
            lines.append(pmi.tail(5).to_string())
            lines.append("")
    except Exception as exc:
        logger.debug("akshare macro_china_pmi failed: %s", exc)

    # — 社会融资规模 —
    _rate_limiter.wait_if_needed("china_macro_news")
    try:
        shrzgm = ak.macro_china_shrzgm()
        if shrzgm is not None and not shrzgm.empty:
            lines.append("## 社会融资规模")
            lines.append(shrzgm.tail(5).to_string())
            lines.append("")
    except Exception as exc:
        logger.debug("akshare macro_china_shrzgm failed: %s", exc)

    return "\n".join(lines)


def get_china_macro_news(
    start_date: str = "",
    end_date: str = "",
    limit: int = 10,
) -> str:
    """Fetch China macroeconomic news + numerical indicator data.

    Args:
        start_date: Start date in ``YYYY-MM-DD`` format.
        end_date: End date in ``YYYY-MM-DD`` format.
        limit: Max news articles to return from the search source.

    Returns:
        Formatted string with news headlines and numerical indicator
        tables, or a ``<no macro news data available>`` placeholder.
    """
    news_block = _fetch_eastmoney_news(start_date, end_date, limit)
    indicators_block = _fetch_akshare_indicators()

    parts = []
    if news_block and not news_block.startswith("<no"):
        parts.append(news_block)
    if indicators_block:
        parts.append(indicators_block)

    if not parts:
        return "<no macro news data available for the requested period>"

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

register_vendor(
    "get_china_macro_news",
    "akshare+eastmoney",
    get_china_macro_news,
    category="china_macro_news",
    category_description="China macroeconomic news and indicator data",
)
