"""Canonical thread identifier validation shared across DeerFlow backends."""

from __future__ import annotations

import re
import uuid
from typing import Annotated

from pydantic import AfterValidator, StringConstraints

THREAD_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
_THREAD_ID_RE = re.compile(THREAD_ID_PATTERN)


def validate_thread_id(thread_id: str) -> str:
    """Return a valid thread ID or raise ``ValueError``.

    Thread IDs are caller-defined opaque identifiers, not necessarily UUIDs,
    but they must be safe for every persistence and filesystem backend.
    """
    if not isinstance(thread_id, str) or _THREAD_ID_RE.fullmatch(thread_id) is None:
        raise ValueError("Invalid thread_id: expected 1-64 ASCII letters, digits, hyphens, or underscores")
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
