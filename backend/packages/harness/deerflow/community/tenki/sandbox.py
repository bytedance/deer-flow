"""``TenkiSandbox`` — DeerFlow :class:`Sandbox` backed by a Tenki cloud sandbox.

Tenki's Python SDK (``tenki-sandbox``) is synchronous, so — unlike
``community/boxlite`` — this adapter calls the SDK directly with no event-loop
bridge. Every operation is a shell command run inside the sandbox (``cat`` /
``find`` / ``grep`` / chunked ``base64``), parsed with the shared
``deerflow.sandbox.search`` helpers, the same exec-driven approach as
``community/e2b_sandbox`` and ``community/boxlite``. Commands use only
busybox-portable flags so any Tenki base image works.

The Tenki SDK is not imported at module load (only its exception *class names*
are matched, as strings), so importing this package never requires
``tenki-sandbox`` to be installed — it is needed only once the provider is
selected and a sandbox is actually created.
"""

from __future__ import annotations

import base64
import errno
import logging
import posixpath
import re
import shlex
import threading
from typing import TYPE_CHECKING, Any

from deerflow.config.paths import VIRTUAL_PATH_PREFIX
from deerflow.sandbox.sandbox import Sandbox, _validate_extra_env
from deerflow.sandbox.search import GrepMatch, path_matches, should_ignore_path, truncate_line

if TYPE_CHECKING:
    from collections.abc import Callable

    from tenki_sandbox import Sandbox as TenkiClientSandbox

logger = logging.getLogger(__name__)

_MAX_DOWNLOAD_SIZE = 100 * 1024 * 1024  # 100 MB
# Tenki sandboxes run as the unprivileged ``tenki`` user (HOME=/home/tenki) and
# ``/mnt`` is root-owned, so DeerFlow's ``/mnt/user-data`` virtual prefix is not
# writable directly. Like ``community/e2b_sandbox``, file ops are remapped under
# this home dir (the provider also best-effort symlinks /mnt/user-data → here so
# agent shell commands using the literal path still work).
DEFAULT_TENKI_HOME_DIR = "/home/tenki"
# One base64 chunk stays well under Linux MAX_ARG_STRLEN (128 KiB per argv
# entry); 60000 is a multiple of 4 so each chunk is a self-contained base64
# unit whose decoded bytes concatenate losslessly.
_B64_CHUNK = 60000

# Tenki SDK exception *class names* that mean the remote session is gone for
# good — matched as strings so this module imports without ``tenki-sandbox``.
# A terminated/not-found/closed session is unrecoverable; the provider drops it
# and rebuilds on the next call. Transport hiccups are NOT in this set.
_TERMINAL_ERROR_NAMES = frozenset(
    {
        "SessionTerminatedError",
        "SessionNotFoundError",
        "InvalidStateError",
        "StreamClosedError",
    }
)

# Substrings (matched case-insensitively on the error message) that mark a
# transient data-plane transport blip — the gRPC channel to a still-alive
# session dropped. Observed in live testing as a one-off on ~1/9 runs. These get
# a single bounded retry; a genuinely dead session raises a *terminal* error
# (above) instead, so this never masks a real failure.
_RETRYABLE_ERROR_MARKERS = (
    "socket closed",
    "unavailable",
    "failed to connect",
    "connection reset",
    "transport is closing",
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

    @staticmethod
    def _is_retryable_failure(error: Exception) -> bool:
        msg = str(error).lower()
        return any(marker in msg for marker in _RETRYABLE_ERROR_MARKERS)

    def close(self) -> None:
        """Terminate the underlying Tenki session (idempotent)."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            sandbox = self._sandbox
        try:
            sandbox.close()
        except Exception as e:
            logger.warning("Error terminating Tenki sandbox %s: %s", self.id, e)

    # ── bridge helpers ──────────────────────────────────────────────────

    def _exec(self, *argv: str, env: dict[str, str] | None = None, timeout: float | None = None) -> Any:
        # No forced cwd: commands run in the sandbox default working directory
        # (like community/e2b_sandbox and community/boxlite); file ops address
        # absolute, home-remapped paths, so cwd is irrelevant to them.
        with self._lock:
            if self._closed:
                raise RuntimeError("sandbox has been closed")
            sandbox = self._sandbox

        # ponytail: one retry, no backoff — enough for the observed transient
        # gRPC data-plane drop; more attempts belong to the provider's
        # recreate-on-terminal path, not here.
        for attempt in range(2):
            try:
                return sandbox.exec(*argv, env=env, timeout=timeout)
            except Exception as e:
                if attempt == 0 and self._is_retryable_failure(e):
                    logger.warning("Transient Tenki transport error on %s (retrying once): %s", self.id, e)
                    continue
                if self._on_terminal_failure is not None and self._is_terminal_failure(e):
                    try:
                        self._on_terminal_failure(self.id, str(e))
                    except Exception:
                        logger.exception("Terminal Tenki failure callback errored for %s", self.id)
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
        if result.exit_code not in (0, None) and not output:
            output = f"Command exited with code {result.exit_code}"
        return output if output else "(no output)"

    # ── file operations ─────────────────────────────────────────────────

    def read_file(self, path: str) -> str:
        resolved = self._resolve_path(path)
        try:
            r = self._exec("cat", "--", resolved)
        except Exception as e:
            logger.error("read_file %s failed: %s", resolved, e)
            return f"Error: {e}"
        if r.exit_code not in (0, None):
            return f"Error: {(r.stderr_text or '').strip() or 'cannot read file'}"
        return r.stdout_text or ""

    def write_file(self, path: str, content: str, append: bool = False) -> None:
        self._write_bytes(self._resolve_path(path), content.encode("utf-8"), append=append)

    def update_file(self, path: str, content: bytes) -> None:
        self._write_bytes(self._resolve_path(path), content, append=False)

    def _write_bytes(self, resolved: str, data: bytes, *, append: bool) -> None:
        parent = posixpath.dirname(resolved)
        if parent:
            mk = self._sh(f"mkdir -p {shlex.quote(parent)}")
            if mk.exit_code not in (0, None):
                raise OSError(f"cannot create parent of '{resolved}': {(mk.stderr_text or '').strip()}")

        b64 = base64.b64encode(data).decode("ascii")
        if not b64:  # empty file — create/truncate without piping
            r = self._sh(f": {'>>' if append else '>'} {shlex.quote(resolved)}")
            if r.exit_code not in (0, None):
                raise OSError(f"write '{resolved}' failed: {(r.stderr_text or '').strip()}")
            return

        first = True
        for i in range(0, len(b64), _B64_CHUNK):
            chunk = b64[i : i + _B64_CHUNK]
            redir = ">>" if (append or not first) else ">"
            r = self._sh(f"printf %s {shlex.quote(chunk)} | base64 -d {redir} {shlex.quote(resolved)}")
            if r.exit_code not in (0, None):
                raise OSError(f"write '{resolved}' failed: {(r.stderr_text or '').strip()}")
            first = False

    def download_file(self, path: str) -> bytes:
        normalized = self._guard_traversal(path)
        stripped = normalized.lstrip("/")
        allowed = VIRTUAL_PATH_PREFIX.lstrip("/")
        if stripped != allowed and not stripped.startswith(f"{allowed}/"):
            raise PermissionError(f"Access denied: path must be under '{VIRTUAL_PATH_PREFIX}': '{path}'")
        resolved = self._resolve_path(path)

        # Enforce the size cap before buffering the whole payload.
        size_r = self._sh(f"wc -c < {shlex.quote(resolved)}")
        if size_r.exit_code not in (0, None):
            raise OSError(f"cannot read '{path}' from sandbox: {(size_r.stderr_text or '').strip() or 'not found'}")
        try:
            size = int((size_r.stdout_text or "0").strip() or "0")
        except ValueError:
            size = 0
        if size > _MAX_DOWNLOAD_SIZE:
            raise OSError(errno.EFBIG, f"File exceeds maximum download size of {_MAX_DOWNLOAD_SIZE} bytes", path)

        r = self._sh(f"base64 {shlex.quote(resolved)}")
        if r.exit_code not in (0, None):
            raise OSError(f"cannot read '{path}' from sandbox: {(r.stderr_text or '').strip()}")
        try:
            return base64.b64decode("".join((r.stdout_text or "").split()))
        except Exception as e:
            raise OSError(f"failed to decode '{path}' from sandbox: {e}") from e

    def list_dir(self, path: str, max_depth: int = 2) -> list[str]:
        resolved = self._resolve_path(path)
        r = self._sh(f"find {shlex.quote(resolved)} -maxdepth {int(max_depth)} \\( -type f -o -type d \\) 2>/dev/null | head -500")
        return [line.strip() for line in (r.stdout_text or "").splitlines() if line.strip()]

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
        # Validate a regex pattern at the boundary (grep uses POSIX ERE, but this
        # catches gross errors); a literal needs none. grep receives the RAW
        # pattern: -F matches it literally, -E as a regex.
        if not literal:
            re.compile(pattern, 0 if case_sensitive else re.IGNORECASE)

        resolved = self._resolve_path(path)
        # busybox+GNU-portable flags: -r recursive (prints the filename), -n line
        # numbers, -I skip binary, -E/-F regex vs fixed. --include and -m are
        # omitted for busybox portability; glob-scoping and the result cap are
        # applied in Python below.
        flags = ["-r", "-n", "-I"]
        if not case_sensitive:
            flags.append("-i")
        flags.append("-F" if literal else "-E")
        total_cap = max(max_results * 4, max_results + 50)
        cmd = "grep " + " ".join(flags) + f" -e {shlex.quote(pattern)} {shlex.quote(resolved)} 2>/dev/null | head -{total_cap}"
        r = self._sh(cmd)

        include = glob.split("/")[-1] if glob else None
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
            if include and not path_matches(include, posixpath.basename(file_path)):
                continue
            matches.append(GrepMatch(path=file_path, line_number=line_number, line=truncate_line(line_text)))
            if len(matches) >= max_results:
                truncated = True
                break
        return matches, truncated
