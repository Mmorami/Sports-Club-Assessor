"""
cache.py
========
File-backed JSON cache with TTL invalidation.

Payloads are stored one file per key under
``data/cache/{league}/{season}/{key}.json`` so that repeated league runs can
skip redundant HTTP scraping for clubs whose data hasn't gone stale yet.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional


class CacheManager:
    """
    Namespaced file-backed cache for a single ``(league, season)`` pair.

    Parameters
    ----------
    league   : League identifier (e.g. ``"championship"``).
    season   : Season identifier (e.g. ``"2026-2027"``).
    base_dir : Root cache directory. Defaults to ``"data/cache"``.
    """

    def __init__(self, league: str, season: str, base_dir: str = "data/cache") -> None:
        self._dir = Path(base_dir) / league / season
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self._dir / f"{key}.json"

    def get(self, key: str) -> Optional[dict]:
        """Return the cached payload for *key*, or ``None`` if not cached."""
        path = self._path(key)
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as f:
            envelope = json.load(f)
        return envelope.get("data")

    def set(self, key: str, data: dict) -> None:
        """Persist *data* for *key*, stamped with the current write time."""
        envelope = {"cached_at": time.time(), "data": data}
        with self._path(key).open("w", encoding="utf-8") as f:
            json.dump(envelope, f, indent=2)

    def is_expired(self, key: str, ttl_hours: int = 168) -> bool:
        """
        Return ``True`` if *key* has no cached entry, or its entry is older
        than *ttl_hours*.
        """
        path = self._path(key)
        if not path.exists():
            return True
        with path.open("r", encoding="utf-8") as f:
            envelope = json.load(f)
        cached_at = envelope.get("cached_at", 0.0)
        age_hours = (time.time() - cached_at) / 3600.0
        return age_hours > ttl_hours
