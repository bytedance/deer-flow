"""Shared classification of skill-package files by name and leading bytes.

The installer, the export guard, and SkillScan must agree on which files are
code and which bytes mark an executable, so both rules live only here.
"""

from __future__ import annotations

from pathlib import PurePath, PurePosixPath

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
MAX_EXECUTABLE_MAGIC_OFFSET = 63
EXECUTABLE_BINARY_PROBE_BYTES = MAX_EXECUTABLE_MAGIC_OFFSET + max(map(len, _EXECUTABLE_MAGIC_PREFIXES))
_UTF8_BOM = b"\xef\xbb\xbf"
_EXECUTABLE_FILLER_BYTES = frozenset(b"\x00\t\n\v\f\r ")


def _posix(path: str | PurePath) -> PurePosixPath:
    return PurePosixPath(str(path).replace("\\", "/"))


def is_code_path(path: str | PurePath) -> bool:
    """Return whether a package-relative path is code by name: a ``scripts/`` member or a code suffix."""
    posix = _posix(path)
    return (bool(posix.parts) and posix.parts[0] == "scripts") or posix.suffix.lower() in CODE_SUFFIXES


def is_code_file(path: str | PurePath, head: bytes) -> bool:
    """Return whether a package file is code; an extensionless file also counts when ``head`` starts with a shebang."""
    return is_code_path(path) or (not _posix(path).suffix and head.startswith(b"#!"))


def executable_binary_kind(prefix: bytes) -> str | None:
    """Return the executable format at byte zero or after a short filler run.

    A UTF-8 BOM is consumed as one sequence so its final byte cannot combine
    with following bytes to form a different executable magic. Other accepted
    filler is limited to ASCII whitespace and NUL, with an explicit 63-byte
    maximum offset to keep every caller's probe bounded.
    """
    offset = 0
    while offset <= MAX_EXECUTABLE_MAGIC_OFFSET:
        if prefix.startswith(_UTF8_BOM, offset):
            offset += len(_UTF8_BOM)
            continue
        for magic in _EXECUTABLE_MAGIC_PREFIXES:
            if prefix.startswith(magic, offset):
                if magic == b"\x7fELF":
                    return "ELF"
                if magic == b"MZ":
                    return "PE"
                return "Mach-O"
        if offset >= len(prefix) or prefix[offset] not in _EXECUTABLE_FILLER_BYTES:
            return None
        offset += 1
    return None


def is_executable_binary_prefix(prefix: bytes) -> bool:
    """Detect ELF, PE, and Mach-O magic with a bounded leading filler run."""
    return executable_binary_kind(prefix) is not None
