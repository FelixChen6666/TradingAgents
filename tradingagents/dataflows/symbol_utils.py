"""Symbol normalization and market-data error types for vendor calls.

Yahoo Finance (the default vendor) uses specific ticker conventions that
differ from the broker / TradingView / MT5 style symbols users often type:

    user types        Yahoo wants       why
    ---------------   ---------------   -----------------------------------
    XAUUSD, XAUUSD+   GC=F              gold has no forex pair on Yahoo;
                                        it is quoted as a COMEX future
    EURUSD            EURUSD=X          spot forex pairs take a ``=X`` suffix
    BTCUSD            BTC-USD           crypto pairs use a ``-`` separator
    SPX500, US500     ^GSPC             index CFDs map to Yahoo index symbols

Passing the raw broker symbol to Yahoo returns an empty result, which the
agents previously received as free text and could hallucinate a price
around (see issue #781). Centralizing the mapping here means every yfinance
entry point resolves symbols the same way, and new instruments are added by
appending a table row rather than editing call sites.
"""

from __future__ import annotations

import logging
import re
from typing import Literal

__all__ = [
    # Errors
    "NoMarketDataError",
    "SymbolFormatError",
    # Type aliases
    "MarketName",
    "AkshareMarket",
    # Normalisation primitives
    "normalize_symbol",
    "is_yahoo_safe",
    # Market detection
    "detect_market",
    "is_a_share",
    "is_shanghai_a_share",
    "is_shenzhen_a_share",
    "get_akshare_market",
    # Suffix / prefix handling
    "strip_exchange_suffix",
    "strip_prefix_market",
    "get_pure_code",
    "to_a_share_code",
    # Vendor-specific formatters
    "get_eastmoney_secid",
    "get_sina_prefix",
]

logger = logging.getLogger(__name__)

# Vendor routing return values (typed to catch typos at static-analysis time).
MarketName = Literal["a_share", "hk", "us", "crypto", "forex", "index", "commodity", "unknown"]
AkshareMarket = Literal["a_share", "hk", "unsupported"]


class NoMarketDataError(Exception):
    """Raised when a vendor returns no rows/records for a symbol.

    Carries both the symbol the user requested and the canonical symbol the
    vendor was actually queried with, so callers can build a clear message
    instead of emitting a vendor-specific empty string into the data channel.
    """

    def __init__(self, symbol: str, canonical: str | None = None, detail: str = ""):
        self.symbol = symbol
        self.canonical = canonical or symbol
        self.detail = detail
        msg = f"No market data for {symbol!r}"
        if canonical and canonical != symbol:
            msg += f" (queried as {canonical!r})"
        if detail:
            msg += f": {detail}"
        super().__init__(msg)


class SymbolFormatError(ValueError):
    """Raised when a symbol cannot be converted to a vendor format.

    Carries the original user input plus an optional vendor tag so that
    CLI layers can show a single, friendly message ("please enter a
    6-digit A-share code") instead of a raw stack trace.

    Attributes:
        symbol: The original input that failed validation.
        vendor: Optional vendor name (e.g. ``"eastmoney"``, ``"sina"``)
            for richer error messages.
    """

    def __init__(self, symbol, vendor: str | None = None, detail: str = ""):
        self.symbol = symbol
        self.vendor = vendor
        prefix = f"[{vendor}] " if vendor else ""
        msg = f"{prefix}invalid symbol {symbol!r}"
        if detail:
            msg += f" ({detail})"
        super().__init__(msg)


# ISO-4217 codes common enough to appear in retail forex pairs. A bare
# six-letter symbol whose halves are BOTH in this set is treated as a spot
# forex pair and given Yahoo's ``=X`` suffix.
_FOREX_CURRENCIES = frozenset(
    {
        "USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD",
        "CNY", "CNH", "HKD", "SGD", "SEK", "NOK", "DKK", "PLN",
        "MXN", "ZAR", "TRY", "INR", "KRW", "BRL", "RUB", "THB",
    }
)

# Crypto bases that brokers quote against USD without a separator.
_CRYPTO_BASES = frozenset(
    {"BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "LTC", "BCH", "DOT", "AVAX", "LINK"}
)

# Explicit aliases for instruments whose broker symbol does not map to a
# Yahoo symbol by rule. Metals/energy resolve to their front-month future;
# index CFD names resolve to the underlying Yahoo index symbol. Extend by
# adding rows — no call site changes required.
_ALIASES = {
    # Precious metals (spot names -> COMEX/NYMEX futures)
    "XAUUSD": "GC=F", "XAU": "GC=F", "GOLD": "GC=F",
    "XAGUSD": "SI=F", "XAG": "SI=F", "SILVER": "SI=F",
    "XPTUSD": "PL=F", "XPDUSD": "PA=F",
    # Energy
    "WTICOUSD": "CL=F", "USOIL": "CL=F", "WTI": "CL=F",
    "BCOUSD": "BZ=F", "UKOIL": "BZ=F", "BRENT": "BZ=F",
    "NATGAS": "NG=F", "XNGUSD": "NG=F",
    "COPPER": "HG=F", "XCUUSD": "HG=F",
    # Index CFDs -> Yahoo index symbols
    "SPX500": "^GSPC", "US500": "^GSPC", "SPX": "^GSPC",
    "NAS100": "^NDX", "US100": "^NDX", "USTEC": "^NDX",
    "US30": "^DJI", "DJI30": "^DJI", "WS30": "^DJI",
    "GER40": "^GDAXI", "GER30": "^GDAXI", "DE40": "^GDAXI",
    "UK100": "^FTSE", "JP225": "^N225", "JPN225": "^N225",
    "FRA40": "^FCHI", "EU50": "^STOXX50E", "HK50": "^HSI",
}

# Yahoo symbols may contain letters, digits, and these structural characters.
_YAHOO_SAFE = re.compile(r"^[A-Za-z0-9._\-\^=]+$")


def normalize_symbol(raw: str) -> str:
    """Map a user/broker symbol to its canonical Yahoo Finance symbol.

    Resolution order (first match wins):
      1. Explicit alias table (metals, energy, index CFDs).
      2. Crypto rule: ``<BASE>USD`` where BASE is a known crypto -> ``BASE-USD``.
      3. Forex rule: six letters that are two ISO currency codes -> ``PAIR=X``.
      4. Otherwise the upper-cased symbol is returned unchanged (plain
         equities, ETFs, Yahoo-native symbols like ``GC=F`` or ``^GSPC``).

    A trailing ``+`` (broker CFD marker, e.g. ``XAUUSD+``) is stripped before
    matching. The function is purely syntactic — it performs no network
    calls — so it is safe to apply on every request.
    """
    if not isinstance(raw, str) or not raw.strip():
        return raw

    s = raw.strip().upper()
    # Broker CFD/qualifier suffixes Yahoo never uses.
    s = s.rstrip("+")

    if s in _ALIASES:
        canonical = _ALIASES[s]
    elif len(s) == 6 and s[:3] in _CRYPTO_BASES and s[3:] == "USD":
        canonical = f"{s[:3]}-USD"
    elif s[:-3] in _CRYPTO_BASES and s.endswith("USD") and "-" not in s:
        canonical = f"{s[:-3]}-USD"
    elif len(s) == 6 and s[:3] in _FOREX_CURRENCIES and s[3:] in _FOREX_CURRENCIES:
        canonical = f"{s}=X"
    else:
        canonical = s

    if canonical != raw.strip().upper():
        logger.info("Resolved symbol %r to Yahoo symbol %r", raw, canonical)
    return canonical


def is_yahoo_safe(symbol: str) -> bool:
    """True when ``symbol`` only contains characters Yahoo symbols use."""
    return bool(symbol) and _YAHOO_SAFE.fullmatch(symbol) is not None


# ---------------------------------------------------------------------------
# Market-detection helpers (multi-vendor awareness)
# ---------------------------------------------------------------------------

# A-share exchanges: Shanghai (6xx, 9xx), Shenzhen (0xx, 2xx, 3xx)
_SH_SE_CODES = frozenset({"600", "601", "603", "605", "688", "689", "900"})
_SZ_SE_CODES = frozenset({"000", "001", "002", "003", "300", "301", "200"})


def detect_market(symbol: str) -> MarketName:
    """Detect the market for a symbol, independent of Yahoo conventions.

    Returns one of ``"a_share"``, ``"hk"``, ``"us"``, ``"crypto"``,
    ``"forex"``, ``"index"``, ``"commodity"``, or ``"unknown"``.
    """
    if not isinstance(symbol, str) or not symbol.strip():
        return "unknown"

    s = symbol.strip().upper()

    # Explicit exchange suffix tells the market directly.
    if s.endswith(".SS") or s.endswith(".SH"):
        return "a_share"
    if s.endswith(".SZ"):
        return "a_share"
    if s.endswith(".HK"):
        return "hk"

    # Check alias table first (it contains definitive mappings).
    if s in _ALIASES:
        alias = _ALIASES[s]
        if "=X" in alias:
            return "forex"
        if "-USD" in alias or "-BTC" in alias:
            return "crypto"
        if alias.startswith("^"):
            return "index"
        if alias.endswith("=F"):
            return "commodity"
        return "us"  # default alias target is US-listed

    # Crypto pattern: 6-letter <BASE>USD
    if len(s) == 6 and s[:3] in _CRYPTO_BASES and s[3:] == "USD":
        return "crypto"
    if len(s) > 3 and s[:-3] in _CRYPTO_BASES and s.endswith("USD"):
        return "crypto"

    # Forex pattern: 6-letter ISO currency pair
    if len(s) == 6 and s[:3] in _FOREX_CURRENCIES and s[3:] in _FOREX_CURRENCIES:
        return "forex"

    # A-share: numeric codes that match Shanghai / Shenzhen prefixes.
    if s.isdigit():
        prefix = s[:3]
        if prefix in _SH_SE_CODES:
            return "a_share"
        if prefix in _SZ_SE_CODES:
            return "a_share"

    # Hong Kong stocks: 5-digit numeric starting with 0 (ex. 00700).
    if s.isdigit() and len(s) == 5:
        return "hk"

    # Fallback — treat as US-listed equity.
    return "us"


def is_a_share(symbol: str) -> bool:
    """Shortcut — True if *symbol* is a China A-share."""
    return detect_market(symbol) == "a_share"


def strip_exchange_suffix(symbol: str) -> str:
    """Remove trailing exchange suffix (.SS, .SH, .SZ, .HK) from *symbol*."""
    s = symbol.strip().upper()
    for suffix in (".SS", ".SH", ".SZ", ".HK", ".L", ".T", ".TO", ".AX", ".BO", ".NS"):
        if s.endswith(suffix):
            return s[: -len(suffix)]
    return s


# ---------------------------------------------------------------------------
# Vendor-format conversion helpers (DRY: used by eastmoney, sina, akshare, ...)
# ---------------------------------------------------------------------------

# Vendor formatters all share the same validation pipeline:
#   1. normalise (strip prefix form + strip suffix form)
#   2. ensure 6-digit numeric A-share code
#   3. classify into Shanghai / Shenzhen via the canonical prefix tables
#      below (_SH_SE_CODES / _SZ_SE_CODES are the single source of truth
#      — extend them to add new A-share sub-markets like 北交所).
#   4. render the vendor-specific representation.
# _normalise_a_share() captures steps 1-3; the formatters only own step 4.


def _normalise_a_share(symbol: str, vendor: str | None = None) -> tuple[str, str]:
    """Normalise *symbol* and classify it as Shanghai / Shenzhen.

    Performs steps 1-3 of the vendor pipeline.  Returns a
    ``(code, market)`` tuple where ``code`` is a 6-digit string and
    ``market`` is ``"sh"`` / ``"sz"``.

    Raises:
        SymbolFormatError: When *symbol* is not a recognised A-share code.
    """
    code = strip_exchange_suffix(strip_prefix_market(symbol))
    if not code.isdigit() or len(code) != 6:
        raise SymbolFormatError(
            symbol, vendor=vendor,
            detail=f"expected 6 digits, got {code!r}",
        )
    market = _classify_a_share_market(code)
    if market is None:
        raise SymbolFormatError(
            symbol, vendor=vendor,
            detail=f"code {code!r} does not match any known A-share exchange prefix",
        )
    return code, market


def _classify_a_share_market(code: str) -> str | None:
    """Return ``"sh"`` / ``"sz"`` for a 6-digit A-share code, else ``None``.

    Validates against the canonical Shanghai/Shenzhen prefix tables so
    that numbers like ``666666`` (not a real exchange code) are rejected
    rather than silently misclassified.

    Args:
        code: A 6-digit numeric string (output of :func:`get_pure_code`).

    Returns:
        ``"sh"``, ``"sz"``, or ``None`` if the code is not a recognised
        A-share prefix.
    """
    if not code.isdigit() or len(code) != 6:
        return None
    if code[:3] in _SH_SE_CODES:
        return "sh"
    if code[:3] in _SZ_SE_CODES:
        return "sz"
    return None


def get_pure_code(symbol: str) -> str:
    """Strip exchange suffix and return the pure uppercase code.

    Thin wrapper around :func:`strip_exchange_suffix` for use by vendor
    modules that want a single canonical helper.  Accepts inputs like
    ``"600519"``, ``"600519.SH"``, ``"sh600519"`` (prefix form is *not*
    handled here — see :func:`strip_prefix_market` for that).

    Returns:
        The upper-cased, suffix-stripped code.
    """
    return strip_exchange_suffix(symbol).upper()


def is_shanghai_a_share(symbol: str) -> bool:
    """True if *symbol* is a Shanghai-listed A-share (incl. 科创板 / B股)."""
    return _classify_a_share_market(get_pure_code(symbol)) == "sh"


def is_shenzhen_a_share(symbol: str) -> bool:
    """True if *symbol* is a Shenzhen-listed A-share (incl. 创业板 / B股)."""
    return _classify_a_share_market(get_pure_code(symbol)) == "sz"


def get_eastmoney_secid(symbol: str) -> str:
    """Convert a stock symbol to East Money's ``secid`` format.

    East Money expects ``1.<code>`` for Shanghai-listed securities and
    ``0.<code>`` for Shenzhen-listed ones, where the first digit encodes
    the exchange (1 = Shanghai, 0 = Shenzhen).

    Args:
        symbol: A-share code in any common form — pure digits
            (``"600519"``), Yahoo suffix (``"600519.SH"``) or Chinese
            retail prefix (``"SH600519"``).

    Returns:
        The secid string (e.g. ``"1.600519"`` or ``"0.000001"``).

    Raises:
        SymbolFormatError: When *symbol* is not a 6-digit A-share code.
            The exception's ``vendor`` attribute is ``"eastmoney"``.
    """
    code, market = _normalise_a_share(symbol, vendor="eastmoney")
    return f"1.{code}" if market == "sh" else f"0.{code}"


def get_sina_prefix(symbol: str) -> str:
    """Return Sina Finance's exchange prefix for *symbol*.

    Sina uses ``sh`` for Shanghai and ``sz`` for Shenzhen (e.g. URLs of
    the form ``finance.sina.com.cn/realstock/company/sh600519/nc.shtml``).

    Args:
        symbol: A-share code in any common form (see
            :func:`get_eastmoney_secid` for accepted inputs).

    Returns:
        The exchange prefix (``"sh"`` or ``"sz"``).

    Raises:
        SymbolFormatError: When *symbol* is not a 6-digit A-share code.
            The exception's ``vendor`` attribute is ``"sina"``.
    """
    _code, market = _normalise_a_share(symbol, vendor="sina")
    return market


def get_akshare_market(symbol: str) -> AkshareMarket:
    """Determine the AKShare market flavour for *symbol*.

    AKShare routes A-share and HK stock queries to different APIs, so
    callers need a quick classifier.  This helper also accepts
    HK-style inputs (5-digit code or ``.HK`` suffix) that the broader
    :func:`detect_market` supports.

    Args:
        symbol: Stock code, with or without an exchange suffix.

    Returns:
        One of ``"a_share"``, ``"hk"``, or ``"unsupported"``.
    """
    s = (symbol or "").strip().upper()
    if not s:
        return "unsupported"

    # Hong Kong: 5-digit numeric or .HK suffix.
    if s.endswith(".HK") or (s.isdigit() and len(s) == 5):
        return "hk"

    if is_a_share(symbol):
        return "a_share"

    return "unsupported"


def strip_prefix_market(symbol: str) -> str:
    """Strip a leading exchange prefix (``SH``/``SZ``/``BJ``/``SS``) from *symbol*.

    Chinese retail-trader inputs sometimes use prefix form
    (``SH600519``) rather than suffix form (``600519.SH``).  This helper
    handles the prefix form; combine with :func:`strip_exchange_suffix`
    to accept both.

    Args:
        symbol: Stock code, possibly with a leading exchange prefix.

    Returns:
        The code with any leading ``SH``/``SZ``/``BJ``/``SS`` removed
        (uppercased).  Returns *symbol* unchanged if no prefix matches.
    """
    s = symbol.strip().upper()
    for prefix in ("SH", "SZ", "BJ", "SS"):
        if (
            s.startswith(prefix)
            and len(s) > len(prefix)
            and s[len(prefix)].isdigit()
        ):
            return s[len(prefix):]
    return s


def to_a_share_code(symbol: str) -> str:
    """Return a normalised 6-digit A-share code from any input form.

    Accepts inputs in either prefix form (``SH600519``) or suffix form
    (``600519.SH``), with or without leading/trailing whitespace, and
    returns the bare 6-digit code (``600519``).  Falls through to
    :func:`strip_exchange_suffix` if no prefix matches.

    This is the canonical "give me the code" helper — vendor modules
    that need a 6-digit code should call this rather than chaining
    :func:`strip_prefix_market` and :func:`strip_exchange_suffix`
    manually.
    """
    return strip_exchange_suffix(strip_prefix_market(symbol))
