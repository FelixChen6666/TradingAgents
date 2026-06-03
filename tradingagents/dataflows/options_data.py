"""Options chain data — wrapper around yfinance option chains.

yfinance provides free options data for US-listed equities and ETFs
(via Yahoo Finance).  No API key is required.

Usage requires ``yfinance`` (already installed as a core dependency).
"""

from __future__ import annotations

import logging

import yfinance as yf

from .registry import register_vendor
from .stockstats_utils import yf_retry
from .symbol_utils import normalize_symbol

logger = logging.getLogger(__name__)


def _format_chain(calls, puts, symbol: str, expiration: str) -> str:
    """Format options chain data as readable text."""
    lines = [
        f"# Options Chain for {symbol}, expiration: {expiration}",
        "",
    ]

    # Calls
    lines.append("## Calls")
    if calls is not None and not calls.empty:
        cols = [c for c in ["strike", "lastPrice", "bid", "ask",
                            "volume", "openInterest", "impliedVolatility"]
                if c in calls.columns]
        lines.append(calls[cols].to_string(index=False))
    else:
        lines.append("(no calls available)")
    lines.append("")

    # Puts
    lines.append("## Puts")
    if puts is not None and not puts.empty:
        cols = [c for c in ["strike", "lastPrice", "bid", "ask",
                            "volume", "openInterest", "impliedVolatility"]
                if c in puts.columns]
        lines.append(puts[cols].to_string(index=False))
    else:
        lines.append("(no puts available)")
    lines.append("")

    return "\n".join(lines)


def get_options_chain(
    symbol: str,
    expiration_date: str = "",
) -> str:
    """Fetch options chain data for a ticker via yfinance.

    Args:
        symbol: Stock/ETF ticker.
        expiration_date: Expiration date in ``YYYY-MM-DD`` format.
            If omitted, returns the nearest expiration date chain.

    Returns:
        Formatted text with calls and puts tables.
    """
    canonical = normalize_symbol(symbol)

    try:
        ticker = yf.Ticker(canonical)
        exp_dates = yf_retry(lambda: ticker.options)
    except Exception as exc:
        logger.debug("Failed to get options expirations for %s: %s", symbol, exc)
        return f"<options data unavailable for {symbol}: {exc}>"

    if not exp_dates:
        return f"<no options available for {symbol}>"

    # Determine which expiration to use
    if expiration_date:
        if expiration_date not in exp_dates:
            available = ", ".join(exp_dates[:5])
            return (
                f"Expiration {expiration_date} not available for {canonical}. "
                f"Available dates: {available} ..."
            )
        target_exp = expiration_date
    else:
        target_exp = exp_dates[0]

    try:
        chain = yf_retry(lambda: ticker.option_chain(target_exp))
    except Exception as exc:
        logger.debug(
            "Failed to get options chain for %s %s: %s",
            symbol, target_exp, exc,
        )
        return f"<options chain unavailable for {symbol} ({target_exp}): {exc}>"

    return _format_chain(chain.calls, chain.puts, canonical, target_exp)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

register_vendor(
    "get_options_chain", "yfinance", get_options_chain,
    category="options_data",
    category_description="Options chain data (calls / puts)",
)
