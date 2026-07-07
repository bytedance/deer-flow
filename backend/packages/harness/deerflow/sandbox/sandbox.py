import re
from abc import ABC, abstractmethod

from deerflow.sandbox.search import GrepMatch

# POSIX env-var name rule: letter or underscore, then letters/digits/underscores.
# Used to validate ``env`` keys before they reach a sandbox implementation.
# No current implementation splices a key into a shell string — the local
# sandbox passes the dict to ``subprocess.run(env=...)`` (no shell), the AIO
# sandbox forwards it via the ``bash.exec`` structured ``env`` field, and e2b
# forwards it as the SDK's ``envs``. The check is defense-in-depth for the
# contract: a future shell-splicing implementation must not have to re-derive
# its own rule.
_ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_extra_env(extra_env: dict[str, str] | None) -> None:
    """Reject ``env`` keys that are not valid POSIX env-var names.

    The :meth:`Sandbox.execute_command` contract accepts arbitrary ``str``
    keys. Today no implementation splices a key into a shell string — the
    local sandbox passes the dict to ``subprocess.run(env=...)`` (no shell),
    the AIO sandbox forwards it via the ``bash.exec`` structured ``env``
    field (no command-string splice), and e2b forwards it as the SDK's
    ``envs``. Enforcing the POSIX env-name rule in the abstract layer is
    defense-in-depth for the contract: a future implementation that does
    route a key through a shell must not have to re-derive its own
    validation rule, and a caller passing a key derived from config /
    payload / user input fails fast with ``ValueError`` instead of silently
    producing an exploit should a future implementation regress to splicing.

    Raises:
        ValueError: When ``extra_env`` is not None and any key does not
            match ``^[A-Za-z_][A-Za-z0-9_]*$``. ``None`` and empty dicts
            pass through unchanged.
    """
    if not extra_env:
        return
    for key in extra_env:
        if not isinstance(key, str) or not _ENV_NAME_PATTERN.fullmatch(key):
            raise ValueError(f"extra_env key {key!r} is not a valid POSIX environment variable name (must match ^[A-Za-z_][A-Za-z0-9_]*$). This protects shell-using sandbox implementations from command injection via the key.")


class Sandbox(ABC):
    """Abstract base class for sandbox environments"""

    _id: str

    def __init__(self, id: str):
        self._id = id

    @property
    def id(self) -> str:
        return self._id

    @abstractmethod
    def execute_command(
        self,
        command: str,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> str:
        """Execute bash command in sandbox.

        Args:
            command: The command to execute.
            env: Optional per-call environment variables to inject into the
                command's process. Used to pass request-scoped secrets (e.g. a
                short-lived end-user token for skill scripts, issue #3861, or a
                GitHub App installation token for ``git push`` / ``gh``) without
                placing them in the prompt, tool arguments, or the command
                string. When ``None`` the sandbox uses its default environment.
                Keys must be valid POSIX environment-variable names
                (``^[A-Za-z_][A-Za-z0-9_]*$``); implementations validate
                via :func:`_validate_extra_env` before use. Values are
                arbitrary strings — shell-using implementations
                ``shlex.quote`` them on splice.
            timeout: Optional per-call wall-clock timeout in seconds. Local
                sandboxes use this to bound host bash commands so long-lived
                foreground processes cannot hang a turn indefinitely. Remote/AIO
                implementations may ignore it when their backend does not expose
                an equivalent command-timeout control separate from its own API
                timeouts.

        Returns:
            The standard or error output of the command.

        Raises:
            ValueError: when an ``env`` key is not a valid env-var name.
        """
        pass

    @abstractmethod
    def read_file(self, path: str) -> str:
        """Read the content of a file.

        Args:
            path: The absolute path of the file to read.

        Returns:
            The content of the file.
        """
        pass

    @abstractmethod
    def download_file(self, path: str) -> bytes:
        """Download the binary content of a file.

        Args:
            path: The absolute path of the file to download.

        Returns:
            Raw file bytes.

        Raises:
            PermissionError: If path traversal is detected or the path is outside
                the allowed virtual prefix.
            OSError: If the file cannot be read or does not exist.  Both local
                and remote implementations must raise ``OSError`` so callers
                have a single exception type to handle.
        """
        pass

    @abstractmethod
    def list_dir(self, path: str, max_depth=2) -> list[str]:
        """List the contents of a directory.

        Args:
            path: The absolute path of the directory to list.
            max_depth: The maximum depth to traverse. Default is 2.

        Returns:
            The contents of the directory.
        """
        pass

    @abstractmethod
    def write_file(self, path: str, content: str, append: bool = False) -> None:
        """Write content to a file.

        Args:
            path: The absolute path of the file to write to.
            content: The text content to write to the file.
            append: Whether to append the content to the file. If False, the file will be created or overwritten.
        """
        pass

    @abstractmethod
    def glob(self, path: str, pattern: str, *, include_dirs: bool = False, max_results: int = 200) -> tuple[list[str], bool]:
        """Find paths that match a glob pattern under a root directory."""
        pass

    @abstractmethod
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
        """Search for matches inside text files under a directory."""
        pass

    @abstractmethod
    def update_file(self, path: str, content: bytes) -> None:
        """Update a file with binary content.

        Args:
            path: The absolute path of the file to update.
            content: The binary content to write to the file.
        """
        pass
