"""
reporter.py
===========
Formatting layer for ``FinalClubRanking`` output: a rich terminal summary
and a Markdown export, both intended for end-user consumption.

Spec reference: docs/DATA_SCHEMA_SPEC.md (FinalClubRanking)
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from rich.console import Console
from rich.table import Table

from src.schemas import FinalClubRanking

_DEFAULT_REPORTS_DIR = "reports"


class ClubReporter:
    """Renders a ``FinalClubRanking`` as a terminal summary or Markdown report."""

    def __init__(self, console: Console | None = None) -> None:
        self._console = console or Console()

    def print_terminal_summary(self, ranking: FinalClubRanking) -> None:
        """Print a formatted summary table of *ranking* to the terminal."""
        self._console.print(
            f"\n[bold]Club Analysis Summary[/bold] — [cyan]{ranking.club_id}[/cyan]"
        )
        self._console.print(f"Overall Score: [bold green]{ranking.overall_score:.2f}[/bold green] / 100\n")

        table = Table(title="Category Breakdown")
        table.add_column("Category", style="bold")
        table.add_column("Raw Score", justify="right")
        table.add_column("Weighted Contribution", justify="right")

        for category in sorted(ranking.breakdown):
            raw = ranking.breakdown[category]
            weighted = ranking.weighted_components.get(category, 0.0)
            table.add_row(category.title(), f"{raw:.2f}", f"{weighted:.2f}")

        self._console.print(table)

    def export_markdown_report(self, ranking: FinalClubRanking, output_path: str = _DEFAULT_REPORTS_DIR) -> str:
        """
        Write a structured Markdown report for *ranking* to *output_path*.

        If *output_path* is a directory (or the default), the report is
        written to ``<output_path>/<club_id>_report.md``. Returns the final
        file path written.
        """
        if output_path.endswith(".md"):
            file_path = output_path
        else:
            file_path = os.path.join(output_path, f"{ranking.club_id}_report.md")

        parent_dir = os.path.dirname(file_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        lines = [
            f"# Club Analysis Report — {ranking.club_id}",
            "",
            f"_Generated {generated_at}_",
            "",
            f"**Overall Score:** {ranking.overall_score:.2f} / 100",
            "",
            "## Category Breakdown",
            "",
            "| Category | Raw Score | Weighted Contribution |",
            "|---|---|---|",
        ]
        for category in sorted(ranking.breakdown):
            raw = ranking.breakdown[category]
            weighted = ranking.weighted_components.get(category, 0.0)
            lines.append(f"| {category.title()} | {raw:.2f} | {weighted:.2f} |")
        lines.append("")

        with open(file_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return file_path
