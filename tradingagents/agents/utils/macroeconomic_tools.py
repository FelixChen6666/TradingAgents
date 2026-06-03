"""LangChain tools for macroeconomic data.

These tools wrap the FRED vendor and are exposed to agents that need
economic context (market analyst, research manager, portfolio manager).
"""

from langchain_core.tools import tool

from tradingagents.dataflows.interface import route_to_vendor


@tool
def get_economic_indicators() -> str:
    """Fetch key US macroeconomic indicators (GDP, CPI, unemployment,
    interest rates, yield curve spread, money supply).

    Returns a formatted summary with the latest available values for each
    indicator. Use this tool when you need to understand the current
    macroeconomic environment, inflation trends, or monetary policy stance.
    """
    return route_to_vendor("get_economic_indicators")


@tool
def get_fred_data(series_id: str, start_date: str = "") -> str:
    """Fetch a specific FRED (Federal Reserve Economic Data) time series.

    Args:
        series_id: The FRED series identifier. Common series:
            GDP / GDPC1 — Gross Domestic Product
            CPIAUCSL — Consumer Price Index
            UNRATE — Unemployment Rate
            FEDFUNDS — Federal Funds Rate
            DGS10 — 10-Year Treasury Yield
            DGS2 — 2-Year Treasury Yield
            T10Y2Y — 10Y-2Y Yield Spread
            M2SL — M2 Money Supply
            INDPRO — Industrial Production
        start_date: Optional start date (YYYY-MM-DD). If omitted, returns
            the most recent 5000 observations.

    Returns:
        A formatted text table of date-value pairs.
    """
    return route_to_vendor("get_fred_data", series_id, start_date)
