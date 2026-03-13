import logging

from e2b import Sandbox as E2bClient

from src.sandbox.sandbox import Sandbox

logger = logging.getLogger(__name__)


class E2bSandbox(Sandbox):
    """Sandbox implementation using E2B cloud sandboxes.

    E2B provides secure, isolated cloud sandboxes with full Linux environments.
    Each sandbox has its own filesystem, network, and process isolation.
    """

    def __init__(self, id: str, client: E2bClient):
        """Initialize the E2B sandbox.

        Args:
            id: Unique identifier (the E2B sandbox_id).
            client: An already-created E2B Sandbox client instance.
        """
        super().__init__(id)
        self._client = client

    @property
    def client(self) -> E2bClient:
        return self._client

    def execute_command(self, command: str) -> str:
        """Execute a shell command in the E2B sandbox.

        Args:
            command: The command to execute.

        Returns:
            The standard or error output of the command.
        """
        try:
            result = self._client.commands.run(cmd=command, timeout=600)
            output = result.stdout
            if result.stderr:
                output += f"\nStd Error:\n{result.stderr}" if output else result.stderr
            if result.exit_code != 0:
                output += f"\nExit Code: {result.exit_code}"
            return output if output else "(no output)"
        except Exception as e:
            logger.error(f"Failed to execute command in E2B sandbox: {e}")
            return f"Error: {e}"

    def read_file(self, path: str) -> str:
        """Read the content of a file in the E2B sandbox.

        Args:
            path: The absolute path of the file to read.

        Returns:
            The content of the file.
        """
        try:
            return self._client.files.read(path=path, format="text")
        except Exception as e:
            logger.error(f"Failed to read file in E2B sandbox: {e}")
            raise OSError(f"Failed to read {path}: {e}") from e

    def list_dir(self, path: str, max_depth: int = 2) -> list[str]:
        """List the contents of a directory in the E2B sandbox.

        Args:
            path: The absolute path of the directory to list.
            max_depth: The maximum depth to traverse. Default is 2.

        Returns:
            The contents of the directory as a list of path strings.
        """
        try:
            entries = self._client.files.list(path=path, depth=max_depth)
            return [entry.path for entry in entries]
        except Exception as e:
            logger.error(f"Failed to list directory in E2B sandbox: {e}")
            return []

    def write_file(self, path: str, content: str, append: bool = False) -> None:
        """Write content to a file in the E2B sandbox.

        Args:
            path: The absolute path of the file to write to.
            content: The text content to write to the file.
            append: Whether to append the content to the file.
        """
        try:
            if append:
                # E2B doesn't have native append — read existing content first
                try:
                    existing = self._client.files.read(path=path, format="text")
                    content = existing + content
                except Exception:
                    # File doesn't exist yet, just write
                    pass
            self._client.files.write(path=path, data=content)
        except Exception as e:
            logger.error(f"Failed to write file in E2B sandbox: {e}")
            raise OSError(f"Failed to write {path}: {e}") from e

    def update_file(self, path: str, content: bytes) -> None:
        """Update a file with binary content in the E2B sandbox.

        Args:
            path: The absolute path of the file to update.
            content: The binary content to write to the file.
        """
        try:
            self._client.files.write(path=path, data=content)
        except Exception as e:
            logger.error(f"Failed to update file in E2B sandbox: {e}")
            raise OSError(f"Failed to update {path}: {e}") from e
