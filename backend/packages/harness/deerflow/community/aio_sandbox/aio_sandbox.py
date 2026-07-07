import base64
import errno
import logging
import shlex
import threading
import uuid

from agent_sandbox import Sandbox as AioSandboxClient
from agent_sandbox.core.api_error import ApiError

from deerflow.config.paths import VIRTUAL_PATH_PREFIX
from deerflow.sandbox.sandbox import Sandbox, _validate_extra_env
from deerflow.sandbox.search import GrepMatch, path_matches, should_ignore_path, truncate_line

logger = logging.getLogger(__name__)

_MAX_DOWNLOAD_SIZE = 100 * 1024 * 1024  # 100 MB

_ERROR_OBSERVATION_SIGNATURE = "'ErrorObservation' object has no attribute 'exit_code'"

# Env-bearing commands require the bash.exec API (POST /v1/bash/exec), which the
# all-in-one-sandbox image only ships since 1.9.x. Older images (including any
# ``latest`` tag frozen on the 1.0.0.x line) answer 404 for the whole /v1/bash/*
# namespace. That raw 404 is useless to the model (it just retries), so the
# sandbox fails fast with this operator-facing message instead (#3921).
_BASH_EXEC_UNSUPPORTED_ERROR = (
    "Error: this sandbox image does not support per-command environment injection "
    "(POST /v1/bash/exec returned 404), which is required to run skills that declare "
    "required-secrets. This is a deployment issue that retrying cannot fix: upgrade the "
    "sandbox image to all-in-one-sandbox >= 1.9.3 (set `sandbox.image` in config.yaml, "
    "e.g. pin the tag `1.11.0`) and recreate the sandbox container, then try again."
)


class AioSandbox(Sandbox):
    """Sandbox implementation using the agent-infra/sandbox Docker container.

    This sandbox connects to a running AIO sandbox container via HTTP API.
    A threading lock serializes shell commands to prevent concurrent requests
    from corrupting the container's single persistent session (see #1433).
    """

    def __init__(self, id: str, base_url: str, home_dir: str | None = None):
        """Initialize the AIO sandbox.

        Args:
            id: Unique identifier for this sandbox instance.
            base_url: URL of the sandbox API (e.g., http://localhost:8080).
            home_dir: Home directory inside the sandbox. If None, will be fetched from the sandbox.
        """
        super().__init__(id)
        self._base_url = base_url
        self._client = AioSandboxClient(base_url=base_url, timeout=600)
        self._home_dir = home_dir
        self._lock = threading.Lock()
        self._closed = False
        # Set to True after bash.exec answers 404 (image predates /v1/bash/*),
        # so later env-bearing calls fail fast instead of re-hitting HTTP (#3921).
        self._bash_exec_unsupported = False

    @property
    def base_url(self) -> str:
        return self._base_url

    def close(self) -> None:
        """Best-effort close of the host-side HTTP client owned by this sandbox.

        The agent_sandbox SDK is Fern-generated and exposes no ``close()`` /
        ``__exit__``, so we reach the socket-owning ``httpx.Client`` explicitly
        through its attribute chain::

            Sandbox._client_wrapper        -> SyncClientWrapper
                .httpx_client              -> Fern HttpClient (a wrapper, NOT httpx.Client)
                    .httpx_client          -> httpx.Client     <- the real socket owner

        Closing it releases pooled sockets so long-running provider lifecycles
        do not accumulate unreclaimed host-side resources (#2872).

        Resolution is most-specific-first with graceful degradation: if a future
        SDK adds a top-level ``Sandbox.close()`` it is picked up automatically
        without changing this code. Idempotent, thread-safe, and non-fatal:
        failures during teardown are logged and swallowed so provider/backend
        cleanup is never blocked.
        """
        with self._lock:
            if self._closed:
                return
            self._closed = True
            client = self._client
            # Drop the reference under the lock for use-after-close safety: any
            # later command on this instance fails loudly instead of reusing a
            # half-closed client.
            self._client = None

        if client is None:
            return

        # Walk from the real httpx.Client up to the top-level client, picking the
        # first object that actually exposes close().
        wrapper = getattr(client, "_client_wrapper", None)
        fern_http = getattr(wrapper, "httpx_client", None)
        real_httpx = getattr(fern_http, "httpx_client", None)
        target = next(
            (c for c in (real_httpx, fern_http, client) if c is not None and hasattr(c, "close")),
            None,
        )
        if target is None:
            logger.debug("AioSandbox %s: no closable client found, nothing to release", self.id)
            return

        try:
            target.close()
        except Exception as e:
            logger.warning(f"Error closing AioSandbox client for {self.id}: {e}")

    @property
    def home_dir(self) -> str:
        """Get the home directory inside the sandbox."""
        if self._home_dir is None:
            context = self._client.sandbox.get_context()
            self._home_dir = context.home_dir
        return self._home_dir

    # Default no_change_timeout for exec_command (seconds).  Matches the
    # client-level timeout so that long-running commands which produce no
    # output are not prematurely terminated by the sandbox's built-in 120 s
    # default.
    _DEFAULT_NO_CHANGE_TIMEOUT = 600

    # Wall-clock hard timeout for env-bearing commands routed through bash.exec.
    # The bash.exec API exposes no idle/no-change timeout (unlike
    # shell.exec_command's ``no_change_timeout`` on the legacy path), so
    # env-bearing commands are bounded by total elapsed wall-clock time, not
    # time-since-last-output. Kept at the same numeric value as the legacy idle
    # budget so the two paths broadly agree on how long a single command may
    # run; a future SDK that exposes an idle timeout on bash.exec should switch
    # this call site to it.
    _DEFAULT_HARD_TIMEOUT = 600.0

    def execute_command(
        self,
        command: str,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> str:
        """Execute a shell command in the sandbox.

        Uses a lock to serialize concurrent requests. The AIO sandbox
        container maintains a single persistent shell session that
        corrupts when hit with concurrent exec_command calls (returns
        ``ErrorObservation`` instead of real output). If corruption is
        detected despite the lock (e.g. multiple processes sharing a
        sandbox), the command is retried on a fresh session.

        Args:
            command: The command to execute.
            env: Optional per-call environment variables (request-scoped secrets,
                issue #3861). When provided, the command runs via the ``bash.exec``
                API (which supports per-command env) on a fresh auto-created session
                so the secrets are scoped to this single command and never persist;
                secret values travel in the structured ``env`` field, never in the
                command string. When ``None`` the legacy persistent-shell path runs
                unchanged.
            timeout: Optional per-call timeout. The current sandbox SDK does not
                expose a command-level timeout distinct from its client/request
                timeout, so DeerFlow keeps using the backend's default here.

        Returns:
            The output of the command.
        """
        del timeout
        # Validate ``env`` keys before forwarding them to the ``bash.exec`` API.
        # The public ``Sandbox.execute_command`` contract accepts arbitrary dict
        # keys; enforcing the POSIX env-var name rule keeps the contract
        # consistent with the local and e2b sandboxes and catches unsafe keys
        # early. ``_validate_extra_env`` is a no-op when ``env`` is None or empty.
        _validate_extra_env(env)
        if env:
            return self._execute_with_env(command, env)
        with self._lock:
            try:
                result = self._client.shell.exec_command(command=command, no_change_timeout=self._DEFAULT_NO_CHANGE_TIMEOUT)
                output = result.data.output if result.data else ""

                if output and _ERROR_OBSERVATION_SIGNATURE in output:
                    logger.warning("ErrorObservation detected in sandbox output, retrying on a fresh session")
                    # exec_command only auto-creates a session when called with
                    # no id, so the recovery session must be created explicitly
                    # before we target it on retry.
                    fresh_id = str(uuid.uuid4())
                    self._client.shell.create_session(id=fresh_id)
                    try:
                        result = self._client.shell.exec_command(command=command, id=fresh_id, no_change_timeout=self._DEFAULT_NO_CHANGE_TIMEOUT)
                        output = result.data.output if result.data else ""
                    finally:
                        # Release the one-shot recovery session, best-effort, so
                        # repeated corruption can't accumulate sessions.
                        try:
                            self._client.shell.cleanup_session(fresh_id)
                        except Exception as cleanup_error:
                            logger.warning(f"Failed to release recovery session {fresh_id}: {cleanup_error}")

                return output if output else "(no output)"
            except Exception as e:
                logger.error(f"Failed to execute command in sandbox: {e}")
                return f"Error: {e}"

    def _execute_with_env(self, command: str, env: dict[str, str]) -> str:
        """Execute a command with per-call environment variables injected.

        The persistent-shell ``shell.exec_command`` API has no env parameter, so
        injected commands use the ``bash.exec`` API which accepts per-command env.
        Each call lets the sandbox auto-create a fresh session (no ``session_id``),
        so injected request-scoped secrets are scoped to this command and never
        persist across calls. Secret values travel in the structured ``env`` field,
        never in the command string.

        Trade-off of the fresh-session choice: consecutive env-bearing bash calls
        within the same skill do not share session state (cwd, sourced venv,
        exported variables). This mirrors the LocalSandbox model (each call is a
        fresh subprocess) and is intentional — a shared session_id would let
        request-scoped secrets ride the session env into later commands, which the
        SDK does not contractually forbid. Skills that need setup must fold it into
        a single command (e.g. ``cd /mnt/user-data/workspace && source .venv/bin/activate && python run.py``).

        The ``_ERROR_OBSERVATION_SIGNATURE`` recovery contract is shared with the
        legacy persistent-shell path: if the (unlikely, since each call is a fresh
        session) corruption marker shows up, the call is retried on another fresh
        session rather than returned verbatim.

        Images older than all-in-one-sandbox 1.9.x have no ``/v1/bash/*`` routes;
        there is no fallback on the legacy shell path that would keep the secret
        values out of the command string, so the only safe behaviour is to fail
        fast with an actionable error (#3921).
        """
        if self._bash_exec_unsupported:
            return _BASH_EXEC_UNSUPPORTED_ERROR
        output = self._run_bash_exec(command, env)
        if output and _ERROR_OBSERVATION_SIGNATURE in output:
            logger.warning("ErrorObservation detected in bash.exec output, retrying on a fresh session")
            retried = self._run_bash_exec(command, env)
            if retried and _ERROR_OBSERVATION_SIGNATURE not in retried:
                return retried
        return output

    def _run_bash_exec(self, command: str, env: dict[str, str]) -> str:
        """Single bash.exec invocation with injected env (one fresh session)."""
        with self._lock:
            try:
                result = self._client.bash.exec(
                    command=command,
                    env=env,
                    hard_timeout=self._DEFAULT_HARD_TIMEOUT,
                )
                data = result.data if result else None
                stdout = (data.stdout or "") if data else ""
                stderr = (data.stderr or "") if data else ""
                output = stdout
                if stderr:
                    output += f"\nStd Error:\n{stderr}" if output else stderr
                return output if output else "(no output)"
            except ApiError as e:
                if e.status_code == 404:
                    self._bash_exec_unsupported = True
                    logger.error("Sandbox %s does not support bash.exec (/v1/bash/exec returned 404); env-bearing commands are unavailable until the sandbox image is upgraded to all-in-one-sandbox >= 1.9.3", self.id)
                    return _BASH_EXEC_UNSUPPORTED_ERROR
                logger.error(f"Failed to execute command with injected env in sandbox: {e}")
                return f"Error: {e}"
            except Exception as e:
                logger.error(f"Failed to execute command with injected env in sandbox: {e}")
                return f"Error: {e}"

    def read_file(self, path: str) -> str:
        """Read the content of a file in the sandbox.

        Args:
            path: The absolute path of the file to read.

        Returns:
            The content of the file.
        """
        try:
            result = self._client.file.read_file(file=path)
            return result.data.content if result.data else ""
        except Exception as e:
            logger.error(f"Failed to read file in sandbox: {e}")
            return f"Error: {e}"

    def download_file(self, path: str) -> bytes:
        """Download file bytes from the sandbox.

        Raises:
            PermissionError: If the path contains '..' traversal segments or is
                outside ``VIRTUAL_PATH_PREFIX``.
            OSError: If the file cannot be retrieved from the sandbox.
        """
        # Reject path traversal before sending to the container API.
        # LocalSandbox gets this implicitly via _resolve_path;
        # here the path is forwarded verbatim so we must check explicitly.
        normalised = path.replace("\\", "/")
        for segment in normalised.split("/"):
            if segment == "..":
                logger.error(f"Refused download due to path traversal: {path}")
                raise PermissionError(f"Access denied: path traversal detected in '{path}'")

        stripped_path = normalised.lstrip("/")
        allowed_prefix = VIRTUAL_PATH_PREFIX.lstrip("/")
        if stripped_path != allowed_prefix and not stripped_path.startswith(f"{allowed_prefix}/"):
            logger.error("Refused download outside allowed directory: path=%s, allowed_prefix=%s", path, VIRTUAL_PATH_PREFIX)
            raise PermissionError(f"Access denied: path must be under '{VIRTUAL_PATH_PREFIX}': '{path}'")

        with self._lock:
            try:
                chunks: list[bytes] = []
                total = 0
                for chunk in self._client.file.download_file(path=path):
                    total += len(chunk)
                    if total > _MAX_DOWNLOAD_SIZE:
                        raise OSError(
                            errno.EFBIG,
                            f"File exceeds maximum download size of {_MAX_DOWNLOAD_SIZE} bytes",
                            path,
                        )
                    chunks.append(chunk)
                return b"".join(chunks)
            except OSError:
                raise
            except Exception as e:
                logger.error(f"Failed to download file in sandbox: {e}")
                raise OSError(f"Failed to download file '{path}' from sandbox: {e}") from e

    def list_dir(self, path: str, max_depth: int = 2) -> list[str]:
        """List the contents of a directory in the sandbox.

        Args:
            path: The absolute path of the directory to list.
            max_depth: The maximum depth to traverse. Default is 2.

        Returns:
            The contents of the directory.
        """
        with self._lock:
            try:
                result = self._client.shell.exec_command(command=f"find {shlex.quote(path)} -maxdepth {max_depth} -type f -o -type d 2>/dev/null | head -500", no_change_timeout=self._DEFAULT_NO_CHANGE_TIMEOUT)
                output = result.data.output if result.data else ""
                if output:
                    return [line.strip() for line in output.strip().split("\n") if line.strip()]
                return []
            except Exception as e:
                logger.error(f"Failed to list directory in sandbox: {e}")
                return []

    def write_file(self, path: str, content: str, append: bool = False) -> None:
        """Write content to a file in the sandbox.

        Args:
            path: The absolute path of the file to write to.
            content: The text content to write to the file.
            append: Whether to append the content to the file.
        """
        with self._lock:
            try:
                if append:
                    existing = self.read_file(path)
                    if not existing.startswith("Error:"):
                        content = existing + content
                self._client.file.write_file(file=path, content=content)
            except Exception as e:
                logger.error(f"Failed to write file in sandbox: {e}")
                raise

    def glob(self, path: str, pattern: str, *, include_dirs: bool = False, max_results: int = 200) -> tuple[list[str], bool]:
        if not include_dirs:
            result = self._client.file.find_files(path=path, glob=pattern)
            files = result.data.files if result.data and result.data.files else []
            filtered = [file_path for file_path in files if not should_ignore_path(file_path)]
            truncated = len(filtered) > max_results
            return filtered[:max_results], truncated

        result = self._client.file.list_path(path=path, recursive=True, show_hidden=False)
        entries = result.data.files if result.data and result.data.files else []
        matches: list[str] = []
        root_path = path.rstrip("/") or "/"
        root_prefix = root_path if root_path == "/" else f"{root_path}/"
        for entry in entries:
            if entry.path != root_path and not entry.path.startswith(root_prefix):
                continue
            if should_ignore_path(entry.path):
                continue
            rel_path = entry.path[len(root_path) :].lstrip("/")
            if path_matches(pattern, rel_path):
                matches.append(entry.path)
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
        import re as _re

        regex_source = _re.escape(pattern) if literal else pattern
        # Validate the pattern locally so an invalid regex raises re.error
        # (caught by grep_tool's except re.error handler) rather than a
        # generic remote API error.
        _re.compile(regex_source, 0 if case_sensitive else _re.IGNORECASE)
        regex = regex_source if case_sensitive else f"(?i){regex_source}"

        if glob is not None:
            find_result = self._client.file.find_files(path=path, glob=glob)
            candidate_paths = find_result.data.files if find_result.data and find_result.data.files else []
        else:
            list_result = self._client.file.list_path(path=path, recursive=True, show_hidden=False)
            entries = list_result.data.files if list_result.data and list_result.data.files else []
            candidate_paths = [entry.path for entry in entries if not entry.is_directory]

        matches: list[GrepMatch] = []
        truncated = False

        for file_path in candidate_paths:
            if should_ignore_path(file_path):
                continue

            search_result = self._client.file.search_in_file(file=file_path, regex=regex)
            data = search_result.data
            if data is None:
                continue

            line_numbers = data.line_numbers or []
            matched_lines = data.matches or []
            for line_number, line in zip(line_numbers, matched_lines):
                matches.append(
                    GrepMatch(
                        path=file_path,
                        line_number=line_number if isinstance(line_number, int) else 0,
                        line=truncate_line(line),
                    )
                )
                if len(matches) >= max_results:
                    truncated = True
                    return matches, truncated

        return matches, truncated

    def update_file(self, path: str, content: bytes) -> None:
        """Update a file with binary content in the sandbox.

        Args:
            path: The absolute path of the file to update.
            content: The binary content to write to the file.
        """
        with self._lock:
            try:
                base64_content = base64.b64encode(content).decode("utf-8")
                self._client.file.write_file(file=path, content=base64_content, encoding="base64")
            except Exception as e:
                logger.error(f"Failed to update file in sandbox: {e}")
                raise
