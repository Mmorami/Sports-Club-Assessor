"""
pipeline.py
===========
Unified integration pipeline that aggregates data across all collectors
(``ManagerClubCollector``, ``TransferCollector``, ``StatsCollector``,
``MedicalCollector``) into a single normalized ``ClubAnalysisReport`` per club.

Collectors are injected via the constructor so tests can substitute
mock-backed doubles for the network-scraping collectors (``StatsCollector``,
``TransferCollector``) without making live HTTP requests. Production code can
rely on the defaults, which use the real collectors.
"""

from __future__ import annotations

from typing import Optional

from src.collectors.base import BaseCollector
from src.collectors.manager import ManagerClubCollector
from src.collectors.medical import MedicalCollector
from src.collectors.stats import StatsCollector
from src.collectors.transfers import TransferCollector
from src.schemas import ClubAnalysisReport, SquadStatsSummary

# Injury-risk normalization ceilings: a full domestic season is ~46 games and
# 365 calendar days, so a squad where every player missed a full season
# through injury caps the score at 1.0.
_MAX_DAYS_OUT_PER_PLAYER = 365
_MAX_GAMES_MISSED_PER_PLAYER = 46


class EFLDataPipeline:
    """
    Aggregates per-club data across all collectors into a ``ClubAnalysisReport``.

    Parameters
    ----------
    manager_collector  : Collector providing club context (roster, manager).
                          Defaults to ``ManagerClubCollector()``.
    transfer_collector : Collector providing transfer transactions.
                          Defaults to ``TransferCollector()``.
    stats_collector     : Collector providing player-season performance stats.
                          Defaults to ``StatsCollector()``.
    medical_collector   : Collector providing injury history.
                          Defaults to ``MedicalCollector()``.
    use_mock           : When ``True`` (default) and a collector is not
                          explicitly injected, ``StatsCollector``,
                          ``TransferCollector``, and ``ManagerClubCollector``
                          are constructed with their ``data/mock/*.json``
                          fixtures instead of making live HTTP requests.
                          ``MedicalCollector`` already defaults to local
                          mock fixtures regardless of this flag.
    """

    def __init__(
        self,
        manager_collector: Optional[BaseCollector] = None,
        transfer_collector: Optional[BaseCollector] = None,
        stats_collector: Optional[BaseCollector] = None,
        medical_collector: Optional[BaseCollector] = None,
        use_mock: bool = True,
    ) -> None:
        self._manager_collector = manager_collector or (
            ManagerClubCollector(mock_path="data/mock/manager_club_mock.json")
            if use_mock
            else ManagerClubCollector()
        )
        self._transfer_collector = transfer_collector or (
            TransferCollector(mock_file="data/mock/transfers_mock.json")
            if use_mock
            else TransferCollector()
        )
        self._stats_collector = stats_collector or (
            StatsCollector(mock_file="data/mock/stats_mock.json")
            if use_mock
            else StatsCollector()
        )
        self._medical_collector = medical_collector or MedicalCollector()

    def run_club_pipeline(self, club_id: str) -> ClubAnalysisReport:
        """
        Collect and aggregate all data sources for *club_id* into a
        ``ClubAnalysisReport``.

        Parameters
        ----------
        club_id : str
            Unique club identifier (e.g. ``"c_399"``).

        Returns
        -------
        ClubAnalysisReport

        Raises
        ------
        ValueError
            If no club context can be resolved for *club_id*.
        """
        club = self._manager_collector.fetch_club_context(club_id)
        if club is None:
            raise ValueError(f"No club context found for club_id={club_id!r}")

        squad_ids = {player.id for player in club.squad_list}

        player_stats = [
            s for s in self._stats_collector.fetch_data(club_id)
            if s.player_id in squad_ids
        ]
        medical_records = [
            m for m in self._medical_collector.fetch_data(club_id)
            if m.player_id in squad_ids
        ]
        transfers = self._transfer_collector.fetch_data(club_id)

        squad_stats_summary = self._build_squad_stats_summary(club, player_stats)
        injury_risk_score = self._calculate_injury_risk_score(club, medical_records)
        transfer_balance = self._calculate_transfer_balance(transfers)

        return ClubAnalysisReport(
            club_info=club,
            squad_stats_summary=squad_stats_summary,
            injury_risk_score=injury_risk_score,
            transfer_balance=transfer_balance,
        )

    @staticmethod
    def _build_squad_stats_summary(club, player_stats) -> SquadStatsSummary:
        squad_size = len(club.squad_list)
        average_age = (
            sum(p.age for p in club.squad_list) / squad_size if squad_size else 0.0
        )
        return SquadStatsSummary(
            total_goals=sum(s.goals for s in player_stats),
            total_assists=sum(s.assists for s in player_stats),
            total_minutes_played=sum(s.minutes_played for s in player_stats),
            average_age=round(average_age, 2),
            squad_size=squad_size,
        )

    @staticmethod
    def _calculate_injury_risk_score(club, medical_records) -> float:
        squad_size = len(club.squad_list)
        if squad_size == 0 or not medical_records:
            return 0.0

        total_days_out = sum(m.days_out for m in medical_records)
        total_games_missed = sum(m.games_missed for m in medical_records)

        days_component = total_days_out / (squad_size * _MAX_DAYS_OUT_PER_PLAYER)
        games_component = total_games_missed / (squad_size * _MAX_GAMES_MISSED_PER_PLAYER)

        score = 0.5 * days_component + 0.5 * games_component
        return round(min(max(score, 0.0), 1.0), 4)

    @staticmethod
    def _calculate_transfer_balance(transfers) -> float:
        fees_in = sum(t.fee or 0.0 for t in transfers if t.direction.value == "IN")
        fees_out = sum(t.fee or 0.0 for t in transfers if t.direction.value == "OUT")
        return round(fees_out - fees_in, 2)
