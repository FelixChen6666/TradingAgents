"""Rich-formatted display and disk-saving for the comparison report."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.layout import Layout
from rich.markdown import Markdown

from tradingagents.agents.schemas import (
    ComparisonReport,
    IndividualStockRanking,
    LeaderPerception,
    ThemeTag,
    render_comparison_report,
)

console = Console()


def display_comparison_report(report: ComparisonReport) -> None:
    """Display the comparison report in the terminal using Rich formatting."""
    # Header
    console.print()
    console.print(Panel(
        f"[bold yellow]Multi-Stock Comparison Report[/bold yellow]\n"
        f"Analysis Date: {report.analysis_date} | "
        f"Stocks: {report.total_stocks} | "
        f"Generated: {report.generated_at}",
        border_style="yellow",
    ))
    console.print()

    # Ranking Table
    _display_ranking_table(report.ranked_stocks)

    # Market Context
    console.print()
    console.print(Panel(
        Markdown(report.market_context),
        title="[bold]Market Context[/bold]",
        border_style="blue",
    ))

    # Key Themes
    if report.key_themes:
        console.print()
        theme_text = "\n".join(f"  {i}. [bold]{theme}[/bold]" for i, theme in enumerate(report.key_themes, 1))
        console.print(Panel(
            theme_text,
            title="[bold magenta]Key Themes[/bold magenta]",
            border_style="magenta",
        ))

    # Detailed per-stock analysis
    console.print()
    console.print("[bold underline]Detailed Stock Analysis[/bold underline]")
    console.print()
    for i, stock in enumerate(report.ranked_stocks, 1):
        _display_stock_detail(i, stock)


def _display_ranking_table(stocks: list[IndividualStockRanking]) -> None:
    """Display the main ranking table."""
    table = Table(
        title="[bold]Ranking & Buy Recommendation[/bold]",
        box=box.ROUNDED,
        header_style="bold cyan",
        show_lines=True,
    )
    table.add_column("Rank", justify="center", width=5)
    table.add_column("Ticker", width=10)
    table.add_column("Company", width=20, overflow="fold")
    table.add_column("Short-Term\nScore", justify="center", width=10)
    table.add_column("PM\nRating", justify="center", width=10)
    table.add_column("Top Themes", width=25, overflow="fold")
    table.add_column("Leader", justify="center", width=7)

    for i, stock in enumerate(stocks, 1):
        top_theme = stock.themes[0].theme_name if stock.themes else "-"
        leader_str = "[green]✓[/green]" if stock.leader_perception.is_leader else "[red]✗[/red]"

        # Color code the score
        score = stock.short_term_score
        if score >= 75:
            score_str = f"[green]{score:.1f}[/green]"
        elif score >= 55:
            score_str = f"[yellow]{score:.1f}[/yellow]"
        else:
            score_str = f"[red]{score:.1f}[/red]"

        # Color code PM rating
        pm = stock.pm_rating
        if pm in ("Buy",):
            pm_str = f"[green]{pm}[/green]"
        elif pm in ("Overweight",):
            pm_str = f"[yellow]{pm}[/yellow]"
        elif pm in ("Underweight", "Sell"):
            pm_str = f"[red]{pm}[/red]"
        else:
            pm_str = pm

        table.add_row(
            str(i),
            stock.ticker,
            stock.company_name[:18],
            score_str,
            pm_str,
            top_theme,
            leader_str,
        )

    console.print(table)


def _display_stock_detail(rank: int, stock: IndividualStockRanking) -> None:
    """Display detailed analysis for a single stock."""
    # Stock header
    header = f"[bold yellow]#{rank} {stock.ticker} — {stock.company_name}[/bold yellow]"
    console.print(Panel(header, border_style="yellow"))
    console.print(f"  [bold]Short-Term Score:[/bold] {stock.short_term_score:.1f}/100")
    console.print(f"  [bold]PM Rating:[/bold] {stock.pm_rating}")
    console.print()

    # Themes
    if stock.themes:
        console.print("  [bold cyan]Themes:[/bold cyan]")
        for theme in stock.themes:
            bar = "█" * int(theme.relevance * 20) + "░" * (20 - int(theme.relevance * 20))
            console.print(f"    {theme.theme_name} [{bar}] {theme.relevance:.0%}")
            console.print(f"      Evidence: {theme.evidence}")
        console.print()

    # Leader perception
    leader = stock.leader_perception
    leader_icon = "✓" if leader.is_leader else "✗"
    confidence_color = {"高": "green", "中": "yellow", "低": "red"}.get(leader.confidence, "white")
    console.print(f"  [bold magenta]Leader Stock:[/bold magenta] {leader_icon}  ")
    console.print(f"  [bold]Sector:[/bold] {leader.sector}")
    console.print(f"  [bold]Confidence:[/bold] [{confidence_color}]{leader.confidence}[/{confidence_color}]")
    console.print(f"  [bold]Reasoning:[/bold] {leader.reasoning}")
    console.print()

    # Report summary
    if stock.report_summary:
        console.print(f"  [bold]Analysis Summary:[/bold]")
        console.print(Panel(
            stock.report_summary[:500],
            border_style="dim",
            padding=(0, 1),
        ))
    console.print()


def save_comparison_report(
    report: ComparisonReport,
    output_dir: str | Path,
    per_stock_results: dict | None = None,
) -> Path:
    """Save the comparison report to disk.

    Creates a directory structure::

        results_dir/comparison/{analysis_date}_{timestamp}/
            comparison_report.md      # Full rendered report
            ranked_list.csv           # Machine-readable ranking
            individual/
                {ticker}.md           # Per-stock details
                {ticker}_factors.json

    Args:
        report: The ComparisonReport to save.
        output_dir: Base output directory (typically config["results_dir"]).
        per_stock_results: Optional dict of ticker -> state & factors for
            saving individual reports.

    Returns:
        Path to the created report directory.
    """
    # Use the analysis date for the directory, consistent with the per-stock
    # save convention (config["results_dir"] / comparison / {date} /).
    analysis_date = report.analysis_date or datetime.now().strftime("%Y-%m-%d")
    timestamp = datetime.now().strftime("%H%M%S")
    report_dir = Path(output_dir) / "comparison" / f"{analysis_date}_{timestamp}"
    report_dir.mkdir(parents=True, exist_ok=True)

    # 1. Full comparison report (markdown)
    md_content = render_comparison_report(report)
    (report_dir / "comparison_report.md").write_text(md_content, encoding="utf-8")

    # 2. Machine-readable CSV ranking
    csv_lines = ["rank,ticker,company,short_term_score,pm_rating,themes,is_leader,confidence\n"]
    for i, stock in enumerate(report.ranked_stocks, 1):
        theme_str = ";".join(t.theme_name for t in stock.themes)
        csv_lines.append(
            f"{i},{stock.ticker},{stock.company_name},{stock.short_term_score:.1f},"
            f"{stock.pm_rating},{theme_str},{stock.leader_perception.is_leader},"
            f"{stock.leader_perception.confidence}\n"
        )
    (report_dir / "ranked_list.csv").write_text("".join(csv_lines), encoding="utf-8")

    # 3. Per-stock individual reports
    if per_stock_results:
        ind_dir = report_dir / "individual"
        ind_dir.mkdir(exist_ok=True)

        for ticker, data in per_stock_results.items():
            state = data.get("state", {}) if isinstance(data, dict) else data[0] if isinstance(data, (list, tuple)) else {}
            factors = data.get("factors") if isinstance(data, dict) else data[1] if isinstance(data, (list, tuple)) else None
            # Save full state text as markdown
            md_parts = [f"# {ticker} — Full Analysis\n"]
            for key in ("market_report", "sentiment_report", "news_report",
                        "fundamentals_report", "investment_plan",
                        "trader_investment_plan", "final_trade_decision"):
                if state.get(key):
                    section_title = key.replace("_", " ").title()
                    md_parts.extend([f"\n## {section_title}\n", state[key]])
            (ind_dir / f"{ticker}.md").write_text("\n".join(md_parts), encoding="utf-8")

            # Save factors as JSON
            if factors:
                safe_ticker = ticker.replace(".", "_").replace("-", "_")
                (ind_dir / f"{safe_ticker}_factors.json").write_text(
                    factors.model_dump_json(indent=2), encoding="utf-8",
                )

    console.print(f"\n[green]Report saved to: {report_dir}[/green]")
    return report_dir
