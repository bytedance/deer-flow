import errno
import ntpath
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from deerflow.sandbox.local.list_dir import list_dir
from deerflow.sandbox.sandbox import Sandbox
from deerflow.sandbox.search import GrepMatch, find_glob_matches, find_grep_matches


@dataclass(frozen=True)
class PathMapping:
    """A path mapping from a container path to a local path with optional read-only flag."""

    container_path: str
    local_path: str
    read_only: bool = False


class LocalSandbox(Sandbox):
    @staticmethod
    def _shell_name(shell: str) -> str:
        """Return the executable name for a shell path or command."""
        return shell.replace("\\", "/").rsplit("/", 1)[-1].lower()

    @staticmethod
    def _is_powershell(shell: str) -> bool:
        """Return whether the selected shell is a PowerShell executable."""
        return LocalSandbox._shell_name(shell) in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}

    @staticmethod
    def _is_cmd_shell(shell: str) -> bool:
        """Return whether the selected shell is cmd.exe."""
        return LocalSandbox._shell_name(shell) in {"cmd", "cmd.exe"}

    @staticmethod
    def _find_first_available_shell(candidates: tuple[str, ...]) -> str | None:
        """Return the first executable shell path or command found from candidates."""
        for shell in candidates:
            if os.path.isabs(shell):
                if os.path.isfile(shell) and os.access(shell, os.X_OK):
                    return shell
                continue

            shell_from_path = shutil.which(shell)
            if shell_from_path is not None:
                return shell_from_path

        return None

    def __init__(self, id: str, path_mappings: list[PathMapping] | None = None):
        """
        Initialize local sandbox with optional path mappings.

        Args:
            id: Sandbox identifier
            path_mappings: List of path mappings with optional read-only flag.
                          Skills directory is read-only by default.
        """
        super().__init__(id)
        self.path_mappings = path_mappings or []
        # Track files written through write_file so read_file only
        # reverse-resolves paths in agent-authored content.
        self._agent_written_paths: set[str] = set()

    def _is_read_only_path(self, resolved_path: str) -> bool:
        """Check if a resolved path is under a read-only mount.

        When multiple mappings match (nested mounts), prefer the most specific
        mapping (i.e. the one whose local_path is the longest prefix of the
        resolved path), similar to how ``_resolve_path`` handles container paths.
        """
        resolved = str(Path(resolved_path).resolve())

        best_mapping: PathMapping | None = None
        best_prefix_len = -1

        for mapping in self.path_mappings:
            local_resolved = str(Path(mapping.local_path).resolve())
            if resolved == local_resolved or resolved.startswith(local_resolved + os.sep):
                prefix_len = len(local_resolved)
                if prefix_len > best_prefix_len:
                    best_prefix_len = prefix_len
                    best_mapping = mapping

        if best_mapping is None:
            return False

        return best_mapping.read_only

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
        for mapping in sorted(self.path_mappings, key=lambda m: len(m.container_path), reverse=True):
            container_path = mapping.container_path
            local_path = mapping.local_path
            if path_str == container_path or path_str.startswith(container_path + "/"):
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
        normalized_path = path.replace("\\", "/")
        path_str = str(Path(normalized_path).resolve())

        # Try each mapping (longest local path first for more specific matches)
        for mapping in sorted(self.path_mappings, key=lambda m: len(m.local_path), reverse=True):
            local_path_resolved = str(Path(mapping.local_path).resolve())
            if path_str == local_path_resolved or path_str.startswith(local_path_resolved + "/"):
                # Replace the local path prefix with container path
                relative = path_str[len(local_path_resolved) :].lstrip("/")
                resolved = f"{mapping.container_path}/{relative}" if relative else mapping.container_path
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
        import re

        # Sort mappings by local path length (longest first) for correct prefix matching
        sorted_mappings = sorted(self.path_mappings, key=lambda m: len(m.local_path), reverse=True)

        if not sorted_mappings:
            return output

        # Create pattern that matches absolute paths
        # Match paths like /Users/... or other absolute paths
        result = output
        for mapping in sorted_mappings:
            # Escape the local path for use in regex
            escaped_local = re.escape(str(Path(mapping.local_path).resolve()))
            # Match the local path followed by optional path components with either separator
            pattern = re.compile(escaped_local + r"(?:[/\\][^\s\"';&|<>()]*)?")

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
        import re

        # Sort mappings by length (longest first) for correct prefix matching
        sorted_mappings = sorted(self.path_mappings, key=lambda m: len(m.container_path), reverse=True)

        # Build regex pattern to match all container paths
        # Match container path followed by optional path components
        if not sorted_mappings:
            return command

        # Create pattern that matches any of the container paths.
        # The lookahead (?=/|$|...) ensures we only match at a path-segment boundary,
        # preventing /mnt/skills from matching inside /mnt/skills-extra.
        patterns = [re.escape(m.container_path) + r"(?=/|$|[\s\"';&|<>()])(?:/[^\s\"';&|<>()]*)?" for m in sorted_mappings]
        pattern = re.compile("|".join(f"({p})" for p in patterns))

        def replace_match(match: re.Match) -> str:
            matched_path = match.group(0)
            return self._resolve_path(matched_path)

        return pattern.sub(replace_match, command)

    def _resolve_paths_in_content(self, content: str) -> str:
        """Resolve container paths to local paths in arbitrary file content.

        Unlike ``_resolve_paths_in_command`` which uses shell-aware boundary
        characters, this method treats the content as plain text and resolves
        every occurrence of a container path prefix.  Resolved paths are
        normalized to forward slashes to avoid backslash-escape issues on
        Windows hosts (e.g. ``C:\\Users\\..`` breaking Python string literals).

        Args:
            content: File content that may contain container paths.

        Returns:
            Content with container paths resolved to local paths (forward slashes).
        """
        import re

        sorted_mappings = sorted(self.path_mappings, key=lambda m: len(m.container_path), reverse=True)
        if not sorted_mappings:
            return content

        patterns = [re.escape(m.container_path) + r"(?=/|$|[^\w./-])(?:/[^\s\"';&|<>()]*)?" for m in sorted_mappings]
        pattern = re.compile("|".join(f"({p})" for p in patterns))

        def replace_match(match: re.Match) -> str:
            matched_path = match.group(0)
            resolved = self._resolve_path(matched_path)
            # Normalize to forward slashes so that Windows backslash paths
            # don't create invalid escape sequences in source files.
            return resolved.replace("\\", "/")

        return pattern.sub(replace_match, content)

    @staticmethod
    def _get_shell() -> str:
        """Detect available shell executable with fallback."""
        shell = LocalSandbox._find_first_available_shell(("/bin/zsh", "/bin/bash", "/bin/sh", "sh"))
        if shell is not None:
            return shell

        if os.name == "nt":
            system_root = os.environ.get("SystemRoot", r"C:\Windows")
            shell = LocalSandbox._find_first_available_shell(
                (
                    "pwsh",
                    "pwsh.exe",
                    "powershell",
                    "powershell.exe",
                    ntpath.join(system_root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe"),
                    "cmd.exe",
                )
            )
            if shell is not None:
                return shell

            raise RuntimeError("No suitable shell executable found. Tried /bin/zsh, /bin/bash, /bin/sh, `sh` on PATH, then PowerShell and cmd.exe fallbacks for Windows.")

        raise RuntimeError("No suitable shell executable found. Tried /bin/zsh, /bin/bash, /bin/sh, and `sh` on PATH.")

    def execute_command(self, command: str) -> str:
        # Resolve container paths in command before execution
        resolved_command = self._resolve_paths_in_command(command)
        shell = self._get_shell()

        if os.name == "nt":
            if self._is_powershell(shell):
                args = [shell, "-NoProfile", "-Command", resolved_command]
            elif self._is_cmd_shell(shell):
                args = [shell, "/c", resolved_command]
            else:
                args = [shell, "-c", resolved_command]

            result = subprocess.run(
                args,
                shell=False,
                capture_output=True,
                text=True,
                timeout=600,
            )
        else:
            args = [shell, "-c", resolved_command]
            result = subprocess.run(
                args,
                shell=False,
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
        try:
            with open(resolved_path, encoding="utf-8") as f:
                content = f.read()
            # Only reverse-resolve paths in files that were previously written
            # by write_file (agent-authored content). User-uploaded files,
            # external tool output, and other non-agent content should not be
            # silently rewritten — see discussion on PR #1935.
            if resolved_path in self._agent_written_paths:
                content = self._reverse_resolve_paths_in_output(content)
            return content
        except OSError as e:
            # Re-raise with the original path for clearer error messages, hiding internal resolved paths
            raise type(e)(e.errno, e.strerror, path) from None

    def write_file(self, path: str, content: str, append: bool = False) -> None:
        resolved_path = self._resolve_path(path)
        if self._is_read_only_path(resolved_path):
            raise OSError(errno.EROFS, "Read-only file system", path)
        try:
            dir_path = os.path.dirname(resolved_path)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)
            # Resolve container paths in content to local paths
            # using the content-specific resolver (forward-slash safe)
            resolved_content = self._resolve_paths_in_content(content)
            mode = "a" if append else "w"
            with open(resolved_path, mode, encoding="utf-8") as f:
                f.write(resolved_content)
            # Track this path so read_file knows to reverse-resolve on read.
            # Only agent-written files get reverse-resolved; user uploads and
            # external tool output are left untouched.
            self._agent_written_paths.add(resolved_path)
        except OSError as e:
            # Re-raise with the original path for clearer error messages, hiding internal resolved paths
            raise type(e)(e.errno, e.strerror, path) from None

    def glob(self, path: str, pattern: str, *, include_dirs: bool = False, max_results: int = 200) -> tuple[list[str], bool]:
        resolved_path = Path(self._resolve_path(path))
        matches, truncated = find_glob_matches(resolved_path, pattern, include_dirs=include_dirs, max_results=max_results)
        return [self._reverse_resolve_path(match) for match in matches], truncated

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
        resolved_path = Path(self._resolve_path(path))
        matches, truncated = find_grep_matches(
            resolved_path,
            pattern,
            glob_pattern=glob,
            literal=literal,
            case_sensitive=case_sensitive,
            max_results=max_results,
        )
        return [
            GrepMatch(
                path=self._reverse_resolve_path(match.path),
                line_number=match.line_number,
                line=match.line,
            )
            for match in matches
        ], truncated

    def update_file(self, path: str, content: bytes) -> None:
        resolved_path = self._resolve_path(path)
        if self._is_read_only_path(resolved_path):
            raise OSError(errno.EROFS, "Read-only file system", path)
        try:
            dir_path = os.path.dirname(resolved_path)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)
            with open(resolved_path, "wb") as f:
                f.write(content)
        except OSError as e:
            # Re-raise with the original path for clearer error messages, hiding internal resolved paths
            raise type(e)(e.errno, e.strerror, path) from None
