"""Vendor registration system for extensible data source routing.

Vendor modules self-register by calling ``register_vendor()`` at import
time so that adding a new data source does not require editing
``interface.py``.

Usage::

    # In tradingagents/dataflows/akshare_stock.py
    from tradingagents.dataflows.registry import register_vendor

    def get_stock_data_akshare(symbol, start_date, end_date):
        ...

    register_vendor("get_stock_data", "akshare", get_stock_data_akshare)
"""

from __future__ import annotations

from typing import Any, Callable

# Re-exported so interface.py imports from here instead of defining inline.
VENDOR_METHODS: dict[str, dict[str, Callable[..., Any]]] = {}
TOOLS_CATEGORIES: dict[str, dict[str, Any]] = {}
VENDOR_LIST: list[str] = []


def register_vendor(
    method: str,
    vendor_name: str,
    func: Callable[..., Any],
    *,
    category: str | None = None,
    category_description: str | None = None,
) -> None:
    """Register a vendor implementation for a data method.

    Args:
        method: Method name (e.g. ``"get_stock_data"``).
        vendor_name: Short vendor identifier (e.g. ``"akshare"``, ``"fred"``).
        func: The implementation function.
        category: If this is a new method, optionally associate it with a
            category for config routing.
        category_description: Human-readable description for the category.
    """
    if method not in VENDOR_METHODS:
        VENDOR_METHODS[method] = {}
        if category:
            tools_list = TOOLS_CATEGORIES.setdefault(
                category,
                {"description": category_description or "", "tools": []},
            )
            if method not in tools_list["tools"]:
                tools_list["tools"].append(method)

    VENDOR_METHODS[method][vendor_name] = func

    if vendor_name not in VENDOR_LIST:
        VENDOR_LIST.append(vendor_name)


def unregister_vendor(method: str, vendor_name: str) -> None:
    """Remove a vendor from a method. Used in tests."""
    if method in VENDOR_METHODS and vendor_name in VENDOR_METHODS[method]:
        del VENDOR_METHODS[method][vendor_name]


def registered_vendors(method: str) -> list[str]:
    """Return all vendor names registered for a given method."""
    return list(VENDOR_METHODS.get(method, {}).keys())
