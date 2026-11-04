"""Canonical thread identifier validation shared across DeerFlow backends."""

from __future__ import annotations

import re
import uuid
from typing import Annotated

from pydantic import AfterValidator, StringConstraints

THREAD_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
_THREAD_ID_RE = re.compile(THREAD_ID_PATTERN)

# Windows reserves these device names in every directory, with or without an
# extension ("NUL" and "NUL.txt" both break path creation). Path components
# must stay safe for every filesystem backend, so they are rejected
# unconditionally, case-insensitively, regardless of the host OS.
_WINDOWS_RESERVED_DEVICE_NAMES = frozenset(
    [
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    ]
)


def _is_windows_reserved_name(thread_id: str) -> bool:
    """True if *thread_id* is a Windows reserved device name (extension allowed)."""
    stem = thread_id.split(".", 1)[0]
    return stem.upper() in _WINDOWS_RESERVED_DEVICE_NAMES


def validate_thread_id(thread_id: str) -> str:
    """Return a valid thread ID or raise ``ValueError``.

    Thread IDs are caller-defined opaque identifiers, not necessarily UUIDs,
    but they must be safe for every persistence and filesystem backend.
    """
    if not isinstance(thread_id, str) or _THREAD_ID_RE.fullmatch(thread_id) is None:
        raise ValueError("Invalid thread_id: expected 1-64 ASCII letters, digits, hyphens, or underscores")
    if _is_windows_reserved_name(thread_id):
        raise ValueError(
            f"Invalid thread_id {thread_id!r}: reserved Windows device names are not allowed"
        )
    return thread_id


def resolve_thread_id(thread_id: str | None) -> str:
    """Validate a supplied ID, generating a UUID only when it is ``None``."""
    if thread_id is None:
        return str(uuid.uuid4())
    return validate_thread_id(thread_id)


ThreadId = Annotated[
    str,
    StringConstraints(min_length=1, max_length=64, pattern=THREAD_ID_PATTERN),
    AfterValidator(validate_thread_id),
]
