"""DeerFlow sandbox backed by a Smol Machines VM."""

from __future__ import annotations

import errno
import posixpath
import re
import shlex
import threading
from typing import TYPE_CHECKING

from deerflow.config.paths import VIRTUAL_PATH_PREFIX
from deerflow.sandbox.read_file_contract import split_file_lines
from deerflow.sandbox.remote_list_dir import parse_remote_list_dir_output, remote_list_dir_command
from deerflow.sandbox.remote_search import parse_remote_search_output, remote_search_command
from deerflow.sandbox.sandbox import Sandbox, _validate_extra_env
from deerflow.sandbox.search import GrepMatch, path_matches, should_ignore_path_under_root, truncate_line

if TYPE_CHECKING:
    from smol import Machine

_MAX_DOWNLOAD_SIZE = 100 * 1024 * 1024


class SmolSandbox(Sandbox):
    """One VM for a DeerFlow thread; each command starts a fresh shell."""

    persistent_shell_sessions = False

    def __init__(self, id: str, machine: Machine, *, default_env: dict[str, str] | None = None, default_timeout: float = 600, target: str = "local") -> None:
        super().__init__(id)
        self._machine = machine
        self._target = target
        self._default_env = dict(default_env or {})
        self._default_timeout = default_timeout
        self._lock = threading.Lock()
        self._closed = False

    @property
    def is_closed(self) -> bool:
        with self._lock:
            return self._closed

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._machine.delete()
            self._closed = True

    @staticmethod
    def _resolve_path(path: str) -> str:
        if not isinstance(path, str) or not path or not path.startswith("/") or path.startswith("//"):
            raise ValueError("sandbox paths must be absolute")
        if any(part == ".." for part in path.replace("\\", "/").split("/")):
            raise PermissionError(f"Access denied: path traversal detected in {path!r}")
        return path

    def _resolve_file_path(self, path: str) -> str:
        resolved = self._resolve_path(path)
        # Cloud's file route can reinterpret URL delimiters and control bytes.
        if self._target == "cloud" and (any(char in resolved for char in "?#%") or any(ord(char) < 32 or ord(char) == 127 for char in resolved)):
            raise ValueError(f"Smol Cloud file path cannot contain ?, #, %, or control characters: {path!r}")
        return resolved

    def _exec(self, command: list[str], *, env: dict[str, str] | None = None, timeout: float | None = None):
        from smol import ExecOptions

        with self._lock:
            if self._closed:
                raise RuntimeError("sandbox has been closed")
            return self._machine.exec(command, ExecOptions(env=env, timeout=timeout))

    def _sh(self, script: str, *, env: dict[str, str] | None = None, timeout: float | None = None):
        return self._exec(["sh", "-lc", script], env=env, timeout=timeout)

    def execute_command(self, command: str, env: dict[str, str] | None = None, timeout: float | None = None) -> str:
        _validate_extra_env(env)
        try:
            result = self._sh(command, env={**self._default_env, **(env or {})} or None, timeout=timeout if timeout is not None else self._default_timeout)
        except Exception as exc:
            return f"Error: {exc}"
        output = "\n".join(part for part in (result.stdout, result.stderr) if part)
        if result.exit_code != 0:
            output = f"{output}\nExit Code: {result.exit_code}" if output else f"Command exited with code {result.exit_code}"
        return output or "(no output)"

    def read_file(self, path: str, start_line: int | None = None, end_line: int | None = None) -> str:
        resolved = self._resolve_file_path(path)
        try:
            with self._lock:
                if self._closed:
                    raise RuntimeError("sandbox has been closed")
                content = self._machine.read_file(resolved).decode("utf-8", "replace")
        except Exception as exc:
            return f"Error: {exc}"
        if start_line is None and end_line is None:
            return content
        lines = split_file_lines(content)
        start = max(start_line or 1, 1)
        end = max(end_line, 0) if end_line is not None else len(lines)
        return "\n".join(lines[start - 1 : end])

    def write_file(self, path: str, content: str, append: bool = False) -> None:
        self._write(path, content.encode("utf-8"), append=append)

    def update_file(self, path: str, content: bytes) -> None:
        self._write(path, content, append=False)

    def _write(self, path: str, content: bytes, *, append: bool) -> None:
        resolved = self._resolve_file_path(path)
        with self._lock:
            if self._closed:
                raise RuntimeError("sandbox has been closed")
            # The native file write uses the same image overlay as exec. Hold
            # the lock over append's read and write to preserve concurrent appends.
            if append:
                try:
                    content = self._machine.read_file(resolved) + content
                except Exception as exc:
                    if getattr(exc, "code", None) != "NOT_FOUND":
                        raise
            parent = posixpath.dirname(resolved)
            created = self._machine.exec(["mkdir", "-p", parent])
            if created.exit_code != 0:
                raise OSError(f"Cannot create {parent}: {created.stderr}")
            self._machine.write_file(resolved, content)

    def download_file(self, path: str) -> bytes:
        resolved = self._resolve_file_path(path)
        if resolved != VIRTUAL_PATH_PREFIX and not resolved.startswith(f"{VIRTUAL_PATH_PREFIX}/"):
            raise PermissionError(f"Access denied: path must be under {VIRTUAL_PATH_PREFIX!r}: {path!r}")
        try:
            with self._lock:
                if self._closed:
                    raise RuntimeError("sandbox has been closed")
                content = self._machine.read_file(resolved)
        except Exception as exc:
            raise OSError(f"cannot read {path!r} from sandbox: {exc}") from exc
        if len(content) > _MAX_DOWNLOAD_SIZE:
            raise OSError(errno.EFBIG, f"File exceeds maximum download size of {_MAX_DOWNLOAD_SIZE} bytes", path)
        return content

    def list_dir(self, path: str, max_depth: int = 2) -> list[str]:
        resolved = self._resolve_path(path)
        result = self._sh(remote_list_dir_command(resolved, max_depth))
        return parse_remote_list_dir_output(result.stdout, resolved, pipeline_exit_code=result.exit_code)

    def glob(self, path: str, pattern: str, *, include_dirs: bool = False, max_results: int = 200) -> tuple[list[str], bool]:
        resolved = self._resolve_path(path)
        types = ("f", "d") if include_dirs else ("f",)
        type_expr = " -o ".join(f"-type {kind}" for kind in types)
        hard_limit = max(max_results * 4, max_results + 50)
        search = f"find -H {shlex.quote(resolved)} \\( {type_expr} \\) -print 2>/dev/null"
        result = self._sh(remote_search_command(search, resolved, limit=hard_limit))
        output = parse_remote_search_output(result.stdout, resolved, tool="find", limit=hard_limit)
        matches: list[str] = []
        root = resolved.rstrip("/") or "/"
        root_prefix = root if root == "/" else f"{root}/"
        for entry in output.text.split("\n"):
            if not entry or (entry != root and not entry.startswith(root_prefix)) or should_ignore_path_under_root(entry, root):
                continue
            relative = entry[len(root) :].lstrip("/")
            if relative and path_matches(pattern, relative):
                matches.append(entry)
                if len(matches) > max_results:
                    return matches[:max_results], True
        return matches, output.truncated

    def grep(self, path: str, pattern: str, *, glob: str | None = None, literal: bool = False, case_sensitive: bool = False, max_results: int = 100) -> tuple[list[GrepMatch], bool]:
        if not literal:
            re.compile(pattern, 0 if case_sensitive else re.IGNORECASE)
        resolved = self._resolve_path(path)
        flags = ["-r", "-H", "-n", "-I"]
        if not case_sensitive:
            flags.append("-i")
        flags.append("-F" if literal else "-E")
        hard_limit = max(max_results * 4, max_results + 50)
        search = "grep " + " ".join(flags) + f" -e {shlex.quote(pattern)} {shlex.quote(resolved)} 2>/dev/null"
        result = self._sh(remote_search_command(search, resolved, limit=hard_limit))
        output = parse_remote_search_output(result.stdout, resolved, tool="grep", limit=hard_limit)
        root = resolved.rstrip("/") or "/"
        root_prefix = root if root == "/" else f"{root}/"
        matches: list[GrepMatch] = []
        for raw in output.text.split("\n"):
            try:
                file_path, number, line = raw.split(":", 2)
                line_number = int(number)
            except ValueError:
                continue
            if should_ignore_path_under_root(file_path, root):
                continue
            if glob is not None:
                if file_path != root and not file_path.startswith(root_prefix):
                    continue
                relative = posixpath.basename(file_path) if file_path == root else file_path[len(root) :].lstrip("/")
                if not path_matches(glob, relative):
                    continue
            matches.append(GrepMatch(path=file_path, line_number=line_number, line=truncate_line(line)))
            if len(matches) > max_results:
                return matches[:max_results], True
        return matches, output.truncated
