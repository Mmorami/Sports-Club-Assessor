"""
medical.py
==========
Deterministic collector for player injury history.

Loads injury records from a local JSON fixture and validates them into
``MedicalRecord`` Pydantic models. No live network requests are made.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List

from pydantic import ValidationError

from src.collectors.base import BaseCollector, ParseError
from src.schemas import MedicalRecord

DEFAULT_MOCK_PATH = Path("data/mock/medical_mock.json")


class MedicalCollector(BaseCollector):
    """Collector that reads injury history from a mock JSON fixture."""

    def __init__(
        self,
        mock_path: Path | str = DEFAULT_MOCK_PATH,
        timeout: int = BaseCollector.DEFAULT_TIMEOUT,
    ) -> None:
        super().__init__(timeout=timeout)
        self._mock_path = Path(mock_path)

    def _load_records(self) -> List[dict[str, Any]]:
        with open(self._mock_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _parse_records(self, raw_records: List[dict[str, Any]]) -> List[MedicalRecord]:
        records: List[MedicalRecord] = []
        for raw in raw_records:
            try:
                records.append(MedicalRecord(**raw))
            except ValidationError as exc:
                raise ParseError(
                    "Failed to validate medical record",
                    field="MedicalRecord",
                    raw=raw,
                ) from exc
        return records

    def fetch_data(self, club_id: str) -> List[MedicalRecord]:
        """Return all medical records available in the mock fixture."""
        return self._parse_records(self._load_records())

    def fetch_medical_history(self, player_id: str) -> List[MedicalRecord]:
        """
        Return injury history for a single player.

        Returns an empty list if the player has no recorded injuries.
        """
        raw_records = self._load_records()
        matching = [r for r in raw_records if r.get("player_id") == player_id]
        return self._parse_records(matching)
