"""Structured transform-trail metadata for tool results.

Middlewares that rewrite a ToolMessage between the raw callable boundary and
the model-visible result append a declared entry here, so observers classify
raw→visible transforms from facts instead of sniffing output wording.
Entries are additive and ordered by application: the last entry produced the
final visible bytes.
"""

from __future__ import annotations

TOOL_TRANSFORMS_KEY = "deerflow_tool_transforms"


def append_tool_transform(additional_kwargs: dict, kind: str, *, by: str, version: str = "1") -> None:
    trail = additional_kwargs.get(TOOL_TRANSFORMS_KEY)
    if not isinstance(trail, list):
        trail = []
    additional_kwargs[TOOL_TRANSFORMS_KEY] = [*trail, {"kind": kind, "by": by, "version": version}]


def read_tool_transforms(message: object) -> tuple[dict[str, str], ...]:
    kwargs = getattr(message, "additional_kwargs", None)
    trail = kwargs.get(TOOL_TRANSFORMS_KEY) if isinstance(kwargs, dict) else None
    if not isinstance(trail, list):
        return ()
    return tuple(entry for entry in trail if isinstance(entry, dict) and isinstance(entry.get("kind"), str))
