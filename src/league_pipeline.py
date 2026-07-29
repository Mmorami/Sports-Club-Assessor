"""
league_pipeline.py
===================
Orchestrates ``EFLDataPipeline`` and ``MatrixEngine`` across every club in a
league season, using ``CacheManager`` to avoid redundant collector calls
(and the live HTTP scraping behind them) on repeat runs.

``LEAGUE_CLUB_REGISTRY`` is a placeholder mapping of league/season to club
ids. No real league-membership data source exists in this codebase yet --
replace this registry (or inject a custom one via the constructor) once one
does.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from src.cache import CacheManager
from src.pipeline import EFLDataPipeline
from src.schemas import ClubAnalysisReport, LeagueAnalysisReport, LeagueClubStanding
from src.scoring.matrix_engine import MatrixEngine

LEAGUE_CLUB_REGISTRY: Dict[str, Dict[str, List[str]]] = {
    "championship": {
        "2026-2027": ["c_399"],
    },
}


class LeaguePipeline:
    """
    Aggregates per-club ``ClubAnalysisReport``/``FinalClubRanking`` pairs into
    a league-wide ``LeagueAnalysisReport`` with relative rankings and
    percentile scores.

    Parameters
    ----------
    club_pipeline : Pipeline used to collect each club's data. Defaults to
                    ``EFLDataPipeline()``.
    matrix_engine : Scorer used to turn each ``ClubAnalysisReport`` into a
                    ``FinalClubRanking``. Defaults to ``MatrixEngine()``.
    registry      : Mapping of ``league_id -> season -> [club_id, ...]``.
                    Defaults to ``LEAGUE_CLUB_REGISTRY``.
    """

    def __init__(
        self,
        club_pipeline: Optional[EFLDataPipeline] = None,
        matrix_engine: Optional[MatrixEngine] = None,
        registry: Optional[Dict[str, Dict[str, List[str]]]] = None,
    ) -> None:
        self._club_pipeline = club_pipeline or EFLDataPipeline()
        self._matrix_engine = matrix_engine or MatrixEngine()
        self._registry = registry or LEAGUE_CLUB_REGISTRY

    def _club_ids_for(self, league_id: str, season: str) -> List[str]:
        try:
            return self._registry[league_id][season]
        except KeyError as exc:
            raise ValueError(
                f"No club registry entry for league={league_id!r} season={season!r}"
            ) from exc

    def run_league(
        self, league_id: str, season: str, use_cache: bool = True
    ) -> LeagueAnalysisReport:
        """
        Run the full analysis pipeline for every club in *league_id* /
        *season*, returning a ``LeagueAnalysisReport`` ranked by overall
        score.
        """
        club_ids = self._club_ids_for(league_id, season)
        cache = CacheManager(league_id, season)

        pairs = []
        for club_id in club_ids:
            report = self._load_report(club_id, cache, use_cache)
            ranking = self._matrix_engine.evaluate_club(report)
            pairs.append((report, ranking))

        return self._build_league_report(league_id, season, pairs)

    def _load_report(
        self, club_id: str, cache: CacheManager, use_cache: bool
    ) -> ClubAnalysisReport:
        if use_cache and not cache.is_expired(club_id):
            cached = cache.get(club_id)
            if cached is not None:
                return ClubAnalysisReport.model_validate(cached)

        report = self._club_pipeline.run_club_pipeline(club_id)
        if use_cache:
            cache.set(club_id, report.model_dump(mode="json"))
        return report

    @staticmethod
    def _build_league_report(league_id, season, pairs) -> LeagueAnalysisReport:
        ranked = sorted(pairs, key=lambda pair: pair[1].overall_score, reverse=True)
        total = len(ranked)

        standings = []
        for index, (report, ranking) in enumerate(ranked):
            league_rank = index + 1
            percentile = (
                round(100.0 * (total - league_rank) / (total - 1), 2)
                if total > 1
                else 100.0
            )
            standings.append(
                LeagueClubStanding(
                    club_id=ranking.club_id,
                    club_name=report.club_info.name,
                    overall_score=ranking.overall_score,
                    breakdown=ranking.breakdown,
                    league_rank=league_rank,
                    percentile=percentile,
                )
            )

        return LeagueAnalysisReport(league_id=league_id, season=season, standings=standings)
