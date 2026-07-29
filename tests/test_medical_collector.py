"""
test_medical_collector.py
==========================
Unit tests for ``MedicalCollector``. Uses only the local mock fixture at
``data/mock/medical_mock.json`` — no live HTTP requests.
"""

from pathlib import Path

import pytest

from src.collectors.medical import MedicalCollector
from src.schemas import MedicalRecord

MOCK_PATH = Path("data/mock/medical_mock.json")


@pytest.fixture
def collector() -> MedicalCollector:
    return MedicalCollector(mock_path=MOCK_PATH)


def test_fetch_medical_history_returns_multiple_records(collector: MedicalCollector) -> None:
    records = collector.fetch_medical_history("p_002")
    assert len(records) == 2
    assert all(isinstance(r, MedicalRecord) for r in records)
    assert {r.season for r in records} == {"2023/2024", "2024/2025"}


def test_fetch_medical_history_single_record(collector: MedicalCollector) -> None:
    records = collector.fetch_medical_history("p_001")
    assert len(records) == 1
    assert records[0].injury_type == "Hamstring Strain"


def test_fetch_medical_history_unknown_player_returns_empty(
    collector: MedicalCollector,
) -> None:
    records = collector.fetch_medical_history("p_999")
    assert records == []


def test_fetch_data_returns_all_validated_records(collector: MedicalCollector) -> None:
    records = collector.fetch_data(club_id="unused")
    assert len(records) == 3
    assert all(isinstance(r, MedicalRecord) for r in records)
