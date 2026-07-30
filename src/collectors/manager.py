"""
manager.py
==========
Deterministic club context and manager information collector.

Live mode scrapes Transfermarkt's club squad ("kader") and club profile
("startseite") pages to build a ``Club`` model (roster + current manager).
Mock mode loads the same shape from a local JSON fixture -- used only when
``mock_path`` is explicitly supplied (see ``EFLDataPipeline``).

Data source (live mode)
------------------------
    https://www.transfermarkt.co.uk/{club-slug}/kader/verein/{club-id}/plus/1
    https://www.transfermarkt.co.uk/{club-slug}/startseite/verein/{club-id}

The page is scraped with ``httpx`` + ``BeautifulSoup``. No API key is
required. Same club ID always produces the same request and parse path.

Manager caveat
--------------
Transfermarkt renders the current manager/head-coach widget client-side on
both the squad and club-profile pages -- it is not present in the static
HTML a plain HTTP client receives (no JS execution), unlike the squad table
itself. ``_parse_manager_name`` is kept as a best-effort extractor for pages
where it *is* present in markup; when it isn't, ``manager`` falls back to
``"Unknown"`` rather than raising, consistent with this pipeline's tolerance
for partial TM data (see ``StatsCollector``'s rating/matches_started caveats).
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup, Tag
from pydantic import ValidationError

from src.collectors.base import BaseCollector, NetworkError, ParseError
from src.collectors.transfers import KNOWN_CLUBS
from src.schemas import Club, Player

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

# Squad ("kader") table column layout, detailed view (plus/1):
# cell[0]  = shirt number
# cell[1]      = player image + combined name+position text (hauptlink anchor)
# cell[2]      = blank
# cell[3]      = player name (duplicate -- skip)
# cell[4]      = position text
# cell[5]      = date of birth + age, e.g. "19/12/2000 (25)"
# cell[6]      = nationality flag(s) (<img alt="...">)
# cell[7]      = height (e.g. "1,94m") -- not used
# cell[...]    = foot / joined date / contract expiry -- not used
# cell[-1]     = current market value, e.g. "€18.00m" (class "rechts hauptlink";
#                always the last cell -- column count varies by row/club, so
#                index from the end rather than a fixed position)
_POSITION_IDX = 4
_DOB_AGE_IDX = 5
_NATIONALITY_IDX = 6
_MIN_CELLS = 7

_AGE_RE = re.compile(r"\((\d+)\)")
_VALUE_RE = re.compile(r"[\$£€]?\s*([\d,.]+)\s*(m|th\.?|k)?", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_market_value(raw: str) -> float:
    """Convert a raw Transfermarkt market-value string (e.g. ``"£18.00m"``) to GBP float."""
    cleaned = raw.strip().lower()
    if not cleaned or cleaned in {"-", "?", "n/a"}:
        return 0.0

    match = _VALUE_RE.search(cleaned)
    if not match:
        return 0.0

    number_str = match.group(1).replace(",", "")
    suffix = (match.group(2) or "").lower()
    try:
        value = float(number_str)
    except ValueError:
        return 0.0

    multiplier = {"m": 1_000_000, "k": 1_000, "th": 1_000, "th.": 1_000}.get(suffix, 1)
    return round(value * multiplier, 2)


def _parse_age(raw: str) -> Optional[int]:
    """Extract the parenthesized age from a date-of-birth cell, e.g. ``"(25)"`` -> ``25``."""
    match = _AGE_RE.search(raw)
    return int(match.group(1)) if match else None


def _parse_squad_row(row: Tag) -> Optional[Player]:
    """
    Parse a single ``<tr>`` from the club squad table into a ``Player``
    instance. Returns ``None`` for header rows or rows without a resolvable
    player link.
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

    position = cells[_POSITION_IDX].get_text(strip=True) or "Unknown"
    age = _parse_age(cells[_DOB_AGE_IDX].get_text(strip=True))
    if age is None:
        logger.warning("Skipping row (no parsable age) player=%r", player_name)
        return None

    flag_imgs = cells[_NATIONALITY_IDX].find_all("img")
    nationality = flag_imgs[0].get("title") or flag_imgs[0].get("alt") if flag_imgs else "Unknown"
    nationality = nationality or "Unknown"

    market_value = _parse_market_value(cells[-1].get_text(strip=True))

    try:
        return Player(
            id=player_id,
            name=player_name,
            age=age,
            primary_position=position,
            secondary_positions=[],
            market_value=market_value,
            nationality=nationality,
        )
    except Exception as exc:  # pydantic ValidationError
        logger.warning("Skipping row (schema validation error) player=%r: %s", player_name, exc)
        return None


def _parse_squad_page(html: str) -> List[Player]:
    """Parse the full club squad HTML page and return one ``Player`` per row."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.items")
    if table is None:
        logger.warning("No table.items found on squad page -- cannot parse roster")
        return []

    players: List[Player] = []
    for row in table.find_all("tr"):
        player = _parse_squad_row(row)
        if player is not None:
            players.append(player)

    logger.info("Scraped %d squad members", len(players))
    return players


def _parse_manager_name(html: str) -> Optional[str]:
    """Extract the current manager/head-coach name from a club profile page."""
    soup = BeautifulSoup(html, "html.parser")

    for span in soup.find_all(["span", "th"]):
        label = span.get_text(strip=True).lower()
        if label in {"manager:", "coach:", "trainer:"}:
            value_el = span.find_next_sibling(["span", "td"])
            if value_el:
                link = value_el.find("a")
                text = (link or value_el).get_text(strip=True)
                if text:
                    return text

    link = soup.select_one("a.sb-trainer")
    if link:
        return link.get_text(strip=True)

    return None


def _extract_club_name(html: str) -> str:
    """Extract club name from the page <h1> or <title>."""
    soup = BeautifulSoup(html, "html.parser")

    h1 = soup.select_one("h1.data-header__headline-wrapper")
    if h1:
        return h1.get_text(strip=True)

    title = soup.find("title")
    if title:
        raw = title.get_text(strip=True)
        parts = [p.strip() for p in raw.split("·")]
        if parts:
            return parts[0]

    return ""


# ---------------------------------------------------------------------------
# ManagerClubCollector
# ---------------------------------------------------------------------------


class ManagerClubCollector(BaseCollector):
    """
    Fetches club context including manager info and squad roster.

    In live mode (default), scrapes the club's Transfermarkt squad and
    profile pages. In mock mode (``mock_path`` supplied), loads a local
    JSON fixture instead of making network requests.

    Parameters
    ----------
    mock_path : str or Path, optional
        Path to a mock JSON fixture file (e.g. "data/mock/manager_club_mock.json").
        When ``None`` (default), the collector fetches live data from
        Transfermarkt.
    timeout : int
        HTTP request timeout in seconds (default 20).
    """

    _KADER_URL_TEMPLATE = "{base}/{slug}/kader/verein/{club_id}/plus/1"
    _PROFILE_URL_TEMPLATE = "{base}/{slug}/startseite/verein/{club_id}"

    def __init__(
        self,
        mock_path: Optional[str | Path] = None,
        timeout: int = BaseCollector.DEFAULT_TIMEOUT,
    ) -> None:
        super().__init__(timeout)
        self._mock_path = Path(mock_path) if mock_path else None
        self._clubs: dict[str, Club] | None = None

    def _load_clubs(self) -> dict[str, Club]:
        """Load and cache club data from mock fixture."""
        if self._clubs is not None:
            return self._clubs

        try:
            with open(self._mock_path, "r") as f:
                raw_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            raise ParseError(f"Failed to load mock fixture from {self._mock_path!r}: {e}")

        if isinstance(raw_data, dict):
            raw_data = [raw_data]
        elif not isinstance(raw_data, list):
            raise ParseError(f"Mock data must be a dict or list, got {type(raw_data).__name__}")

        self._clubs = {}
        for item in raw_data:
            try:
                club = Club(**item)
                self._clubs[club.id] = club
            except Exception as e:
                raise ParseError(f"Failed to parse club data: {e}")

        return self._clubs

    def fetch_data(self, club_id: str) -> List[Any]:
        """
        Fetch and return a list containing the Club for *club_id*.

        Parameters
        ----------
        club_id : str
            Unique club identifier (e.g. "c_399") or Transfermarkt numeric
            ID / slug when in live mode.

        Returns
        -------
        List[Any]
            A list containing a single Club instance, or empty list if not found.

        Raises
        ------
        ParseError
            If the mock fixture cannot be loaded or parsed.
        NetworkError
            On HTTP failure while fetching live data.
        """
        if self._mock_path is not None:
            clubs = self._load_clubs()
            return [clubs[club_id]] if club_id in clubs else []

        club = self._fetch_live_club(club_id)
        return [club] if club is not None else []

    def fetch_club_context(self, club_id: str) -> Club | None:
        """
        Fetch and return the Club object for *club_id*.

        Parameters
        ----------
        club_id : str
            Unique club identifier (e.g. "c_399") or Transfermarkt numeric
            ID / slug when in live mode.

        Returns
        -------
        Club or None
            The Club instance if found, otherwise None.

        Raises
        ------
        ParseError
            If the mock fixture cannot be loaded or parsed.
        NetworkError
            On HTTP failure while fetching live data.
        """
        result = self.fetch_data(club_id)
        return result[0] if result else None

    # ------------------------------------------------------------------
    # Live-mode internals
    # ------------------------------------------------------------------

    def _fetch_live_club(self, club_id: str) -> Optional[Club]:
        numeric_id, slug = self._resolve_club(club_id)

        kader_url = self._KADER_URL_TEMPLATE.format(base=BASE_URL, slug=slug, club_id=numeric_id)
        logger.info("Fetching squad: club_id=%r url=%r", club_id, kader_url)
        kader_html = self._get_html(kader_url)

        club_name = _extract_club_name(kader_html) or slug.replace("-", " ").title()
        squad_list = _parse_squad_page(kader_html)

        profile_url = self._PROFILE_URL_TEMPLATE.format(base=BASE_URL, slug=slug, club_id=numeric_id)
        manager_name = None
        try:
            logger.info("Fetching profile: club_id=%r url=%r", club_id, profile_url)
            profile_html = self._get_html(profile_url)
            manager_name = _parse_manager_name(profile_html)
        except NetworkError as exc:
            logger.warning("Could not fetch club profile for %r: %s", club_id, exc)

        if not manager_name:
            logger.warning("No manager found for club_id=%r -- defaulting to 'Unknown'", club_id)
            manager_name = "Unknown"

        if not squad_list:
            logger.warning("No squad members parsed for club_id=%r -- page structure may have changed", club_id)

        try:
            return Club(
                id=club_id,
                name=club_name,
                manager=manager_name,
                squad_list=squad_list,
                transfers_in=[],
                transfers_out=[],
            )
        except ValidationError as exc:
            raise ParseError(f"Failed to build Club for {club_id!r}: {exc}") from exc

    @staticmethod
    def _resolve_club(club_id: str) -> Tuple[str, str]:
        """
        Return ``(numeric_id, slug)`` for the given *club_id*.

        Accepts a numeric Transfermarkt ID, a slug from ``KNOWN_CLUBS``, or
        an internal ``"c_<numeric>"`` id (e.g. ``"c_1003"``).
        """
        raw = club_id[2:] if club_id.startswith("c_") else club_id

        if raw.isdigit():
            slug = next((s for s, cid in KNOWN_CLUBS.items() if cid == raw), raw)
            return raw, slug

        if raw in KNOWN_CLUBS:
            return KNOWN_CLUBS[raw], raw

        raise ParseError(
            f"Unknown club_id {club_id!r}. "
            "Provide a numeric Transfermarkt ID, an internal 'c_<id>' id, or a key from KNOWN_CLUBS.",
            field="club_id",
            raw=club_id,
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
            with httpx.Client(timeout=self._timeout, follow_redirects=True, headers=_HEADERS) as client:
                response = client.get(url)

            if response.status_code != 200:
                raise NetworkError(
                    f"Transfermarkt returned HTTP {response.status_code}", url=url, status=response.status_code
                )

            return response.text

        except NetworkError:
            raise
        except httpx.TimeoutException as exc:
            raise NetworkError(f"Request timed out after {self._timeout}s", url=url) from exc
        except httpx.RequestError as exc:
            raise NetworkError(str(exc), url=url) from exc

    def __repr__(self) -> str:
        return f"ManagerClubCollector(timeout={self._timeout}, mock_path={self._mock_path!r})"
