"""
injury_scorer.py
================
Injury & Availability Scorer.

Produces a single 0.0-100.0 "availability" score from a ``ClubAnalysisReport``,
where higher is better (lower injury risk, deeper squad).

Note on inputs
--------------
``ClubAnalysisReport`` does not carry raw ``MedicalRecord`` data or a
``total_days_missed`` field -- only the pre-normalized ``injury_risk_score``
(0.0-1.0), which ``EFLDataPipeline`` already derives from days/games missed.
That field is therefore reused as the proxy for the "days missed" component
below; no independent day-count is available at this layer.
"""

from __future__ import annotations

from src.schemas import ClubAnalysisReport


class InjuryScorer:
    """Computes an availability score for a club from its analysis report."""

    IDEAL_SQUAD_SIZE = 25

    RISK_WEIGHT = 0.5
    DEPTH_WEIGHT = 0.3
    DAYS_MISSED_WEIGHT = 0.2

    def calculate_score(self, report: ClubAnalysisReport) -> float:
        """Return an availability score in the range [0.0, 100.0].

        Higher scores indicate lower injury risk and a deeper squad.
        """
        risk_component = 1.0 - report.injury_risk_score

        squad_size = report.squad_stats_summary.squad_size
        depth_component = min(squad_size / self.IDEAL_SQUAD_SIZE, 1.0)

        # Proxy for total days missed -- see module docstring.
        days_missed_component = 1.0 - report.injury_risk_score

        weighted = (
            risk_component * self.RISK_WEIGHT
            + depth_component * self.DEPTH_WEIGHT
            + days_missed_component * self.DAYS_MISSED_WEIGHT
        )

        score = weighted * 100.0
        return max(0.0, min(100.0, score))
