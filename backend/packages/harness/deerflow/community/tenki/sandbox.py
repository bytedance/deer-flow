"""``TenkiSandbox`` — DeerFlow :class:`Sandbox` backed by a Tenki cloud sandbox.

Tenki's Python SDK (the ``tenki`` distribution, which ships the
``tenki_sandbox`` module) is synchronous, so — unlike
``community/boxlite`` — this adapter calls the SDK directly with no event-loop
bridge. File transport uses Tenki's native ``sandbox.fs`` API (``read_text`` /
``read_stream`` / ``write_stream`` / ``mkdir`` / ``stat``), which is binary-safe
and streams, so no base64/shell encoding is involved. Directory and content
*search* (``list_dir`` / ``glob`` / ``grep``) still shells out to ``find`` /
``grep`` — the fs API is single-level and has no content search — and is parsed
with the shared ``deerflow.sandbox.search`` helpers, the same approach as
``community/e2b_sandbox``. Those commands use only busybox-portable flags so any
Tenki base image works.

The Tenki SDK is not imported at module load (only its exception *class names*
are matched, as strings), so importing this package never requires
``tenki`` to be installed — it is needed only once the provider is
selected and a sandbox is actually created.
"""

from __future__ import annotations

import errno
import logging
import posixpath
import re
import shlex
import threading
from typing import TYPE_CHECKING, Any, TypeVar

from deerflow.config.paths import VIRTUAL_PATH_PREFIX
from deerflow.sandbox.sandbox import Sandbox, _validate_extra_env
from deerflow.sandbox.search import GrepMatch, path_matches, should_ignore_path, truncate_line

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from tenki_sandbox import Sandbox as TenkiClientSandbox
    from tenki_sandbox.fs import SandboxFS

T = TypeVar("T")

logger = logging.getLogger(__name__)

_MAX_DOWNLOAD_SIZE = 100 * 1024 * 1024  # 100 MB
# Tenki sandboxes run as the unprivileged ``tenki`` user (HOME=/home/tenki) and
# ``/mnt`` is root-owned, so DeerFlow's ``/mnt/user-data`` virtual prefix is not
# writable directly. Like ``community/e2b_sandbox``, file ops are remapped under
# this home dir (the provider also best-effort symlinks /mnt/user-data → here so
# agent shell commands using the literal path still work).
DEFAULT_TENKI_HOME_DIR = "/home/tenki"
# Frame size for fs.write_stream uploads.
_STREAM_CHUNK = 1024 * 1024

# Tenki SDK exception *class names* that mean the remote session is gone for
# good — matched as strings so this module imports without ``tenki``.
# A terminated/not-found/closed session is unrecoverable; the provider drops it
# and rebuilds on the next call. This is only the named-error half of the rule:
# _is_terminal_failure ALSO treats the builtin ConnectionError / BrokenPipeError
# / EOFError as terminal via isinstance, so a transport reset evicts the sandbox
# and cold-starts the next acquire too. That is a deliberate fail-safe (a reset
# often means the microVM is gone); the cost is churning a warm sandbox on a
# one-off flaky-network blip.
_TERMINAL_ERROR_NAMES = frozenset(
    {
        "SessionTerminatedError",
        "SessionNotFoundError",
        "InvalidStateError",
        "StreamClosedError",
    }
)


class TenkiSandbox(Sandbox):
    """DeerFlow Sandbox adapter that delegates to a live Tenki cloud sandbox.

    Args:
        id: DeerFlow-side sandbox id (the provider's cache key).
        sandbox: A live, started ``tenki_sandbox.Sandbox``. The provider owns
            its lifecycle; this adapter terminates it on :meth:`close`.
        default_env: Static environment merged into every command, overridden
            per-call by the ``env`` passed to :meth:`execute_command`
            (request-scoped secrets).
        home_dir: Writable directory that backs the ``VIRTUAL_PATH_PREFIX``
            (``/mnt/user-data``) prefix inside the sandbox. Defaults to
            :data:`DEFAULT_TENKI_HOME_DIR`.
        on_terminal_failure: Optional callback ``(sandbox_id, reason)`` invoked
            when an operation fails with a terminal Tenki error, so the provider
            can evict the dead sandbox.
    """

    #: Every call is a fresh ``sh -lc`` exec in the sandbox — no shell state
    #: survives into the next command.
    persistent_shell_sessions = False

    def __init__(
        self,
        id: str,
        sandbox: TenkiClientSandbox,
        *,
        default_env: dict[str, str] | None = None,
        home_dir: str = DEFAULT_TENKI_HOME_DIR,
        on_terminal_failure: Callable[[str, str], None] | None = None,
    ) -> None:
        super().__init__(id)
        self._sandbox = sandbox
        self._default_env = dict(default_env or {})
        self._home_dir = home_dir.rstrip("/") or "/"
        self._on_terminal_failure = on_terminal_failure
        self._lock = threading.Lock()
        # Serialises the append read-modify-write across its three fs ops. A
        # lock distinct from _lock, so it can wrap the whole sequence without the
        # per-op eviction callback (which reaches back into the provider) ever
        # running under it.
        self._write_lock = threading.Lock()
        self._closed = False

    @property
    def is_closed(self) -> bool:
        with self._lock:
            return self._closed

    @staticmethod
    def _is_terminal_failure(error: Exception) -> bool:
        if isinstance(error, (BrokenPipeError, ConnectionError, EOFError)):
            return True
        return type(error).__name__ in _TERMINAL_ERROR_NAMES

    def close(self) -> None:
        """Terminate the underlying Tenki session (idempotent).

        The microVM is terminated *first*; the adapter is only marked closed once
        the session is actually gone, so a failed termination stays retryable
        instead of silently leaking a running (billed) sandbox. A terminal
        session error means it is already gone, which counts as closed; anything
        else is raised so the caller can retry or alert.
        """
        with self._lock:
            if self._closed:
                return
            sandbox = self._sandbox
        try:
            sandbox.close()
        except Exception as e:
            if not self._is_terminal_failure(e):
                logger.error("Error terminating Tenki sandbox %s: %s", self.id, e)
                raise
            logger.info("Tenki sandbox %s was already gone at close: %s", self.id, e)
        with self._lock:
            self._closed = True

    # ── bridge helpers ──────────────────────────────────────────────────

    def _note_failure(self, error: Exception) -> None:
        """Evict this sandbox when an operation failed with a terminal error."""
        if self._on_terminal_failure is None or not self._is_terminal_failure(error):
            return
        try:
            self._on_terminal_failure(self.id, str(error))
        except Exception:
            logger.exception("Terminal Tenki failure callback errored for %s", self.id)

    def _fs_op(self, op: Callable[[SandboxFS], T]) -> T:
        """Run a native ``sandbox.fs`` call, evicting the sandbox on terminal errors.

        The lock is held across ``op`` (not just the fs lookup) so concurrent
        calls on the same sandbox serialise: the Tenki SDK shares one connection
        per instance, like community/e2b_sandbox. ``_note_failure`` runs *after*
        the lock is released — it reaches back into the provider, which locks in
        the opposite order (provider then sandbox), so holding both at once could
        deadlock.
        """
        with self._lock:
            if self._closed:
                raise RuntimeError("sandbox has been closed")
            fs = self._sandbox.fs
            try:
                return op(fs)
            except Exception as e:
                failure = e
        self._note_failure(failure)
        raise failure

    def _exec(self, *argv: str, env: dict[str, str] | None = None, timeout: float | None = None) -> Any:
        # No forced cwd: commands run in the sandbox default working directory
        # (like community/e2b_sandbox and community/boxlite); file ops address
        # absolute, home-remapped paths, so cwd is irrelevant to them.
        #
        # No auto-retry: exec is not idempotent (the command may have run
        # server-side before a transport ack dropped), so re-running it risks
        # double side effects. Like boxlite, a transient error is surfaced to the
        # caller (returned as text by execute_command); a terminal session error
        # additionally evicts the sandbox so the next acquire rebuilds it.
        with self._lock:
            if self._closed:
                raise RuntimeError("sandbox has been closed")
            sandbox = self._sandbox
        try:
            return sandbox.exec(*argv, env=env, timeout=timeout)
        except Exception as e:
            self._note_failure(e)
            raise

    def _sh(self, script: str, env: dict[str, str] | None = None, timeout: float | None = None) -> Any:
        return self._exec("sh", "-lc", script, env=env, timeout=timeout)

    # ── path safety (mirrors community/e2b_sandbox) ──────────────────────

    @staticmethod
    def _guard_traversal(path: str) -> str:
        if not path:
            raise ValueError("path must be a non-empty string")
        normalized = path.replace("\\", "/")
        for segment in normalized.split("/"):
            if segment == "..":
                raise PermissionError(f"Access denied: path traversal detected in '{path}'")
        return normalized

    def _resolve_path(self, path: str) -> str:
        """Map DeerFlow virtual paths into the writable sandbox home dir.

        ``VIRTUAL_PATH_PREFIX`` (``/mnt/user-data``) is rewritten under
        :attr:`_home_dir`; other absolute paths pass through so the sandbox can
        reach system directories when needed. Traversal is always rejected.
        """
        normalized = self._guard_traversal(path)
        if normalized == VIRTUAL_PATH_PREFIX or normalized.startswith(f"{VIRTUAL_PATH_PREFIX}/"):
            tail = normalized[len(VIRTUAL_PATH_PREFIX) :].lstrip("/")
            return f"{self._home_dir}/{tail}".rstrip("/") if tail else self._home_dir
        return normalized

    def _virtual_path(self, resolved: str) -> str:
        """Inverse of :meth:`_resolve_path` — the form callers gave us.

        Everything that *returns* paths (``list_dir``/``glob``/``grep``) reports
        them under ``VIRTUAL_PATH_PREFIX``, not the sandbox-internal home dir, so
        results can be fed straight back into the other file APIs.
        """
        if resolved == self._home_dir:
            return VIRTUAL_PATH_PREFIX
        if resolved.startswith(f"{self._home_dir}/"):
            return f"{VIRTUAL_PATH_PREFIX}/{resolved[len(self._home_dir) :].lstrip('/')}"
        return resolved

    # ── command execution ───────────────────────────────────────────────

    def execute_command(
        self,
        command: str,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> str:
        """Run ``command`` through a shell in the Tenki sandbox and return output.

        DeerFlow passes a bash command *string*; it runs through ``sh -lc``.
        Per-call ``env`` is layered over the static config environment and
        scoped to this command only (request-scoped secrets, issue #3861).
        """
        _validate_extra_env(env)  # POSIX env-var key rule; raises ValueError on a bad key
        if self.is_closed:
            return "Error: sandbox has been closed"
        merged_env = {**self._default_env, **(env or {})} or None
        try:
            result = self._sh(command, env=merged_env, timeout=timeout)
        except Exception as e:
            logger.error("Failed to execute command in Tenki sandbox %s: %s", self.id, e)
            return f"Error: {e}"

        stdout = result.stdout_text or ""
        stderr = result.stderr_text or ""
        if stdout and stderr:
            output = f"{stdout}\n{stderr}"
        else:
            output = stdout or stderr
        if result.exit_code not in (0, None):
            # Mirror LocalSandbox: preserve a nonzero exit in the output text
            # even when the command produced output (see e2b_sandbox).
            output = f"{output}\nExit Code: {result.exit_code}" if output else f"Command exited with code {result.exit_code}"
        return output if output else "(no output)"

    # ── file operations ─────────────────────────────────────────────────

    def read_file(self, path: str) -> str:
        resolved = self._resolve_path(path)
        try:
            return self._fs_op(lambda fs: fs.read_text(resolved))
        except Exception as e:
            logger.error("read_file %s failed: %s", resolved, e)
            return f"Error: {e}"

    def write_file(self, path: str, content: str, append: bool = False) -> None:
        self._write_bytes(self._resolve_path(path), content.encode("utf-8"), append=append)

    def update_file(self, path: str, content: bytes) -> None:
        self._write_bytes(self._resolve_path(path), content, append=False)

    def _write_bytes(self, resolved: str, data: bytes, *, append: bool) -> None:
        parent = posixpath.dirname(resolved)
        if not append:
            if parent:
                self._fs_op(lambda fs: fs.mkdir(parent))
            self._fs_op(lambda fs: fs.write_stream(resolved, _frames(data)))
            return

        # Tenki's write stream has no append mode (it starts at offset 0), so we
        # read-modify-write like community/e2b_sandbox. The read and the write are
        # separate fs ops, so two concurrent appends could both read the same
        # pre-image and the second would clobber the first; _write_lock makes the
        # whole sequence atomic.
        with self._write_lock:
            if parent:
                self._fs_op(lambda fs: fs.mkdir(parent))
            try:
                data = self._fs_op(lambda fs: fs.read_bytes(resolved)) + data
            except Exception as e:
                if type(e).__name__ != "FileNotFoundError":
                    raise
            self._fs_op(lambda fs: fs.write_stream(resolved, _frames(data)))

    def download_file(self, path: str) -> bytes:
        normalized = self._guard_traversal(path)
        stripped = normalized.lstrip("/")
        allowed = VIRTUAL_PATH_PREFIX.lstrip("/")
        if stripped != allowed and not stripped.startswith(f"{allowed}/"):
            raise PermissionError(f"Access denied: path must be under '{VIRTUAL_PATH_PREFIX}': '{path}'")
        resolved = self._resolve_path(path)

        with self._lock:
            if self._closed:
                raise RuntimeError("sandbox has been closed")
            fs = self._sandbox.fs

        # Deliberate: the lock is dropped before streaming, unlike _fs_op which
        # holds it across its op. _fs_op's serialization guards short, bounded
        # calls; a download can be up to _MAX_DOWNLOAD_SIZE (100 MB), and holding
        # the instance lock across it would block every other tool on this
        # sandbox for the whole transfer. The Tenki read stream is safe to run
        # alongside other ops (the SDK multiplexes over its connection), so we
        # accept the interleave here for latency and still evict on a terminal
        # transport error via _note_failure below.
        #
        # The cap is enforced on bytes actually received, so a file that grows
        # mid-transfer still can't exceed it (a stat-then-read check could).
        chunks: list[bytes] = []
        total = 0
        try:
            for chunk in fs.read_stream(resolved):
                total += len(chunk)
                if total > _MAX_DOWNLOAD_SIZE:
                    raise OSError(errno.EFBIG, f"File exceeds maximum download size of {_MAX_DOWNLOAD_SIZE} bytes", path)
                chunks.append(chunk)
        except OSError as e:
            # Our own EFBIG size-cap is not a session death — let it pass through
            # without evicting. Every other OSError is a real transport failure:
            # ConnectionError / BrokenPipeError / EOFError are OSError subclasses
            # that _is_terminal_failure treats as terminal, so they must route
            # through _note_failure like _fs_op/_exec do. Without this, a session
            # that dies mid-download is never evicted and the agent keeps hitting
            # OSErrors until some other op happens to reap it.
            if e.errno == errno.EFBIG:
                raise
            self._note_failure(e)
            raise
        except Exception as e:
            self._note_failure(e)
            raise OSError(f"cannot read '{path}' from sandbox: {e}") from e
        return b"".join(chunks)

    def list_dir(self, path: str, max_depth: int = 2) -> list[str]:
        resolved = self._resolve_path(path)
        r = self._sh(f"find {shlex.quote(resolved)} -maxdepth {int(max_depth)} \\( -type f -o -type d \\) 2>/dev/null | head -500")
        return [self._virtual_path(line.strip()) for line in (r.stdout_text or "").splitlines() if line.strip()]

    def glob(
        self,
        path: str,
        pattern: str,
        *,
        include_dirs: bool = False,
        max_results: int = 200,
    ) -> tuple[list[str], bool]:
        resolved = self._resolve_path(path)
        types = ("f", "d") if include_dirs else ("f",)
        type_expr = " -o ".join(f"-type {t}" for t in types)
        hard_limit = max(max_results * 4, max_results + 50)
        r = self._sh(f"find {shlex.quote(resolved)} \\( {type_expr} \\) -print 2>/dev/null | head -{hard_limit}")

        matches: list[str] = []
        root = resolved.rstrip("/") or "/"
        root_prefix = root if root == "/" else f"{root}/"
        for entry in (r.stdout_text or "").splitlines():
            entry = entry.strip()
            if not entry or (entry != root and not entry.startswith(root_prefix)):
                continue
            if should_ignore_path(entry):
                continue
            rel_path = entry[len(root) :].lstrip("/")
            if not rel_path:
                continue
            if path_matches(pattern, rel_path):
                matches.append(self._virtual_path(entry))
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
        # Validate a regex pattern at the boundary (grep uses POSIX ERE, but this
        # catches gross errors); a literal needs none. grep receives the RAW
        # pattern: -F matches it literally, -E as a regex.
        if not literal:
            re.compile(pattern, 0 if case_sensitive else re.IGNORECASE)

        resolved = self._resolve_path(path)
        # busybox+GNU-portable flags: -r recursive, -H always print the filename
        # (without it, grep -r on a path that resolves to a single file prints
        # "line:text" and the file:line:text unpack below drops every match), -n
        # line numbers, -I skip binary, -E/-F regex vs fixed. --include and -m are
        # omitted for busybox portability; glob-scoping and the result cap are
        # applied in Python below.
        flags = ["-r", "-H", "-n", "-I"]
        if not case_sensitive:
            flags.append("-i")
        flags.append("-F" if literal else "-E")
        total_cap = max(max_results * 4, max_results + 50)
        cmd = "grep " + " ".join(flags) + f" -e {shlex.quote(pattern)} {shlex.quote(resolved)} 2>/dev/null | head -{total_cap}"
        r = self._sh(cmd)

        root = resolved.rstrip("/") or "/"
        root_prefix = root if root == "/" else f"{root}/"
        matches: list[GrepMatch] = []
        truncated = False
        for raw in (r.stdout_text or "").splitlines():
            try:
                file_path, line_no_str, line_text = raw.split(":", 2)
            except ValueError:
                continue
            try:
                line_number = int(line_no_str)
            except ValueError:
                continue
            if should_ignore_path(file_path):
                continue
            if glob is not None:
                # Match the caller's real directory scope: a pattern like
                # "src/*.js" must not broaden to every *.js in the tree. Same
                # helper, same relative-to-root semantics as glob() above.
                if file_path != root and not file_path.startswith(root_prefix):
                    continue
                rel_path = posixpath.basename(file_path) if file_path == root else file_path[len(root) :].lstrip("/")
                if not path_matches(glob, rel_path):
                    continue
            matches.append(GrepMatch(path=self._virtual_path(file_path), line_number=line_number, line=truncate_line(line_text)))
            if len(matches) >= max_results:
                truncated = True
                break
        return matches, truncated


def _frames(data: bytes) -> Iterator[bytes]:
    """Slice ``data`` into upload frames for ``fs.write_stream``."""
    for i in range(0, len(data), _STREAM_CHUNK):
        yield data[i : i + _STREAM_CHUNK]
