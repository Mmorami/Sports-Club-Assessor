"""
financial_scorer.py
====================
Financial & PSR (Profit and Sustainability Rules) sustainability scorer.

Derives a single 0.0-100.0 health score from a ``ClubAnalysisReport`` by
combining three sub-scores, none of which exist as direct fields on the
schema and are instead computed from ``transfer_balance``, squad market
values, and squad output figures:

- PSR risk proxy      : net transfer spend relative to total squad market
                         value. High spend against a small asset base is
                         treated as elevated PSR breach risk.
- Net spend health     : net transfer spend in absolute terms, scaled
                         against squad value, rewarding clubs operating
                         with a transfer surplus or modest net spend.
- Budget efficiency    : squad output (goals + assists) per GBP of squad
                         market value, rewarding value-for-money squads.

Spec reference: docs/DATA_SCHEMA_SPEC.md (ClubAnalysisReport)
"""

from __future__ import annotations

from src.schemas import ClubAnalysisReport

# Weights must sum to 1.0.
_PSR_RISK_WEIGHT = 0.40
_NET_SPEND_WEIGHT = 0.35
_BUDGET_EFFICIENCY_WEIGHT = 0.25

# Output per GBP1m of squad value considered "excellent" efficiency (caps the sub-score at 100).
_EFFICIENCY_TARGET_PER_MILLION = 0.5


class FinancialScorer:
    """Computes a 0.0-100.0 financial & PSR sustainability score for a club."""

    def calculate_score(self, report: ClubAnalysisReport) -> float:
        squad_value = sum(p.market_value for p in report.club_info.squad_list)
        net_spend = -report.transfer_balance

        psr_score = self._psr_risk_score(net_spend, squad_value)
        spend_score = self._net_spend_score(net_spend, squad_value)
        efficiency_score = self._budget_efficiency_score(
            report.squad_stats_summary.total_goals
            + report.squad_stats_summary.total_assists,
            squad_value,
        )

        total = (
            psr_score * _PSR_RISK_WEIGHT
            + spend_score * _NET_SPEND_WEIGHT
            + efficiency_score * _BUDGET_EFFICIENCY_WEIGHT
        )
        return round(_clamp(total), 2)

    @staticmethod
    def _psr_risk_score(net_spend: float, squad_value: float) -> float:
        """Higher net-spend-to-squad-value ratio => higher PSR risk => lower score."""
        if squad_value <= 0.0:
            return 0.0 if net_spend > 0.0 else 100.0
        ratio = net_spend / squad_value
        # ratio <= 0 (surplus/breakeven) scores full marks; ratio >= 1.0 (spend
        # matches or exceeds total squad value) scores zero.
        return _clamp(100.0 * (1.0 - ratio))

    @staticmethod
    def _net_spend_score(net_spend: float, squad_value: float) -> float:
        """Rewards transfer surplus, tolerates modest net spend, penalizes heavy spend."""
        if net_spend <= 0.0:
            return 100.0
        if squad_value <= 0.0:
            return 0.0
        ratio = net_spend / squad_value
        return _clamp(100.0 * (1.0 - ratio))

    @staticmethod
    def _budget_efficiency_score(total_output: int, squad_value: float) -> float:
        """Goals + assists produced per GBP1m of squad value, scaled to 0-100."""
        if squad_value <= 0.0:
            return 0.0
        squad_value_millions = squad_value / 1_000_000.0
        if squad_value_millions <= 0.0:
            return 0.0
        output_per_million = total_output / squad_value_millions
        return _clamp(100.0 * (output_per_million / _EFFICIENCY_TARGET_PER_MILLION))


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))
