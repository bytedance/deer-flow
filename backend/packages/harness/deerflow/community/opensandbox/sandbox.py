"""DeerFlow :class:`Sandbox` adapter for an OpenSandbox sync client."""

from __future__ import annotations

import errno
import logging
import posixpath
import re
import shlex
import threading
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from deerflow.config.paths import VIRTUAL_PATH_PREFIX
from deerflow.sandbox.sandbox import Sandbox, _validate_extra_env
from deerflow.sandbox.search import GrepMatch, path_matches, should_ignore_path, truncate_line

if TYPE_CHECKING:
    from collections.abc import Callable

    from opensandbox.sync import SandboxSync

logger = logging.getLogger(__name__)

_TERMINAL_ERROR_NAMES = frozenset({"SandboxUnhealthyException"})
_COMMAND_TTL_GRACE = timedelta(seconds=30)
_MAX_DOWNLOAD_SIZE = 100 * 1024 * 1024


def _exception_chain(error: BaseException):
    """Yield an exception and its explicit causes without looping forever."""
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__


def _is_terminal_failure(error: BaseException, *, api_not_found_is_terminal: bool = False) -> bool:
    """Return whether an SDK failure means this remote sandbox is unusable."""
    for item in _exception_chain(error):
        if isinstance(item, (BrokenPipeError, ConnectionError, EOFError)):
            return True
        if type(item).__name__ in _TERMINAL_ERROR_NAMES:
            return True
        status_code = getattr(item, "status_code", None)
        if status_code == 410 or (api_not_found_is_terminal and status_code == 404):
            return True
    return False


def _is_not_found(error: BaseException) -> bool:
    for item in _exception_chain(error):
        if isinstance(item, FileNotFoundError) or getattr(item, "status_code", None) == 404:
            return True
    return False


def _join_event_text(chunks) -> str:
    """Reconstruct the line-oriented text emitted by OpenSandbox SSE events."""
    return "\n".join(str(chunk).rstrip("\n") for chunk in chunks)


def _append_output(output: str, value: str) -> str:
    if not value:
        return output
    if not output or output.endswith("\n"):
        return output + value
    return f"{output}\n{value}"


def execution_stdout(execution: Any) -> str:
    return _join_event_text(message.text for message in getattr(getattr(execution, "logs", None), "stdout", []))


def format_execution(execution: Any) -> str:
    """Combine stdout, result text, and stderr using DeerFlow's string contract."""
    output = execution_stdout(execution)
    result = _join_event_text(item.text for item in getattr(execution, "result", []) if getattr(item, "text", None) is not None)
    output = _append_output(output, result)
    stderr = _join_event_text(message.text for message in getattr(getattr(execution, "logs", None), "stderr", []))
    output = _append_output(output, stderr)
    error = getattr(execution, "error", None)
    if error is not None:
        detail = f"{getattr(error, 'name', type(error).__name__)}: {getattr(error, 'value', error)}"
        output = _append_output(output, detail)
    return output


class OpenSandboxSandbox(Sandbox):
    """Wrap one live ``opensandbox.sync.SandboxSync`` instance."""

    def __init__(
        self,
        id: str,
        sandbox: SandboxSync,
        *,
        run_command_opts_cls: Callable[..., Any],
        default_env: dict[str, str] | None = None,
        sandbox_timeout: timedelta | None = None,
        default_command_timeout: float = 600,
        on_terminal_failure: Callable[[str, str], None] | None = None,
    ) -> None:
        super().__init__(id)
        if sandbox_timeout is not None and sandbox_timeout.total_seconds() <= 0:
            raise ValueError("sandbox_timeout must be positive or None")
        if default_command_timeout <= 0:
            raise ValueError("default_command_timeout must be positive")
        self._sandbox = sandbox
        self._run_command_opts_cls = run_command_opts_cls
        self._default_env = dict(default_env or {})
        self._sandbox_timeout = sandbox_timeout
        self._default_command_timeout = float(default_command_timeout)
        self._on_terminal_failure = on_terminal_failure
        self._state_lock = threading.Lock()
        # renew() sets an absolute expiration instead of taking a maximum. Keep
        # each renewal and its operation under one lock so a later short file
        # operation cannot shorten the horizon of a long-running command.
        self._operation_lock = threading.Lock()
        self._append_lock = threading.Lock()
        self._closed = False

    @property
    def remote_id(self) -> str:
        return str(self._sandbox.id)

    @property
    def is_closed(self) -> bool:
        with self._state_lock:
            return self._closed

    def destroy(self) -> None:
        """Terminate the remote sandbox and close its SDK resources."""
        with self._operation_lock:
            with self._state_lock:
                if self._closed:
                    return
            error: Exception | None = None
            try:
                self._sandbox.destroy()
            except Exception as exc:  # SDK errors are normalized below.
                error = exc
            finally:
                # SandboxSync.destroy() closes its transport even when kill fails,
                # so this client cannot safely be reused after either outcome.
                with self._state_lock:
                    self._closed = True
            if error is not None and not _is_terminal_failure(error, api_not_found_is_terminal=True):
                raise error

    def _note_failure(self, error: Exception, *, api_not_found_is_terminal: bool = False) -> None:
        if self._on_terminal_failure is None or not _is_terminal_failure(error, api_not_found_is_terminal=api_not_found_is_terminal):
            return
        try:
            self._on_terminal_failure(self.id, str(error))
        except Exception:
            logger.exception("Terminal OpenSandbox failure callback errored for %s", self.id)

    def renew(self) -> None:
        """Refresh this provider-owned remote's server-side lifetime."""
        if self._sandbox_timeout is None:
            return
        with self._operation_lock:
            with self._state_lock:
                if self._closed:
                    raise RuntimeError("sandbox has been closed")
            try:
                self._sandbox.renew(self._sandbox_timeout)
                return
            except Exception as exc:
                failure = exc
        self._note_failure(failure, api_not_found_is_terminal=True)
        raise failure

    def _run(self, command: str, *, env: dict[str, str] | None = None, timeout: float | None = None) -> Any:
        command_timeout = self._default_command_timeout if timeout is None else float(timeout)
        if command_timeout <= 0:
            raise ValueError(f"timeout must be positive, got {timeout}")
        sdk_timeout = timedelta(seconds=command_timeout)
        renewal_timeout = self._sandbox_timeout
        if renewal_timeout is not None:
            renewal_timeout = max(renewal_timeout, sdk_timeout + _COMMAND_TTL_GRACE)
        opts = self._run_command_opts_cls(timeout=sdk_timeout, envs=env)
        with self._operation_lock:
            with self._state_lock:
                if self._closed:
                    raise RuntimeError("sandbox has been closed")
            try:
                if renewal_timeout is not None:
                    self._sandbox.renew(renewal_timeout)
                return self._sandbox.commands.run(command, opts=opts)
            except Exception as exc:
                failure = exc
        # A command-path 404 means the execd endpoint/sandbox is gone. File APIs
        # use 404 for an ordinary missing path, so only command operations opt in.
        self._note_failure(failure, api_not_found_is_terminal=True)
        raise failure

    def _file_op(self, operation):
        with self._operation_lock:
            with self._state_lock:
                if self._closed:
                    raise RuntimeError("sandbox has been closed")
            try:
                if self._sandbox_timeout is not None:
                    self._sandbox.renew(self._sandbox_timeout)
            except Exception as exc:
                failure = exc
                renewal_failed = True
            else:
                try:
                    return operation(self._sandbox.files)
                except Exception as exc:
                    failure = exc
                    renewal_failed = False
        self._note_failure(failure, api_not_found_is_terminal=renewal_failed)
        raise failure

    @staticmethod
    def _resolve_path(path: str) -> str:
        if not isinstance(path, str) or not path:
            raise ValueError("path must be a non-empty string")
        normalized = path.replace("\\", "/")
        if not normalized.startswith("/"):
            raise ValueError(f"path must be absolute: '{path}'")
        if any(segment == ".." for segment in normalized.split("/")):
            raise PermissionError(f"Access denied: path traversal detected in '{path}'")
        return normalized

    @classmethod
    def _resolve_download_path(cls, path: str) -> str:
        normalized = cls._resolve_path(path)
        stripped = normalized.lstrip("/")
        allowed = VIRTUAL_PATH_PREFIX.lstrip("/")
        if stripped != allowed and not stripped.startswith(f"{allowed}/"):
            raise PermissionError(f"Access denied: path must be under '{VIRTUAL_PATH_PREFIX}': '{path}'")
        return normalized

    def execute_command(self, command: str, env: dict[str, str] | None = None, timeout: float | None = None) -> str:
        _validate_extra_env(env)
        merged_env = {**self._default_env, **(env or {})} or None
        try:
            execution = self._run(command, env=merged_env, timeout=timeout)
        except Exception as exc:
            logger.error("Failed to execute command in OpenSandbox %s: %s", self.id, exc)
            return f"Error: {exc}"
        output = format_execution(execution)
        exit_code = getattr(execution, "exit_code", None)
        if exit_code is None:
            detail = output or "no completion or error event"
            return f"Error: OpenSandbox command completed without an exit code: {detail}"
        if exit_code != 0 and not output:
            output = f"Command exited with code {exit_code}"
        return output if output else "(no output)"

    def read_file(self, path: str, start_line: int | None = None, end_line: int | None = None) -> str:
        resolved = self._resolve_path(path)
        try:
            content = self._file_op(lambda files: files.read_file(resolved))
        except Exception as exc:
            logger.error("Failed to read OpenSandbox file %s: %s", resolved, exc)
            return f"Error: {exc}"
        if start_line is None and end_line is None:
            return content or ""
        lines = (content or "").splitlines()
        start = start_line or 1
        end = end_line if end_line is not None else len(lines)
        return "\n".join(lines[start - 1 : end])

    def write_file(self, path: str, content: str, append: bool = False) -> None:
        resolved = self._resolve_path(path)
        if not append:
            self._file_op(lambda files: files.write_file(resolved, content, mode=644))
            return
        with self._append_lock:
            try:
                previous = self._file_op(lambda files: files.read_bytes(resolved))
            except Exception as exc:
                if not _is_not_found(exc):
                    raise
                previous = b""
            data = previous + content.encode("utf-8")
            self._file_op(lambda files: files.write_file(resolved, data, mode=644))

    def update_file(self, path: str, content: bytes) -> None:
        resolved = self._resolve_path(path)
        self._file_op(lambda files: files.write_file(resolved, content, mode=644))

    def download_file(self, path: str) -> bytes:
        resolved = self._resolve_download_path(path)

        def read_bounded(files) -> bytes:
            chunks: list[bytes] = []
            total = 0
            stream = files.read_bytes_stream(resolved)
            try:
                for chunk in stream:
                    total += len(chunk)
                    if total > _MAX_DOWNLOAD_SIZE:
                        raise OSError(errno.EFBIG, f"File exceeds maximum download size of {_MAX_DOWNLOAD_SIZE} bytes", path)
                    chunks.append(chunk)
            finally:
                close = getattr(stream, "close", None)
                if callable(close):
                    close()
            return b"".join(chunks)

        try:
            return self._file_op(read_bounded)
        except OSError:
            raise
        except Exception as exc:
            raise OSError(f"cannot read '{path}' from OpenSandbox: {exc}") from exc

    def list_dir(self, path: str, max_depth: int = 2) -> list[str]:
        depth = int(max_depth)
        if depth < 0:
            raise ValueError("max_depth must be non-negative")
        resolved = self._resolve_path(path)
        execution = self._run(f"find {shlex.quote(resolved)} -maxdepth {depth} \\( -type f -o -type d \\) 2>/dev/null | head -500")
        return [line.strip() for line in execution_stdout(execution).splitlines() if line.strip()]

    def glob(self, path: str, pattern: str, *, include_dirs: bool = False, max_results: int = 200) -> tuple[list[str], bool]:
        if max_results <= 0:
            raise ValueError("max_results must be positive")
        resolved = self._resolve_path(path)
        types = ("f", "d") if include_dirs else ("f",)
        type_expr = " -o ".join(f"-type {entry_type}" for entry_type in types)
        hard_limit = max(max_results * 4, max_results + 50)
        execution = self._run(f"find {shlex.quote(resolved)} \\( {type_expr} \\) -print 2>/dev/null | head -{hard_limit}")

        matches: list[str] = []
        root = resolved.rstrip("/") or "/"
        root_prefix = root if root == "/" else f"{root}/"
        for entry in execution_stdout(execution).splitlines():
            entry = entry.strip()
            if not entry or (entry != root and not entry.startswith(root_prefix)) or should_ignore_path(entry):
                continue
            relative = entry[len(root) :].lstrip("/")
            if relative and path_matches(pattern, relative):
                matches.append(entry)
                if len(matches) >= max_results:
                    return matches, True
        return matches, False

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
        resolved = self._resolve_path(path)
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
        command = f'{{ {primary}; status=$?; [ "$status" -eq 2 ] && {fallback}; }} | head -{hard_limit}'
        execution = self._run(command)

        root = resolved.rstrip("/") or "/"
        root_prefix = root if root == "/" else f"{root}/"
        matches: list[GrepMatch] = []
        seen_positions: set[tuple[str, int]] = set()
        for raw in execution_stdout(execution).splitlines():
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
        return matches, False

    def ping(self, timeout: float = 10) -> bool:
        if self.is_closed:
            return False
        try:
            execution = self._run("true", timeout=timeout)
        except Exception as exc:
            logger.warning("OpenSandbox %s health check failed: %s", self.id, exc)
            return False
        return getattr(execution, "exit_code", None) == 0


__all__ = ["OpenSandboxSandbox"]
