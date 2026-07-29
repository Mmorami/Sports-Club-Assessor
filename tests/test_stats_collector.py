"""
tests/test_stats_collector.py
==============================
Simple integration test / runner for ``StatsCollector``.

What it does
------------
1. Instantiates ``StatsCollector`` for the last 2 seasons.
2. Calls ``fetch_player_stats`` for a sample set of players from our test
   club (Leeds United).
3. Asserts basic structural correctness on the returned models.
4. Serialises the results to ``data/raw/stats_test.json``.

Run from the project root::

    python -m tests.test_stats_collector

    # or directly:
    python tests/test_stats_collector.py

The script exits with code 0 on success, non-zero on failure.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

# Make sure the project root is on sys.path when running as a script
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.collectors.base import CollectorError, NetworkError, ParseError
from src.collectors.stats import StatsCollector
from src.schemas import PlayerStats

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_stats_collector")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TEST_CLUB_ID = "leeds-united"

# Sample player IDs from the test club (Transfermarkt numeric IDs, prefixed
# to match the "tm_" convention produced by TransferCollector). Resolved by
# inspecting the Leeds United squad Leistungsdaten page.
SAMPLE_PLAYER_IDS = [
    "tm_542586",   # Illan Meslier
    "tm_410708",   # Pascal Struijk
    "tm_297212",   # Joe Rodon
]

OUTPUT_PATH = _PROJECT_ROOT / "data" / "raw" / "stats_test.json"


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _assert_stats_schema(stats: PlayerStats, idx: int) -> None:
    """Run deterministic assertions on a single PlayerStats instance."""
    assert isinstance(stats, PlayerStats), \
        f"[{idx}] Expected PlayerStats, got {type(stats)}"
    assert stats.player_id, \
        f"[{idx}] player_id must be non-empty"
    assert "/" in stats.season, \
        f"[{idx}] season must be in YYYY/YYYY format, got {stats.season!r}"
    assert stats.minutes_played >= 0, \
        f"[{idx}] minutes_played must be >= 0"
    assert stats.goals >= 0, \
        f"[{idx}] goals must be >= 0"
    assert stats.assists >= 0, \
        f"[{idx}] assists must be >= 0"
    assert 0.0 <= stats.rating <= 10.0, \
        f"[{idx}] rating must be within 0.0-10.0, got {stats.rating}"
    assert stats.matches_started >= 0, \
        f"[{idx}] matches_started must be >= 0"


def _save_results(all_stats: list[PlayerStats], path: Path) -> None:
    """Serialise stats to JSON and write to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "club": TEST_CLUB_ID,
        "players": SAMPLE_PLAYER_IDS,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "count": len(all_stats),
        "stats": [json.loads(s.model_dump_json()) for s in all_stats],
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    logger.info("Saved %d stats records → %s", len(all_stats), path)


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run() -> int:
    """Execute the collector test. Returns exit code (0 = pass, 1 = fail)."""
    logger.info("=" * 60)
    logger.info("StatsCollector integration test")
    logger.info("Club : %s", TEST_CLUB_ID)
    logger.info("Players : %s", ", ".join(SAMPLE_PLAYER_IDS))
    logger.info("=" * 60)

    collector = StatsCollector(club_id=TEST_CLUB_ID)
    all_stats: list[PlayerStats] = []
    failures: list[str] = []

    for player_id in SAMPLE_PLAYER_IDS:
        try:
            t_start = time.monotonic()
            player_stats = collector.fetch_player_stats(player_id)
            elapsed = time.monotonic() - t_start
        except NetworkError as exc:
            logger.error("Network failure for %s: %s", player_id, exc)
            logger.error("Check your internet connection or Transfermarkt availability.")
            return 1
        except ParseError as exc:
            logger.error("Parse failure for %s: %s", player_id, exc)
            return 1
        except CollectorError as exc:
            logger.error("Collector error for %s: %s", player_id, exc)
            return 1

        logger.info(
            "Fetched %d season(s) for %s in %.2fs",
            len(player_stats),
            player_id,
            elapsed,
        )

        for idx, stats in enumerate(player_stats):
            try:
                _assert_stats_schema(stats, idx)
            except AssertionError as exc:
                failures.append(str(exc))

        all_stats.extend(player_stats)

    if failures:
        logger.error("%d assertion(s) failed:", len(failures))
        for f in failures:
            logger.error("  ✗ %s", f)
        return 1

    logger.info("All %d PlayerStats model assertions passed ✓", len(all_stats))

    # --- Save -----------------------------------------------------------------
    _save_results(all_stats, OUTPUT_PATH)

    # --- Summary --------------------------------------------------------------
    logger.info("-" * 60)
    if all_stats:
        logger.info("Sample stats record (first result):")
        logger.info(all_stats[0].model_dump_json(indent=2))
    else:
        logger.warning(
            "No stats returned — players may have no recorded appearances, "
            "or TM page structure may have changed."
        )

    logger.info("=" * 60)
    logger.info("TEST PASSED")
    logger.info("Output: %s", OUTPUT_PATH)
    logger.info("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(run())
