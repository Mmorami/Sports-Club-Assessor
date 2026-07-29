"""
schemas.py
==========
Pydantic v2 data schemas for the Championship Squad Tracker pipeline.

Single source of truth for all entity structures.  Contains only model and
enum definitions — zero runtime side-effects, fully deterministic.

Entities
--------
- TransferDirection  (Enum)
- TransferType       (Enum)
- Player
- Transfer
- PlayerStats
- MedicalRecord      (also exported as MedicalHistory for spec compatibility)
- Club
- SquadVacuumResult  (derived / computed — not persisted)

Spec reference: docs/DATA_SCHEMA_SPEC.md
"""

from __future__ import annotations

import re
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

SEASON_PATTERN = re.compile(r"^\d{4}/\d{4}$")


class TransferDirection(str, Enum):
    """Whether a transfer brings a player IN or sends them OUT."""

    IN = "IN"
    OUT = "OUT"


class TransferType(str, Enum):
    """The commercial nature of a transfer transaction."""

    PERMANENT = "PERMANENT"
    LOAN = "LOAN"
    FREE = "FREE"
    UNDISCLOSED = "UNDISCLOSED"


# ---------------------------------------------------------------------------
# Player
# ---------------------------------------------------------------------------


class Player(BaseModel):
    """
    Represents an individual footballer in a Championship squad.

    Fields
    ------
    id                  : Unique player identifier (e.g. ``"p_001"``).
    name                : Full display name.
    age                 : Current age in years (> 0).
    primary_position    : Primary playing position code (e.g. ``"ST"``, ``"GK"``).
    secondary_positions : Additional positions the player can fill (may be empty).
    market_value        : Estimated market value in GBP (>= 0.0).
    nationality         : Player nationality.
    """

    model_config = {"frozen": True, "populate_by_name": True}

    id: str = Field(..., min_length=1, description="Unique player identifier")
    name: str = Field(..., min_length=1, description="Full display name")
    age: int = Field(..., gt=0, description="Current age in years")
    primary_position: str = Field(
        ..., min_length=1, description="Primary playing position code"
    )
    secondary_positions: List[str] = Field(
        default_factory=list,
        description="Additional positions the player can cover",
    )
    market_value: float = Field(
        ..., ge=0.0, description="Estimated market value in GBP"
    )
    nationality: str = Field(..., min_length=1, description="Player nationality")


# ---------------------------------------------------------------------------
# Transfer
# ---------------------------------------------------------------------------


class Transfer(BaseModel):
    """
    Represents a single transfer transaction (incoming or outgoing).

    Fields
    ------
    player_id     : References ``Player.id``.
    direction     : ``IN`` -- player joined; ``OUT`` -- player left.
    fee           : Transfer fee in GBP; ``None`` for free / undisclosed deals.
    previous_club : Club the player transferred from.
    current_club  : Club the player transferred to.
    transfer_type : Nature of the transfer (PERMANENT, LOAN, FREE, UNDISCLOSED).
    """

    model_config = {"frozen": True}

    player_id: str = Field(..., min_length=1, description="References Player.id")
    direction: TransferDirection = Field(
        ..., description="Direction of the transfer relative to the tracking club"
    )
    fee: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Transfer fee in GBP; None for free / undisclosed",
    )
    previous_club: str = Field(..., min_length=1, description="Origin club name")
    current_club: str = Field(..., min_length=1, description="Destination club name")
    transfer_type: TransferType = Field(
        ..., description="Commercial nature of the transfer"
    )

    @model_validator(mode="after")
    def _fee_consistency(self) -> "Transfer":
        """FREE transfers must not carry a positive fee."""
        if (
            self.transfer_type is TransferType.FREE
            and self.fee is not None
            and self.fee > 0.0
        ):
            raise ValueError(
                "A FREE transfer cannot have a positive fee. Set fee=0.0 or fee=None."
            )
        return self


# ---------------------------------------------------------------------------
# PlayerStats
# ---------------------------------------------------------------------------


class PlayerStats(BaseModel):
    """
    Season-level performance statistics for a player.

    Fields
    ------
    player_id       : References ``Player.id``.
    season          : Season identifier in ``"YYYY/YYYY"`` format (e.g. ``"2024/2025"``).
    minutes_played  : Total minutes on the pitch (>= 0).
    goals           : Goals scored (>= 0).
    assists         : Assists provided (>= 0).
    rating          : Average match rating on a 0.0-10.0 scale.
    matches_started : Number of matches started from the XI (>= 0).
    """

    model_config = {"frozen": True}

    player_id: str = Field(..., min_length=1, description="References Player.id")
    season: str = Field(
        ...,
        description='Season identifier, format "YYYY/YYYY" e.g. "2024/2025"',
    )
    minutes_played: int = Field(..., ge=0, description="Total minutes on the pitch")
    goals: int = Field(..., ge=0, description="Goals scored")
    assists: int = Field(..., ge=0, description="Assists provided")
    rating: float = Field(
        ..., ge=0.0, le=10.0, description="Average match rating (0.0-10.0)"
    )
    matches_started: int = Field(..., ge=0, description="Number of matches started")

    @field_validator("season")
    @classmethod
    def _validate_season_format(cls, value: str) -> str:
        if not SEASON_PATTERN.match(value):
            raise ValueError(
                f'season must be in "YYYY/YYYY" format (e.g. "2024/2025"), got: {value!r}'
            )
        start_year, end_year = (int(p) for p in value.split("/"))
        if end_year != start_year + 1:
            raise ValueError(
                f"season end year must be exactly one year after start, got: {value!r}"
            )
        return value


# ---------------------------------------------------------------------------
# MedicalRecord  (also aliased as MedicalHistory per spec)
# ---------------------------------------------------------------------------


class MedicalRecord(BaseModel):
    """
    Individual injury record for a player within a season.

    Fields
    ------
    player_id    : References ``Player.id``.
    injury_type  : Description of the injury (e.g. ``"ACL Tear"``).
    days_out     : Calendar days absent (>= 0).
    games_missed : Competitive matches missed (>= 0).
    season       : Season in which the injury occurred.
    """

    model_config = {"frozen": True}

    player_id: str = Field(..., min_length=1, description="References Player.id")
    injury_type: str = Field(
        ..., min_length=1, description='Injury description (e.g. "Hamstring Strain")'
    )
    days_out: int = Field(..., ge=0, description="Calendar days absent")
    games_missed: int = Field(..., ge=0, description="Competitive matches missed")
    season: str = Field(..., min_length=1, description="Season the injury occurred in")


# Spec uses "MedicalHistory" -- export both names to stay compatible.
MedicalHistory = MedicalRecord


# ---------------------------------------------------------------------------
# Club
# ---------------------------------------------------------------------------


class Club(BaseModel):
    """
    Aggregate entity representing a Championship club and its squad.

    Fields
    ------
    id             : Unique club identifier.
    name           : Official club name.
    manager        : Current head coach / manager.
    squad_list     : Current squad roster (list of ``Player`` objects).
    transfers_in   : Incoming transfers this window.
    transfers_out  : Outgoing transfers this window.
    """

    model_config = {"frozen": True}

    id: str = Field(..., min_length=1, description="Unique club identifier")
    name: str = Field(..., min_length=1, description="Official club name")
    manager: str = Field(..., min_length=1, description="Current head coach / manager")
    squad_list: List[Player] = Field(
        default_factory=list, description="Current squad roster"
    )
    transfers_in: List[Transfer] = Field(
        default_factory=list, description="Incoming transfers this window"
    )
    transfers_out: List[Transfer] = Field(
        default_factory=list, description="Outgoing transfers this window"
    )

    @model_validator(mode="after")
    def _transfers_direction_consistency(self) -> "Club":
        """Guard: transfers_in entries must have direction=IN; transfers_out must be OUT."""
        for t in self.transfers_in:
            if t.direction is not TransferDirection.IN:
                raise ValueError(
                    f"Transfer for player {t.player_id!r} is in transfers_in "
                    f"but has direction={t.direction!r}"
                )
        for t in self.transfers_out:
            if t.direction is not TransferDirection.OUT:
                raise ValueError(
                    f"Transfer for player {t.player_id!r} is in transfers_out "
                    f"but has direction={t.direction!r}"
                )
        return self


# ---------------------------------------------------------------------------
# SquadVacuumResult  (derived / computed -- not a stored entity)
# ---------------------------------------------------------------------------


class SquadVacuumResult(BaseModel):
    """
    Computed output from ``calculate_squad_vacuum()``.

    Not a persisted entity -- produced on demand by the analysis layer.

    Fields
    ------
    total_lost_minutes      : Sum of minutes from all departed players.
    total_lost_goals        : Sum of goals from all departed players.
    total_lost_assists      : Sum of assists from all departed players.
    departed_players_count  : Number of players who left the club.
    """

    model_config = {"frozen": True}

    total_lost_minutes: int = Field(
        ..., ge=0, description="Sum of minutes from departed players"
    )
    total_lost_goals: int = Field(
        ..., ge=0, description="Sum of goals from departed players"
    )
    total_lost_assists: int = Field(
        ..., ge=0, description="Sum of assists from departed players"
    )
    departed_players_count: int = Field(
        ..., ge=0, description="Number of players who left"
    )


# ---------------------------------------------------------------------------
# SquadStatsSummary / ClubAnalysisReport  (derived / computed -- pipeline output)
# ---------------------------------------------------------------------------


class SquadStatsSummary(BaseModel):
    """
    Aggregated performance figures across a club's squad.

    Not a persisted entity -- produced on demand by ``EFLDataPipeline``.

    Fields
    ------
    total_goals           : Sum of goals across all matched player-season stats.
    total_assists         : Sum of assists across all matched player-season stats.
    total_minutes_played  : Sum of minutes played across all matched player-season stats.
    average_age           : Mean age across the current squad roster.
    squad_size            : Number of players in the current squad roster.
    """

    model_config = {"frozen": True}

    total_goals: int = Field(..., ge=0, description="Sum of goals across squad stats")
    total_assists: int = Field(..., ge=0, description="Sum of assists across squad stats")
    total_minutes_played: int = Field(
        ..., ge=0, description="Sum of minutes played across squad stats"
    )
    average_age: float = Field(..., ge=0.0, description="Mean age across the squad roster")
    squad_size: int = Field(..., ge=0, description="Number of players in the squad roster")


class ClubAnalysisReport(BaseModel):
    """
    Unified per-club output of ``EFLDataPipeline.run_club_pipeline``.

    Not a persisted entity -- produced on demand by the integration pipeline.

    Fields
    ------
    club_info             : The club's core context (roster, manager, transfers).
    squad_stats_summary   : Aggregated goals/assists/minutes/age across the squad.
    injury_risk_score     : Normalized 0.0-1.0 score derived from days/games missed.
    transfer_balance      : Net transfer position in GBP (outgoing fees minus
                            incoming fees; positive = net income from sales).
    """

    model_config = {"frozen": True}

    club_info: Club = Field(..., description="Club core context")
    squad_stats_summary: SquadStatsSummary = Field(
        ..., description="Aggregated squad performance figures"
    )
    injury_risk_score: float = Field(
        ..., ge=0.0, le=1.0, description="Normalized injury risk score (0.0-1.0)"
    )
    transfer_balance: float = Field(
        ..., description="Net transfer position in GBP (outgoing fees minus incoming fees)"
    )


# ---------------------------------------------------------------------------
# Public API surface
# ---------------------------------------------------------------------------

__all__ = [
    # Enums
    "TransferDirection",
    "TransferType",
    # Core entities
    "Player",
    "Transfer",
    "PlayerStats",
    "MedicalRecord",
    "MedicalHistory",   # alias -- spec uses this name
    "Club",
    # Derived
    "SquadVacuumResult",
    "SquadStatsSummary",
    "ClubAnalysisReport",
]
