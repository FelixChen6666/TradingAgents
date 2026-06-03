"""AKShare vendor implementation — Chinese market data.

AKShare is a pure-Python open-source library that wraps public APIs from
East Money (东方财富), Sina Finance (新浪财经), and other Chinese financial
data providers.  **No API key is required.**

Usage requires ``pip install akshare``.

Reference
---------
- Homepage: https://github.com/akfamily/akshare
- Docs:     https://akshare.akfamily.xyz
"""

from __future__ import annotations

import logging

from .placeholders import no_data_found, source_unavailable
from .rate_limiter import get_rate_limiter
from .registry import register_vendor
from .symbol_utils import (
    NoMarketDataError,
    detect_market,
    strip_exchange_suffix,
)

logger = logging.getLogger(__name__)

_rate_limiter = get_rate_limiter()
_rate_limiter.configure("akshare", max_calls=10, period=1.0)

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

def _to_akshare_code(symbol: str) -> str:
    """Strip exchange suffix from an A-share / HK symbol for AKShare."""
    code = strip_exchange_suffix(symbol)
    return code


def _detect_akshare_market(symbol: str) -> str:
    """Return the AKShare market flavour for *symbol*."""
    raw = symbol.strip().upper()
    if raw.endswith(".HK") or (raw.isdigit() and len(raw) == 5):
        return "hk"
    if detect_market(symbol) == "a_share":
        return "a_share"
    return "unsupported"


# ---------------------------------------------------------------------------
# OHLCV — A-share daily data
# ---------------------------------------------------------------------------

def get_stock_data_akshare(
    symbol: str,
    start_date: str,
    end_date: str,
) -> str:
    """Fetch A-share or HK daily OHLCV via AKShare."""
    if not _AKSHARE_AVAILABLE:
        return "<akshare not available: install with 'pip install akshare'>"

    market = _detect_akshare_market(symbol)
    if market == "unsupported":
        raise NoMarketDataError(
            symbol, symbol,
            "AKShare only supports A-share and HK stocks",
        )

    _rate_limiter.wait_if_needed("akshare")
    code = _to_akshare_code(symbol)
    try:
        if market == "a_share":
            df = ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
                adjust="qfq",
            )
        else:
            df = ak.stock_hk_hist(
                symbol=code,
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
            )
    except Exception as exc:
        logger.debug("AKShare query failed for %s: %s", symbol, exc)
        raise NoMarketDataError(symbol, code, detail=str(exc)) from exc

    if df is None or df.empty:
        raise NoMarketDataError(symbol, code, "AKShare returned empty")

    return _format_ohlcv(df, symbol, start_date, end_date, market)


def _format_ohlcv(
    df, symbol: str, start_date: str, end_date: str, market: str
) -> str:
    """Format an AKShare OHLCV DataFrame to the expected CSV string."""
    if market == "a_share":
        # AKShare A-share columns: 日期,开盘,收盘,最高,最低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率
        lines = [
            f"# Stock data for {symbol} (AKShare/A-share) "
            f"from {start_date} to {end_date}",
            f"# Total records: {len(df)}",
            "",
            "Date,Open,High,Low,Close,Volume,Change%",
        ]
        for _, row in df.iterrows():
            lines.append(
                f"{row['日期']},{row['开盘']},{row['最高']},{row['最低']},"
                f"{row['收盘']},{row['成交量']},{row.get('涨跌幅', '')}"
            )
    else:
        lines = [
            f"# Stock data for {symbol} (AKShare/HK) "
            f"from {start_date} to {end_date}",
            f"# Total records: {len(df)}",
            "",
            "Date,Open,High,Low,Close,Volume",
        ]
        for _, row in df.iterrows():
            lines.append(
                f"{row['日期']},{row['开盘']},{row['最高']},{row['最低']},"
                f"{row['收盘']},{row['成交量']}"
            )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Fundamentals — Chinese financial statements (summary)
# ---------------------------------------------------------------------------

def get_fundamentals_akshare(symbol: str) -> str:
    """Fetch A-share fundamentals summary via AKShare."""
    if not _AKSHARE_AVAILABLE:
        return "<akshare not available>"

    market = _detect_akshare_market(symbol)
    if market != "a_share":
        return no_data_found("akshare", symbol, "fundamentals")

    _rate_limiter.wait_if_needed("akshare")
    code = _to_akshare_code(symbol)
    try:
        df = ak.stock_financial_abstract(symbol=code)
    except Exception as exc:
        logger.debug("AKShare fundamentals failed for %s: %s", symbol, exc)
        return source_unavailable("akshare", str(exc))

    if df is None or df.empty:
        return no_data_found("akshare", symbol, "fundamentals")

    return f"# Fundamentals (AKShare) for {symbol}\n{df.to_string()}\n"


# ---------------------------------------------------------------------------
# China market overview
# ---------------------------------------------------------------------------

def get_china_market_overview() -> str:
    """Fetch A-share market breadth overview via AKShare."""
    if not _AKSHARE_AVAILABLE:
        return "<akshare not available>"

    _rate_limiter.wait_if_needed("akshare")
    try:
        df = ak.stock_zh_a_spot_em()
    except Exception as exc:
        return source_unavailable("akshare", str(exc))

    if df is None or df.empty:
        return "<no data from akshare for market overview>"

    return f"# A-share Market Overview (AKShare)\n{df.to_string()}\n"


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

register_vendor(
    "get_stock_data", "akshare", get_stock_data_akshare,
    category="chinese_market_data",
    category_description="China A-share and Hong Kong market data",
)
register_vendor(
    "get_fundamentals", "akshare", get_fundamentals_akshare,
)
