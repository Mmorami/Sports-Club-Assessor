"""
test_e2e_cli.py
================
End-to-end integration test: CLI invocation -> pipeline -> matrix engine ->
report generation, entirely against local mock fixtures (no network I/O).
"""

from __future__ import annotations

import os

import pytest

from src.cli import main

CLUB_ID = "c_399"  # Leeds United, per data/mock/manager_club_mock.json


def test_analyze_prints_summary_and_exports_markdown(tmp_path, capsys):
    output_path = tmp_path / "reports" / f"{CLUB_ID}_report.md"

    exit_code = main(
        [
            "analyze",
            "--club-id",
            CLUB_ID,
            "--mock",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0

    captured = capsys.readouterr()
    assert "Club Analysis Summary" in captured.out
    assert CLUB_ID in captured.out
    assert "Overall Score" in captured.out

    assert output_path.exists()
    content = output_path.read_text(encoding="utf-8")
    assert f"# Club Analysis Report — {CLUB_ID}" in content
    assert "Overall Score:" in content
    assert "Category Breakdown" in content
    for category in ("Injury", "Financial", "Tactical"):
        assert category in content


def test_analyze_without_output_skips_markdown_export(capsys):
    reports_dir_existed_before = os.path.isdir("reports")

    exit_code = main(["analyze", "--club-id", CLUB_ID, "--mock"])

    assert exit_code == 0
    assert os.path.isdir("reports") == reports_dir_existed_before


def test_analyze_missing_club_id_errors():
    with pytest.raises(SystemExit):
        main(["analyze"])
