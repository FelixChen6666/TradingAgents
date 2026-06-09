"""Interactive selection flow for the multi-stock comparison feature."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import questionary
from rich.console import Console

from cli.models import AnalystType, AssetType
from cli.utils import (
    TICKER_INPUT_EXAMPLES,
    ANALYST_ORDER,
    filter_analysts_for_asset_type,
    detect_asset_type,
    select_analysts,
    select_research_depth,
    get_analysis_date,
    normalize_ticker_symbol,
)

console = Console()


def get_comparison_selections() -> dict[str, Any]:
    """Run the interactive selection flow for multi-stock comparison.

    Returns a dict with keys: tickers, analysis_date, analysts, language, ...etc.
    """
    selections: dict[str, Any] = {}

    # Step 1: Number of stocks
    num_stocks = _ask_num_stocks()
    selections["num_stocks"] = num_stocks

    # Step 2: Input tickers
    tickers = _ask_tickers(num_stocks)
    selections["tickers"] = tickers

    # Detect asset type from the first ticker (assume homogeneous)
    asset_type = detect_asset_type(tickers[0])
    selections["asset_type"] = asset_type

    # Step 3: Analysis date
    selections["analysis_date"] = get_analysis_date()

    # Step 4: Output language
    selections["language"] = _ask_language()

    # Step 5: Analyst selection
    analysts = select_analysts(asset_type)
    selections["analysts"] = analysts

    # Step 6: Data provider preset
    selections["data_preset"] = _ask_data_preset()

    # Step 7: Research depth
    selections["research_depth"] = select_research_depth()

    # Step 8: LLM provider and model
    selections["llm_provider"] = _ask_llm_provider()

    # Step 9: Parallelism
    selections["max_workers"] = _ask_parallelism()

    return selections


def _ask_num_stocks() -> int:
    """Ask how many stocks to compare (2-10)."""
    choice = questionary.text(
        "Number of stocks to compare (2-10):",
        default="3",
        validate=lambda x: (
            x.strip().isdigit() and 2 <= int(x.strip()) <= 10
        ) or "Please enter a number between 2 and 10.",
        style=questionary.Style([("text", "fg:green"), ("highlighted", "noinherit")]),
    ).ask()

    if not choice:
        console.print("\n[red]No selection. Exiting...[/red]")
        exit(1)

    return int(choice.strip())


def _ask_tickers(num: int) -> list[str]:
    """Ask for N stock tickers one by one."""
    tickers = []
    for i in range(num):
        ticker = questionary.text(
            f"Enter ticker symbol #{i + 1} (e.g. {TICKER_INPUT_EXAMPLES}):",
            validate=lambda x: (
                not x.strip()
                or (
                    all(ch.isalnum() or ch in "._-^" for ch in x.strip())
                    and len(x.strip()) <= 32
                )
                or "Please enter a valid ticker symbol."
            ),
            style=questionary.Style([("text", "fg:green"), ("highlighted", "noinherit")]),
        ).ask()

        if not ticker:
            console.print("\n[red]No ticker symbol provided. Exiting...[/red]")
            exit(1)

        tickers.append(normalize_ticker_symbol(ticker))

    return tickers


def _ask_language() -> str:
    """Ask for output language."""
    language = questionary.select(
        "Select Output Language:",
        choices=[
            "Chinese (中文)",
            "English",
            "Japanese (日本語)",
            "Korean (한국어)",
            questionary.Choice("Custom", value="custom"),
        ],
        default="Chinese (中文)",
        style=questionary.Style([("selected", "fg:yellow noinherit"), ("highlighted", "fg:yellow noinherit")]),
    ).ask()

    if language == "custom":
        language = questionary.text("Enter custom language instruction:").ask()

    return language or "Chinese (中文)"


def _ask_data_preset() -> str:
    """Ask for data provider preset."""
    preset = questionary.select(
        "Select Data Provider Preset:",
        choices=[
            questionary.Choice("China A-Shares (AKShare + East Money)", value="china"),
            questionary.Choice("Hong Kong Stocks (Yahoo + Sina)", value="hk"),
            questionary.Choice("Global/Diversified", value="global"),
            questionary.Choice("Custom Configuration", value="custom"),
        ],
        default="china",
        style=questionary.Style([("selected", "fg:yellow noinherit"), ("highlighted", "fg:yellow noinherit")]),
    ).ask()

    return preset or "china"


def _ask_llm_provider() -> str:
    """Ask for LLM provider."""
    provider = questionary.select(
        "Select LLM Provider:",
        choices=[
            "OpenAI",
            "Anthropic",
            "Google",
            "xAI",
            "DeepSeek",
            "Qwen",
            "GLM",
            questionary.Choice("Custom (OpenAI-compatible)", value="custom"),
        ],
        default="OpenAI",
        style=questionary.Style([("selected", "fg:yellow noinherit"), ("highlighted", "fg:yellow noinherit")]),
    ).ask()

    return provider or "OpenAI"


def _ask_parallelism() -> int:
    """Ask for maximum parallel workers."""
    choice = questionary.text(
        "Max parallel analyses (1-5, higher = faster but more API calls):",
        default="3",
        validate=lambda x: (
            x.strip().isdigit() and 1 <= int(x.strip()) <= 5
        ) or "Please enter a number between 1 and 5.",
        style=questionary.Style([("text", "fg:green"), ("highlighted", "noinherit")]),
    ).ask()

    if not choice:
        return 3

    return int(choice.strip())
