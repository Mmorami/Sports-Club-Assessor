"""Unit tests for src/scoring/financial_scorer.py — no network I/O, mock models only."""

from __future__ import annotations

import pytest

from src.schemas import (
    Club,
    ClubAnalysisReport,
    Player,
    SquadStatsSummary,
    Transfer,
    TransferDirection,
    TransferType,
)
from src.scoring.financial_scorer import FinancialScorer


def _make_player(player_id: str, market_value: float) -> Player:
    return Player(
        id=player_id,
        name=f"Player {player_id}",
        age=25,
        primary_position="ST",
        secondary_positions=[],
        market_value=market_value,
        nationality="England",
    )


def _make_transfer(
    player_id: str, direction: TransferDirection, fee: float | None
) -> Transfer:
    return Transfer(
        player_id=player_id,
        direction=direction,
        fee=fee,
        previous_club="Some FC",
        current_club="Other FC",
        transfer_type=TransferType.PERMANENT if fee else TransferType.FREE,
    )


def _make_report(
    squad_values: list[float],
    transfers_in_fees: list[float],
    transfers_out_fees: list[float],
    total_goals: int = 10,
    total_assists: int = 10,
) -> ClubAnalysisReport:
    squad_list = [_make_player(f"p_{i}", v) for i, v in enumerate(squad_values)]
    transfers_in = [
        _make_transfer(f"in_{i}", TransferDirection.IN, fee)
        for i, fee in enumerate(transfers_in_fees)
    ]
    transfers_out = [
        _make_transfer(f"out_{i}", TransferDirection.OUT, fee)
        for i, fee in enumerate(transfers_out_fees)
    ]
    club = Club(
        id="club_1",
        name="Test FC",
        manager="Test Manager",
        squad_list=squad_list,
        transfers_in=transfers_in,
        transfers_out=transfers_out,
    )
    transfer_balance = sum(transfers_out_fees) - sum(transfers_in_fees)
    return ClubAnalysisReport(
        club_info=club,
        squad_stats_summary=SquadStatsSummary(
            total_goals=total_goals,
            total_assists=total_assists,
            total_minutes_played=90000,
            average_age=25.0,
            squad_size=len(squad_list),
        ),
        injury_risk_score=0.1,
        transfer_balance=transfer_balance,
    )


def test_score_within_bounds():
    report = _make_report(
        squad_values=[10_000_000, 20_000_000],
        transfers_in_fees=[5_000_000],
        transfers_out_fees=[1_000_000],
    )
    score = FinancialScorer().calculate_score(report)
    assert 0.0 <= score <= 100.0


def test_high_net_spend_low_squad_value_scores_lower_than_surplus_high_value():
    heavy_spend_report = _make_report(
        squad_values=[2_000_000],
        transfers_in_fees=[15_000_000],
        transfers_out_fees=[0],
        total_goals=1,
        total_assists=1,
    )
    surplus_report = _make_report(
        squad_values=[50_000_000],
        transfers_in_fees=[0],
        transfers_out_fees=[10_000_000],
        total_goals=40,
        total_assists=30,
    )

    heavy_spend_score = FinancialScorer().calculate_score(heavy_spend_report)
    surplus_score = FinancialScorer().calculate_score(surplus_report)

    assert surplus_score > heavy_spend_score


def test_empty_squad_does_not_raise_and_returns_valid_float():
    report = _make_report(
        squad_values=[],
        transfers_in_fees=[],
        transfers_out_fees=[],
        total_goals=0,
        total_assists=0,
    )
    score = FinancialScorer().calculate_score(report)
    assert isinstance(score, float)
    assert 0.0 <= score <= 100.0


def test_zero_squad_value_with_positive_spend_scores_zero_on_risk_components():
    report = _make_report(
        squad_values=[0.0],
        transfers_in_fees=[5_000_000],
        transfers_out_fees=[0],
    )
    score = FinancialScorer().calculate_score(report)
    assert score == pytest.approx(0.0)


def test_net_spend_surplus_scores_full_marks_on_spend_component():
    report = _make_report(
        squad_values=[10_000_000],
        transfers_in_fees=[0],
        transfers_out_fees=[5_000_000],
        total_goals=0,
        total_assists=0,
    )
    score = FinancialScorer().calculate_score(report)
    # PSR risk (40%) and net spend (35%) both max out at 100 on surplus;
    # only budget efficiency (25%) can pull the score down.
    assert score >= 75.0
