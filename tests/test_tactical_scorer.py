"""Unit tests for src/scoring/tactical_scorer.py — no network I/O, mock models only."""

from __future__ import annotations

import pytest

from src.schemas import Club, ClubAnalysisReport, SquadStatsSummary
from src.scoring.tactical_scorer import TacticalScorer


def _make_report(
    manager_tenure_years: float | None,
    average_age: float,
    performance_trend: float | None,
    squad_size: int = 25,
) -> ClubAnalysisReport:
    club = Club(
        id="club_1",
        name="Test FC",
        manager="Test Manager",
        manager_tenure_years=manager_tenure_years,
        squad_list=[],
        transfers_in=[],
        transfers_out=[],
    )
    return ClubAnalysisReport(
        club_info=club,
        squad_stats_summary=SquadStatsSummary(
            total_goals=0,
            total_assists=0,
            total_minutes_played=0,
            average_age=average_age,
            squad_size=squad_size,
        ),
        injury_risk_score=0.0,
        transfer_balance=0.0,
        performance_trend=performance_trend,
    )


def test_score_within_bounds():
    report = _make_report(
        manager_tenure_years=3.0, average_age=25.5, performance_trend=0.2
    )
    score = TacticalScorer().calculate_score(report)
    assert 0.0 <= score <= 100.0


def test_ideal_profile_scores_near_maximum():
    report = _make_report(
        manager_tenure_years=3.5, average_age=25.5, performance_trend=1.0
    )
    score = TacticalScorer().calculate_score(report)
    assert score >= 90.0


def test_worst_case_profile_scores_near_minimum():
    report = _make_report(
        manager_tenure_years=0.0, average_age=34.0, performance_trend=-1.0
    )
    score = TacticalScorer().calculate_score(report)
    assert score <= 10.0


def test_new_manager_scores_lower_than_settled_manager():
    new_manager_report = _make_report(
        manager_tenure_years=0.1, average_age=25.5, performance_trend=0.0
    )
    settled_manager_report = _make_report(
        manager_tenure_years=3.0, average_age=25.5, performance_trend=0.0
    )
    assert TacticalScorer().calculate_score(
        settled_manager_report
    ) > TacticalScorer().calculate_score(new_manager_report)


def test_very_long_tenure_scores_lower_than_sweet_spot_tenure():
    long_tenure_report = _make_report(
        manager_tenure_years=12.0, average_age=25.5, performance_trend=0.0
    )
    sweet_spot_report = _make_report(
        manager_tenure_years=4.0, average_age=25.5, performance_trend=0.0
    )
    assert TacticalScorer().calculate_score(
        sweet_spot_report
    ) > TacticalScorer().calculate_score(long_tenure_report)


def test_young_squad_scores_lower_than_ideal_age_squad():
    young_squad_report = _make_report(
        manager_tenure_years=3.0, average_age=19.0, performance_trend=0.0
    )
    ideal_squad_report = _make_report(
        manager_tenure_years=3.0, average_age=26.0, performance_trend=0.0
    )
    assert TacticalScorer().calculate_score(
        ideal_squad_report
    ) > TacticalScorer().calculate_score(young_squad_report)


def test_aging_squad_scores_lower_than_ideal_age_squad():
    aging_squad_report = _make_report(
        manager_tenure_years=3.0, average_age=33.0, performance_trend=0.0
    )
    ideal_squad_report = _make_report(
        manager_tenure_years=3.0, average_age=26.0, performance_trend=0.0
    )
    assert TacticalScorer().calculate_score(
        ideal_squad_report
    ) > TacticalScorer().calculate_score(aging_squad_report)


def test_declining_trend_scores_lower_than_improving_trend():
    declining_report = _make_report(
        manager_tenure_years=3.0, average_age=25.5, performance_trend=-0.8
    )
    improving_report = _make_report(
        manager_tenure_years=3.0, average_age=25.5, performance_trend=0.8
    )
    assert TacticalScorer().calculate_score(
        improving_report
    ) > TacticalScorer().calculate_score(declining_report)


def test_missing_tenure_and_trend_do_not_raise_and_use_neutral_score():
    report = _make_report(
        manager_tenure_years=None, average_age=25.5, performance_trend=None
    )
    score = TacticalScorer().calculate_score(report)
    assert isinstance(score, float)
    assert 0.0 <= score <= 100.0
    # Tenure and trend both fall back to neutral (50.0); only the age
    # component (ideal here) can move the score away from 50.0.
    assert 50.0 <= score <= 100.0


def test_flat_trend_scores_neutral():
    report = _make_report(
        manager_tenure_years=3.5, average_age=25.5, performance_trend=0.0
    )
    score = TacticalScorer().calculate_score(report)
    # Tenure and age both near-max, trend neutral (50.0 * 0.35 weight).
    assert 60.0 <= score <= 85.0


@pytest.mark.parametrize("boundary_age", [24.0, 27.0])
def test_age_ideal_band_boundaries_score_full_marks_on_age_component(boundary_age):
    report = _make_report(
        manager_tenure_years=3.5, average_age=boundary_age, performance_trend=1.0
    )
    score = TacticalScorer().calculate_score(report)
    assert score >= 95.0
