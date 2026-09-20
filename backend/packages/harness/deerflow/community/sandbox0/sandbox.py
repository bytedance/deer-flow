"""Sandbox0 command and file adapter; every command gets a fresh process."""

from __future__ import annotations

import base64
import math
import posixpath
import re
import shlex
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from deerflow.sandbox.remote_list_dir import parse_remote_list_dir_output, remote_list_dir_command
from deerflow.sandbox.remote_search import parse_remote_search_output, remote_search_command
from deerflow.sandbox.sandbox import Sandbox, _validate_extra_env
from deerflow.sandbox.search import GrepMatch, path_matches, should_ignore_path, truncate_line

if TYPE_CHECKING:
    from sandbox0 import Sandbox as RemoteSandbox


class Sandbox0Sandbox(Sandbox):
    """Adapt the official SDK without exposing control-plane credentials to guests."""

    persistent_shell_sessions = False

    def __init__(self, id: str, remote: RemoteSandbox, *, command_timeout: float = 600, environment: dict[str, str] | None = None, refresh: Callable[[], object] | None = None, refresh_interval: float = 60):
        super().__init__(id)
        self.remote = remote
        self._command_timeout = command_timeout
        self._environment = dict(environment or {})
        self._refresh = refresh
        self._refresh_interval = refresh_interval
        self._refresh_lock = threading.Lock()
        self._refreshed_at: float | None = None

    def _touch(self):
        # Tool activity renews the runtime TTL, never the durable hard deadline.
        if self._refresh is None:
            return
        with self._refresh_lock:
            now = time.monotonic()
            if self._refreshed_at is None or now - self._refreshed_at >= self._refresh_interval:
                self._refresh()
                self._refreshed_at = now

    @property
    def remote_id(self) -> str:
        return self.remote.id

    def _run(self, command: str, *, env: dict[str, str] | None = None, timeout: float | None = None):
        from sandbox0 import CmdOptions

        _validate_extra_env(env)
        duration = self._command_timeout if timeout is None else timeout
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("command timeout must be finite and positive")
        self._touch()
        result = self.remote.cmd(
            command or "true",
            CmdOptions(command=["bash", "-lc", command or "true"], wait=True, ttl_sec=math.ceil(duration), env_vars={**self._environment, **(env or {})} or None),
        )
        if result.exit_code is None:
            raise OSError("Sandbox0 command has no terminal exit code (it may have timed out)")
        return result

    def _checked(self, command: str, *, timeout: float | None = None) -> str:
        result = self._run(command, timeout=timeout)
        if result.exit_code != 0:
            raise OSError(f"Sandbox0 command failed with exit code {result.exit_code}: {result.stderr}")
        return result.stdout

    def execute_command(self, command: str, env: dict[str, str] | None = None, timeout: float | None = None) -> str:
        result = self._run(command, env=env, timeout=timeout)
        output = result.stdout
        if result.stderr:
            output += ("\n" if output and not output.endswith("\n") else "") + result.stderr
        if result.exit_code != 0:
            output += f"\nExit Code: {result.exit_code}"
        return output or "(no output)"

    @staticmethod
    def _path(path: str) -> str:
        if not path or not path.startswith("/") or "\x00" in path:
            raise ValueError("path must be an absolute POSIX path")
        if ".." in path.split("/"):
            raise PermissionError("path traversal is not allowed")
        return posixpath.normpath(path)

    def read_file(self, path: str, start_line: int | None = None, end_line: int | None = None) -> str:
        path = self._path(path)
        self._touch()
        try:
            content = self.remote.read_file(path).decode("utf-8", errors="replace")
        except Exception as exc:
            # DeerFlow's read-before-write gate distinguishes a new file from
            # a failed inspection. Keep the filesystem exception contract.
            if getattr(exc, "status_code", None) == 404:
                raise FileNotFoundError(path) from exc
            raise
        if start_line is None and end_line is None:
            return content
        if (start_line is not None and start_line < 1) or (end_line is not None and end_line < 1):
            raise ValueError("line numbers start at 1")
        return "\n".join(content.splitlines()[(start_line or 1) - 1 : end_line])

    def update_file(self, path: str, content: bytes) -> None:
        path = self._path(path)
        self._touch()
        self.remote.mkdir(posixpath.dirname(path), recursive=True)
        self.remote.write_file(path, content)

    def write_file(self, path: str, content: str, append: bool = False) -> None:
        path = self._path(path)
        if not append:
            self.update_file(path, content.encode("utf-8"))
            return
        # O_APPEND avoids a read/modify/write race with concurrent tool calls.
        data = base64.b64encode(content.encode("utf-8")).decode("ascii")
        self._touch()
        self.remote.mkdir(posixpath.dirname(path), recursive=True)
        self._checked(f"printf %s {shlex.quote(data)} | base64 -d >> {shlex.quote(path)}")

    def download_file(self, path: str) -> bytes:
        path = self._path(path)
        if not path.startswith("/mnt/user-data/"):
            raise PermissionError("downloads must be under /mnt/user-data")
        # Validate canonical paths as well: the agent can create symlinks with bash.
        script = "import os,sys; p=os.path.realpath(sys.argv[1]); assert p.startswith('/mnt/user-data/'), 'download path escapes user-data'; assert os.path.getsize(p)<=100*1024*1024, 'download exceeds 100 MiB'"
        try:
            self._checked(f"python3 -c {shlex.quote(script)} {shlex.quote(path)}")
            return self.remote.read_file(path)
        except Exception as exc:
            raise OSError(f"Cannot download sandbox file {path}") from exc

    def list_dir(self, path: str, max_depth: int = 2) -> list[str]:
        path = self._path(path)
        if max_depth < 0:
            raise ValueError("max_depth must be non-negative")
        result = self._run(remote_list_dir_command(path, int(max_depth)))
        return parse_remote_list_dir_output(result.stdout, path, pipeline_exit_code=result.exit_code)

    def glob(self, path: str, pattern: str, *, include_dirs: bool = False, max_results: int = 200) -> tuple[list[str], bool]:
        if max_results <= 0:
            raise ValueError("max_results must be positive")
        resolved = self._path(path)
        types = ("f", "d") if include_dirs else ("f",)
        type_expr = " -o ".join(f"-type {entry_type}" for entry_type in types)
        hard_limit = max(max_results * 4, max_results + 50)
        # -H follows a symlinked search root, as list_dir does.
        search = f"find -H {shlex.quote(resolved)} \\( {type_expr} \\) -print 2>/dev/null"
        execution = self._run(remote_search_command(search, resolved, limit=hard_limit))
        # A missing root or a failed find must not read as "no files matched" (#5376).
        output = parse_remote_search_output(execution.stdout, resolved, tool="find", limit=hard_limit)

        matches: list[str] = []
        root = resolved.rstrip("/") or "/"
        root_prefix = root if root == "/" else f"{root}/"
        for entry in output.text.splitlines():
            # Do NOT strip: trailing whitespace can be part of the filename.
            if not entry or (entry != root and not entry.startswith(root_prefix)) or should_ignore_path(entry):
                continue
            relative = entry[len(root) :].lstrip("/")
            if relative and path_matches(pattern, relative):
                matches.append(entry)
                if len(matches) >= max_results:
                    return matches, True
        return matches, output.truncated

    def grep(
        self,
        path: str,
        pattern: str,
        *,
        glob: str | None = None,
        literal: bool = False,
        case_sensitive: bool = False,
        max_results: int = 100,
    ) -> tuple[list[GrepMatch], bool]:
        if max_results <= 0:
            raise ValueError("max_results must be positive")
        if not literal:
            re.compile(pattern, 0 if case_sensitive else re.IGNORECASE)
        resolved = self._path(path)
        flags = ["-r", "-H", "-n", "-I"]
        if not case_sensitive:
            flags.append("-i")
        flags.append("-F" if literal else "-E")
        portable_flags = list(flags)
        if glob is not None:
            include_pattern = glob.split("/")[-1] or glob
            flags.append(shlex.quote(f"--include={include_pattern}"))
        per_file_cap = max(max_results, 50)
        flags.append(f"-m{per_file_cap}")
        hard_limit = max(max_results * 4, max_results + 50)
        arguments = f" -e {shlex.quote(pattern)} {shlex.quote(resolved)} 2>/dev/null"
        primary = "grep " + " ".join(flags) + arguments
        fallback = "grep " + " ".join(portable_flags) + arguments
        # Retry without --include/-m only when the primary grep errors (BusyBox
        # lacks them). Keep the primary's status otherwise, so a missing grep
        # (127) is not reported as "no matches" (#5376).
        search = f'{primary}; status=$?; if [ "$status" -eq 2 ]; then {fallback}; status=$?; fi; (exit "$status")'
        execution = self._run(remote_search_command(search, resolved, limit=hard_limit))
        output = parse_remote_search_output(execution.stdout, resolved, tool="grep", limit=hard_limit)

        root = resolved.rstrip("/") or "/"
        root_prefix = root if root == "/" else f"{root}/"
        matches: list[GrepMatch] = []
        seen_positions: set[tuple[str, int]] = set()
        for raw in output.text.splitlines():
            try:
                file_path, line_number_text, line = raw.split(":", 2)
                line_number = int(line_number_text)
            except ValueError:
                continue
            if should_ignore_path(file_path):
                continue
            if glob is not None:
                if file_path != root and not file_path.startswith(root_prefix):
                    continue
                relative = posixpath.basename(file_path) if file_path == root else file_path[len(root) :].lstrip("/")
                if not path_matches(glob, relative):
                    continue
            position = (file_path, line_number)
            if position in seen_positions:
                continue
            seen_positions.add(position)
            matches.append(GrepMatch(path=file_path, line_number=line_number, line=truncate_line(line)))
            if len(matches) >= max_results:
                return matches, True
        return matches, output.truncated
