import asyncio
import os
import shutil
import subprocess

from deerflow.sandbox.local.list_dir import list_dir
from deerflow.sandbox.sandbox import Sandbox


class LocalSandbox(Sandbox):
    def __init__(self, id: str):
        """
        Initialize local sandbox.

        Args:
            id: Sandbox identifier
        """
        super().__init__(id)

    @staticmethod
    def _get_shell() -> str:
        """Detect available shell executable with fallback.

        Returns the first available shell in order of preference:
        /bin/zsh → /bin/bash → /bin/sh → first `sh` found on PATH.
        Raises a RuntimeError if no suitable shell is found.
        """
        for shell in ("/bin/zsh", "/bin/bash", "/bin/sh"):
            if os.path.isfile(shell) and os.access(shell, os.X_OK):
                return shell
        shell_from_path = shutil.which("sh")
        if shell_from_path is not None:
            return shell_from_path
        raise RuntimeError("No suitable shell executable found. Tried /bin/zsh, /bin/bash, /bin/sh, and `sh` on PATH.")

    async def execute_command(self, command: str) -> str:
        try:
            # Use asyncio for non-blocking command execution
            process = await asyncio.create_subprocess_shell(
                command,
                executable=self._get_shell(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                # Wait for command completion with timeout
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=600)
                stdout_text = stdout.decode("utf-8", errors="replace")
                stderr_text = stderr.decode("utf-8", errors="replace")
                return_code = process.returncode
            except asyncio.TimeoutError:
                # Terminate the process on timeout
                try:
                    process.kill()
                    await process.wait()
                except ProcessLookupError:
                    pass
                return f"Error: Command timed out after 600 seconds"

            output = stdout_text
            if stderr_text:
                output += f"\nStd Error:\n{stderr_text}" if output else stderr_text
            if return_code != 0:
                output += f"\nExit Code: {return_code}"

            return output if output else "(no output)"

        except Exception as e:
            return f"Error executing command: {str(e)}"

    def list_dir(self, path: str, max_depth=2) -> list[str]:
        return list_dir(path, max_depth)

    def read_file(self, path: str) -> str:
        with open(path, encoding="utf-8") as f:
            return f.read()

    def write_file(self, path: str, content: str, append: bool = False) -> None:
        dir_path = os.path.dirname(path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
        mode = "a" if append else "w"
        with open(path, mode, encoding="utf-8") as f:
            f.write(content)

    def update_file(self, path: str, content: bytes) -> None:
        dir_path = os.path.dirname(path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
        with open(path, "wb") as f:
            f.write(content)
