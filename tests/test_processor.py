"""
tests/test_processor.py
========================
Test runner and validation script for the deterministic squad processing engine.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict, List, Any

# Make sure the project root is on sys.path when running as a script
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.schemas import Transfer, PlayerStats, TransferDirection, TransferType
from src.processors.squad_processor import filter_relevant_transfers, calculate_squad_vacuum

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_processor")

# File paths
RAW_TRANSFERS_PATH = _PROJECT_ROOT / "data" / "raw" / "transfers_test.json"
PROCESSED_IMPACT_PATH = _PROJECT_ROOT / "data" / "processed" / "squad_impact_test.json"

# Representative mock stats for key players in transfers_test.json
MOCK_STATS: Dict[str, Dict[str, Any]] = {
    # Outgoing key players
    "tm_538977": {  # Georginio Rutter
        "player_id": "tm_538977",
        "season": "2023/2024",
        "minutes_played": 3662,
        "goals": 7,
        "assists": 15,
        "rating": 7.35,
        "matches_started": 41,
    },
    "tm_922693": {  # Archie Gray
        "player_id": "tm_922693",
        "season": "2023/2024",
        "minutes_played": 3810,
        "goals": 0,
        "assists": 2,
        "rating": 7.10,
        "matches_started": 44,
    },
    "tm_474701": {  # Crysencio Summerville
        "player_id": "tm_474701",
        "season": "2023/2024",
        "minutes_played": 3788,
        "goals": 20,
        "assists": 9,
        "rating": 7.72,
        "matches_started": 41,
    },
    "tm_512385": {  # Luis Sinisterra (Under min_minutes limit)
        "player_id": "tm_512385",
        "season": "2023/2024",
        "minutes_played": 87,  # played very little before transfer/loan
        "goals": 0,
        "assists": 0,
        "rating": 6.20,
        "matches_started": 1,
    },
    "tm_242632": {  # Glen Kamara
        "player_id": "tm_242632",
        "season": "2023/2024",
        "minutes_played": 2890,
        "goals": 0,
        "assists": 3,
        "rating": 6.95,
        "matches_started": 33,
    },
    "tm_336869": {  # Marc Roca (Under min_minutes limit - was on loan)
        "player_id": "tm_336869",
        "season": "2023/2024",
        "minutes_played": 0,
        "goals": 0,
        "assists": 0,
        "rating": 6.00,
        "matches_started": 0,
    },
    # Note: "tm_328784" (Robin Koch) is omitted from stats to test missing stats handling

    # Incoming key players (for filtering verification)
    "tm_297212": {  # Joe Rodon
        "player_id": "tm_297212",
        "season": "2023/2024",
        "minutes_played": 4120,
        "goals": 0,
        "assists": 0,
        "rating": 7.25,
        "matches_started": 46,
    },
    "tm_518644": {  # Largie Ramazani
        "player_id": "tm_518644",
        "season": "2023/2024",
        "minutes_played": 1820,
        "goals": 3,
        "assists": 5,
        "rating": 6.80,
        "matches_started": 20,
    },
}


def run() -> int:
    """Execute processing tests and export results. Returns 0 on success, 1 on failure."""
    logger.info("=" * 60)
    logger.info("Squad Processor Test Suite")
    logger.info("=" * 60)

    # 1. Read transfers_test.json
    if not RAW_TRANSFERS_PATH.exists():
        logger.error("Raw transfers file not found at %s. Please run tests/test_transfer_collector.py first.", RAW_TRANSFERS_PATH)
        return 1

    try:
        with open(RAW_TRANSFERS_PATH, "r", encoding="utf-8") as fh:
            raw_data = json.load(fh)
    except Exception as exc:
        logger.error("Failed to load raw transfer data: %s", exc)
        return 1

    club_name = raw_data.get("club", "unknown")
    season = raw_data.get("season", "unknown")
    raw_transfers = raw_data.get("transfers", [])

    logger.info("Loaded %d raw transfers for %s (%s)", len(raw_transfers), club_name, season)

    # 2. Parse into Pydantic models
    try:
        transfers = [Transfer(**t) for t in raw_transfers]
    except Exception as exc:
        logger.error("Pydantic validation of raw transfers failed: %s", exc)
        return 1

    # 3. Construct PlayerStats objects
    player_stats: Dict[str, PlayerStats] = {}
    for player_id, stat_dict in MOCK_STATS.items():
        try:
            player_stats[player_id] = PlayerStats(**stat_dict)
        except Exception as exc:
            logger.error("Failed to parse mock stats for %s: %s", player_id, exc)
            return 1

    # 4. Run filter_relevant_transfers
    min_minutes = 500
    filtered_transfers = filter_relevant_transfers(transfers, player_stats, min_minutes=min_minutes)
    logger.info("Filtered relevant transfers (min_minutes=%d): %d / %d remaining", min_minutes, len(filtered_transfers), len(transfers))

    # Assertions on filtering logic
    # - tm_538977 (Rutter) has 3662 mins -> should be kept
    # - tm_512385 (Sinisterra) has 87 mins -> should be filtered out
    # - tm_328784 (Koch) has missing stats -> should be filtered out
    rutter_kept = any(t.player_id == "tm_538977" for t in filtered_transfers)
    sinisterra_filtered = not any(t.player_id == "tm_512385" for t in filtered_transfers)
    koch_filtered = not any(t.player_id == "tm_328784" for t in filtered_transfers)

    try:
        assert rutter_kept, "Rutter (3662 mins) should have been kept"
        assert sinisterra_filtered, "Sinisterra (87 mins) should have been filtered out"
        assert koch_filtered, "Koch (missing stats) should have been filtered out"
        logger.info("✓ filter_relevant_transfers assertions passed")
    except AssertionError as exc:
        logger.error("Filter assertion failed: %s", exc)
        return 1

    # 5. Run calculate_squad_vacuum
    # We calculate the vacuum of all departing players
    transfers_out = [t for t in transfers if t.direction == TransferDirection.OUT]
    vacuum_all = calculate_squad_vacuum(transfers_out, player_stats)

    # We also calculate the vacuum of the relevant (filtered) departing players
    filtered_transfers_out = [t for t in filtered_transfers if t.direction == TransferDirection.OUT]
    vacuum_filtered = calculate_squad_vacuum(filtered_transfers_out, player_stats)

    logger.info("Squad Vacuum (All Departures): %s", vacuum_all)
    logger.info("Squad Vacuum (Filtered Departures >= %dm): %s", min_minutes, vacuum_filtered)

    # Assertions on vacuum logic
    # Departing players: Georginio Rutter (tm_538977), Archie Gray (tm_922693), Crysencio Summerville (tm_474701), Luis Sinisterra (tm_512385), Glen Kamara (tm_242632), Marc Roca (tm_336869), Robin Koch (tm_328784), etc.
    # Out of these, the ones with stats in MOCK_STATS:
    # - tm_538977: 3662 mins, 7 goals, 15 assists, 41 starts
    # - tm_922693: 3810 mins, 0 goals, 2 assists, 44 starts
    # - tm_474701: 3788 mins, 20 goals, 9 assists, 41 starts
    # - tm_512385: 87 mins, 0 goals, 0 assists, 1 start
    # - tm_242632: 2890 mins, 0 goals, 3 assists, 33 starts
    # - tm_336869: 0 mins, 0 goals, 0 assists, 0 starts
    # - tm_328784: (missing / 0 stats)
    #
    # Summing all departures (with stats):
    # - minutes: 3662 + 3810 + 3788 + 87 + 2890 + 0 = 14237
    # - goals: 7 + 0 + 20 + 0 + 0 + 0 = 27
    # - assists: 15 + 2 + 9 + 0 + 3 + 0 = 29
    # - appearances (starts): 41 + 44 + 41 + 1 + 33 + 0 = 160
    #
    # Summing filtered departures (minutes >= 500):
    # Only Rutter, Gray, Summerville, Kamara are kept.
    # - minutes: 3662 + 3810 + 3788 + 2890 = 14150
    # - goals: 7 + 0 + 20 + 0 = 27
    # - assists: 15 + 2 + 9 + 3 = 29
    # - appearances (starts): 41 + 44 + 41 + 33 = 159

    try:
        assert vacuum_all["total_lost_minutes"] == 14237, f"Expected 14237 lost minutes for all, got {vacuum_all['total_lost_minutes']}"
        assert vacuum_all["total_lost_goals"] == 27, f"Expected 27 lost goals for all, got {vacuum_all['total_lost_goals']}"
        assert vacuum_all["total_lost_assists"] == 29, f"Expected 29 lost assists for all, got {vacuum_all['total_lost_assists']}"
        assert vacuum_all["total_lost_appearances"] == 160, f"Expected 160 lost appearances for all, got {vacuum_all['total_lost_appearances']}"

        assert vacuum_filtered["total_lost_minutes"] == 14150, f"Expected 14150 lost minutes for filtered, got {vacuum_filtered['total_lost_minutes']}"
        assert vacuum_filtered["total_lost_goals"] == 27, f"Expected 27 lost goals for filtered, got {vacuum_filtered['total_lost_goals']}"
        assert vacuum_filtered["total_lost_assists"] == 29, f"Expected 29 lost assists for filtered, got {vacuum_filtered['total_lost_assists']}"
        assert vacuum_filtered["total_lost_appearances"] == 159, f"Expected 159 lost appearances for filtered, got {vacuum_filtered['total_lost_appearances']}"

        logger.info("✓ calculate_squad_vacuum assertions passed")
    except AssertionError as exc:
        logger.error("Vacuum assertion failed: %s", exc)
        return 1

    # 6. Save results to data/processed/squad_impact_test.json
    PROCESSED_IMPACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    summary_data = {
        "club": club_name,
        "season": season,
        "processed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "filter_params": {
            "min_minutes": min_minutes
        },
        "original_transfers_count": len(transfers),
        "filtered_transfers_count": len(filtered_transfers),
        "vacuum_metrics_all": vacuum_all,
        "vacuum_metrics_filtered": vacuum_filtered,
        "filtered_transfers": [json.loads(t.model_dump_json()) for t in filtered_transfers]
    }

    try:
        with open(PROCESSED_IMPACT_PATH, "w", encoding="utf-8") as fh:
            json.dump(summary_data, fh, indent=2, ensure_ascii=False)
        logger.info("Saved squad impact summary → %s", PROCESSED_IMPACT_PATH)
    except Exception as exc:
        logger.error("Failed to write output JSON: %s", exc)
        return 1

    logger.info("=" * 60)
    logger.info("TESTS PASSED")
    logger.info("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(run())
