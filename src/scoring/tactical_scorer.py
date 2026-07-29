"""
tactical_scorer.py
===================
Tactical & Manager Profile scorer.

Derives a single 0.0-100.0 score from a ``ClubAnalysisReport`` by combining
three sub-scores:

- Manager stability  : ``club_info.manager_tenure_years`` scored against a
                        "sweet spot" tenure band. Very short tenures (little
                        time to implement a system) and very long tenures
                        (risk of stagnation) both score lower than a settled
                        mid-length tenure. Unknown tenure (``None``) scores
                        neutral (50.0), since the schema treats it as
                        optional data that isn't always collected.
- Squad age profile  : ``squad_stats_summary.average_age`` scored against an
                        ideal age band, rewarding squads with a blend of
                        experience and legs, penalizing squads that skew too
                        young (inexperienced) or too old (declining legs).
- Performance trend   : ``performance_trend`` (-1.0 to 1.0) linearly mapped
                        to 0-100. Unknown trend (``None``) scores neutral
                        (50.0).

Spec reference: docs/DATA_SCHEMA_SPEC.md (ClubAnalysisReport)
"""

from __future__ import annotations

from src.schemas import ClubAnalysisReport

# Weights must sum to 1.0.
_MANAGER_TENURE_WEIGHT = 0.30
_SQUAD_AGE_WEIGHT = 0.35
_PERFORMANCE_TREND_WEIGHT = 0.35

_NEUTRAL_SCORE = 50.0

# Manager tenure "sweet spot": full marks between these two values (years).
_TENURE_SWEET_SPOT_LOW = 2.0
_TENURE_SWEET_SPOT_HIGH = 5.0
# Beyond these bounds the tenure score has fully decayed to 0.
_TENURE_FLOOR = 0.0
_TENURE_CEILING = 10.0

# Squad age "ideal" band: full marks between these two values (years).
_AGE_IDEAL_LOW = 24.0
_AGE_IDEAL_HIGH = 27.0
# Beyond these bounds the age score has fully decayed to 0.
_AGE_FLOOR = 18.0
_AGE_CEILING = 34.0


class TacticalScorer:
    """Computes a 0.0-100.0 tactical & manager profile score for a club."""

    def calculate_score(self, report: ClubAnalysisReport) -> float:
        tenure_score = self._manager_tenure_score(
            report.club_info.manager_tenure_years
        )
        age_score = self._squad_age_score(report.squad_stats_summary.average_age)
        trend_score = self._performance_trend_score(report.performance_trend)

        total = (
            tenure_score * _MANAGER_TENURE_WEIGHT
            + age_score * _SQUAD_AGE_WEIGHT
            + trend_score * _PERFORMANCE_TREND_WEIGHT
        )
        return round(_clamp(total), 2)

    @staticmethod
    def _manager_tenure_score(tenure_years: float | None) -> float:
        """Rewards a settled mid-length tenure; penalizes very short or very long ones."""
        if tenure_years is None:
            return _NEUTRAL_SCORE
        if tenure_years <= _TENURE_FLOOR:
            return 0.0
        if _TENURE_SWEET_SPOT_LOW <= tenure_years <= _TENURE_SWEET_SPOT_HIGH:
            return 100.0
        if tenure_years < _TENURE_SWEET_SPOT_LOW:
            span = _TENURE_SWEET_SPOT_LOW - _TENURE_FLOOR
            return _clamp(100.0 * (tenure_years - _TENURE_FLOOR) / span)
        span = _TENURE_CEILING - _TENURE_SWEET_SPOT_HIGH
        if span <= 0.0:
            return 0.0
        return _clamp(100.0 * (1.0 - (tenure_years - _TENURE_SWEET_SPOT_HIGH) / span))

    @staticmethod
    def _squad_age_score(average_age: float) -> float:
        """Rewards a balanced squad age; penalizes squads skewing too young or too old."""
        if _AGE_IDEAL_LOW <= average_age <= _AGE_IDEAL_HIGH:
            return 100.0
        if average_age < _AGE_IDEAL_LOW:
            span = _AGE_IDEAL_LOW - _AGE_FLOOR
            if span <= 0.0:
                return 0.0
            return _clamp(100.0 * (average_age - _AGE_FLOOR) / span)
        span = _AGE_CEILING - _AGE_IDEAL_HIGH
        if span <= 0.0:
            return 0.0
        return _clamp(100.0 * (1.0 - (average_age - _AGE_IDEAL_HIGH) / span))

    @staticmethod
    def _performance_trend_score(trend: float | None) -> float:
        """Linearly maps a -1.0..1.0 trend indicator to a 0-100 score."""
        if trend is None:
            return _NEUTRAL_SCORE
        return _clamp(100.0 * (trend + 1.0) / 2.0)


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))
