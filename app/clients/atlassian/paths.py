"""Helpers for building safe Atlassian URLs."""

from typing import Any
from urllib.parse import quote


def seg(value: object) -> str:
    """Encode one path segment so user-supplied keys cannot alter the request path."""
    return quote(str(value), safe="")


def first(items: list[Any] | None) -> Any:
    return items[0] if items else None
