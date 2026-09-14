"""Shared classification of skill-package files by name and leading bytes.

The installer, the export guard, and SkillScan must agree on which files are
code and which bytes mark an executable, so both rules live only here.
"""

from __future__ import annotations

from pathlib import PurePath, PurePosixPath

CODE_SUFFIXES = frozenset({".bash", ".cjs", ".js", ".mjs", ".php", ".pl", ".ps1", ".py", ".rb", ".sh", ".ts", ".zsh"})
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


def is_executable_binary_prefix(prefix: bytes) -> bool:
    """Detect ELF, PE, and Mach-O executables by magic bytes."""
    return prefix.startswith(_EXECUTABLE_MAGIC_PREFIXES)
