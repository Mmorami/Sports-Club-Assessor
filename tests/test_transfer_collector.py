"""
tests/test_transfer_collector.py
=================================
Simple integration test / runner for ``TransferCollector``.

What it does
------------
1. Instantiates ``TransferCollector`` for the 2024/25 summer window.
2. Calls ``fetch_data`` for **Leeds United** (Transfermarkt ID ``399``).
3. Asserts basic structural correctness on the returned models.
4. Serialises the results to ``data/raw/transfers_test.json``.

Run from the project root::

    python -m tests.test_transfer_collector

    # or directly:
    python tests/test_transfer_collector.py

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
from src.collectors.transfers import TransferCollector, KNOWN_CLUBS
from src.schemas import Transfer, TransferDirection

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_transfer_collector")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TEST_CLUB_ID = "leeds-united"   # slug key — resolves to numeric TM ID 399
SEASON_YEAR = 2024              # 2024/25 summer window
OUTPUT_PATH = _PROJECT_ROOT / "data" / "raw" / "transfers_test.json"


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _assert_transfer_schema(transfer: Transfer, idx: int) -> None:
    """Run deterministic assertions on a single Transfer instance."""
    assert isinstance(transfer, Transfer), \
        f"[{idx}] Expected Transfer, got {type(transfer)}"
    assert transfer.player_id, \
        f"[{idx}] player_id must be non-empty"
    assert transfer.direction in (TransferDirection.IN, TransferDirection.OUT), \
        f"[{idx}] Unexpected direction: {transfer.direction!r}"
    assert transfer.previous_club, \
        f"[{idx}] previous_club must be non-empty"
    assert transfer.current_club, \
        f"[{idx}] current_club must be non-empty"
    if transfer.fee is not None:
        assert transfer.fee >= 0.0, \
            f"[{idx}] fee must be >= 0, got {transfer.fee}"


def _save_results(transfers: list[Transfer], path: Path) -> None:
    """Serialise transfers to JSON and write to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "club": TEST_CLUB_ID,
        "season": f"{SEASON_YEAR}/{SEASON_YEAR + 1}",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "count": len(transfers),
        "transfers": [json.loads(t.model_dump_json()) for t in transfers],
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    logger.info("Saved %d transfers → %s", len(transfers), path)


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run() -> int:
    """Execute the collector test.  Returns exit code (0 = pass, 1 = fail)."""
    logger.info("=" * 60)
    logger.info("TransferCollector integration test")
    logger.info("Club : %s (ID: %s)", TEST_CLUB_ID, KNOWN_CLUBS.get(TEST_CLUB_ID, "?"))
    logger.info("Season : %d/%d", SEASON_YEAR, SEASON_YEAR + 1)
    logger.info("=" * 60)

    collector = TransferCollector(season_year=SEASON_YEAR)

    # --- Fetch ----------------------------------------------------------------
    try:
        t_start = time.monotonic()
        transfers = collector.fetch_data(TEST_CLUB_ID)
        elapsed = time.monotonic() - t_start
    except NetworkError as exc:
        logger.error("Network failure: %s", exc)
        logger.error("Check your internet connection or Transfermarkt availability.")
        return 1
    except ParseError as exc:
        logger.error("Parse failure: %s", exc)
        return 1
    except CollectorError as exc:
        logger.error("Collector error: %s", exc)
        return 1

    logger.info("Fetched %d transfers in %.2fs", len(transfers), elapsed)

    # --- Schema assertions ----------------------------------------------------
    failures: list[str] = []
    for idx, transfer in enumerate(transfers):
        try:
            _assert_transfer_schema(transfer, idx)
        except AssertionError as exc:
            failures.append(str(exc))

    if failures:
        logger.error("%d assertion(s) failed:", len(failures))
        for f in failures:
            logger.error("  ✗ %s", f)
        return 1

    logger.info("All %d Transfer model assertions passed ✓", len(transfers))

    # --- Direction counts -----------------------------------------------------
    ins = sum(1 for t in transfers if t.direction is TransferDirection.IN)
    outs = len(transfers) - ins
    logger.info("  IN : %d  |  OUT : %d", ins, outs)

    # --- Save -----------------------------------------------------------------
    _save_results(transfers, OUTPUT_PATH)

    # --- Summary --------------------------------------------------------------
    logger.info("-" * 60)
    if transfers:
        logger.info("Sample transfer (first result):")
        logger.info(transfers[0].model_dump_json(indent=2))
    else:
        logger.warning(
            "No transfers returned — page may be empty for this season, "
            "or TM page structure may have changed."
        )

    logger.info("=" * 60)
    logger.info("TEST PASSED")
    logger.info("Output: %s", OUTPUT_PATH)
    logger.info("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(run())
