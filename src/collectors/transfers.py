"""
transfers.py
============
Concrete collector that scrapes summer transfer data for an EFL Championship
club from Transfermarkt and maps the results to ``Transfer`` Pydantic models.

Data source
-----------
Transfermarkt club-transfers page::

    https://www.transfermarkt.co.uk/{club-slug}/transfers/verein/{club-id}/saison_id/{season-year}

The page is scraped with ``httpx`` + ``BeautifulSoup``.  No API key is
required.  All logic is fully deterministic: same club ID + season year
always produces the same request and the same parse path.

Transfermarkt club IDs (numeric)
---------------------------------
You can find any club's numeric ID in the URL when you navigate to their
transfers page on the site.  Common EFL Championship clubs are listed in
``KNOWN_CLUBS`` for convenience.

Usage
-----
.. code-block:: python

    from src.collectors.transfers import TransferCollector

    collector = TransferCollector(season_year=2024)
    transfers = collector.fetch_data("399")        # Leeds United
    # -> List[Transfer]
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup, Tag
from pydantic import ValidationError

from src.schemas import Transfer, TransferDirection, TransferType
from src.collectors.base import BaseCollector, NetworkError, ParseError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://www.transfermarkt.co.uk"

# Polite browser-like headers — required by Transfermarkt (blocks bare urllib)
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

# Mapping of transfer type keywords found in the fee cell → TransferType enum
_FEE_TYPE_MAP: List[Tuple[str, TransferType]] = [
    ("loan", TransferType.LOAN),
    ("free transfer", TransferType.FREE),
    ("end of contract", TransferType.FREE),
    ("released", TransferType.FREE),
    ("undisclosed", TransferType.UNDISCLOSED),
    ("draft", TransferType.UNDISCLOSED),
]

# Regex: strips currency symbols / suffixes, captures numeric value
# e.g. "£8.00m" → 8_000_000.0  |  "£500Th." → 500_000.0
_FEE_RE = re.compile(r"[\$£€]?\s*([\d,.]+)\s*(m|th\.?|k)?", re.IGNORECASE)

# Season string helper
_SEASON_RE = re.compile(r"^(\d{4})$")

# ---------------------------------------------------------------------------
# Well-known EFL Championship Transfermarkt IDs (numeric club IDs)
# ---------------------------------------------------------------------------

KNOWN_CLUBS: Dict[str, str] = {
    "leeds-united": "399",
    "leicester-city": "1003",
    "burnley": "1132",
    "sunderland": "289",
    "sheffield-united": "350",
    "middlesbrough": "1131",
    "coventry-city": "406",
    "millwall": "1145",
    "hull-city": "884",
    "luton-town": "1031",
    "watford": "1010",
    "stoke-city": "877",
    "norwich-city": "276",
    "blackburn-rovers": "164",
    "swansea-city": "2288",
    "cardiff-city": "1148",
    "ipswich-town": "677",        # recently promoted then relegated
    "queens-park-rangers": "1039",
    "plymouth-argyle": "1229",
    "bristol-city": "1139",
    "derby-county": "22",
    "sheffield-wednesday": "380",
    "oxford-united": "368",
    "portsmouth": "392",
}


# ---------------------------------------------------------------------------
# Fee parsing helpers
# ---------------------------------------------------------------------------

def _parse_fee(raw: str) -> Tuple[Optional[float], TransferType]:
    """
    Convert a raw Transfermarkt fee string into ``(fee_gbp, TransferType)``.

    Returns
    -------
    (None, TransferType.FREE)          for "Free Transfer", "Released", etc.
    (None, TransferType.UNDISCLOSED)   for "Undisclosed".
    (None, TransferType.LOAN)          for "Loan fee" or "-" within a loan row.
    (float, TransferType.PERMANENT)    for numeric values like "£8.00m".
    """
    cleaned = raw.strip().lower()

    # Check keyword table first (order matters — "loan" before numeric)
    for keyword, transfer_type in _FEE_TYPE_MAP:
        if keyword in cleaned:
            return (None, transfer_type)

    # Dash / hyphen / empty → treat as undisclosed rather than raising
    if not cleaned or cleaned in {"-", "?", "n/a"}:
        return (None, TransferType.UNDISCLOSED)

    # Numeric parse
    m = _FEE_RE.search(cleaned)
    if m:
        number_str = m.group(1).replace(",", "")
        suffix = (m.group(2) or "").lower()
        try:
            value = float(number_str)
        except ValueError as exc:
            raise ParseError(
                f"Cannot convert fee to float: {raw!r}",
                field="fee",
                raw=raw,
            ) from exc

        multiplier = {"m": 1_000_000, "k": 1_000, "th": 1_000, "th.": 1_000}.get(
            suffix, 1
        )
        return (round(value * multiplier, 2), TransferType.PERMANENT)

    # Fallback
    logger.debug("Unrecognised fee format %r — treating as UNDISCLOSED", raw)
    return (None, TransferType.UNDISCLOSED)


def _season_label(year: int) -> str:
    """Convert start year integer to ``"YYYY/YYYY"`` season label."""
    return f"{year}/{year + 1}"


# ---------------------------------------------------------------------------
# Row parser
# ---------------------------------------------------------------------------

# Live column layout (verified 2024-07 against TM HTML):
# cell[0]  = blank / position icon
# cell[1]  = player image + combined name+position text  (td.hauptlink a lives here)
# cell[2]  = blank
# cell[3]  = player name (duplicate — skip)
# cell[4]  = position text
# cell[5]  = age
# cell[6]  = blank
# cell[7]  = other club name + league  (first <a> = club page link)
# cell[8]  = blank
# cell[9]  = other club name (clean text-only cell)
# cell[10] = league name
# cell[11] = fee
_CLUB_CELL_IDX = 9
_FEE_CELL_IDX = 11
_MIN_CELLS = 12


def _parse_row(
    row: Tag,
    direction: TransferDirection,
    club_name: str,
    season_year: int,
) -> Optional[Transfer]:
    """
    Parse a single ``<tr>`` from a Transfermarkt transfers table into a
    ``Transfer`` instance.

    Returns ``None`` for header rows or rows without a player link.
    """
    cells = row.find_all("td")
    if len(cells) < _MIN_CELLS:
        return None

    # ---- Player identity ------------------------------------------------------
    # The hauptlink anchor is inside cell[1] (player combined block)
    player_link = row.select_one("td.hauptlink a")
    if player_link is None:
        return None

    player_name: str = player_link.get_text(strip=True)
    if not player_name:
        return None

    # Derive a stable player_id from the href, e.g. "/player-name/profil/spieler/12345"
    href: str = player_link.get("href", "")
    player_id_match = re.search(r"/spieler/(\d+)", href)
    if player_id_match:
        player_id = f"tm_{player_id_match.group(1)}"
    else:
        slug = re.sub(r"\W+", "_", player_name).lower()
        player_id = f"tm_{slug}"

    # ---- Other club -----------------------------------------------------------
    # cell[9] holds the clean club-name-only text; cell[7] has a link if needed
    other_club_name = cells[_CLUB_CELL_IDX].get_text(strip=True) or "Unknown"
    if not other_club_name or other_club_name == "-":
        # Fallback: first <a> in cell[7]
        link = cells[7].find("a") if len(cells) > 7 else None
        other_club_name = link.get_text(strip=True) if link else "Unknown"
    other_club_name = other_club_name or "Unknown"

    # ---- Fee ------------------------------------------------------------------
    raw_fee_text = cells[_FEE_CELL_IDX].get_text(strip=True)

    try:
        fee_value, transfer_type = _parse_fee(raw_fee_text)
    except ParseError:
        logger.warning(
            "Skipping row (fee parse error) player=%r fee_raw=%r",
            player_name,
            raw_fee_text,
        )
        return None

    # ---- Assemble Transfer ----------------------------------------------------
    if direction is TransferDirection.IN:
        previous_club = other_club_name
        current_club = club_name
    else:
        previous_club = club_name
        current_club = other_club_name

    try:
        return Transfer(
            player_id=player_id,
            direction=direction,
            fee=fee_value,
            previous_club=previous_club,
            current_club=current_club,
            transfer_type=transfer_type,
        )
    except Exception as exc:  # pydantic ValidationError
        logger.warning(
            "Skipping row (schema validation error) player=%r: %s",
            player_name,
            exc,
        )
        return None


# ---------------------------------------------------------------------------
# Page scraper
# ---------------------------------------------------------------------------

def _scrape_transfers_page(
    html: str,
    club_name: str,
    season_year: int,
) -> List[Transfer]:
    """
    Parse the full Transfermarkt transfers HTML page and return a list of
    ``Transfer`` instances for both directions.

    Strategy
    --------
    TM renders two ``<table class="items">`` elements on the transfers page:
    - ``table[0]`` = Arrivals  → ``TransferDirection.IN``
    - ``table[1]`` = Departures → ``TransferDirection.OUT``

    We verify this mapping against the nearest ``<h2>`` heading; if the
    heading text contains "arrival" / "departure" we bind accordingly,
    otherwise we fall back to positional order (0=IN, 1=OUT).
    """
    soup = BeautifulSoup(html, "html.parser")
    results: List[Transfer] = []

    tables = soup.select("table.items")
    if not tables:
        logger.warning("No table.items found on page — cannot parse transfers")
        return results

    # Build (direction, table) pairs
    paired: List[Tuple[TransferDirection, Any]] = []
    for table in tables[:2]:  # at most 2
        # Walk up the DOM to find the nearest content-box headline
        heading_text = ""
        ancestor = table.parent
        for _ in range(6):  # max 6 levels up
            if ancestor is None:
                break
            h2 = ancestor.find("h2", {"class": "content-box-headline"})
            if h2:
                heading_text = h2.get_text(strip=True).lower()
                break
            ancestor = ancestor.parent

        if "arrival" in heading_text:
            direction = TransferDirection.IN
        elif "departure" in heading_text:
            direction = TransferDirection.OUT
        else:
            # Positional fallback: first = IN, second = OUT
            direction = TransferDirection.IN if not paired else TransferDirection.OUT

        paired.append((direction, table))

    for direction, table in paired:
        for row in table.find_all("tr"):
            transfer = _parse_row(row, direction, club_name, season_year)
            if transfer is not None:
                results.append(transfer)

    logger.info(
        "Scraped %d transfers for %r (season %s)",
        len(results),
        club_name,
        _season_label(season_year),
    )
    return results


# ---------------------------------------------------------------------------
# TransferCollector
# ---------------------------------------------------------------------------


class TransferCollector(BaseCollector):
    """
    Fetches summer transfer data for an EFL Championship club from
    Transfermarkt and returns a list of ``Transfer`` Pydantic models.

    Parameters
    ----------
    season_year : int
        The **start** year of the season (e.g. ``2024`` for 2024/25).
        Defaults to the most recently completed summer window (2024).
    timeout : int
        HTTP request timeout in seconds (default 20).
    polite_delay : float
        Seconds to sleep between retries (default 1.5).  Keeps scraping
        respectful and helps avoid rate-limit blocks.

    Examples
    --------
    .. code-block:: python

        collector = TransferCollector(season_year=2024)

        # Using a known slug (resolved via KNOWN_CLUBS)
        transfers = collector.fetch_data("leeds-united")

        # Using a raw Transfermarkt numeric ID
        transfers = collector.fetch_data("399")          # Leeds United
        transfers = collector.fetch_data("1003")         # Leicester City
    """

    _TM_URL_TEMPLATE = (
        "{base}/{slug}/transfers/verein/{club_id}/saison_id/{year}"
    )

    def __init__(
        self,
        season_year: int = 2024,
        timeout: int = BaseCollector.DEFAULT_TIMEOUT,
        polite_delay: float = 1.5,
        mock_file: Optional[str] = None,
    ) -> None:
        super().__init__(timeout=timeout)
        if not _SEASON_RE.match(str(season_year)):
            raise ValueError(f"season_year must be a 4-digit integer, got {season_year!r}")
        self._season_year = season_year
        self._polite_delay = polite_delay
        self._mock_file = Path(mock_file) if mock_file else None

    def _load_mock_transfers(self) -> List[Transfer]:
        """Load and validate ``Transfer`` fixtures from ``self._mock_file``."""
        with open(self._mock_file, "r", encoding="utf-8") as f:
            raw_records: List[Dict[str, Any]] = json.load(f)

        transfers: List[Transfer] = []
        for raw in raw_records:
            try:
                transfers.append(Transfer(**raw))
            except ValidationError as exc:
                raise ParseError(
                    "Failed to validate transfer record",
                    field="Transfer",
                    raw=raw,
                ) from exc
        return transfers

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def fetch_data(self, club_id: str) -> List[Transfer]:
        """
        Fetch and parse transfers for *club_id*.

        Parameters
        ----------
        club_id : str
            Either a Transfermarkt numeric club ID (``"399"``) or a known
            slug key from ``KNOWN_CLUBS`` (``"leeds-united"``).

        Returns
        -------
        List[Transfer]
            Parsed ``Transfer`` instances.  Empty list if no transfers are
            found or the page is empty.

        Raises
        ------
        NetworkError
            On HTTP failure (non-2xx or connection refused).
        ParseError
            If the page structure has changed enough to prevent any parsing.
        """
        if self._mock_file is not None:
            return self._load_mock_transfers()

        numeric_id, slug = self._resolve_club(club_id)
        url = self._build_url(numeric_id, slug)

        logger.info(
            "Fetching transfers: club_id=%r  url=%r  season=%s",
            club_id,
            url,
            _season_label(self._season_year),
        )

        html = self._get_html(url)
        club_name = self._extract_club_name(html) or slug.replace("-", " ").title()

        transfers = _scrape_transfers_page(html, club_name, self._season_year)

        if not transfers:
            logger.warning(
                "No transfers parsed for club_id=%r — page structure may have changed",
                club_id,
            )

        return transfers

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_club(self, club_id: str) -> Tuple[str, str]:
        """
        Return ``(numeric_id, slug)`` for the given *club_id*.

        Accepts either a numeric ID string or a slug from ``KNOWN_CLUBS``.
        """
        if club_id.isdigit():
            # Reverse-look up slug for URL construction (fallback to id)
            slug = next(
                (s for s, cid in KNOWN_CLUBS.items() if cid == club_id),
                club_id,
            )
            return club_id, slug

        if club_id in KNOWN_CLUBS:
            return KNOWN_CLUBS[club_id], club_id

        raise ParseError(
            f"Unknown club_id {club_id!r}. "
            "Provide a numeric Transfermarkt ID or a key from KNOWN_CLUBS.",
            field="club_id",
            raw=club_id,
        )

    def _build_url(self, numeric_id: str, slug: str) -> str:
        return self._TM_URL_TEMPLATE.format(
            base=BASE_URL,
            slug=slug,
            club_id=numeric_id,
            year=self._season_year,
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

    @staticmethod
    def _extract_club_name(html: str) -> str:
        """Extract club name from the page <title> or heading."""
        soup = BeautifulSoup(html, "html.parser")

        # Try <h1> inside the club header
        h1 = soup.select_one("h1.data-header__headline-wrapper")
        if h1:
            return h1.get_text(strip=True)

        # Fallback: parse <title>
        title = soup.find("title")
        if title:
            # Typical TM title: "Transfers · Leeds United · 2024/25"
            raw = title.get_text(strip=True)
            parts = [p.strip() for p in raw.split("·")]
            if len(parts) >= 2:
                return parts[1]

        return ""

    def __repr__(self) -> str:
        return (
            f"TransferCollector("
            f"season_year={self._season_year}, "
            f"timeout={self._timeout}, "
            f"mock_file={self._mock_file!r})"
        )
