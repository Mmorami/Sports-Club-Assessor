"""
tests/test_pipeline.py
=======================
Unit test for ``EFLDataPipeline`` using mock fixtures only -- no live HTTP
requests are made.

``ManagerClubCollector`` and ``MedicalCollector`` already read from
``data/mock/`` fixtures directly. ``StatsCollector`` and ``TransferCollector``
scrape Transfermarkt live with no mock mode, so this test injects lightweight
fake doubles that read ``data/mock/stats_mock.json`` and
``data/mock/transfers_mock.json`` instead, satisfying the pipeline's
collector interface without any network access.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List

from src.collectors.base import BaseCollector
from src.collectors.manager import ManagerClubCollector
from src.collectors.medical import MedicalCollector
from src.pipeline import EFLDataPipeline
from src.schemas import ClubAnalysisReport, PlayerStats, Transfer

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_MOCK_DIR = _PROJECT_ROOT / "data" / "mock"

TEST_CLUB_ID = "c_399"


class _MockStatsCollector(BaseCollector):
    """Fake stats collector reading from the mock fixture, no network calls."""

    def __init__(self, mock_path: Path = _MOCK_DIR / "stats_mock.json") -> None:
        super().__init__()
        self._mock_path = mock_path

    def fetch_data(self, club_id: str) -> List[PlayerStats]:
        with open(self._mock_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return [PlayerStats(**row) for row in raw]


class _MockTransferCollector(BaseCollector):
    """Fake transfer collector reading from the mock fixture, no network calls."""

    def __init__(self, mock_path: Path = _MOCK_DIR / "transfers_mock.json") -> None:
        super().__init__()
        self._mock_path = mock_path

    def fetch_data(self, club_id: str) -> List[Transfer]:
        with open(self._mock_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return [Transfer(**row) for row in raw]


def _build_pipeline() -> EFLDataPipeline:
    return EFLDataPipeline(
        manager_collector=ManagerClubCollector(),
        transfer_collector=_MockTransferCollector(),
        stats_collector=_MockStatsCollector(),
        medical_collector=MedicalCollector(),
    )


def test_run_club_pipeline_returns_valid_report() -> None:
    pipeline = _build_pipeline()
    report = pipeline.run_club_pipeline(TEST_CLUB_ID)

    assert isinstance(report, ClubAnalysisReport)
    assert report.club_info.id == TEST_CLUB_ID
    assert report.squad_stats_summary.squad_size == len(report.club_info.squad_list)
    assert 0.0 <= report.injury_risk_score <= 1.0


def test_squad_stats_summary_aggregates_matched_players() -> None:
    pipeline = _build_pipeline()
    report = pipeline.run_club_pipeline(TEST_CLUB_ID)

    # stats_mock.json has p_001 (goals 18+21) and p_002 (goals 2+3); both are
    # in the manager mock's squad_list, so both seasons should be aggregated.
    summary = report.squad_stats_summary
    assert summary.total_goals == 18 + 21 + 2 + 3
    assert summary.total_assists == 6 + 5 + 9 + 11
    assert summary.total_minutes_played == 3120 + 3350 + 2450 + 2870
    assert summary.average_age > 0.0


def test_injury_risk_score_reflects_medical_history() -> None:
    pipeline = _build_pipeline()
    report = pipeline.run_club_pipeline(TEST_CLUB_ID)

    # medical_mock.json has injuries for p_001 and p_002, both in squad_list,
    # so the score must be strictly positive.
    assert report.injury_risk_score > 0.0


def test_transfer_balance_is_outgoing_minus_incoming_fees() -> None:
    pipeline = _build_pipeline()
    report = pipeline.run_club_pipeline(TEST_CLUB_ID)

    # transfers_mock.json: IN fee=4,500,000 + IN fee=None; OUT fee=2,000,000 + OUT fee=None
    assert report.transfer_balance == 2_000_000.0 - 4_500_000.0


def test_missing_club_raises_value_error() -> None:
    pipeline = _build_pipeline()
    try:
        pipeline.run_club_pipeline("does-not-exist")
        assert False, "Expected ValueError for unknown club_id"
    except ValueError:
        pass


if __name__ == "__main__":
    import sys

    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    sys.exit(1 if failures else 0)
