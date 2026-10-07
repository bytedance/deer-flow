"""Portability checks for host-visible path segments."""

from __future__ import annotations

import os
from pathlib import Path


def extended_length_path(path: Path) -> Path:
    """Use Windows' extended namespace for local filesystem access.

    Prefix before appending children: even a short root can contain a long
    document filename. Normalize relative segments before adding the prefix;
    extended paths bypass Win32's ordinary path normalization. This is lexical
    only: callers must still resolve symlinks and enforce their own confinement.
    POSIX paths are unchanged. Do not use this spelling for Docker mount sources
    or persisted relative paths.
    """
    if os.name != "nt":
        return path
    absolute = os.path.abspath(path)
    if absolute.startswith("\\\\?\\"):
        return Path(absolute)
    if absolute.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + absolute[2:])
    return Path("\\\\?\\" + absolute)


# Windows also treats the ISO-8859-1 superscript digits ¹, ² and ³ as device numbers.
# https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file
# CONIN$ and CONOUT$ open the console input and output buffers, not ordinary files.
# https://learn.microsoft.com/en-us/windows/console/console-handles
_WINDOWS_RESERVED_NAMES = frozenset({"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {f"COM{i}" for i in "123456789¹²³"} | {f"LPT{i}" for i in "123456789¹²³"})


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
