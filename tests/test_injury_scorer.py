"""Unit tests for src/scoring/injury_scorer.py -- pure in-memory, no network/mock fixtures."""

from __future__ import annotations

import pytest

from src.schemas import Club, ClubAnalysisReport, Player, SquadStatsSummary
from src.scoring.injury_scorer import InjuryScorer


def _make_player(player_id: str, age: int = 25) -> Player:
    return Player(
        id=player_id,
        name=f"Player {player_id}",
        age=age,
        primary_position="CM",
        market_value=1_000_000.0,
        nationality="England",
    )


def _make_report(
    squad_size: int,
    injury_risk_score: float,
    club_id: str = "c_001",
) -> ClubAnalysisReport:
    squad_list = [_make_player(f"p_{i:03d}") for i in range(squad_size)]
    club = Club(
        id=club_id,
        name="Test FC",
        manager="Test Manager",
        manager_tenure_years=2.0,
        squad_list=squad_list,
    )
    summary = SquadStatsSummary(
        total_goals=0,
        total_assists=0,
        total_minutes_played=0,
        average_age=25.0,
        squad_size=squad_size,
    )
    return ClubAnalysisReport(
        club_info=club,
        squad_stats_summary=summary,
        injury_risk_score=injury_risk_score,
        transfer_balance=0.0,
        performance_trend=0.0,
    )


class TestInjuryScorer:
    def test_full_squad_low_risk_scores_high(self):
        report = _make_report(squad_size=25, injury_risk_score=0.0)
        score = InjuryScorer().calculate_score(report)
        assert score == pytest.approx(100.0)

    def test_thin_squad_high_risk_scores_low(self):
        report = _make_report(squad_size=5, injury_risk_score=1.0)
        score = InjuryScorer().calculate_score(report)
        assert score < 30.0

    def test_score_within_bounds(self):
        for squad_size in (0, 5, 25, 40):
            for risk in (0.0, 0.25, 0.5, 0.75, 1.0):
                report = _make_report(squad_size=squad_size, injury_risk_score=risk)
                score = InjuryScorer().calculate_score(report)
                assert 0.0 <= score <= 100.0

    def test_monotonic_with_injury_risk(self):
        low_risk = _make_report(squad_size=25, injury_risk_score=0.1)
        high_risk = _make_report(squad_size=25, injury_risk_score=0.9)
        assert InjuryScorer().calculate_score(low_risk) > InjuryScorer().calculate_score(
            high_risk
        )

    def test_monotonic_with_squad_depth(self):
        thin = _make_report(squad_size=10, injury_risk_score=0.3)
        deep = _make_report(squad_size=30, injury_risk_score=0.3)
        assert InjuryScorer().calculate_score(deep) > InjuryScorer().calculate_score(thin)

    def test_oversized_squad_does_not_exceed_full_depth_credit(self):
        report_at_ideal = _make_report(squad_size=25, injury_risk_score=0.2)
        report_oversized = _make_report(squad_size=40, injury_risk_score=0.2)
        assert InjuryScorer().calculate_score(
            report_at_ideal
        ) == pytest.approx(InjuryScorer().calculate_score(report_oversized))

    def test_empty_squad_scores_low_but_valid(self):
        report = _make_report(squad_size=0, injury_risk_score=0.0)
        score = InjuryScorer().calculate_score(report)
        assert 0.0 <= score <= 100.0
