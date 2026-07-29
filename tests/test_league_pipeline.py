"""
tests/test_league_pipeline.py
==============================
Unit tests for ``LeaguePipeline`` -- uses fake club-pipeline and
matrix-engine doubles (no real collectors, no live HTTP requests) so
behavior is fully deterministic and cache reuse can be counted directly.
"""

from __future__ import annotations

from src.league_pipeline import LeaguePipeline
from src.schemas import Club, ClubAnalysisReport, FinalClubRanking, SquadStatsSummary

TEST_REGISTRY = {"championship": {"2026-2027": ["c_1", "c_2", "c_3"]}}

# club_id -> overall_score, used by both the fake pipeline and fake engine
_SCORES = {"c_1": 90.0, "c_2": 70.0, "c_3": 50.0}


def _make_report(club_id: str) -> ClubAnalysisReport:
    return ClubAnalysisReport(
        club_info=Club(id=club_id, name=f"Club {club_id}", manager="Test Manager"),
        squad_stats_summary=SquadStatsSummary(
            total_goals=0, total_assists=0, total_minutes_played=0,
            average_age=25.0, squad_size=0,
        ),
        injury_risk_score=0.0,
        transfer_balance=0.0,
    )


class _FakeClubPipeline:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def run_club_pipeline(self, club_id: str) -> ClubAnalysisReport:
        self.calls.append(club_id)
        return _make_report(club_id)


class _FakeMatrixEngine:
    def evaluate_club(self, report: ClubAnalysisReport) -> FinalClubRanking:
        club_id = report.club_info.id
        score = _SCORES[club_id]
        return FinalClubRanking(
            club_id=club_id,
            overall_score=score,
            breakdown={"injury": score, "financial": score, "tactical": score},
            weighted_components={"injury": score / 3, "financial": score / 3, "tactical": score / 3},
        )


def _build_pipeline(tmp_path, club_pipeline=None):
    pipeline = LeaguePipeline(
        club_pipeline=club_pipeline or _FakeClubPipeline(),
        matrix_engine=_FakeMatrixEngine(),
        registry=TEST_REGISTRY,
    )
    # Cache directory is created inside run_league via CacheManager(league, season);
    # point it at tmp_path by monkeypatching the default base_dir indirectly
    # through CacheManager's own tests instead -- here we just isolate cwd.
    return pipeline


def test_run_league_orders_standings_by_score_descending(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    pipeline = _build_pipeline(tmp_path)

    report = pipeline.run_league("championship", "2026-2027", use_cache=False)

    club_ids_in_order = [s.club_id for s in report.standings]
    assert club_ids_in_order == ["c_1", "c_2", "c_3"]
    assert [s.league_rank for s in report.standings] == [1, 2, 3]


def test_run_league_computes_percentiles(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    pipeline = _build_pipeline(tmp_path)

    report = pipeline.run_league("championship", "2026-2027", use_cache=False)

    percentiles = {s.club_id: s.percentile for s in report.standings}
    assert percentiles["c_1"] == 100.0
    assert percentiles["c_2"] == 50.0
    assert percentiles["c_3"] == 0.0


def test_run_league_uses_cache_to_avoid_second_collection(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    fake_pipeline = _FakeClubPipeline()
    pipeline = _build_pipeline(tmp_path, club_pipeline=fake_pipeline)

    pipeline.run_league("championship", "2026-2027", use_cache=True)
    assert sorted(fake_pipeline.calls) == ["c_1", "c_2", "c_3"]

    fake_pipeline.calls.clear()
    pipeline.run_league("championship", "2026-2027", use_cache=True)

    assert fake_pipeline.calls == []


def test_run_league_force_refresh_bypasses_cache(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    fake_pipeline = _FakeClubPipeline()
    pipeline = _build_pipeline(tmp_path, club_pipeline=fake_pipeline)

    pipeline.run_league("championship", "2026-2027", use_cache=True)
    fake_pipeline.calls.clear()

    pipeline.run_league("championship", "2026-2027", use_cache=False)

    assert sorted(fake_pipeline.calls) == ["c_1", "c_2", "c_3"]


def test_unknown_league_raises_value_error(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    pipeline = _build_pipeline(tmp_path)

    try:
        pipeline.run_league("unknown-league", "2026-2027")
        assert False, "Expected ValueError for unknown league"
    except ValueError:
        pass
