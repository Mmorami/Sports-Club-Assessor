"""
test_manager_collector.py
=========================
Unit tests for ManagerClubCollector using mock fixture data.
"""

import pytest
from src.collectors.manager import ManagerClubCollector
from src.collectors.base import ParseError
from src.schemas import Club


class TestManagerClubCollector:
    """Test suite for ManagerClubCollector."""

    @pytest.fixture
    def collector(self):
        """Create a collector instance pointing to the mock fixture."""
        return ManagerClubCollector(mock_path="data/mock/manager_club_mock.json")

    def test_fixture_loads_without_error(self, collector):
        """Verify mock fixture can be loaded."""
        clubs = collector._load_clubs()
        assert isinstance(clubs, dict)
        assert len(clubs) > 0

    def test_fetch_data_returns_list(self, collector):
        """Verify fetch_data returns a list containing Club instances."""
        result = collector.fetch_data("c_399")
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], Club)

    def test_fetch_data_existing_club(self, collector):
        """Verify fetch_data returns club with correct structure."""
        result = collector.fetch_data("c_399")
        club = result[0]

        assert club.id == "c_399"
        assert club.name == "Leeds United"
        assert club.manager == "Daniel Farke"
        assert len(club.squad_list) == 3
        assert len(club.transfers_in) == 2
        assert len(club.transfers_out) == 1

    def test_fetch_data_nonexistent_club(self, collector):
        """Verify fetch_data returns empty list for unknown club_id."""
        result = collector.fetch_data("c_999")
        assert result == []

    def test_fetch_club_context_existing_club(self, collector):
        """Verify fetch_club_context returns Club for valid club_id."""
        club = collector.fetch_club_context("c_399")
        assert club is not None
        assert isinstance(club, Club)
        assert club.id == "c_399"
        assert club.name == "Leeds United"

    def test_fetch_club_context_nonexistent_club(self, collector):
        """Verify fetch_club_context returns None for unknown club_id."""
        club = collector.fetch_club_context("c_999")
        assert club is None

    def test_squad_list_players_are_valid(self, collector):
        """Verify all players in squad_list are valid Player instances."""
        club = collector.fetch_club_context("c_399")
        assert len(club.squad_list) == 3

        for player in club.squad_list:
            assert player.id
            assert player.name
            assert player.age > 0
            assert player.primary_position
            assert player.market_value >= 0.0
            assert player.nationality

    def test_transfers_in_have_correct_direction(self, collector):
        """Verify all transfers_in have direction=IN."""
        club = collector.fetch_club_context("c_399")
        for transfer in club.transfers_in:
            assert transfer.direction.value == "IN"

    def test_transfers_out_have_correct_direction(self, collector):
        """Verify all transfers_out have direction=OUT."""
        club = collector.fetch_club_context("c_399")
        for transfer in club.transfers_out:
            assert transfer.direction.value == "OUT"

    def test_transfer_fee_consistency(self, collector):
        """Verify FREE transfers do not have positive fees."""
        club = collector.fetch_club_context("c_399")
        for transfer in club.transfers_in + club.transfers_out:
            if transfer.transfer_type.value == "FREE":
                assert transfer.fee is None or transfer.fee == 0.0

    def test_invalid_mock_path_raises_error(self):
        """Verify ParseError is raised for non-existent mock file."""
        collector = ManagerClubCollector(mock_path="/nonexistent/path.json")
        with pytest.raises(ParseError):
            collector.fetch_data("c_399")

    def test_collector_repr(self, collector):
        """Verify collector has informative repr."""
        repr_str = repr(collector)
        assert "ManagerClubCollector" in repr_str
        assert "timeout" in repr_str
