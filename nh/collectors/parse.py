"""Coercion helpers that return None instead of inventing a zero.

.claude/rules/data.md rule 6: absent data is NULL, never 0. The prototypes wrote
``int(st.get("viewCount", 0))``, so a video whose stats were hidden became a
real 0 view row — indistinguishable from a genuine flop, and poisonous to every
median, z-score and breakthrough ratio computed downstream.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

_ISO_DURATION = re.compile(r"^P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$")


def as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def as_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.strip().lower()
        if low in {"true", "1", "yes"}:
            return True
        if low in {"false", "0", "no"}:
            return False
        return None
    return bool(value)


def as_utc(value: Any) -> datetime | None:
    """Parse an ISO-8601 / RFC-3339 timestamp to an aware UTC datetime."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def iso_duration_s(value: Any) -> int | None:
    """PT8M31S -> 511. Returns None for a missing or unparseable duration
    rather than 0, which would read as a zero-length video."""
    if not value:
        return None
    match = _ISO_DURATION.match(str(value))
    if not match:
        return None
    days, hours, minutes, seconds = (int(g) if g else 0 for g in match.groups())
    total = days * 86_400 + hours * 3_600 + minutes * 60 + seconds
    return total if any(match.groups()) else None
