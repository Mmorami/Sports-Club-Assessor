"""
matrix_engine.py
=================
Hierarchical Weighted Matrix Engine.

Aggregates the individual category scorers (``InjuryScorer``,
``FinancialScorer``, ``TacticalScorer``) into a single normalized overall
rank score for a club, using a configurable weighted matrix.

Spec reference: docs/DATA_SCHEMA_SPEC.md (ClubAnalysisReport, FinalClubRanking)
"""

from __future__ import annotations

from src.schemas import ClubAnalysisReport, FinalClubRanking
from src.scoring.financial_scorer import FinancialScorer
from src.scoring.injury_scorer import InjuryScorer
from src.scoring.tactical_scorer import TacticalScorer

_DEFAULT_INJURY_WEIGHT = 0.35
_DEFAULT_FINANCIAL_WEIGHT = 0.35
_DEFAULT_TACTICAL_WEIGHT = 0.30

_WEIGHT_SUM_TOLERANCE = 1e-6


class MatrixEngine:
    """Combines category scorers into a final weighted club ranking."""

    def __init__(
        self,
        injury_weight: float = _DEFAULT_INJURY_WEIGHT,
        financial_weight: float = _DEFAULT_FINANCIAL_WEIGHT,
        tactical_weight: float = _DEFAULT_TACTICAL_WEIGHT,
    ) -> None:
        weight_total = injury_weight + financial_weight + tactical_weight
        if abs(weight_total - 1.0) > _WEIGHT_SUM_TOLERANCE:
            raise ValueError(
                "Weights must sum to 1.0, got "
                f"injury={injury_weight}, financial={financial_weight}, "
                f"tactical={tactical_weight} (sum={weight_total})"
            )

        self._weights = {
            "injury": injury_weight,
            "financial": financial_weight,
            "tactical": tactical_weight,
        }
        self._scorers = {
            "injury": InjuryScorer(),
            "financial": FinancialScorer(),
            "tactical": TacticalScorer(),
        }

    def evaluate_club(self, report: ClubAnalysisReport) -> FinalClubRanking:
        """Run all category scorers against ``report`` and produce a FinalClubRanking."""
        breakdown: dict[str, float] = {}
        for category, scorer in self._scorers.items():
            try:
                score = scorer.calculate_score(report)
            except Exception:
                # A category scorer failing (e.g. unexpected missing data) must not
                # abort the overall evaluation -- treat it as a neutral zero.
                score = 0.0
            breakdown[category] = _clamp(float(score))

        weighted_components = {
            category: round(breakdown[category] * weight, 4)
            for category, weight in self._weights.items()
        }

        overall_score = _clamp(sum(weighted_components.values()))

        return FinalClubRanking(
            club_id=report.club_info.id,
            overall_score=round(overall_score, 2),
            breakdown=breakdown,
            weighted_components=weighted_components,
        )


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))
