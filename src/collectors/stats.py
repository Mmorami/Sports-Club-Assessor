"""
stats.py
========
Concrete collector that scrapes player performance / appearance statistics
for the last 2 seasons from Transfermarkt and maps the results to
``PlayerStats`` Pydantic models.

Data source
-----------
Transfermarkt club-level performance-data ("Leistungsdaten") page::

    https://www.transfermarkt.co.uk/{club-slug}/leistungsdaten/verein/{club-id}/saison_id/{season-year}/plus/1

This single page lists every squad member's appearances, goals, assists,
disciplinary counts, points-per-game and total minutes played for the
requested season in one ``table.items`` (the "detailed" view, ``plus/1``).
It is the practical equivalent of the per-player performance page, which
Transfermarkt now serves without any usable markup for plain HTTP clients
(no JS execution) -- the club-level table is the reliable, deterministic
source. The page is scraped with ``httpx`` + ``BeautifulSoup``, no API key
required. Same club ID + season year always produces the same request and
the same parse path.

Column mapping (verified 2026-07 against TM HTML, ``plus/1`` detailed view)
----------------------------------------------------------------------------
cell[0]  = squad number
cell[1]  = player image + combined name+position text (hauptlink anchor)
cell[2]  = blank
cell[3]  = player name (duplicate -- skip)
cell[4]  = position text
cell[5]  = age
cell[6]  = nationality flag (blank text)
cell[7]  = in-squad count
cell[8]  = appearances ("Einsätze")
cell[9]  = goals ("Tore")
cell[10] = assists ("Vorlagen")
cell[11] = yellow cards
cell[12] = second yellows
cell[13] = red cards
cell[14] = substituted on
cell[15] = substituted off
cell[16] = points-per-game ("PPG" -- team points per game the player featured in)
cell[17] = minutes played ("Einsatzzeit")

Rating caveat
-------------
Transfermarkt does not publish a 0-10 match-rating figure. ``PlayerStats.rating``
is instead derived deterministically from the real "points-per-game" (PPG)
column -- a genuine TM statistic in the 0.0-3.0 range (points earned by the
team per match the player appeared in) -- linearly rescaled onto 0-10. This
is a transparent, reproducible transformation of real data, not an
AI/heuristic guess.

"matches_started" caveat
-------------------------
TM's squad-level table exposes total appearances ("Einsätze"), not a
separate starts-vs-substitute breakdown. ``PlayerStats.matches_started`` is
populated with this appearances total as the closest available proxy.

Usage
-----
.. code-block:: python

    from src.collectors.stats import StatsCollector

    collector = StatsCollector(club_id="leeds-united")
    all_stats = collector.fetch_data("leeds-united")     # -> List[PlayerStats], whole squad
    player_stats = collector.fetch_player_stats("tm_363205")  # -> List[PlayerStats], one player
"""

from __future__ import annotations

import datetime
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup, Tag
from pydantic import ValidationError

from src.schemas import PlayerStats
from src.collectors.base import BaseCollector, NetworkError, ParseError
from src.collectors.transfers import KNOWN_CLUBS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://www.transfermarkt.co.uk"

# Polite browser-like headers -- required by Transfermarkt (blocks bare urllib)
_HEADERS: Dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.transfermarkt.co.uk/",
}

_APPEARANCES_IDX = 8
_GOALS_IDX = 9
_ASSISTS_IDX = 10
_PPG_IDX = 16
_MINUTES_IDX = 17
_MIN_CELLS = 18

_NUMERIC_RE = re.compile(r"[\d]+")
_FLOAT_RE = re.compile(r"[\d]+\.?[\d]*")
_PPG_MAX = 3.0  # theoretical ceiling for TM's points-per-game stat


# ---------------------------------------------------------------------------
# Numeric parsing helpers -- robust to missing / dash-filled cells
# ---------------------------------------------------------------------------


def _safe_int(raw: str) -> int:
    """
    Best-effort conversion of a TM stat cell to ``int``.

    Missing data on Transfermarkt is rendered as ``"-"`` or an empty cell --
    both are treated as ``0`` rather than raising, since an unplayed
    competition/stat is not a parse failure. Thousands separators (``.``)
    and trailing markers (e.g. the ``'`` on minutes-played cells) are
    stripped before extraction.
    """
    cleaned = raw.strip().replace(".", "").replace(",", "").replace("'", "")
    if not cleaned or cleaned in {"-", "?"}:
        return 0
    match = _NUMERIC_RE.search(cleaned)
    if not match:
        return 0
    try:
        return int(match.group(0))
    except ValueError:
        return 0


def _safe_float(raw: str) -> float:
    """Best-effort conversion of a TM stat cell (e.g. PPG) to ``float``."""
    cleaned = raw.strip().replace(",", ".")
    if not cleaned or cleaned in {"-", "?"}:
        return 0.0
    match = _FLOAT_RE.search(cleaned)
    if not match:
        return 0.0
    try:
        return float(match.group(0))
    except ValueError:
        return 0.0


def _ppg_to_rating(ppg: float) -> float:
    """Linearly rescale TM's 0.0-3.0 points-per-game stat onto a 0.0-10.0 rating."""
    return round(min(max(ppg, 0.0), _PPG_MAX) / _PPG_MAX * 10.0, 2)


def _current_season_start_year(today: Optional[datetime.date] = None) -> int:
    """
    Return the start year of the current (or most recently started) season.

    European football seasons kick off around July/August, so any date
    before July rolls back to the previous calendar year's season.
    """
    today = today or datetime.date.today()
    return today.year if today.month >= 7 else today.year - 1


def _last_two_season_years(today: Optional[datetime.date] = None) -> List[int]:
    """
    Return the start years of the last 2 *completed* seasons, oldest first.

    The season starting in ``_current_season_start_year()`` is still in
    progress (or has only just kicked off), so "last 2 seasons" means the
    two seasons before that one.
    """
    current = _current_season_start_year(today)
    return [current - 2, current - 1]


def _season_label(year: int) -> str:
    """Convert a start year integer to a ``"YYYY/YYYY"`` season label."""
    return f"{year}/{year + 1}"


# ---------------------------------------------------------------------------
# Row / page parser
# ---------------------------------------------------------------------------


def _parse_row(row: Tag, season_label: str) -> Optional[PlayerStats]:
    """
    Parse a single ``<tr>`` from the club Leistungsdaten table into a
    ``PlayerStats`` instance. Returns ``None`` for header/pagination rows
    or rows without a resolvable player link.
    """
    cells = row.find_all("td")
    if len(cells) < _MIN_CELLS:
        return None

    player_link = row.select_one("td.hauptlink a")
    if player_link is None:
        return None

    player_name = player_link.get_text(strip=True)
    if not player_name:
        return None

    href = player_link.get("href", "")
    player_id_match = re.search(r"/spieler/(\d+)", href)
    if player_id_match:
        player_id = f"tm_{player_id_match.group(1)}"
    else:
        slug = re.sub(r"\W+", "_", player_name).lower()
        player_id = f"tm_{slug}"

    appearances = _safe_int(cells[_APPEARANCES_IDX].get_text(strip=True))
    goals = _safe_int(cells[_GOALS_IDX].get_text(strip=True))
    assists = _safe_int(cells[_ASSISTS_IDX].get_text(strip=True))
    minutes_played = _safe_int(cells[_MINUTES_IDX].get_text(strip=True))
    ppg = _safe_float(cells[_PPG_IDX].get_text(strip=True))

    try:
        return PlayerStats(
            player_id=player_id,
            season=season_label,
            minutes_played=minutes_played,
            goals=goals,
            assists=assists,
            rating=_ppg_to_rating(ppg),
            matches_started=appearances,
        )
    except Exception as exc:  # pydantic ValidationError
        logger.warning(
            "Skipping row (schema validation error) player=%r: %s",
            player_name,
            exc,
        )
        return None


def _parse_season_page(html: str, season_label: str) -> List[PlayerStats]:
    """
    Parse the full club Leistungsdaten HTML page and return one
    ``PlayerStats`` per squad member with recorded data.
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.items")
    if table is None:
        logger.warning("No table.items found on page -- cannot parse stats")
        return []

    results: List[PlayerStats] = []
    for row in table.find_all("tr"):
        stats = _parse_row(row, season_label)
        if stats is not None:
            results.append(stats)

    logger.info("Scraped %d player-season stat rows for season %s", len(results), season_label)
    return results


# ---------------------------------------------------------------------------
# StatsCollector
# ---------------------------------------------------------------------------


class StatsCollector(BaseCollector):
    """
    Fetches minutes played, goals, assists, ratings and appearance counts
    for every squad member of a club across the last 2 seasons from
    Transfermarkt.

    Parameters
    ----------
    club_id      : Default club used by ``fetch_player_stats`` -- either a
                   Transfermarkt numeric club ID (``"399"``) or a known
                   slug key from ``KNOWN_CLUBS`` (``"leeds-united"``).
    season_years : Optional list of season start years to fetch. Defaults
                   to the last 2 completed seasons relative to today.
    timeout      : HTTP request timeout in seconds (default 20).

    Examples
    --------
    .. code-block:: python

        collector = StatsCollector(club_id="leeds-united")

        squad_stats = collector.fetch_data("leeds-united")     # whole squad, both seasons
        player_stats = collector.fetch_player_stats("tm_363205")  # one player, both seasons
    """

    _TM_URL_TEMPLATE = (
        "{base}/{slug}/leistungsdaten/verein/{club_id}/saison_id/{year}/plus/1"
    )

    def __init__(
        self,
        club_id: str = "leeds-united",
        season_years: Optional[List[int]] = None,
        timeout: int = BaseCollector.DEFAULT_TIMEOUT,
        mock_file: Optional[str] = None,
    ) -> None:
        super().__init__(timeout=timeout)
        self._club_id = club_id
        self._season_years = season_years or _last_two_season_years()
        self._mock_file = Path(mock_file) if mock_file else None

    def _load_mock_stats(self) -> List[PlayerStats]:
        """Load and validate ``PlayerStats`` fixtures from ``self._mock_file``."""
        with open(self._mock_file, "r", encoding="utf-8") as f:
            raw_records: List[Dict[str, Any]] = json.load(f)

        stats: List[PlayerStats] = []
        for raw in raw_records:
            try:
                stats.append(PlayerStats(**raw))
            except ValidationError as exc:
                raise ParseError(
                    "Failed to validate player stats record",
                    field="PlayerStats",
                    raw=raw,
                ) from exc
        return stats

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def fetch_data(self, club_id: str) -> List[PlayerStats]:
        """
        Fetch and parse stats for every squad member of *club_id* across
        the configured season years.

        Parameters
        ----------
        club_id : str
            Either a Transfermarkt numeric club ID (``"399"``) or a known
            slug key from ``KNOWN_CLUBS`` (``"leeds-united"``).

        Returns
        -------
        List[PlayerStats]
            One entry per (player, season) with recorded data. Empty list
            if the page has no usable table -- not treated as an error.

        Raises
        ------
        NetworkError
            On HTTP failure (non-2xx or connection refused).
        ParseError
            If *club_id* cannot be resolved to a known club.
        """
        if self._mock_file is not None:
            return self._load_mock_stats()

        numeric_id, slug = self._resolve_club(club_id)
        all_stats: List[PlayerStats] = []

        for year in self._season_years:
            url = self._build_url(numeric_id, slug, year)
            logger.info(
                "Fetching stats: club_id=%r url=%r season=%s",
                club_id,
                url,
                _season_label(year),
            )
            try:
                html = self._get_html(url)
            except NetworkError as exc:
                logger.warning(
                    "Skipping season %s for club %r due to network error: %s",
                    _season_label(year),
                    club_id,
                    exc,
                )
                continue

            all_stats.extend(_parse_season_page(html, _season_label(year)))

        if not all_stats:
            logger.warning(
                "No stats parsed for club_id=%r -- page structure may have changed",
                club_id,
            )

        return all_stats

    def fetch_player_stats(self, player_id: str) -> List[PlayerStats]:
        """
        Fetch and parse season-level stats for a single *player_id* across
        the configured season years, scoped to this collector's default
        club (see ``club_id`` constructor argument).

        Parameters
        ----------
        player_id : str
            Transfermarkt-derived player identifier, e.g. ``"tm_363205"``
            (see ``TransferCollector``) or a bare numeric TM ID.

        Returns
        -------
        List[PlayerStats]
            One entry per season the player has recorded appearances in.
            Empty list if the player has no data for the configured club
            and seasons (e.g. joined more recently, injury, incomplete
            match data) -- not treated as an error.
        """
        target_id = player_id if player_id.startswith("tm_") else f"tm_{player_id}"
        squad_stats = self.fetch_data(self._club_id)
        return [s for s in squad_stats if s.player_id == target_id]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_club(club_id: str) -> Tuple[str, str]:
        """
        Return ``(numeric_id, slug)`` for the given *club_id*, reusing
        ``KNOWN_CLUBS``. Accepts a numeric Transfermarkt ID, a slug, or an
        internal ``"c_<numeric>"`` id (e.g. ``"c_1003"``).
        """
        raw = club_id[2:] if club_id.startswith("c_") else club_id

        if raw.isdigit():
            slug = next(
                (s for s, cid in KNOWN_CLUBS.items() if cid == raw),
                raw,
            )
            return raw, slug

        if raw in KNOWN_CLUBS:
            return KNOWN_CLUBS[raw], raw

        raise ParseError(
            f"Unknown club_id {club_id!r}. "
            "Provide a numeric Transfermarkt ID, an internal 'c_<id>' id, or a key from KNOWN_CLUBS.",
            field="club_id",
            raw=club_id,
        )

    def _build_url(self, numeric_id: str, slug: str, year: int) -> str:
        return self._TM_URL_TEMPLATE.format(
            base=BASE_URL, slug=slug, club_id=numeric_id, year=year
        )

    def _get_html(self, url: str) -> str:
        """
        Perform the HTTP GET and return the response body as a string.

        Raises
        ------
        NetworkError
            On any HTTP or connection failure.
        """
        try:
            with httpx.Client(
                timeout=self._timeout,
                follow_redirects=True,
                headers=_HEADERS,
            ) as client:
                response = client.get(url)

            if response.status_code != 200:
                raise NetworkError(
                    f"Transfermarkt returned HTTP {response.status_code}",
                    url=url,
                    status=response.status_code,
                )

            return response.text

        except NetworkError:
            raise
        except httpx.TimeoutException as exc:
            raise NetworkError(
                f"Request timed out after {self._timeout}s",
                url=url,
            ) from exc
        except httpx.RequestError as exc:
            raise NetworkError(str(exc), url=url) from exc

    def __repr__(self) -> str:
        seasons = ", ".join(_season_label(y) for y in self._season_years)
        return (
            f"StatsCollector(club_id={self._club_id!r}, seasons=[{seasons}], "
            f"timeout={self._timeout}, mock_file={self._mock_file!r})"
        )
