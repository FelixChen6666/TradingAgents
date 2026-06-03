"""Standardized placeholder patterns for data source responses.

Every vendor implementation returns a *string* — never raises.  When the
source has no data or is unreachable, the function returns a structured
placeholder so downstream consumers can distinguish "empty" from "broken"
from "not configured".
"""


def no_data_available(symbol: str, detail: str = "") -> str:
    """Symbol not found in any vendor."""
    msg = (
        f"NO_DATA_AVAILABLE: No data found for '{symbol}' from "
        f"any configured vendor."
    )
    if detail:
        msg += f" {detail}"
    return msg


def source_unavailable(source: str, reason: str) -> str:
    """Source reachable but returned an error / is rate-limited."""
    return f"<{source} unavailable: {reason}>"


def no_data_found(source: str, symbol: str, data_type: str = "data") -> str:
    """Source reachable but returned no rows for the requested symbol."""
    return f"<no {data_type} found from {source} for {symbol}>"


def not_configured(source: str, env_var: str) -> str:
    """Source requires an env var that is not set."""
    return (
        f"<{source} not configured: {env_var} environment variable is not set. "
        f"Data from this source is unavailable.>"
    )


def invalid_symbol(symbol: str, reason: str = "") -> str:
    """Symbol failed validation / normalisation."""
    base = f"<invalid symbol: {symbol}>"
    if reason:
        return f"{base} ({reason})"
    return base
