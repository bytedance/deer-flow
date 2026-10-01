"""Portability checks for host-visible path segments."""

from __future__ import annotations

_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def windows_incompatible_segment(segment: str) -> str | None:
    """Return a reason when *segment* is unsafe to create as a host path component.

    Reserved device names and trailing dots or spaces are rejected on every
    platform when a name is created: uploads, new custom-skill support files,
    and sandbox writes of a path that is not already stored. Reads, deletes of
    an existing support file, and access to a path that already exists on the
    host do not use this check. Those names alias devices or are silently
    stripped on Windows.

    ``.`` and ``..`` are ignored here; callers already reject traversal.
    Do not reject colons, quotes, or control characters here.
    """
    if segment in {"", ".", ".."}:
        return None
    if segment.endswith((" ", ".")):
        return "trailing dot or space"
    stem = segment.split(".", 1)[0]
    if stem.upper() in _WINDOWS_RESERVED_NAMES:
        return "reserved Windows device name"
    return None
