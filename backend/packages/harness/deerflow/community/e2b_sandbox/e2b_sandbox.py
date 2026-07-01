from __future__ import annotations

import errno
import logging
import re
import shlex
import threading

from e2b_code_interpreter import Sandbox as E2BClientSandbox

from deerflow.config.paths import VIRTUAL_PATH_PREFIX
from deerflow.sandbox.sandbox import Sandbox
from deerflow.sandbox.search import GrepMatch, path_matches, should_ignore_path, truncate_line

logger = logging.getLogger(__name__)

_MAX_DOWNLOAD_SIZE = 100 * 1024 * 1024  # 100 MB

# Where DeerFlow's ``/mnt/user-data`` virtual prefix is materialised inside
# the e2b sandbox.  e2b code-interpreter templates default to ``/home/user``
# as the working directory.
DEFAULT_E2B_HOME_DIR = "/home/user"

_E2B_NOT_FOUND_SIGNATURES = (
    "sandbox was not found",
    "sandbox not found",
    "paused sandbox",
)


def _is_sandbox_gone_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(sig in msg for sig in _E2B_NOT_FOUND_SIGNATURES)


class E2BSandbox(Sandbox):
    """DeerFlow Sandbox adapter that delegates to an e2b cloud sandbox.

    Args:
        id: DeerFlow-side sandbox id (used as cache key in the provider).
        client: A live ``e2b_code_interpreter.Sandbox`` (sync) instance.
            The caller owns the connection and is responsible for ``kill()``;
            this wrapper only calls ``close()`` on its host-side HTTP client
            during release.
        home_dir: Directory inside the sandbox that backs the
            ``VIRTUAL_PATH_PREFIX`` (``/mnt/user-data``) prefix.  Defaults to
            :data:`DEFAULT_E2B_HOME_DIR`.
    """

    def __init__(
        self,
        id: str,
        client: E2BClientSandbox,
        *,
        home_dir: str = DEFAULT_E2B_HOME_DIR,
    ) -> None:
        super().__init__(id)
        self._client = client
        self._home_dir = home_dir.rstrip("/") or "/"
        self._lock = threading.Lock()
        self._closed = False
        self._dead = False

    # ── Properties / lifecycle ───────────────────────────────────────────

    @property
    def client(self) -> E2BClientSandbox:
        return self._client

    @property
    def home_dir(self) -> str:
        return self._home_dir

    @property
    def sandbox_id(self) -> str:
        """e2b-side sandbox id (different from DeerFlow's ``self.id`` cache key)."""
        return getattr(self._client, "sandbox_id", self.id)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            client = self._client
            self._client = None

        if client is None:
            return

        for closer in (
            getattr(client, "close", None),
            getattr(getattr(client, "_transport", None), "close", None),
        ):
            if callable(closer):
                try:
                    closer()
                except Exception as e:
                    logger.warning("Error closing E2BSandbox %s: %s", self.id, e)
                return

    def _resolve_path(self, path: str) -> str:
        """Map DeerFlow virtual paths into the e2b sandbox filesystem.

        ``VIRTUAL_PATH_PREFIX`` (``/mnt/user-data``) is rewritten under
        :attr:`home_dir`, mirroring how ``LocalContainerBackend`` bind-mounts
        the host workspace into the AIO container at ``/mnt/user-data``.
        Other absolute paths are returned verbatim so the sandbox can reach
        system directories (``/tmp``, ``/etc``, …) when needed.
        """
        if not path:
            raise ValueError("path must be a non-empty string")
        normalised = path.replace("\\", "/")
        for segment in normalised.split("/"):
            if segment == "..":
                raise PermissionError(f"Access denied: path traversal detected in '{path}'")
        if normalised == VIRTUAL_PATH_PREFIX or normalised.startswith(f"{VIRTUAL_PATH_PREFIX}/"):
            tail = normalised[len(VIRTUAL_PATH_PREFIX) :].lstrip("/")
            return f"{self._home_dir}/{tail}".rstrip("/") if tail else self._home_dir
        return normalised

    def execute_command(self, command: str) -> str:
        """Execute a shell command via ``sandbox.commands.run``.

        Returns the combined stdout/stderr.
        The lock serialises concurrent calls on the same instance
        because the e2b SDK shares a single HTTP/2 connection per sandbox.
        """
        with self._lock:
            client = self._client
            if client is None:
                return "Error: sandbox client has been closed"
            if self._dead:
                return "Error: e2b sandbox has been reaped by the control plane (idle timeout or explicit pause). The provider will rebuild a fresh sandbox on the next tool call."
            try:
                result = client.commands.run(command)
                stdout = getattr(result, "stdout", "") or ""
                stderr = getattr(result, "stderr", "") or ""
                exit_code = getattr(result, "exit_code", 0)
                if stdout and stderr:
                    output = f"{stdout}\n{stderr}"
                else:
                    output = stdout or stderr
                if exit_code not in (0, None) and not output:
                    output = f"Command exited with code {exit_code}"
                return output if output else "(no output)"
            except Exception as e:
                if _is_sandbox_gone_error(e):
                    self._dead = True
                logger.error("Failed to execute command in e2b sandbox: %s", e)
                return f"Error: {e}"

    @property
    def is_dead(self) -> bool:
        """Whether the underlying e2b VM is known to be reaped.

        Updated lazily by ``execute_command`` and the provider's ``ping`` /
        bootstrap calls — there is no proactive heartbeat. Reading the value
        does *not* round-trip to the API.
        """
        with self._lock:
            return self._dead

    def ping(self) -> bool:
        """Cheap health check: returns False if the e2b VM has been reaped.

        Run as ``commands.run("true")`` so successful execution implies the
        full HTTP path (auth + control plane + envd) is alive.  Sets
        ``_dead = True`` on the same "sandbox not found" signature
        :func:`_is_sandbox_gone_error` recognises so subsequent calls
        short-circuit.
        """
        with self._lock:
            if self._dead or self._client is None:
                return False
            client = self._client
        try:
            client.commands.run("true")
            return True
        except Exception as e:
            if _is_sandbox_gone_error(e):
                with self._lock:
                    self._dead = True
                return False
            logger.warning("e2b sandbox ping raised non-fatal error: %s", e)
            return True

    def read_file(self, path: str) -> str:
        resolved = self._resolve_path(path)
        try:
            content = self._client.files.read(resolved)
            if isinstance(content, bytes):
                return content.decode("utf-8", errors="replace")
            return content if content is not None else ""
        except Exception as e:
            logger.error("Failed to read file %s in e2b sandbox: %s", resolved, e)
            return f"Error: {e}"

    def download_file(self, path: str) -> bytes:
        normalised = path.replace("\\", "/")
        for segment in normalised.split("/"):
            if segment == "..":
                logger.error("Refused download due to path traversal: %s", path)
                raise PermissionError(f"Access denied: path traversal detected in '{path}'")

        stripped_path = normalised.lstrip("/")
        allowed_prefix = VIRTUAL_PATH_PREFIX.lstrip("/")
        if stripped_path != allowed_prefix and not stripped_path.startswith(f"{allowed_prefix}/"):
            logger.error(
                "Refused download outside allowed directory: path=%s, allowed_prefix=%s",
                path,
                VIRTUAL_PATH_PREFIX,
            )
            raise PermissionError(f"Access denied: path must be under '{VIRTUAL_PATH_PREFIX}': '{path}'")

        resolved = self._resolve_path(path)
        # Prefer the streaming API so the 100 MB cap is enforced *before* the
        # whole payload is buffered in the gateway process.  ``format="bytes"``
        # is implemented by the e2b SDK as ``bytearray(r.content)`` — i.e. the
        # entire file is materialised in memory before returning — which would
        # let a multi-GB artifact OOM the shared gateway on hosted deployments.
        # ``format="stream"`` returns a ``FileStreamReader`` (an
        # ``Iterator[bytes]``) that owns its HTTP response and releases the
        # pooled connection on exhaustion / close / error.
        with self._lock:
            client = self._client
            if client is None:
                raise RuntimeError("sandbox client has been closed")
            try:
                data = client.files.read(resolved, format="stream")
            except TypeError:
                try:
                    data = client.files.read(resolved, format="bytes")
                except Exception as e:
                    logger.error("Failed to download file %s from e2b sandbox: %s", resolved, e)
                    raise OSError(f"Failed to download file '{path}' from sandbox: {e}") from e
            except Exception as e:
                logger.error("Failed to download file %s from e2b sandbox: %s", resolved, e)
                raise OSError(f"Failed to download file '{path}' from sandbox: {e}") from e

        if data is None:
            return b""

        # Buffered fallbacks (bytes/bytearray/str): apply the cap up front so
        # we still refuse oversize payloads even on this path.
        if isinstance(data, (bytes, bytearray)):
            if len(data) > _MAX_DOWNLOAD_SIZE:
                raise OSError(
                    errno.EFBIG,
                    f"File exceeds maximum download size of {_MAX_DOWNLOAD_SIZE} bytes",
                    path,
                )
            return bytes(data)
        if isinstance(data, str):
            encoded = data.encode("utf-8")
            if len(encoded) > _MAX_DOWNLOAD_SIZE:
                raise OSError(
                    errno.EFBIG,
                    f"File exceeds maximum download size of {_MAX_DOWNLOAD_SIZE} bytes",
                    path,
                )
            return encoded

        chunks: list[bytes] = []
        total = 0
        close = getattr(data, "close", None)
        try:
            try:
                for chunk in data:
                    if not chunk:
                        continue
                    chunk_bytes = chunk if isinstance(chunk, bytes) else bytes(chunk)
                    total += len(chunk_bytes)
                    if total > _MAX_DOWNLOAD_SIZE:
                        raise OSError(
                            errno.EFBIG,
                            f"File exceeds maximum download size of {_MAX_DOWNLOAD_SIZE} bytes",
                            path,
                        )
                    chunks.append(chunk_bytes)
            except OSError:
                raise
            except Exception as e:
                logger.error("Failed to stream file %s from e2b sandbox: %s", resolved, e)
                raise OSError(f"Failed to download file '{path}' from sandbox: {e}") from e
        finally:
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        return b"".join(chunks)

    def list_dir(self, path: str, max_depth: int = 2) -> list[str]:
        resolved = self._resolve_path(path)
        with self._lock:
            client = self._client
            if client is None:
                return []
            try:
                result = client.commands.run(f"find {shlex.quote(resolved)} -maxdepth {int(max_depth)} \\( -type f -o -type d \\) 2>/dev/null | head -500")
                output = getattr(result, "stdout", "") or ""
                return [line.strip() for line in output.splitlines() if line.strip()]
            except Exception as e:
                logger.error("Failed to list_dir %s in e2b sandbox: %s", resolved, e)
                return []

    def write_file(self, path: str, content: str, append: bool = False) -> None:
        resolved = self._resolve_path(path)
        with self._lock:
            client = self._client
            if client is None:
                raise RuntimeError("sandbox client has been closed")
            try:
                if append:
                    existing = ""
                    try:
                        existing = client.files.read(resolved) or ""
                        if isinstance(existing, bytes):
                            existing = existing.decode("utf-8", errors="replace")
                    except Exception:
                        existing = ""
                    content = (existing or "") + content
                client.files.write(resolved, content)
            except Exception as e:
                logger.error("Failed to write file %s in e2b sandbox: %s", resolved, e)
                raise

    def update_file(self, path: str, content: bytes) -> None:
        resolved = self._resolve_path(path)
        with self._lock:
            client = self._client
            if client is None:
                raise RuntimeError("sandbox client has been closed")
            try:
                # e2b's ``files.write`` accepts either ``str`` or ``bytes`` —
                # passing bytes preserves binary content losslessly.
                client.files.write(resolved, content)
            except Exception as e:
                logger.error("Failed to update file %s in e2b sandbox: %s", resolved, e)
                raise

    def glob(
        self,
        path: str,
        pattern: str,
        *,
        include_dirs: bool = False,
        max_results: int = 200,
    ) -> tuple[list[str], bool]:
        resolved = self._resolve_path(path)
        types = "f,d" if include_dirs else "f"
        with self._lock:
            client = self._client
            if client is None:
                return [], False
            try:
                hard_limit = max(max_results * 4, max_results + 50)
                cmd = f"find {shlex.quote(resolved)} \\( " + " -o ".join(f"-type {t}" for t in types.split(",")) + f" \\) -print 2>/dev/null | head -{hard_limit}"
                result = client.commands.run(cmd)
                output = getattr(result, "stdout", "") or ""
            except Exception as e:
                logger.error("Failed to glob in e2b sandbox: %s", e)
                return [], False

        matches: list[str] = []
        root = resolved.rstrip("/") or "/"
        root_prefix = root if root == "/" else f"{root}/"
        for entry in output.splitlines():
            entry = entry.strip()
            if not entry:
                continue
            if entry != root and not entry.startswith(root_prefix):
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
        regex_source = re.escape(pattern) if literal else pattern
        re.compile(regex_source, 0 if case_sensitive else re.IGNORECASE)

        resolved = self._resolve_path(path)
        # Build a portable ``grep`` invocation:
        # -r recursive, -n line numbers, -H always print filename, -I skip
        # binary files, -E extended regex (or -F for literal/fixed strings).
        flags = ["-r", "-n", "-H", "-I"]
        if not case_sensitive:
            flags.append("-i")
        if literal:
            flags.append("-F")
        else:
            flags.append("-E")
        if glob is not None:
            include_pattern = glob.split("/")[-1] or glob
            flags.append(f"--include={include_pattern}")

        per_file_cap = max(max_results, 50)
        total_cap = max(max_results * 4, max_results + 50)
        flags.append(f"-m{per_file_cap}")

        cmd = "grep " + " ".join(flags) + f" -- {shlex.quote(regex_source)} {shlex.quote(resolved)} 2>/dev/null" + f" | head -{total_cap}"

        with self._lock:
            client = self._client
            if client is None:
                return [], False
            try:
                result = client.commands.run(cmd)
                output = getattr(result, "stdout", "") or ""
            except Exception as e:
                logger.error("Failed to grep in e2b sandbox: %s", e)
                return [], False

        matches: list[GrepMatch] = []
        truncated = False
        for raw in output.splitlines():
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
            matches.append(
                GrepMatch(
                    path=file_path,
                    line_number=line_number,
                    line=truncate_line(line_text),
                )
            )
            if len(matches) >= max_results:
                truncated = True
                break
        return matches, truncated
