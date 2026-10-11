"""Configuration for user projects (Phase 2: instructions injection, shelf, trash)."""

from __future__ import annotations

import logging
import math
from typing import Any

from annotated_types import Ge, Le
from pydantic import BaseModel, Field, model_validator

from deerflow.config.reload_boundary import format_field_description

logger = logging.getLogger(__name__)


class ProjectsConfig(BaseModel):
    """User projects: instructions injection bound, shelf index bounds, trash retention, document summaries.

    ``instructions_max_bytes`` caps project instructions in UTF-8 bytes at write
    time (the gateway rejects oversized values with 422; it never truncates).
    The two ``shelf_index_*`` knobs bound the request-scoped ``<documents>``
    index rendered from each run's pinned shelf snapshot, and
    ``trash_retention_days`` is the window after which trashed documents become
    eligible for the retention purge. The ``summary_*`` knobs govern the
    best-effort per-document LLM summary pipeline;
    summaries are off by default and rendering of stored summaries is always
    on regardless of the generation switch.
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
    summaries_enabled: bool = Field(
        default=False,
        description=format_field_description(
            "projects.summaries_enabled",
            field_doc="Master switch for per-document LLM summary generation (default off, opt-in). Rendering of already-stored summaries is unaffected by this switch.",
        ),
    )
    summary_max_bytes: int = Field(
        default=256,
        ge=64,
        le=1024,
        description=format_field_description(
            "projects.summary_max_bytes",
            field_doc="Hard UTF-8 write-time cap for a generated document summary; applied at generation time, never at render time.",
        ),
    )
    summary_model_name: str | None = Field(
        default=None,
        description=format_field_description(
            "projects.summary_model_name",
            field_doc="Optional model override for summary generation; None falls back to the default chat model resolution.",
        ),
    )
    summary_concurrency: int = Field(
        default=2,
        ge=1,
        le=16,
        description=format_field_description(
            "projects.summary_concurrency",
            field_doc="Global cap on concurrent summary generation tasks (LLM call plus possible document conversion); excess tasks enter the bounded queue.",
        ),
    )
    summary_queue_size: int = Field(
        default=32,
        ge=1,
        le=256,
        description=format_field_description(
            "projects.summary_queue_size",
            field_doc="Bounded in-memory queue of pending summary generation tasks; tasks arriving at a full queue are skipped.",
        ),
    )
    summary_timeout_seconds: int = Field(
        default=60,
        ge=5,
        le=300,
        description=format_field_description(
            "projects.summary_timeout_seconds",
            field_doc="Caller-side wait limit for one summary model call; abandons the wait (not the remote work), and never covers document conversion.",
        ),
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
            annotation = field_info.annotation
            if annotation is bool:
                # Strict bool: no int/str coercion — anything else falls back.
                if not isinstance(value, bool):
                    logger.warning("Invalid projects.%s value %r; falling back to %r", name, value, field_info.default)
                    cleaned.pop(name)
                continue
            if annotation is not int:
                # Optional-str fields (e.g. summary_model_name): a string or
                # None passes; anything else falls back to the default.
                if value is not None and not isinstance(value, str):
                    logger.warning("Invalid projects.%s value %r; falling back to %r", name, value, field_info.default)
                    cleaned.pop(name)
                continue
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
