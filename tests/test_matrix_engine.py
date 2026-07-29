"""
test_matrix_engine.py
======================
Unit tests for MatrixEngine (src/scoring/matrix_engine.py).

Uses a mock ClubAnalysisReport -- no network access, per repo mock-first policy.
"""

from __future__ import annotations

import pytest

from src.schemas import (
    Club,
    ClubAnalysisReport,
    Player,
    SquadStatsSummary,
)
from src.scoring.financial_scorer import FinancialScorer
from src.scoring.injury_scorer import InjuryScorer
from src.scoring.matrix_engine import MatrixEngine
from src.scoring.tactical_scorer import TacticalScorer


def _make_report(
    manager_tenure_years: float | None = 3.0,
    average_age: float = 26.0,
    injury_risk_score: float = 0.2,
    transfer_balance: float = -5_000_000.0,
    performance_trend: float | None = 0.4,
    squad_size: int = 25,
) -> ClubAnalysisReport:
    squad = [
        Player(
            id=f"p_{i:03d}",
            name=f"Player {i}",
            age=25,
            primary_position="CM",
            market_value=2_000_000.0,
            nationality="England",
        )
        for i in range(squad_size)
    ]
    club = Club(
        id="club_001",
        name="Mock Town FC",
        manager="Mock Manager",
        manager_tenure_years=manager_tenure_years,
        squad_list=squad,
    )
    return ClubAnalysisReport(
        club_info=club,
        squad_stats_summary=SquadStatsSummary(
            total_goals=40,
            total_assists=30,
            total_minutes_played=90_000,
            average_age=average_age,
            squad_size=squad_size,
        ),
        injury_risk_score=injury_risk_score,
        transfer_balance=transfer_balance,
        performance_trend=performance_trend,
    )


class TestMatrixEngineWeights:
    def test_default_weights_sum_to_one(self):
        engine = MatrixEngine()
        assert pytest.approx(sum(engine._weights.values())) == 1.0

    def test_custom_weights_must_sum_to_one(self):
        with pytest.raises(ValueError):
            MatrixEngine(injury_weight=0.5, financial_weight=0.5, tactical_weight=0.5)

    def test_custom_weights_accepted_when_valid(self):
        engine = MatrixEngine(injury_weight=0.5, financial_weight=0.3, tactical_weight=0.2)
        report = _make_report()
        ranking = engine.evaluate_club(report)
        assert ranking.club_id == "club_001"


class TestMatrixEngineAggregation:
    def test_breakdown_matches_individual_scorers(self):
        report = _make_report()
        engine = MatrixEngine()
        ranking = engine.evaluate_club(report)

        assert ranking.breakdown["injury"] == InjuryScorer().calculate_score(report)
        assert ranking.breakdown["financial"] == FinancialScorer().calculate_score(report)
        assert ranking.breakdown["tactical"] == TacticalScorer().calculate_score(report)

    def test_weighted_components_apply_configured_weights(self):
        report = _make_report()
        engine = MatrixEngine(injury_weight=0.35, financial_weight=0.35, tactical_weight=0.30)
        ranking = engine.evaluate_club(report)

        assert ranking.weighted_components["injury"] == pytest.approx(
            ranking.breakdown["injury"] * 0.35, abs=1e-3
        )
        assert ranking.weighted_components["financial"] == pytest.approx(
            ranking.breakdown["financial"] * 0.35, abs=1e-3
        )
        assert ranking.weighted_components["tactical"] == pytest.approx(
            ranking.breakdown["tactical"] * 0.30, abs=1e-3
        )

    def test_overall_score_is_sum_of_weighted_components(self):
        report = _make_report()
        engine = MatrixEngine()
        ranking = engine.evaluate_club(report)

        expected = sum(ranking.weighted_components.values())
        assert ranking.overall_score == pytest.approx(expected, abs=1e-2)

    def test_different_weights_change_overall_score(self):
        report = _make_report()
        default_engine = MatrixEngine()
        injury_heavy_engine = MatrixEngine(
            injury_weight=0.8, financial_weight=0.1, tactical_weight=0.1
        )

        default_ranking = default_engine.evaluate_club(report)
        injury_heavy_ranking = injury_heavy_engine.evaluate_club(report)

        assert default_ranking.overall_score != injury_heavy_ranking.overall_score


class TestMatrixEngineNormalization:
    def test_overall_score_within_bounds(self):
        report = _make_report()
        engine = MatrixEngine()
        ranking = engine.evaluate_club(report)
        assert 0.0 <= ranking.overall_score <= 100.0

    def test_handles_missing_optional_data_gracefully(self):
        report = _make_report(manager_tenure_years=None, performance_trend=None)
        engine = MatrixEngine()
        ranking = engine.evaluate_club(report)
        assert 0.0 <= ranking.overall_score <= 100.0

    def test_handles_empty_squad_gracefully(self):
        report = _make_report(squad_size=0)
        engine = MatrixEngine()
        ranking = engine.evaluate_club(report)
        assert 0.0 <= ranking.overall_score <= 100.0

    def test_club_id_matches_report(self):
        report = _make_report()
        engine = MatrixEngine()
        ranking = engine.evaluate_club(report)
        assert ranking.club_id == report.club_info.id
