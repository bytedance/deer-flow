"""Shared classification of skill-package files by name and leading bytes.

The installer, the export guard, and SkillScan must agree on which files are
code and which bytes mark an executable, so both rules live only here.
"""

from __future__ import annotations

from pathlib import PurePath, PurePosixPath

#: Filler bytes an executable magic may hide behind: ASCII whitespace (space,
#: tab, LF, CR, vertical tab, form feed) and NUL padding.
_EXEC_SNIFF_FILLER = b" \t\n\r\x0b\x0c\x00"
#: Cap on the leading-filler run the sniff tolerates.
_EXEC_SNIFF_LIMIT = 64

CODE_SUFFIXES = frozenset({".bash", ".bat", ".cjs", ".cmd", ".hta", ".js", ".jse", ".mjs", ".php", ".pl", ".ps1", ".psm1", ".py", ".rb", ".sct", ".sh", ".ts", ".vbe", ".vbs", ".wsf", ".zsh"})
# Full magics per variant — a shorter shared prefix would also match
# non-executable data files.
_EXECUTABLE_MAGIC_PREFIXES = (
    b"\x7fELF",  # ELF
    b"MZ",  # PE/DOS
    b"\xfe\xed\xfa\xce",  # Mach-O 32-bit big-endian
    b"\xfe\xed\xfa\xcf",  # Mach-O 64-bit big-endian
    b"\xce\xfa\xed\xfe",  # Mach-O 32-bit little-endian
    b"\xcf\xfa\xed\xfe",  # Mach-O 64-bit little-endian
    b"\xca\xfe\xba\xbe",  # Mach-O fat binary big-endian
    b"\xbe\xba\xfe\xca",  # Mach-O fat binary little-endian
    b"\xca\xfe\xba\xbf",  # Mach-O fat64 binary big-endian
    b"\xbf\xba\xfe\xca",  # Mach-O fat64 binary little-endian
)


def _posix(path: str | PurePath) -> PurePosixPath:
    return PurePosixPath(str(path).replace("\\", "/"))


def is_code_path(path: str | PurePath) -> bool:
    """Return whether a package-relative path is code by name: a ``scripts/`` member or a code suffix."""
    posix = _posix(path)
    return (bool(posix.parts) and posix.parts[0] == "scripts") or posix.suffix.lower() in CODE_SUFFIXES


def is_code_file(path: str | PurePath, head: bytes) -> bool:
    """Return whether a package file is code; an extensionless file also counts when ``head`` starts with a shebang."""
    return is_code_path(path) or (not _posix(path).suffix and head.startswith(b"#!"))


#: Bytes callers should hand over so a capped whitespace run plus the longest
#: magic always fits the sniff window.
EXEC_SNIFF_BYTES = _EXEC_SNIFF_LIMIT + max(len(magic) for magic in _EXECUTABLE_MAGIC_PREFIXES)


def executable_binary_magic(prefix: bytes) -> bytes | None:
    """Return the executable magic *prefix* starts with, after leading whitespace.

    A binary does not need its magic at byte 0 to be loadable: glibc's
    ``ld.so`` maps segments through the program headers (shebang/whitespace-
    prefixed ELFs are a shipped packaging trick) and the PE loader likewise
    locates sections through the header stored inside the image, so padding
    the magic with spaces or newlines evades an offset-0 probe while leaving
    the payload executable. The tolerated run is capped at
    ``_EXEC_SNIFF_LIMIT`` bytes so indented prose cannot widen the existing
    2-byte ``MZ`` false-positive surface without bound.
    """
    head = prefix[:_EXEC_SNIFF_LIMIT]
    offset = len(head) - len(head.lstrip(_EXEC_SNIFF_FILLER))
    if offset == _EXEC_SNIFF_LIMIT or offset >= len(prefix):
        return None
    return next((magic for magic in _EXECUTABLE_MAGIC_PREFIXES if prefix.startswith(magic, offset)), None)


def is_executable_binary_prefix(prefix: bytes) -> bool:
    """Detect ELF, PE, and Mach-O executables by magic bytes.

    Tolerates a bounded leading run of ASCII whitespace (see
    :func:`executable_binary_magic`); callers passing only a head window
    should provide at least ``EXEC_SNIFF_BYTES`` bytes.
    """
    return executable_binary_magic(prefix) is not None
