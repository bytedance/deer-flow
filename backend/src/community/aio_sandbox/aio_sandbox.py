import base64
import logging

from agent_sandbox import Sandbox as AioSandboxClient

from src.sandbox.sandbox import Sandbox

logger = logging.getLogger(__name__)


class AioSandbox(Sandbox):
    """Sandbox implementation using the agent-infra/sandbox Docker container.

    This sandbox connects to a running AIO sandbox container via HTTP API.
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

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def home_dir(self) -> str:
        """Get the home directory inside the sandbox."""
        if self._home_dir is None:
            context = self._client.sandbox.get_context()
            self._home_dir = context.home_dir
        return self._home_dir

    def execute_command(self, command: str) -> str:
        """Execute a shell command in the sandbox.

        Args:
            command: The command to execute.

        Returns:
            The output of the command.
        """
        try:
            result = self._client.shell.exec_command(command=command)
            output = result.data.output if result.data else ""
            return output if output else "(no output)"
        except Exception as e:
            logger.error(f"Failed to execute command in sandbox: {e}")
            return f"Error: {e}"

    def _read_file_raw(self, path: str) -> str:
        """Read file content, raising on failure.

        This is the internal implementation that propagates exceptions.
        Use read_file() for the public API that returns error strings.

        Args:
            path: The absolute path of the file to read.

        Returns:
            The content of the file.

        Raises:
            Exception: If the file cannot be read.
        """
        result = self._client.file.read_file(file=path)
        return result.data.content if result.data else ""

    def read_file(self, path: str) -> str:
        """Read the content of a file in the sandbox.

        Args:
            path: The absolute path of the file to read.

        Returns:
            The content of the file, or an error string on failure.
        """
        try:
            return self._read_file_raw(path)
        except Exception as e:
            logger.error(f"Failed to read file in sandbox: {e}")
            return f"Error: {e}"

    def list_dir(self, path: str, max_depth: int = 2) -> list[str]:
        """List the contents of a directory in the sandbox.

        Args:
            path: The absolute path of the directory to list.
            max_depth: The maximum depth to traverse. Default is 2.

        Returns:
            The contents of the directory.
        """
        try:
            # Use shell command to list directory with depth limit
            # The -L flag limits the depth for the tree command
            result = self._client.shell.exec_command(command=f"find {path} -maxdepth {max_depth} -type f -o -type d 2>/dev/null | head -500")
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
        try:
            if append:
                # Read existing content and append. Use _read_file_raw() which
                # raises on failure instead of returning error strings — avoids
                # the fragile startswith("Error:") check that would silently
                # discard file content legitimately starting with "Error:".
                try:
                    existing = self._read_file_raw(path)
                    content = existing + content
                except Exception:
                    pass  # File doesn't exist yet, write fresh content
            self._client.file.write_file(file=path, content=content)
        except Exception as e:
            logger.error(f"Failed to write file in sandbox: {e}")
            raise

    def update_file(self, path: str, content: bytes) -> None:
        """Update a file with binary content in the sandbox.

        Args:
            path: The absolute path of the file to update.
            content: The binary content to write to the file.
        """
        try:
            base64_content = base64.b64encode(content).decode("utf-8")
            self._client.file.write_file(file=path, content=base64_content, encoding="base64")
        except Exception as e:
            logger.error(f"Failed to update file in sandbox: {e}")
            raise
