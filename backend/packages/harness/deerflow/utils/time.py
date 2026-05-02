"""ISO 8601 timestamp helpers for the Gateway and embedded runtime.

DeerFlow stores and serializes thread/run timestamps as ISO 8601 UTC
strings to match the LangGraph Platform schema (see
``langgraph_sdk.schema.Thread``, where ``created_at`` / ``updated_at``
are ``datetime`` and JSON-encode to ISO 8601). All timestamp generation
should funnel through :func:`now_iso` so the wire format stays
consistent across endpoints, the embedded ``RunManager``, and the
checkpoint metadata written by the Gateway.

:func:`coerce_iso` provides a forward-compatible read path for legacy
records that historically stored ``str(time.time())`` floats.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

__all__ = ["coerce_iso", "now_iso"]

_UNIX_TIMESTAMP_PATTERN = re.compile(r"^\d{10}(?:\.\d+)?$")
"""Matches the unix-timestamp string shape historically written by
``str(time.time())`` (10-digit seconds with optional fractional part).
The 10-digit anchor avoids accidentally rewriting ISO years like
``"2026"`` and stays valid until the year 2286.
"""


def now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string.

    Example: ``"2026-04-27T03:19:46.511479+00:00"``.
    """
    return datetime.now(UTC).isoformat()


def coerce_iso(value: object) -> str:
    """Best-effort coerce a stored timestamp to an ISO 8601 string.

    Translates legacy unix-timestamp floats / strings written by older
    DeerFlow versions into ISO without a one-shot migration. ISO strings
    pass through unchanged; ``datetime`` instances are normalised to UTC
    (tz-naive values are assumed to be UTC) and emitted via
    ``isoformat()`` so the wire format always uses the ``T`` separator;
    empty values become ``""``; unrecognised values are stringified as a
    last resort.
    """
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        # ``bool`` is a subclass of ``int`` — treat as garbage, not 0/1.
        return str(value)
    if isinstance(value, datetime):
        # ``datetime`` must be handled before the ``int``/``float`` check;
        # str(datetime) would produce ``"YYYY-MM-DD HH:MM:SS+00:00"``
        # (space separator), which breaks strict ISO 8601 consumers.
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        else:
            value = value.astimezone(UTC)
        return value.isoformat()
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), UTC).isoformat()
        except (ValueError, OverflowError, OSError):
            return str(value)
    if isinstance(value, str):
        if _UNIX_TIMESTAMP_PATTERN.match(value):
            try:
                return datetime.fromtimestamp(float(value), UTC).isoformat()
            except (ValueError, OverflowError, OSError):
                return value
        return value
    return str(value)
