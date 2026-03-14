import os
import re
import shutil
import subprocess
from pathlib import Path

from src.sandbox.local.list_dir import list_dir
from src.sandbox.sandbox import Sandbox

# Module-level cache for detected shell executable (avoids filesystem checks per call).
_cached_shell: str | None = None


class LocalSandbox(Sandbox):
    def __init__(self, id: str, path_mappings: dict[str, str] | None = None):
        """
        Initialize local sandbox with optional path mappings.

        Args:
            id: Sandbox identifier
            path_mappings: Dictionary mapping container paths to local paths
                          Example: {"/mnt/skills": "/absolute/path/to/skills"}
        """
        super().__init__(id)
        self.path_mappings = path_mappings or {}
        self._build_path_caches()

    def _build_path_caches(self) -> None:
        """Pre-compute sorted mappings and compiled regex patterns.

        Called once from __init__. Since path_mappings are set once and never
        mutated, these caches remain valid for the lifetime of the sandbox.
        """
        # Sorted by container path length (longest first) for correct prefix matching
        self._sorted_by_container_key: list[tuple[str, str]] = sorted(self.path_mappings.items(), key=lambda x: len(x[0]), reverse=True)

        # Sorted by local path length (longest first) for correct prefix matching
        self._sorted_by_local_key: list[tuple[str, str]] = sorted(self.path_mappings.items(), key=lambda x: len(x[1]), reverse=True)

        # Pre-compiled patterns for _reverse_resolve_paths_in_output:
        # Each entry is (container_path, compiled_regex) for the corresponding local path
        self._reverse_patterns: list[tuple[str, re.Pattern]] = []
        for container_path, local_path in self._sorted_by_local_key:
            local_path_resolved = str(Path(local_path).resolve())
            escaped_local = re.escape(local_path_resolved)
            pattern = re.compile(escaped_local + r"(?:/[^\s\"';&|<>()]*)?")
            self._reverse_patterns.append((container_path, pattern))

        # Pre-compiled unified pattern for _resolve_paths_in_command
        if self._sorted_by_container_key:
            patterns = [re.escape(container_path) + r"(?:/[^\s\"';&|<>()]*)??" for container_path, _ in self._sorted_by_container_key]
            self._forward_pattern: re.Pattern | None = re.compile("|".join(f"({p})" for p in patterns))
        else:
            self._forward_pattern = None

    def _resolve_path(self, path: str) -> str:
        """
        Resolve container path to actual local path using mappings.

        Args:
            path: Path that might be a container path

        Returns:
            Resolved local path
        """
        path_str = str(path)

        # Try each mapping (longest prefix first for more specific matches)
        for container_path, local_path in self._sorted_by_container_key:
            if path_str.startswith(container_path):
                # Replace the container path prefix with local path
                relative = path_str[len(container_path) :].lstrip("/")
                resolved = str(Path(local_path) / relative) if relative else local_path
                return resolved

        # No mapping found, return original path
        return path_str

    def _reverse_resolve_path(self, path: str) -> str:
        """
        Reverse resolve local path back to container path using mappings.

        Args:
            path: Local path that might need to be mapped to container path

        Returns:
            Container path if mapping exists, otherwise original path
        """
        path_str = str(Path(path).resolve())

        # Try each mapping (longest local path first for more specific matches)
        for container_path, local_path in self._sorted_by_local_key:
            local_path_resolved = str(Path(local_path).resolve())
            if path_str.startswith(local_path_resolved):
                # Replace the local path prefix with container path
                relative = path_str[len(local_path_resolved) :].lstrip("/")
                resolved = f"{container_path}/{relative}" if relative else container_path
                return resolved

        # No mapping found, return original path
        return path_str

    def _reverse_resolve_paths_in_output(self, output: str) -> str:
        """
        Reverse resolve local paths back to container paths in output string.

        Args:
            output: Output string that may contain local paths

        Returns:
            Output with local paths resolved to container paths
        """
        if not self._reverse_patterns:
            return output

        result = output
        for _container_path, pattern in self._reverse_patterns:

            def replace_match(match: re.Match) -> str:
                matched_path = match.group(0)
                return self._reverse_resolve_path(matched_path)

            result = pattern.sub(replace_match, result)

        return result

    def _resolve_paths_in_command(self, command: str) -> str:
        """
        Resolve container paths to local paths in a command string.

        Args:
            command: Command string that may contain container paths

        Returns:
            Command with container paths resolved to local paths
        """
        if self._forward_pattern is None:
            return command

        def replace_match(match: re.Match) -> str:
            matched_path = match.group(0)
            return self._resolve_path(matched_path)

        return self._forward_pattern.sub(replace_match, command)

    @staticmethod
    def _get_shell() -> str:
        """Detect available shell executable with fallback.

        Returns the first available shell in order of preference:
        /bin/zsh → /bin/bash → /bin/sh → first `sh` found on PATH.
        Raises a RuntimeError if no suitable shell is found.

        Results are cached at module level so filesystem checks only run once.
        """
        global _cached_shell
        if _cached_shell is not None:
            return _cached_shell
        for shell in ("/bin/zsh", "/bin/bash", "/bin/sh"):
            if os.path.isfile(shell) and os.access(shell, os.X_OK):
                _cached_shell = shell
                return shell
        shell_from_path = shutil.which("sh")
        if shell_from_path is not None:
            _cached_shell = shell_from_path
            return shell_from_path
        raise RuntimeError(
            "No suitable shell executable found. Tried /bin/zsh, /bin/bash, "
            "/bin/sh, and `sh` on PATH."
        )

    def execute_command(self, command: str) -> str:
        # Resolve container paths in command before execution
        resolved_command = self._resolve_paths_in_command(command)

        result = subprocess.run(
            resolved_command,
            executable=self._get_shell(),
            shell=True,
            capture_output=True,
            text=True,
            timeout=600,
        )
        output = result.stdout
        if result.stderr:
            output += f"\nStd Error:\n{result.stderr}" if output else result.stderr
        if result.returncode != 0:
            output += f"\nExit Code: {result.returncode}"

        final_output = output if output else "(no output)"
        # Reverse resolve local paths back to container paths in output
        return self._reverse_resolve_paths_in_output(final_output)

    def list_dir(self, path: str, max_depth=2) -> list[str]:
        resolved_path = self._resolve_path(path)
        entries = list_dir(resolved_path, max_depth)
        # Reverse resolve local paths back to container paths in output
        return [self._reverse_resolve_paths_in_output(entry) for entry in entries]

    def read_file(self, path: str) -> str:
        resolved_path = self._resolve_path(path)
        with open(resolved_path) as f:
            return f.read()

    def write_file(self, path: str, content: str, append: bool = False) -> None:
        resolved_path = self._resolve_path(path)
        dir_path = os.path.dirname(resolved_path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
        mode = "a" if append else "w"
        with open(resolved_path, mode) as f:
            f.write(content)

    def update_file(self, path: str, content: bytes) -> None:
        resolved_path = self._resolve_path(path)
        dir_path = os.path.dirname(resolved_path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
        with open(resolved_path, "wb") as f:
            f.write(content)
