"""
cli.py
======
Command-line entry point for running a full club analysis: pipeline
collection -> matrix scoring -> reporting.

Usage
-----
    python -m src.cli analyze --club-id c_399 --mock --output reports/c_399_report.md
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from src.league_pipeline import LeaguePipeline
from src.pipeline import EFLDataPipeline
from src.reporter import ClubReporter
from src.scoring.matrix_engine import MatrixEngine


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="club-assessor",
        description="Sports Club Assessor CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze_parser = subparsers.add_parser(
        "analyze", help="Run a full club analysis and produce a report."
    )
    analyze_parser.add_argument(
        "--club-id", required=True, help="Club identifier to analyze (e.g. c_399)."
    )
    analyze_parser.add_argument(
        "--mock",
        dest="mock",
        action="store_true",
        default=True,
        help="Use local mock fixtures instead of live network requests (default: True).",
    )
    analyze_parser.add_argument(
        "--no-mock",
        dest="mock",
        action="store_false",
        help="Disable mock fixtures and use live network collectors.",
    )
    analyze_parser.add_argument(
        "--output",
        default=None,
        help="Optional path (file or directory) to export a Markdown report to.",
    )

    league_parser = subparsers.add_parser(
        "analyze-league",
        help="Run a full league analysis and print league table rankings.",
    )
    league_parser.add_argument(
        "--league", required=True, help="League identifier (e.g. championship)."
    )
    league_parser.add_argument(
        "--season", required=True, help="Season identifier (e.g. 2026-2027)."
    )
    league_parser.add_argument(
        "--mock",
        dest="mock",
        action="store_true",
        default=True,
        help="Use local mock fixtures instead of live network requests (default: True).",
    )
    league_parser.add_argument(
        "--no-mock",
        dest="mock",
        action="store_false",
        help="Disable mock fixtures and use live network collectors (Transfermarkt).",
    )
    league_parser.add_argument(
        "--force-refresh",
        dest="use_cache",
        action="store_false",
        default=True,
        help="Bypass the cache and re-fetch league standings and club data from Transfermarkt.",
    )

    return parser


def run_analyze(club_id: str, use_mock: bool, output: Optional[str]) -> int:
    pipeline = EFLDataPipeline(use_mock=use_mock)
    report = pipeline.run_club_pipeline(club_id)

    engine = MatrixEngine()
    ranking = engine.evaluate_club(report)

    reporter = ClubReporter()
    reporter.print_terminal_summary(ranking)

    if output:
        file_path = reporter.export_markdown_report(ranking, output)
        print(f"\nMarkdown report written to: {file_path}")

    return 0


def run_analyze_league(league: str, season: str, use_cache: bool, use_mock: bool) -> int:
    pipeline = LeaguePipeline(use_mock=use_mock)
    league_report = pipeline.run_league(league, season, use_cache=use_cache)

    print(f"League Table: {league} {season}\n")
    header = f"{'Rank':<6}{'Club':<28}{'Score':<10}{'Percentile':<12}"
    print(header)
    print("-" * len(header))
    for standing in league_report.standings:
        print(
            f"{standing.league_rank:<6}"
            f"{standing.club_name:<28}"
            f"{standing.overall_score:<10.2f}"
            f"{standing.percentile:<12.2f}"
        )

    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "analyze":
        return run_analyze(args.club_id, args.mock, args.output)

    if args.command == "analyze-league":
        return run_analyze_league(args.league, args.season, args.use_cache, args.mock)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
