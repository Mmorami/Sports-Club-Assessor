"""
base.py
=======
Abstract base class and shared exception hierarchy for all pipeline collectors.

All concrete collectors inherit from ``BaseCollector`` and must implement
``fetch_data(club_id: str) -> List[Any]``.  The interface is intentionally
minimal — deterministic, side-effect-free except for the HTTP call and any
file I/O that the caller orchestrates.

Exception hierarchy
-------------------
CollectorError          Root for all collector-specific exceptions.
  NetworkError          Raised on any HTTP / connection failure.
  ParseError            Raised when raw data cannot be mapped to a schema.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, List


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class CollectorError(Exception):
    """Root exception for all collector failures."""


class NetworkError(CollectorError):
    """
    Raised when a collector cannot reach the remote data source.

    Attributes
    ----------
    url     : The URL that failed.
    status  : HTTP status code, if a response was received (else ``None``).
    """

    def __init__(self, message: str, url: str = "", status: int | None = None) -> None:
        super().__init__(message)
        self.url = url
        self.status = status

    def __str__(self) -> str:
        base = super().__str__()
        parts = [base]
        if self.url:
            parts.append(f"url={self.url!r}")
        if self.status is not None:
            parts.append(f"status={self.status}")
        return " | ".join(parts)


class ParseError(CollectorError):
    """
    Raised when raw data from a source cannot be parsed into schema models.

    Attributes
    ----------
    field   : The field or column that caused the failure (if known).
    raw     : The raw value that could not be coerced (if known).
    """

    def __init__(
        self,
        message: str,
        field: str = "",
        raw: Any = None,
    ) -> None:
        super().__init__(message)
        self.field = field
        self.raw = raw

    def __str__(self) -> str:
        base = super().__str__()
        parts = [base]
        if self.field:
            parts.append(f"field={self.field!r}")
        if self.raw is not None:
            parts.append(f"raw={self.raw!r}")
        return " | ".join(parts)


# ---------------------------------------------------------------------------
# Abstract base collector
# ---------------------------------------------------------------------------


class BaseCollector(ABC):
    """
    Contract that every pipeline collector must satisfy.

    Implementors
    ------------
    - ``TransferCollector``   (src/collectors/transfers.py)

    Usage pattern
    -------------
    All public state produced by a collector flows through ``fetch_data()``.
    Callers must not depend on any instance state mutated by the method —
    two calls with the same ``club_id`` must return semantically identical
    results (determinism contract).

    Parameters
    ----------
    timeout : HTTP request timeout in seconds (default 20).
    """

    DEFAULT_TIMEOUT: int = 20

    def __init__(self, timeout: int = DEFAULT_TIMEOUT) -> None:
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def fetch_data(self, club_id: str) -> List[Any]:
        """
        Fetch and return a list of Pydantic model instances for *club_id*.

        Parameters
        ----------
        club_id : Collector-specific club identifier (e.g. a Transfermarkt
                  numeric ID or a slug string).

        Returns
        -------
        List[Any]
            A list of Pydantic model instances.  An empty list is a valid
            result (no data found) and must **not** raise an exception.

        Raises
        ------
        NetworkError
            If the remote source is unreachable or returns a non-2xx response.
        ParseError
            If the raw payload cannot be mapped to the expected schema.
        """

    # ------------------------------------------------------------------
    # Helpers available to all subclasses
    # ------------------------------------------------------------------

    @property
    def timeout(self) -> int:
        """HTTP request timeout in seconds."""
        return self._timeout

    def __repr__(self) -> str:
        return f"{type(self).__name__}(timeout={self._timeout})"
