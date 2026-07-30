"""
league_pipeline.py
===================
Orchestrates ``EFLDataPipeline`` and ``MatrixEngine`` across every club in a
league season, using ``CacheManager`` to avoid redundant collector calls
(and the live HTTP scraping behind them) on repeat runs.

League membership is fetched live from Transfermarkt via ``LeagueCollector``
and cached annually so it stays current with promotions/relegations.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from src.cache import CacheManager
from src.collectors.league import LeagueCollector
from src.pipeline import EFLDataPipeline
from src.schemas import ClubAnalysisReport, LeagueAnalysisReport, LeagueClubStanding
from src.scoring.matrix_engine import MatrixEngine

logger = logging.getLogger(__name__)

# Map Transfermarkt league IDs to league names
LEAGUE_CODES = {
    "championship": "GB2",
    "premier-league": "GB1",
}


class LeaguePipeline:
    """
    Aggregates per-club ``ClubAnalysisReport``/``FinalClubRanking`` pairs into
    a league-wide ``LeagueAnalysisReport`` with relative rankings and
    percentile scores.

    League membership is fetched live from Transfermarkt via ``LeagueCollector``
    and cached annually, ensuring it stays current with promotions/relegations.

    Parameters
    ----------
    club_pipeline : Pipeline used to collect each club's data. Defaults to
                    ``EFLDataPipeline(use_mock=use_mock)``.
    matrix_engine : Scorer used to turn each ``ClubAnalysisReport`` into a
                    ``FinalClubRanking``. Defaults to ``MatrixEngine()``.
    league_collector : Collector for fetching current league standings.
                       Defaults to ``LeagueCollector()`` for live Transfermarkt
                       data. Pass a custom instance to inject test doubles.
    use_mock      : When True (default), use local mock fixtures. When False,
                    fetch live data from Transfermarkt.
    """

    def __init__(
        self,
        club_pipeline: Optional[EFLDataPipeline] = None,
        matrix_engine: Optional[MatrixEngine] = None,
        league_collector: Optional[LeagueCollector] = None,
        use_mock: bool = True,
    ) -> None:
        self._club_pipeline = club_pipeline or EFLDataPipeline(use_mock=use_mock)
        self._matrix_engine = matrix_engine or MatrixEngine()
        self._league_collector = league_collector
        self._use_mock = use_mock

    def _club_ids_for(
        self, league_id: str, season: str, use_cache: bool = True
    ) -> List[str]:
        """
        Fetch club IDs for a league/season from cache or live Transfermarkt.

        Parameters
        ----------
        league_id : str
            League identifier (e.g., 'championship').
        season : str
            Season identifier (e.g., '2026-2027').
        use_cache : bool
            Whether to use cached league data (default True). Set to False to
            force a fresh fetch from Transfermarkt.

        Returns
        -------
        List[str]
            List of club IDs for the league.

        Raises
        ------
        ValueError
            If the league is not supported.
        """
        cache_key = f"{league_id}_{season}"
        cache = CacheManager(league_id, season)

        # Check cache first (1 year TTL = 8760 hours)
        if use_cache and not cache.is_expired(cache_key, ttl_hours=8760):
            cached = cache.get(cache_key)
            if cached and isinstance(cached, dict):
                club_ids = cached.get("club_ids", [])
                if club_ids:
                    logger.info(
                        f"Using cached league data for {league_id}/{season} "
                        f"({len(club_ids)} clubs)"
                    )
                    return club_ids

        # Fetch from Transfermarkt via LeagueCollector
        tm_league_id = LEAGUE_CODES.get(league_id)
        if not tm_league_id:
            raise ValueError(f"Unsupported league: {league_id!r}")

        collector = self._league_collector or LeagueCollector(tm_league_id)
        try:
            club_ids = collector.fetch_data()
        except Exception as e:
            logger.error(f"Failed to fetch league data from Transfermarkt: {e}")
            raise ValueError(
                f"Failed to fetch clubs for league={league_id!r} season={season!r}"
            ) from e

        # Cache the result
        cache.set(cache_key, {"club_ids": club_ids, "season": season})
        logger.info(
            f"Fetched {len(club_ids)} clubs for {league_id}/{season} from Transfermarkt"
        )
        return club_ids

    def run_league(
        self, league_id: str, season: str, use_cache: bool = True
    ) -> LeagueAnalysisReport:
        """
        Run the full analysis pipeline for every club in *league_id* /
        *season*, returning a ``LeagueAnalysisReport`` ranked by overall
        score.

        Parameters
        ----------
        league_id : str
            League identifier (e.g., 'championship').
        season : str
            Season identifier (e.g., '2026-2027').
        use_cache : bool
            If True, use cached data for both league membership and club
            analysis. If False, force fresh fetches from Transfermarkt.
        """
        club_ids = self._club_ids_for(league_id, season, use_cache=use_cache)
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
