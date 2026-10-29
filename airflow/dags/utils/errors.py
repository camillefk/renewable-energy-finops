"""Project-specific exceptions."""

from __future__ import annotations

from typing import Any, List, Optional


class DataQualityError(Exception):
    """Raised when a payload or a set of rows violates the data quality contract.

    `errors` carries a JSON-serializable list of violations so the DAG can log
    them as structured data (and a future alerting callback can reuse them).
    """

    def __init__(self, message: str, errors: Optional[List[Any]] = None) -> None:
        super().__init__(message)
        self.errors: List[Any] = errors or []

