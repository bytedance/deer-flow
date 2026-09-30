"""Portability checks for host-visible path segments."""

from __future__ import annotations

_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def windows_incompatible_segment(segment: str) -> str | None:
    """Return a reason when *segment* is unsafe as a host path component.

    Reserved device names and trailing dots or spaces are rejected on every
    platform. Uploads, custom-skill support files, and local-sandbox paths are
    stored or mapped on the host, including Windows, where those names alias
    devices or are silently stripped. The same check also rejects them inside
    Linux sandbox virtual paths.

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
