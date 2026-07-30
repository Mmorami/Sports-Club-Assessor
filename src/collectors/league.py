"""
league.py
=========
Fetches current league standings and extracts club IDs from Transfermarkt.

Live mode scrapes Transfermarkt's league standings table to build an
authoritative list of clubs in a given league for a season. This eliminates
the need for a hardcoded LEAGUE_CLUB_REGISTRY that gets stale.

Data source (live mode)
-----------------------
    https://www.transfermarkt.co.uk/{league-slug}/startseite/wettbewerb/{league-id}

The page is scraped with ``httpx`` + ``BeautifulSoup`` to extract club IDs
from the standings table.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

import httpx
from bs4 import BeautifulSoup

from src.collectors.base import BaseCollector, NetworkError, ParseError

logger = logging.getLogger(__name__)

BASE_URL = "https://www.transfermarkt.co.uk"

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

# Regex to extract club ID from Transfermarkt URLs
# Matches: /verein/{club_id}/ or similar patterns
_CLUB_ID_RE = re.compile(r"/verein/(\d+)")


class LeagueCollector(BaseCollector):
    """
    Fetches the current list of clubs in a league/season from Transfermarkt.

    Parameters
    ----------
    league_id : str
        Transfermarkt league identifier (e.g., 'GB2' for Championship).
    timeout : int
        HTTP request timeout in seconds (default: 10).
    polite_delay : float
        Delay between requests in seconds to be respectful to Transfermarkt
        (default: 1.0).
    """

    def __init__(
        self, league_id: str, timeout: int = 10, polite_delay: float = 1.0
    ) -> None:
        super().__init__(timeout)
        self.league_id = league_id
        self.polite_delay = polite_delay

    def fetch_data(self, club_id: str = None) -> List[str]:
        """
        Fetch club IDs for all teams currently in this league.

        Parameters
        ----------
        club_id : str, ignored
            Not used for league collection (kept for BaseCollector interface).

        Returns
        -------
        List[str]
            List of club IDs (e.g., ['c_399', 'c_1003', ...]).

        Raises
        ------
        NetworkError
            If the HTTP request fails.
        ParseError
            If the standings table cannot be parsed.
        """
        return self._fetch_league_standings()

    def _fetch_league_standings(self) -> List[str]:
        """Fetch and parse the league standings page."""
        # Map league_id to URL slug
        league_slugs = {
            "GB2": "championship",
            "GB1": "premier-league",
        }
        slug = league_slugs.get(self.league_id, self.league_id.lower())

        # URL for the league's main page which includes current season standings
        url = f"{BASE_URL}/{slug}/startseite/wettbewerb/{self.league_id}"

        try:
            response = httpx.get(url, headers=_HEADERS, timeout=self.timeout)
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise NetworkError(
                f"Failed to fetch league standings from {url}",
                url,
                getattr(e.response, "status_code", None),
            ) from e

        return self._parse_standings_table(response.text, url)

    @staticmethod
    def _parse_standings_table(html: str, source_url: str) -> List[str]:
        """
        Parse the standings table and extract club IDs.

        The table structure on Transfermarkt's league page is:
        <table class="items">
          <tbody>
            <tr>
              <td>1</td>  <!-- rank -->
              <td><a href="/verein/{club_id}/...">{club_name}</a></td>
              ...
            </tr>
            ...
          </tbody>
        </table>
        """
        soup = BeautifulSoup(html, "html.parser")

        # Find the standings table (usually the first .items table)
        tables = soup.find_all("table", class_="items")
        if not tables:
            raise ParseError(
                "No standings table found on league page",
                "table.items",
                html[:200],
            )

        club_ids = []
        standings_table = tables[0]
        tbody = standings_table.find("tbody")
        if not tbody:
            raise ParseError(
                "No tbody in standings table",
                "tbody",
                str(standings_table)[:200],
            )

        for row in tbody.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 2:
                continue

            # Second cell typically contains the team link
            team_cell = cells[1]
            team_link = team_cell.find("a")
            if not team_link or not team_link.get("href"):
                continue

            href = team_link.get("href", "")
            match = _CLUB_ID_RE.search(href)
            if match:
                club_id = f"c_{match.group(1)}"
                club_ids.append(club_id)
                logger.debug(f"Extracted {club_id} from {href}")

        if not club_ids:
            raise ParseError(
                "No club IDs extracted from standings table",
                "club links",
                str(standings_table)[:200],
            )

        logger.info(f"Extracted {len(club_ids)} clubs from {source_url}")
        return club_ids

    def __repr__(self) -> str:
        return f"LeagueCollector(league_id={self.league_id!r}, timeout={self.timeout})"
