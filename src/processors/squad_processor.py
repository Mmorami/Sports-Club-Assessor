"""
squad_processor.py
==================
Deterministic processing engine for filtering transfers and calculating squad vacuum metrics.
"""

from typing import Any, Dict, List
from src.schemas import Transfer, PlayerStats


def filter_relevant_transfers(
    transfers: List[Transfer],
    player_stats: Dict[str, PlayerStats],
    min_minutes: int = 500,
) -> List[Transfer]:
    """
    Filters out transfers of players who logged fewer than min_minutes in the previous season.

    If a player's ID is not present in player_stats, they are assumed to have logged 0 minutes
    (and thus will be filtered out if min_minutes > 0).

    Parameters
    ----------
    transfers : List[Transfer]
        The list of transfers to filter.
    player_stats : Dict[str, PlayerStats]
        A mapping from player ID to their performance stats from the previous season.
    min_minutes : int, default 500
        The minimum number of minutes required to keep the transfer in the list.

    Returns
    -------
    List[Transfer]
        The filtered list of transfers.
    """
    filtered = []
    for transfer in transfers:
        stats = player_stats.get(transfer.player_id)
        minutes = stats.minutes_played if stats is not None else 0
        if minutes >= min_minutes:
            filtered.append(transfer)
    return filtered


def calculate_squad_vacuum(
    transfers_out: List[Transfer],
    player_stats: Dict[str, PlayerStats],
) -> Dict[str, Any]:
    """
    Calculates totals for lost minutes, lost goals, lost assists, and lost appearances
    from departing players.

    A departing player is identified by their presence in the transfers_out list.
    Metrics are aggregated across unique departing players to prevent double counting.

    Parameters
    ----------
    transfers_out : List[Transfer]
        The list of outgoing transfers.
    player_stats : Dict[str, PlayerStats]
        A mapping from player ID to their performance stats from the previous season.

    Returns
    -------
    Dict[str, Any]
        A dictionary containing:
        - "total_lost_minutes": int
        - "total_lost_goals": int
        - "total_lost_assists": int
        - "total_lost_appearances": int
        - "departed_players_count": int
    """
    departing_player_ids = {t.player_id for t in transfers_out}

    total_lost_minutes = 0
    total_lost_goals = 0
    total_lost_assists = 0
    total_lost_appearances = 0

    for player_id in departing_player_ids:
        stats = player_stats.get(player_id)
        if stats is not None:
            total_lost_minutes += stats.minutes_played
            total_lost_goals += stats.goals
            total_lost_assists += stats.assists
            total_lost_appearances += stats.matches_started

    return {
        "total_lost_minutes": total_lost_minutes,
        "total_lost_goals": total_lost_goals,
        "total_lost_assists": total_lost_assists,
        "total_lost_appearances": total_lost_appearances,
        "departed_players_count": len(departing_player_ids),
    }
