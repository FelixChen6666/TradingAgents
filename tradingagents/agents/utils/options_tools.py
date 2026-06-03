"""LangChain tool for options chain data.

Exposes the options chain vendor method as a callable tool that agents
can use to fetch calls/puts data for a ticker.
"""

from langchain_core.tools import tool

from tradingagents.dataflows.interface import route_to_vendor


@tool
def get_options_chain(symbol: str, expiration_date: str = "") -> str:
    """Fetch options chain data (calls and puts) for a stock or ETF.

    Returns a formatted table with strike prices, last prices, bid/ask,
    volume, open interest, and implied volatility for all available
    contracts at the given expiration.

    Args:
        symbol: Stock/ETF ticker (e.g. "AAPL", "SPY").
        expiration_date: Optional expiration date in YYYY-MM-DD format.
            If omitted, returns the nearest expiration chain.

    Returns:
        Formatted text with Calls and Puts tables.
    """
    return route_to_vendor("get_options_chain", symbol, expiration_date)
