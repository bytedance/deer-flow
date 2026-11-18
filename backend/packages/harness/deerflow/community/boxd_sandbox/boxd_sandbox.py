"""``BoxdSandbox``: DeerFlow :class:`Sandbox` backed by one boxd machine.

A boxd machine is a full Ubuntu microVM with a persistent disk. The provider
bootstraps ``/mnt/user-data`` and the skills root as real directories owned by
the machine user, so virtual paths need no remapping: the agent's shell and the
file APIs see the same paths.

Commands run through ``bash -lc`` with the per-call environment passed as
structured exec options, never spliced into the command string. Writes use the
SDK's streaming ``machines.fs`` API; reads run as a bounded ``head -c`` exec
with a deadline. Search (``list_dir`` / ``glob`` /
``grep``) shells out to ``find`` / ``grep`` and is parsed with the shared
``deerflow.sandbox`` helpers, like ``community/e2b_sandbox``.

The ``boxd`` SDK is never imported here. Errors are classified by the names in
their class hierarchy, so this module imports without the optional dependency.
"""

from __future__ import annotations

import errno
import logging
import math
import re
import shlex
import threading
import time
from typing import TYPE_CHECKING, Any

from deerflow.config.paths import VIRTUAL_PATH_PREFIX
from deerflow.sandbox.download import DEFAULT_DOWNLOAD_LIMIT as _MAX_DOWNLOAD_SIZE
from deerflow.sandbox.download import download_limit
from deerflow.sandbox.read_file_contract import split_file_lines
from deerflow.sandbox.remote_list_dir import parse_remote_list_dir_output, remote_list_dir_command
from deerflow.sandbox.remote_search import parse_remote_search_output, remote_search_command
from deerflow.sandbox.sandbox import Sandbox, _validate_extra_env
from deerflow.sandbox.search import GrepMatch, path_matches, should_ignore_path_under_root, truncate_line

if TYPE_CHECKING:
    from collections.abc import Callable

    from boxd import Boxd

logger = logging.getLogger(__name__)

# Extra seconds the SDK call waits after the in-machine ``timeout`` fired, so
# the command's own exit code 124 and its partial output come back first.
_TIMEOUT_GRACE_SECONDS = 30.0
# Seconds between SIGTERM and SIGKILL for a command that hit its deadline.
_KILL_AFTER_SECONDS = 5
# Bound for internal helper commands (search, listing, health probes).
_HELPER_TIMEOUT_SECONDS = 120.0
# How long a started machine may take before commands reach it again.
_START_PROBE_SECONDS = 60.0
_START_PROBE_INTERVAL = 1.0
# Upper bound for one read_file call, so a huge file cannot exhaust Gateway memory.
_MAX_READ_FILE_SIZE = _MAX_DOWNLOAD_SIZE
# Deadlines for file reads, which run as a bounded ``head -c`` exec.
_READ_TIMEOUT_SECONDS = 120.0
_DOWNLOAD_TIMEOUT_SECONDS = 300.0
# Command deadline when the caller gives none (SandboxConfig.bash_command_timeout default).
DEFAULT_COMMAND_TIMEOUT = 600.0


def _error_names(error: BaseException) -> set[str]:
    return {cls.__name__ for cls in type(error).__mro__}


def is_machine_gone_error(error: BaseException) -> bool:
    """The machine itself no longer exists (not a missing file inside it)."""
    names = _error_names(error)
    return "NotFoundError" in names and "MachineFilesystemError" not in names


def is_stopped_machine_error(error: BaseException) -> bool:
    """A conflict that a later ``start`` can clear (the machine is stopped)."""
    names = _error_names(error)
    return "ConflictError" in names and "MachineFilesystemError" not in names


def is_missing_file_error(error: BaseException) -> bool:
    return isinstance(error, FileNotFoundError) or "MachineFileNotFoundError" in _error_names(error)


class BoxdSandbox(Sandbox):
    """DeerFlow Sandbox adapter that delegates to a live boxd machine.

    Args:
        id: DeerFlow-side sandbox id (the provider's cache key).
        client: A ``boxd.Boxd`` client. It is shared by every sandbox of one
            provider; this adapter never closes it.
        machine_id: The boxd machine id. Every call addresses the machine by id.
        region: Region the machine lives in, forwarded to every call.
        default_env: Static environment merged into every command, overridden
            per call by the ``env`` passed to :meth:`execute_command`.
        default_command_timeout: Deadline in seconds for commands whose caller
            gives none.
        on_terminal_failure: Optional callback ``(sandbox_id, reason)`` invoked
            when the machine is gone, so the provider can evict this sandbox.
    """

    #: Every call is a fresh ``bash -lc`` exec; no shell state survives.
    persistent_shell_sessions = False
    artifact_root = VIRTUAL_PATH_PREFIX

    def __init__(
        self,
        id: str,
        client: Boxd,
        machine_id: str,
        *,
        region: str | None = None,
        default_env: dict[str, str] | None = None,
        default_command_timeout: float = DEFAULT_COMMAND_TIMEOUT,
        on_terminal_failure: Callable[[str, str], None] | None = None,
    ) -> None:
        super().__init__(id)
        self._client = client
        self._machine_id = machine_id
        self._region = region
        self._default_env = dict(default_env or {})
        self._default_command_timeout = default_command_timeout
        self._on_terminal_failure = on_terminal_failure
        self._lock = threading.Lock()
        # Serializes the append read-modify-write. Distinct from _lock so the
        # eviction callback, which reaches back into the provider, never runs
        # under it.
        self._write_lock = threading.Lock()
        self._closed = False

    # ── Properties / lifecycle ───────────────────────────────────────────

    @property
    def machine_id(self) -> str:
        return self._machine_id

    @property
    def is_closed(self) -> bool:
        with self._lock:
            return self._closed

    def close(self) -> None:
        """Delete the machine (idempotent).

        The sandbox is marked closed only after the delete was accepted or the
        machine is confirmed gone. Any other failure is raised, so the provider
        keeps the handle and retries instead of leaving a machine running.
        """
        with self._lock:
            if self._closed:
                return
            try:
                self._client.machines.delete(self._machine_id, region=self._region)
            except Exception as e:
                if not is_machine_gone_error(e):
                    logger.error("Error deleting boxd machine for sandbox %s: %s", self.id, e)
                    raise
                logger.info("boxd machine for sandbox %s was already gone at close", self.id)
            self._closed = True

    def ping(self) -> bool:
        """Return True when the machine answers a trivial command."""
        try:
            result = self._run(["bash", "-lc", "echo ok"], timeout=30.0)
        except Exception as e:
            logger.warning("boxd sandbox %s health check error: %s", self.id, e)
            return False
        return result.exit_code == 0 and "ok" in _text(result.stdout).split()

    # ── SDK bridge ───────────────────────────────────────────────────────

    def _note_failure(self, error: Exception) -> None:
        if self._on_terminal_failure is None or not is_machine_gone_error(error):
            return
        # Confirm before the provider drops the sandbox: a not-found answer
        # from one call is not proof that the machine itself is gone.
        try:
            self._client.machines.get(self._machine_id, region=self._region)
        except Exception as e:
            if not is_machine_gone_error(e):
                return
        else:
            return
        try:
            self._on_terminal_failure(self.id, str(error))
        except Exception:
            logger.exception("Terminal boxd failure callback errored for %s", self.id)

    def _ensure_open(self) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("sandbox has been closed")

    def _start_machine(self) -> None:
        """Start a stopped machine and wait until it runs commands again.

        ``wait_until_ready`` reports the machine state; a no-op probe confirms
        that commands reach it before the original call is repeated.
        """
        logger.info("boxd machine for sandbox %s is stopped; starting it", self.id)
        machines = self._client.machines
        machines.start(self._machine_id, region=self._region)
        machines.wait_until_ready(self._machine_id, region=self._region)
        deadline = time.monotonic() + _START_PROBE_SECONDS
        while True:
            try:
                machines.exec(self._machine_id, ["true"], timeout=_START_PROBE_INTERVAL * 5, region=self._region)
                return
            except Exception:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(_START_PROBE_INTERVAL)

    def _call(self, op: Callable[[], Any], *, repeat: bool = True, recover: bool = True) -> Any:
        """Run one SDK call, starting the machine if it is stopped.

        A machine in standby or hibernation wakes on the call itself. A stopped
        machine is started, and the call is repeated once when ``repeat`` is
        true. Commands pass ``repeat=False``: a machine stopped while the
        command ran must not run it a second time, so the caller gets an error
        and decides. Budgeted mirror calls pass ``recover=False`` to skip the
        control-plane calls used for recovery and failure confirmation.
        """
        self._ensure_open()
        if not recover:
            # Budgeted output copies must not enter control-plane recovery or
            # failure probes, whose SDK calls have separate request deadlines.
            return op()
        try:
            try:
                return op()
            except Exception as first:
                if not is_stopped_machine_error(first):
                    raise
                try:
                    status = str(getattr(self._client.machines.get(self._machine_id, region=self._region), "status", ""))
                except Exception:
                    raise first from None
                if status.rsplit(".", 1)[-1].lower() != "stopped":
                    raise
                self._start_machine()
                if not repeat:
                    raise RuntimeError("The sandbox machine was stopped and has been started again; the command did not run to completion, run it again") from first
                return op()
        except Exception as e:
            self._note_failure(e)
            raise

    def _run(self, argv: list[str], *, env: dict[str, str] | None = None, timeout: float | None = None, binary: bool = False, repeat: bool = True, deadline: float | None = None) -> Any:
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("boxd output synchronization deadline exceeded")
            timeout = min(timeout, remaining) if timeout is not None else remaining
        return self._call(
            lambda: self._client.machines.exec(
                self._machine_id,
                argv,
                env=env or None,
                timeout=timeout,
                encoding="buffer" if binary else "utf-8",
                region=self._region,
            ),
            repeat=repeat,
            recover=deadline is None,
        )

    def run_shell(self, script: str, *, timeout: float = _HELPER_TIMEOUT_SECONDS, binary: bool = False, deadline: float | None = None) -> Any:
        """Run an internal helper script with the configured environment."""
        return self._run(["bash", "-lc", script], env=self._default_env, timeout=timeout, binary=binary, deadline=deadline)

    # ── Paths ────────────────────────────────────────────────────────────

    @staticmethod
    def _guard_path(path: str) -> str:
        if not path:
            raise ValueError("path must be a non-empty string")
        normalized = path.replace("\\", "/")
        if any(segment == ".." for segment in normalized.split("/")):
            raise PermissionError(f"Access denied: path traversal detected in '{path}'")
        if not normalized.startswith("/"):
            raise ValueError(f"path must be absolute: '{path}'")
        return normalized

    # ── Command execution ────────────────────────────────────────────────

    def execute_command(
        self,
        command: str,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> str:
        """Run ``command`` through ``bash -lc`` and return combined output.

        The deadline (``timeout``, else the provider default) is enforced
        inside the machine with coreutils ``timeout``, which ends the whole
        command with exit code 124 and keeps the output it produced so far.
        The SDK call gets a slightly longer deadline as a backstop.
        """
        _validate_extra_env(env)
        if self.is_closed:
            return "Error: sandbox has been closed"
        merged_env = {**self._default_env, **(env or {})}
        if timeout is None or not math.isfinite(timeout) or timeout <= 0:
            timeout = self._default_command_timeout
        seconds = max(1, math.ceil(timeout))
        argv = ["timeout", "-k", str(_KILL_AFTER_SECONDS), str(seconds), "bash", "-lc", command]
        call_timeout = seconds + _KILL_AFTER_SECONDS + _TIMEOUT_GRACE_SECONDS
        try:
            result = self._run(argv, env=merged_env, timeout=call_timeout, repeat=False)
        except Exception as e:
            logger.error("Failed to execute command in boxd sandbox %s: %s", self.id, e)
            return f"Error: {e}"

        stdout = _text(result.stdout)
        stderr = _text(result.stderr)
        if stdout and stderr:
            output = f"{stdout}\n{stderr}"
        else:
            output = stdout or stderr
        exit_code = result.exit_code
        if exit_code not in (0, None):
            output = f"{output}\nExit Code: {exit_code}" if output else f"Command exited with code {exit_code}\nExit Code: {exit_code}"
        return output if output else "(no output)"

    # ── File operations ──────────────────────────────────────────────────

    def _read_bytes(self, path: str, limit: int, *, timeout: float = _READ_TIMEOUT_SECONDS, deadline: float | None = None) -> bytes:
        """Read at most ``limit`` bytes with a deadline.

        ``head -c limit+1`` bounds what the machine sends, so an oversized
        file is detected without buffering more than one byte past the cap,
        and the exec deadline bounds a stalled transfer.
        """
        result = self._run(["head", "-c", str(limit + 1), "--", path], timeout=timeout, binary=True, deadline=deadline)
        data = result.stdout if isinstance(result.stdout, bytes) else _text(result.stdout).encode("utf-8")
        if result.exit_code != 0:
            message = _text(result.stderr).strip() or f"head exited with code {result.exit_code}"
            if "No such file" in message:
                raise FileNotFoundError(errno.ENOENT, "No such file or directory", path)
            if "Is a directory" in message:
                raise IsADirectoryError(errno.EISDIR, "Is a directory", path)
            if "Permission denied" in message:
                raise PermissionError(errno.EACCES, "Permission denied", path)
            raise OSError(f"cannot read '{path}': {message}")
        if len(data) > limit:
            raise OSError(errno.EFBIG, f"File exceeds maximum download size of {limit} bytes", path)
        return data

    def read_file(
        self,
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> str:
        try:
            resolved = self._guard_path(path)
            content = self._read_bytes(resolved, _MAX_READ_FILE_SIZE).decode("utf-8", errors="replace")
        except Exception as e:
            logger.error("read_file %s failed: %s", path, e)
            return f"Error: {e}"
        if start_line is None and end_line is None:
            return content
        lines = split_file_lines(content)
        # Clamp like LocalSandbox.read_file: a negative start must not wrap
        # around through negative-index slicing.
        start = max(start_line or 1, 1)
        end = max(end_line, 0) if end_line is not None else len(lines)
        return "\n".join(lines[start - 1 : end])

    def write_file(self, path: str, content: str, append: bool = False) -> None:
        self._write_bytes(self._guard_path(path), content.encode("utf-8"), append=append)

    def update_file(self, path: str, content: bytes) -> None:
        self._write_bytes(self._guard_path(path), content, append=False)

    def _write_bytes(self, resolved: str, data: bytes, *, append: bool) -> None:
        fs = self._client.machines.fs
        if not append:
            # fs.write creates missing parent directories.
            self._call(lambda: fs.write(self._machine_id, resolved, data, region=self._region))
            return
        with self._write_lock:
            try:
                existing = self._read_bytes(resolved, _MAX_READ_FILE_SIZE)
            except Exception as e:
                if not is_missing_file_error(e):
                    raise
                existing = b""
            payload = existing + data
            self._call(lambda: fs.write(self._machine_id, resolved, payload, region=self._region))

    def download_file(self, path: str, *, max_bytes: int | None = None, deadline: float | None = None) -> bytes:
        """Download under the size cap and optional monotonic mirror deadline."""
        limit = download_limit(max_bytes, _MAX_DOWNLOAD_SIZE)
        normalized = self._guard_path(path)
        if normalized != VIRTUAL_PATH_PREFIX and not normalized.startswith(f"{VIRTUAL_PATH_PREFIX}/"):
            raise PermissionError(f"Access denied: path must be under '{VIRTUAL_PATH_PREFIX}': '{path}'")
        # head -c stops one byte past the cap, so a file that grows during
        # the transfer still cannot exceed it.
        try:
            return self._read_bytes(normalized, limit, timeout=_DOWNLOAD_TIMEOUT_SECONDS, deadline=deadline)
        except OSError as e:
            if e.errno == errno.EFBIG or is_missing_file_error(e):
                raise
            raise OSError(f"cannot read '{path}' from sandbox: {e}") from e
        except Exception as e:
            raise OSError(f"cannot read '{path}' from sandbox: {e}") from e

    def list_dir(self, path: str, max_depth: int = 2) -> list[str]:
        resolved = self._guard_path(path)
        result = self.run_shell(remote_list_dir_command(resolved, max_depth))
        return parse_remote_list_dir_output(_text(result.stdout), resolved, pipeline_exit_code=result.exit_code)

    def glob(
        self,
        path: str,
        pattern: str,
        *,
        include_dirs: bool = False,
        max_results: int = 200,
    ) -> tuple[list[str], bool]:
        resolved = self._guard_path(path)
        types = ("f", "d") if include_dirs else ("f",)
        type_expr = " -o ".join(f"-type {t}" for t in types)
        hard_limit = max(max_results * 4, max_results + 50)
        # -H follows a symlinked search root, as list_dir does.
        search = f"find -H {shlex.quote(resolved)} \\( {type_expr} \\) -print 2>/dev/null"
        result = self.run_shell(remote_search_command(search, resolved, limit=hard_limit))
        # A missing root or a failed find must not read as "no files matched".
        output = parse_remote_search_output(_text(result.stdout), resolved, tool="find", limit=hard_limit)

        matches: list[str] = []
        root = resolved.rstrip("/") or "/"
        root_prefix = root if root == "/" else f"{root}/"
        # Records are LF-delimited; other splitlines() boundaries can be path characters.
        for entry in output.text.split("\n"):
            # Do not strip: trailing whitespace can be part of a file name.
            if not entry or (entry != root and not entry.startswith(root_prefix)):
                continue
            if should_ignore_path_under_root(entry, root):
                continue
            rel_path = entry[len(root) :].lstrip("/")
            if not rel_path:
                continue
            if path_matches(pattern, rel_path):
                matches.append(entry)
                # Look one match past the cap so an exhausted tree that held
                # exactly max_results is not reported as truncated.
                if len(matches) > max_results:
                    return matches[:max_results], True
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
        # grep gets the raw pattern: -F matches it literally, -E as a regex.
        # The Python compile only catches gross errors at the boundary.
        if not literal:
            re.compile(pattern, 0 if case_sensitive else re.IGNORECASE)

        resolved = self._guard_path(path)
        # --null ends the file name with NUL, so a colon in a path cannot be
        # mistaken for the line-number separator.
        flags = ["-r", "-n", "-H", "-I", "--null"]
        if not case_sensitive:
            flags.append("-i")
        flags.append("-F" if literal else "-E")
        if glob is not None:
            # --include matches basenames only; it is a coarse pre-filter and
            # path_matches below enforces the real directory scope.
            include_pattern = glob.split("/")[-1] or glob
            flags.append(shlex.quote(f"--include={include_pattern}"))
        per_file_cap = max(max_results + 1, 50)
        total_cap = max(max_results * 4, max_results + 50)
        flags.append(f"-m{per_file_cap}")
        search = "grep " + " ".join(flags) + f" -- {shlex.quote(pattern)} {shlex.quote(resolved)} 2>/dev/null"
        result = self.run_shell(remote_search_command(search, resolved, limit=total_cap))
        # A missing root, a missing grep or an unreadable tree must not read as "no matches".
        output = parse_remote_search_output(_text(result.stdout), resolved, tool="grep", limit=total_cap)

        root = resolved.rstrip("/") or "/"
        root_prefix = root if root == "/" else f"{root}/"
        matches: list[GrepMatch] = []
        for raw in output.text.split("\n"):
            try:
                file_path, rest = raw.split("\0", 1)
                line_no_str, line_text = rest.split(":", 1)
                line_number = int(line_no_str)
            except ValueError:
                continue
            if should_ignore_path_under_root(file_path, root):
                continue
            if glob is not None:
                if file_path != root and not file_path.startswith(root_prefix):
                    continue
                rel_path = file_path.rsplit("/", 1)[-1] if file_path == root else file_path[len(root) :].lstrip("/")
                if not path_matches(glob, rel_path):
                    continue
            matches.append(GrepMatch(path=file_path, line_number=line_number, line=truncate_line(line_text)))
            if len(matches) > max_results:
                return matches[:max_results], True
        return matches, output.truncated


def _text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


__all__ = ["BoxdSandbox"]
