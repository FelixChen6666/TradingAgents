"""FRED vendor implementation — US macroeconomic data.

FRED (Federal Reserve Economic Data) is operated by the Federal Reserve
Bank of St. Louis and provides 816,000+ economic time series completely
**free of charge**.

API key registration: https://fred.stlouisfed.org → My Account → API Keys.
Rate limit with key: 120 requests / minute.

Usage requires either the ``FRED_API_KEY`` environment variable or passing
the key via config.

Reference
---------
- API docs: https://fred.stlouisfed.org/docs/api/fred/
"""

from __future__ import annotations

import logging
import os

import requests

from .placeholders import no_data_found, not_configured, source_unavailable
from .rate_limiter import get_rate_limiter
from .registry import register_vendor

logger = logging.getLogger(__name__)

_rate_limiter = get_rate_limiter()
_rate_limiter.configure("fred", max_calls=30, period=60.0)

_FRED_BASE = "https://api.stlouisfed.org/fred"

# Common macro series pre-defined for quick access.
WELL_KNOWN_SERIES: dict[str, str] = {
    "GDP": "Gross Domestic Product (nominal, quarterly)",
    "GDPC1": "Real Gross Domestic Product (quarterly)",
    "CPIAUCSL": "Consumer Price Index for All Urban Consumers (monthly)",
    "CPILFESL": "Core CPI (less food and energy, monthly)",
    "UNRATE": "Civilian Unemployment Rate (monthly)",
    "PAYEMS": "Nonfarm Payroll Employment (monthly)",
    "FEDFUNDS": "Federal Funds Effective Rate (daily)",
    "DGS10": "10-Year Treasury Constant Maturity Rate (daily)",
    "DGS2": "2-Year Treasury Constant Maturity Rate (daily)",
    "T10Y2Y": "10-Year Treasury Constant Maturity Minus 2-Year (daily)",
    "T5YIE": "5-Year Breakeven Inflation Rate (daily)",
    "M2SL": "M2 Money Supply (monthly)",
    "INDPRO": "Industrial Production Index (monthly)",
    "SP500": "S&P 500 (daily, FRED series)",
}


def _get_api_key(config: dict) -> str:
    """Read the FRED API key from config or environment."""
    key = config.get("api_keys", {}).get("fred", "") or os.environ.get(
        "FRED_API_KEY", ""
    )
    return key.strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_fred_data(series_id: str, start_date: str = "") -> str:
    """Fetch a FRED time series by *series_id*.

    Args:
        series_id: FRED series ID (e.g. ``"GDP"``, ``"UNRATE"``).
        start_date: Optional start date in ``YYYY-MM-DD`` format.

    Returns:
        Formatted text of date-value pairs, or a placeholder string.
    """
    from .config import get_config

    config = get_config()
    api_key = _get_api_key(config)
    if not api_key:
        return not_configured("fred", "FRED_API_KEY")

    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 5000,
    }
    if start_date:
        params["observation_start"] = start_date

    _rate_limiter.wait_if_needed("fred")
    try:
        resp = requests.get(
            f"{_FRED_BASE}/series/observations",
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        logger.debug("FRED request failed for %s: %s", series_id, exc)
        return source_unavailable("fred", str(exc))

    obs = data.get("observations", [])
    if not obs:
        return no_data_found("fred", series_id, "observations")

    name = WELL_KNOWN_SERIES.get(series_id, series_id)
    lines = [f"# FRED data — {name} ({series_id})", f"# Total observations: {len(obs)}", ""]
    for o in obs:
        val = o.get("value", "")
        date = o.get("date", "")
        if val and val != ".":
            lines.append(f"{date}: {val}")

    return "\n".join(lines)


def get_economic_indicators() -> str:
    """Return a summary report of key US macroeconomic indicators.

    Fetches GDP, CPI, unemployment rate, Fed funds rate, and the
    10Y-2Y yield spread.
    """
    lines = ["# US Macroeconomic Indicators Summary (FRED)", ""]
    for series_id in ("GDP", "CPIAUCSL", "UNRATE", "FEDFUNDS", "T10Y2Y", "M2SL"):
        result = get_fred_data(series_id)
        lines.append(f"--- {WELL_KNOWN_SERIES.get(series_id, series_id)} ---")
        lines.append(result)
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

register_vendor(
    "get_economic_indicators", "fred", get_economic_indicators,
    category="macroeconomic_data",
    category_description="US macroeconomic indicators from FRED",
)
register_vendor(
    "get_fred_data", "fred", get_fred_data,
)
