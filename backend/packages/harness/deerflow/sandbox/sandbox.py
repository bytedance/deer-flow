from abc import ABC, abstractmethod

from deerflow.sandbox.search import GrepMatch


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
                short-lived end-user token) to skill scripts without placing them
                in the prompt, tool arguments, or the command string (issue #3861).
                When ``None`` the sandbox uses its default environment.
            timeout: Optional per-call wall-clock timeout in seconds. Local
                sandboxes use this to bound host bash commands so long-lived
                foreground processes cannot hang a turn indefinitely. Remote/AIO
                implementations may ignore it when their backend does not expose
                an equivalent command-timeout control separate from its own API
                timeouts.

        Returns:
            The standard or error output of the command.
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
