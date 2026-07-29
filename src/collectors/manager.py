"""
manager.py
==========
Deterministic club context and manager information collector.

Loads club details, manager information, and financial constraint placeholders
into Club Pydantic models using mock fixture data.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List

from src.collectors.base import BaseCollector, ParseError
from src.schemas import Club


class ManagerClubCollector(BaseCollector):
    """
    Fetches club context including manager info and financial constraints.

    Loads mock club data from a JSON fixture and validates against the Club schema.

    Parameters
    ----------
    mock_path : str or Path
        Path to the mock JSON fixture file (e.g., "data/mock/manager_club_mock.json").
    timeout : int
        HTTP request timeout in seconds (default 20). Not used for mock data
        but kept for interface compatibility.
    """

    def __init__(self, mock_path: str | Path = "data/mock/manager_club_mock.json", timeout: int = BaseCollector.DEFAULT_TIMEOUT) -> None:
        super().__init__(timeout)
        self._mock_path = Path(mock_path)
        self._clubs: dict[str, Club] | None = None

    def _load_clubs(self) -> dict[str, Club]:
        """Load and cache club data from mock fixture."""
        if self._clubs is not None:
            return self._clubs

        try:
            with open(self._mock_path, "r") as f:
                raw_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            raise ParseError(f"Failed to load mock fixture from {self._mock_path!r}: {e}")

        if isinstance(raw_data, dict):
            raw_data = [raw_data]
        elif not isinstance(raw_data, list):
            raise ParseError(f"Mock data must be a dict or list, got {type(raw_data).__name__}")

        self._clubs = {}
        for item in raw_data:
            try:
                club = Club(**item)
                self._clubs[club.id] = club
            except Exception as e:
                raise ParseError(f"Failed to parse club data: {e}")

        return self._clubs

    def fetch_data(self, club_id: str) -> List[Any]:
        """
        Fetch and return a list containing the Club for *club_id*.

        Parameters
        ----------
        club_id : str
            Unique club identifier (e.g. "c_399").

        Returns
        -------
        List[Any]
            A list containing a single Club instance, or empty list if not found.

        Raises
        ------
        ParseError
            If the mock fixture cannot be loaded or parsed.
        """
        clubs = self._load_clubs()
        if club_id in clubs:
            return [clubs[club_id]]
        return []

    def fetch_club_context(self, club_id: str) -> Club | None:
        """
        Fetch and return the Club object for *club_id*.

        Parameters
        ----------
        club_id : str
            Unique club identifier (e.g. "c_399").

        Returns
        -------
        Club or None
            The Club instance if found, otherwise None.

        Raises
        ------
        ParseError
            If the mock fixture cannot be loaded or parsed.
        """
        result = self.fetch_data(club_id)
        return result[0] if result else None
