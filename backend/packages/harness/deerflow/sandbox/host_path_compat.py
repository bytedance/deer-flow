"""Translate configured host paths to DeerFlow virtual paths.

This module is deliberately independent from the sandbox tools.  Callers can
use it at a boundary where a user or configuration value may still contain a
Windows host spelling, while the rest of DeerFlow continues to use the
configured virtual mount path.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from dataclasses import dataclass

from deerflow.config.sandbox_config import VolumeMountConfig

_WINDOWS_DRIVE_PATH = re.compile(r"^(?P<drive>[A-Za-z]):(?:/|$)")
_GIT_BASH_DRIVE_PATH = re.compile(r"^/(?P<drive>[A-Za-z])(?:/|$)")
_PROGRAM_ARGUMENT_DRIVE = re.compile(r"^[A-Za-z]:")
_PROGRAM_ARGUMENT_TRAVERSAL = re.compile(r"(?:^|[\\/])\.\.(?:[\\/]|$)")
_URL_SCHEME_ANYWHERE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://")
_FILE_URL_SCHEME = re.compile(r"^file://", re.IGNORECASE)

# Match only absolute Windows drive spellings in command text.  POSIX paths
# remain opaque command arguments unless the caller explicitly normalizes one.
_COMMAND_HOST_PATH = re.compile(r"(?<![:A-Za-z0-9_])(?P<path>(?:[A-Za-z]:[\\/]|/[A-Za-z][\\/])[^\s\"';&|<>()\r\n]*)")
_QUOTED_COMMAND_HOST_PATH = re.compile(r"(?<!:)(?P<quote>[\"'])(?P<path>(?:[A-Za-z]:[\\/]|/[A-Za-z][\\/])[^\"'\r\n]*)(?P=quote)")
type MountInput = VolumeMountConfig | Iterable[VolumeMountConfig]


@dataclass(frozen=True, slots=True)
class _Mount:
    host_path: str
    container_path: str
    windows_style: bool


def _permission_error(path: str, reason: str) -> PermissionError:
    return PermissionError(f"Host path is not allowed: {path!r} ({reason})")


def is_windows_host_path_spelling(path: str, *, platform_name: str | None = None) -> bool:
    """Return whether *path* uses a Windows drive or Git Bash spelling.

    ``platform_name`` lets callers retain their own platform-test seam while
    keeping the spelling rules in this boundary module.
    """
    if (os.name if platform_name is None else platform_name) != "nt":
        return False
    normalized = path.replace("\\", "/")
    return bool(_WINDOWS_DRIVE_PATH.match(normalized) or _GIT_BASH_DRIVE_PATH.match(normalized))


def _has_program_path_syntax(value: str) -> bool:
    normalized = value.replace("\\", "/")
    return bool(value) and (normalized.startswith("/") or value.startswith("\\") or _PROGRAM_ARGUMENT_DRIVE.match(normalized) is not None or _PROGRAM_ARGUMENT_TRAVERSAL.search(normalized) is not None)


def _contains_file_url(value: str) -> bool:
    """Return whether an argument's path candidate is a local ``file://`` URL."""
    if not isinstance(value, str) or not value:
        return False

    value = value.strip()
    if not value:
        return False

    # A network URL is opaque even when its query or fragment happens to
    # contain the text ``file://``. Only inspect nested values after an
    # argument separator, response-file marker, or option-colon prefix.
    if _FILE_URL_SCHEME.match(value):
        return True
    if _URL_SCHEME_ANYWHERE.match(value):
        return False
    if value.startswith("@"):
        return _contains_file_url(value[1:])
    if "=" in value:
        candidate = value.split("=", 1)[1]
        if _URL_SCHEME_ANYWHERE.match(candidate) and not _FILE_URL_SCHEME.match(candidate):
            return False
        return _contains_file_url(candidate)

    for index, character in enumerate(value):
        if character == ":" and _FILE_URL_SCHEME.match(value[index + 1 :]):
            return True
    return False


def split_program_argument(value: str) -> tuple[str, str]:
    """Split an option-bearing program argument into prefix and path candidate.

    The candidate may be a complete argument (``C:\\tool.exe``), an option
    value (``--tool=C:\\tool.exe``), a colon option (``/out:C:\\tool.exe``),
    or a response-file argument (``@C:\\args.rsp``). URL values remain opaque.
    """
    if not isinstance(value, str) or not value or _URL_SCHEME_ANYWHERE.search(value):
        return "", value

    if "=" in value:
        prefix, candidate = value.split("=", 1)
        nested_prefix, nested_candidate = split_program_argument(candidate)
        return f"{prefix}={nested_prefix}", nested_candidate

    if value.startswith("@") and _has_program_path_syntax(value[1:]):
        return "@", value[1:]

    if _PROGRAM_ARGUMENT_DRIVE.match(value):
        return "", value

    for index, character in enumerate(value):
        if character != ":" or index == 0 or (index == 1 and value[0].isalpha()):
            continue
        candidate = value[index + 1 :]
        if _has_program_path_syntax(candidate):
            nested_prefix, nested_candidate = split_program_argument(candidate)
            return f"{value[: index + 1]}{nested_prefix}", nested_candidate

    return "", value


def program_argument_candidate(value: str) -> str:
    """Return the path-bearing portion of a program argument."""
    return split_program_argument(value)[1]


def is_program_argument_path(value: str) -> bool:
    """Return whether a program argument contains a rooted, drive, or escape path."""
    if _URL_SCHEME_ANYWHERE.search(value):
        return _contains_file_url(value)
    if _contains_file_url(value):
        return True
    return _has_program_path_syntax(program_argument_candidate(value))


def _canonical_host_path(path: str) -> tuple[str, bool]:
    if not isinstance(path, str) or not path:
        raise _permission_error(str(path), "path must be a non-empty string")

    normalized = path.replace("\\", "/")
    git_bash_match = _GIT_BASH_DRIVE_PATH.match(normalized)
    windows_match = _WINDOWS_DRIVE_PATH.match(normalized)

    if git_bash_match:
        normalized = f"{git_bash_match.group('drive').upper()}:{normalized[2:]}"
        windows_style = True
    elif windows_match:
        normalized = f"{windows_match.group('drive').upper()}:{normalized[2:]}"
        windows_style = True
    elif normalized.startswith("/"):
        windows_style = False
    else:
        raise _permission_error(path, "only absolute paths are supported")

    parts = normalized.split("/")
    if any(part == ".." for part in parts):
        raise _permission_error(path, "path traversal is not allowed")

    if windows_style:
        drive = parts[0]
        tail = [part for part in parts[1:] if part not in {"", "."}]
        return f"{drive}/" + "/".join(tail) if tail else f"{drive}/", True

    tail = [part for part in parts if part not in {"", "."}]
    return "/" + "/".join(tail) if tail else "/", False


def _canonical_container_path(path: str, original: str) -> str:
    normalized = path.replace("\\", "/")
    if re.match(r"^[A-Za-z]:/", normalized) or (os.name == "nt" and re.match(r"^/[A-Za-z](?:/|$)", normalized)):
        raise _permission_error(original, "container_path must not be drive-shaped")
    if not normalized.startswith("/"):
        raise _permission_error(original, "container_path must be absolute")
    parts = normalized.split("/")
    if any(part == ".." for part in parts):
        raise _permission_error(original, "container_path traversal is not allowed")
    tail = [part for part in parts if part not in {"", "."}]
    return "/" + "/".join(tail) if tail else "/"


def _prepare_mounts(mounts: Iterable[VolumeMountConfig]) -> list[_Mount]:
    if isinstance(mounts, VolumeMountConfig):
        mounts = [mounts]
    prepared: list[_Mount] = []
    for mount in mounts:
        host_path, windows_style = _canonical_host_path(mount.host_path)
        prepared.append(
            _Mount(
                host_path=host_path,
                container_path=_canonical_container_path(mount.container_path, mount.container_path),
                windows_style=windows_style,
            )
        )
    return sorted(prepared, key=lambda item: len(item.host_path), reverse=True)


def _is_within(path: str, root: str, *, case_insensitive: bool) -> bool:
    candidate = path.casefold() if case_insensitive else path
    configured = root.casefold() if case_insensitive else root
    if configured == "/" or candidate == configured.rstrip("/"):
        return True
    return candidate.startswith(configured.rstrip("/") + "/")


def _normalize_host_path(path: str, mounts: list[_Mount]) -> str:
    canonical_path, windows_style = _canonical_host_path(path)
    for mount in mounts:
        if mount.windows_style != windows_style:
            continue
        if not _is_within(canonical_path, mount.host_path, case_insensitive=windows_style):
            continue
        if mount.host_path == "/":
            relative = canonical_path.lstrip("/")
        else:
            relative = canonical_path[len(mount.host_path.rstrip("/")) :].lstrip("/")
        return f"{mount.container_path}/{relative}" if relative else mount.container_path
    raise _permission_error(path, "path is outside configured mounts")


def normalize_host_path(path: str, mounts: MountInput) -> str:
    """Map an allowed host path to its configured virtual mount path.

    Windows drive paths, slash-separated Windows paths, and Git Bash
    ``/c/...`` paths are compared case-insensitively.  The returned path always
    uses POSIX separators.  Paths outside every configured mount are rejected.
    """

    return _normalize_host_path(path, _prepare_mounts(mounts))


def replace_host_paths_in_command(command: str, mounts: MountInput) -> str:
    """Replace configured Windows host paths embedded in a command string.

    Quotes, whitespace, shell operators, and all non-path text are preserved.
    A host-looking path that is not under a configured mount raises
    ``PermissionError`` instead of being silently passed through.
    """

    if not command:
        return command
    prepared_mounts = _prepare_mounts(mounts)

    def replace_path(raw_path: str, *, preserve_trailing_space: bool = False) -> str:
        path_without_trailing_space = raw_path.rstrip() if preserve_trailing_space else raw_path
        trailing_space = raw_path[len(path_without_trailing_space) :]
        git_bash_match = _GIT_BASH_DRIVE_PATH.match(path_without_trailing_space)
        if git_bash_match:
            drive = f"{git_bash_match.group('drive').upper()}:"
            has_configured_drive = any(mount.windows_style and mount.host_path.casefold().startswith(drive.casefold()) for mount in prepared_mounts)
            if not has_configured_drive:
                return raw_path
        return _normalize_host_path(path_without_trailing_space, prepared_mounts) + trailing_space

    def replace_quoted(match: re.Match[str]) -> str:
        quote = match.group("quote")
        return f"{quote}{replace_path(match.group('path'))}{quote}"

    def replace(match: re.Match[str]) -> str:
        raw_path = match.group("path")
        prefix = command[: match.start()]
        if re.match(r"^[A-Za-z]://", raw_path) or prefix.endswith(("://", ":/")) or (prefix and prefix[-1].isalnum() and raw_path.startswith("/")):
            return raw_path
        return replace_path(raw_path, preserve_trailing_space=True)

    command = _QUOTED_COMMAND_HOST_PATH.sub(replace_quoted, command)
    return _COMMAND_HOST_PATH.sub(replace, command)


__all__ = [
    "is_program_argument_path",
    "is_windows_host_path_spelling",
    "normalize_host_path",
    "program_argument_candidate",
    "replace_host_paths_in_command",
    "split_program_argument",
]
