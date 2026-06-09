"""Vendor routing engine — dispatches data method calls to the right provider.

``route_to_vendor()`` is the single entry point that agent tools call.
Vendors are discovered via the :mod:`~.registry` module; adding a new data
source means writing a module that calls ``register_vendor()`` — no other
file needs to change.
"""

from typing import Annotated

# Import from vendor-specific modules to trigger self-registration.
from . import alpha_vantage  # noqa: F401
from . import y_finance  # noqa: F401
from . import yfinance_news  # noqa: F401
from . import social_sentiment  # noqa: F401
from . import chinese_sentiment  # noqa: F401 — imported separately so it
                                 # registers *after* social_sentiment has
                                 # created the TOOLS_CATEGORIES entry
from . import eastmoney_news  # noqa: F401
from . import sina_finance_news  # noqa: F401
from . import fred  # noqa: F401
from . import options_data  # noqa: F401
from . import akshare_stock  # noqa: F401
from . import china_macro_news  # noqa: F401
from . import china_policy_news  # noqa: F401
from . import china_global_market_news  # noqa: F401
from . import china_market_flow  # noqa: F401
from . import china_stock_ranking
from . import chinese_news_guba        # noqa: F401 — A 股散户情绪 (东方财富股吧)
from . import chinese_news_xueqiu      # noqa: F401 — A 股价值投资者情绪 (雪球)

from .alpha_vantage_common import AlphaVantageRateLimitError
from .config import get_config
from .registry import (
    TOOLS_CATEGORIES,
    VENDOR_LIST,
    VENDOR_METHODS,
    register_vendor,
)
from .symbol_utils import NoMarketDataError

# ---------------------------------------------------------------------------
# Register the built-in vendors on the legacy inline schema so that existing
# code continues to work unchanged.  New vendors self-register in their own
# modules via ``register_vendor()``.
# ---------------------------------------------------------------------------
# core_stock_apis
register_vendor("get_stock_data", "yfinance", y_finance.get_YFin_data_online)
register_vendor("get_stock_data", "alpha_vantage", alpha_vantage.get_stock)

# technical_indicators
register_vendor(
    "get_indicators",
    "yfinance",
    y_finance.get_stock_stats_indicators_window,
)
register_vendor(
    "get_indicators",
    "alpha_vantage",
    alpha_vantage.get_indicator,
)

# fundamental_data
register_vendor("get_fundamentals", "yfinance", y_finance.get_fundamentals)
register_vendor(
    "get_fundamentals", "alpha_vantage", alpha_vantage.get_fundamentals
)
register_vendor("get_balance_sheet", "yfinance", y_finance.get_balance_sheet)
register_vendor(
    "get_balance_sheet", "alpha_vantage", alpha_vantage.get_balance_sheet
)
register_vendor("get_cashflow", "yfinance", y_finance.get_cashflow)
register_vendor("get_cashflow", "alpha_vantage", alpha_vantage.get_cashflow)
register_vendor(
    "get_income_statement", "yfinance", y_finance.get_income_statement
)
register_vendor(
    "get_income_statement",
    "alpha_vantage",
    alpha_vantage.get_income_statement,
)

# news_data
register_vendor("get_news", "yfinance", yfinance_news.get_news_yfinance)
register_vendor("get_news", "alpha_vantage", alpha_vantage.get_news)
register_vendor(
    "get_global_news", "yfinance", yfinance_news.get_global_news_yfinance
)
register_vendor(
    "get_global_news", "alpha_vantage", alpha_vantage.get_global_news
)
register_vendor(
    "get_insider_transactions",
    "yfinance",
    y_finance.get_insider_transactions,
)
register_vendor(
    "get_insider_transactions",
    "alpha_vantage",
    alpha_vantage.get_insider_transactions,
)

# Ensure the existing *inline* categories are also present so that
# ``get_category_for_method()`` works for methods registered above.
_REFCAT = TOOLS_CATEGORIES
for _cat, _info in {
    "core_stock_apis": {
        "description": "OHLCV stock price data",
        "tools": ["get_stock_data"],
    },
    "technical_indicators": {
        "description": "Technical analysis indicators",
        "tools": ["get_indicators"],
    },
    "fundamental_data": {
        "description": "Company fundamentals",
        "tools": [
            "get_fundamentals",
            "get_balance_sheet",
            "get_cashflow",
            "get_income_statement",
        ],
    },
    "news_data": {
        "description": "News and insider data",
        "tools": [
            "get_news",
            "get_global_news",
            "get_insider_transactions",
        ],
    },
    "china_macro_news": {
        "description": "China macroeconomic news and indicator data",
        "tools": ["get_china_macro_news"],
    },
    "china_policy_news": {
        "description": "China policy and regulatory news",
        "tools": ["get_china_policy_news"],
    },
    "china_global_market_news": {
        "description": "A-share relevant global market and geopolitical news",
        "tools": ["get_china_global_market_news"],
    },
    "china_market_flow": {
        "description": "A-share market sentiment and capital flow statistics",
        "tools": ["get_china_market_flow"],
    },
}.items():
    if _cat not in _REFCAT:
        _REFCAT[_cat] = _info
    else:
        # Vendor self-registration may have created the category with only a
        # subset of tools (e.g. eastmoney registers "search_news" with
        # category="news_data").  Merge in any missing tools so that methods
        # registered inline (e.g. get_insider_transactions) are discoverable.
        existing_tools = _REFCAT[_cat]["tools"]
        for tool in _info["tools"]:
            if tool not in existing_tools:
                existing_tools.append(tool)


def get_category_for_method(method: str) -> str:
    """Get the category that contains the specified method."""
    for category, info in TOOLS_CATEGORIES.items():
        if method in info["tools"]:
            return category
    raise ValueError(f"Method '{method}' not found in any category")


def get_vendor(category: str, method: str = None) -> str:
    """Get the configured vendor for a data category or specific tool method.
    Tool-level configuration takes precedence over category-level.
    """
    config = get_config()

    # Check tool-level configuration first (if method provided)
    if method:
        tool_vendors = config.get("tool_vendors", {})
        if method in tool_vendors:
            return tool_vendors[method]

    # Fall back to category-level configuration
    return config.get("data_vendors", {}).get(category, "default")


def route_to_vendor(method: str, *args, **kwargs):
    """Route method calls to appropriate vendor implementation with fallback support."""
    category = get_category_for_method(method)
    vendor_config = get_vendor(category, method)
    primary_vendors = [v.strip() for v in vendor_config.split(",")]

    if method not in VENDOR_METHODS:
        raise ValueError(f"Method '{method}' not supported")

    # Build fallback chain: primary vendors first, then remaining available vendors
    all_available_vendors = list(VENDOR_METHODS[method].keys())
    fallback_vendors = primary_vendors.copy()
    for vendor in all_available_vendors:
        if vendor not in fallback_vendors:
            fallback_vendors.append(vendor)

    last_no_data: NoMarketDataError | None = None
    first_error: Exception | None = None
    for vendor in fallback_vendors:
        if vendor not in VENDOR_METHODS[method]:
            continue

        vendor_impl = VENDOR_METHODS[method][vendor]
        impl_func = vendor_impl[0] if isinstance(vendor_impl, list) else vendor_impl

        try:
            return impl_func(*args, **kwargs)
        except AlphaVantageRateLimitError:
            continue  # Rate limits: try the next vendor
        except NoMarketDataError as e:
            last_no_data = e  # No data here; another vendor may have it
            continue
        except Exception as e:
            # A fallback vendor failing for an incidental reason (e.g. no API
            # key configured) must not crash the call when another vendor
            # already determined the symbol simply has no data. Remember the
            # first error so a genuine primary-vendor failure still surfaces.
            if first_error is None:
                first_error = e
            continue

    # If any vendor reported "no data", the symbol is genuinely unavailable.
    if last_no_data is not None:
        sym = last_no_data.symbol
        canonical = last_no_data.canonical
        resolved = "" if canonical == sym else f" (resolved to '{canonical}')"
        return (
            f"NO_DATA_AVAILABLE: No market data found for '{sym}'{resolved} from "
            f"any configured vendor. The symbol may be invalid, delisted, or not "
            f"covered by Yahoo Finance / Alpha Vantage. Do not estimate or "
            f"fabricate values — report that data is unavailable for this symbol."
        )

    # No vendor returned data and none reported clean "no data" — surface the
    # first real error (e.g. the primary vendor's network failure).
    if first_error is not None:
        raise first_error

    raise RuntimeError(f"No available vendor for '{method}'")
