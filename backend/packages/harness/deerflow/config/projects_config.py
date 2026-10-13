"""Configuration for user projects (Phase 2: instructions injection, shelf, trash)."""

from __future__ import annotations

import logging
import math
from typing import Any

from annotated_types import Ge, Le
from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)


class ProjectsConfig(BaseModel):
    """User projects: instructions injection bound, shelf index bounds, trash retention.

    ``instructions_max_bytes`` caps project instructions in UTF-8 bytes at write
    time (the gateway rejects oversized values with 422; it never truncates).
    The two ``shelf_index_*`` knobs bound the request-scoped ``<documents>``
    index rendered from each run's pinned shelf snapshot, and
    ``trash_retention_days`` is the window after which trashed documents become
    eligible for the retention purge.
    """

    instructions_max_bytes: int = Field(
        default=8192,
        ge=256,
        le=262144,
        description=("Hard UTF-8 byte cap for project instructions, enforced at write time (422, never truncated). Multi-byte characters count as their UTF-8 byte length, not as characters."),
    )
    shelf_index_max_entries: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Maximum shelf entries rendered into the request-scoped <documents> index per run.",
    )
    shelf_index_max_bytes: int = Field(
        default=4096,
        ge=512,
        le=65536,
        description=("UTF-8 byte cap for the rendered <documents> index, counting IDs, escaped names, the header, the closing tag, separators and the overflow note. Usually binds before the entry cap for CJK names."),
    )
    trash_retention_days: int = Field(
        default=30,
        ge=1,
        le=3650,
        description="Days a trashed project document stays recoverable before the retention sweep may purge it.",
    )

    @model_validator(mode="before")
    @classmethod
    def _drop_invalid_values(cls, data: Any) -> Any:
        """Fall back to the field default (with a warning) for invalid values.

        Mirrors the ``_get_upload_limit`` idiom: a malformed or out-of-bounds
        value in ``config.yaml`` must not crash config loading; the key is
        dropped so the documented default applies. The ``Field(ge=..., le=...)``
        constraints remain the enforcement for direct construction.
        """
        if not isinstance(data, dict):
            return data
        cleaned = dict(data)
        for name, field_info in cls.model_fields.items():
            if name not in cleaned:
                continue
            value = cleaned[name]
            lower = next((m.ge for m in field_info.metadata if isinstance(m, Ge)), None)
            upper = next((m.le for m in field_info.metadata if isinstance(m, Le)), None)
            try:
                # Integer-compatible only: an int (never a bool) or an
                # int-valued FINITE float (the ``_get_upload_limit`` idiom
                # accepts ``8192.0`` the same way). Fractional floats, inf,
                # nan, non-numeric values, and out-of-bounds numbers all fall
                # back — and the coerced int is what stays, so Pydantic never
                # sees the original fractional/overflowing value.
                if isinstance(value, bool):
                    raise ValueError
                if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
                    raise ValueError
                coerced = int(value)
                if (lower is not None and coerced < lower) or (upper is not None and coerced > upper):
                    raise ValueError
            except (TypeError, ValueError, OverflowError):
                logger.warning("Invalid projects.%s value %r; falling back to %d", name, value, field_info.default)
                cleaned.pop(name)
            else:
                cleaned[name] = coerced
        return cleaned
