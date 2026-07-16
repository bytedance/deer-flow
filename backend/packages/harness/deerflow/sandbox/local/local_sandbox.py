import errno
import logging
import ntpath
import os
import re
import shutil
import signal
import subprocess
import threading
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import NamedTuple

from deerflow.config.paths import VIRTUAL_PATH_PREFIX
from deerflow.sandbox.env_policy import build_sandbox_env
from deerflow.sandbox.local.list_dir import list_dir
from deerflow.sandbox.path_patterns import build_output_mask_pattern
from deerflow.sandbox.sandbox import Sandbox, _validate_extra_env
from deerflow.sandbox.search import GrepMatch, find_glob_matches, find_grep_matches

logger = logging.getLogger(__name__)

# Default wall-clock timeout (seconds) for a single host bash command. A
# blocking foreground command (for example a server started without
# backgrounding) is terminated after this long so the agent's turn cannot hang
# indefinitely. Overridable per call via ``execute_command(timeout=...)`` and,
# for the bash tool, via ``sandbox.bash_command_timeout`` in config.yaml.
DEFAULT_COMMAND_TIMEOUT_SECONDS = 600
_COMMAND_CAPTURE_LIMIT_BYTES = 10 * 1024 * 1024
_PIPE_DRAIN_JOIN_TIMEOUT_SECONDS = 0.2


class _BoundedPipeCapture:
    """Drain a subprocess pipe while keeping only bounded output in memory."""

    def __init__(self, *, limit_bytes: int = _COMMAND_CAPTURE_LIMIT_BYTES) -> None:
        self._limit_bytes = limit_bytes
        self._chunks: list[bytes] = []
        self._kept_bytes = 0
        self._total_bytes = 0
        self._lock = threading.Lock()

    def append(self, chunk: bytes) -> None:
        with self._lock:
            self._total_bytes += len(chunk)
            if self._kept_bytes >= self._limit_bytes:
                return
            remaining = self._limit_bytes - self._kept_bytes
            kept = chunk[:remaining]
            self._chunks.append(kept)
            self._kept_bytes += len(kept)

    def read(self) -> str:
        with self._lock:
            data = b"".join(self._chunks)
            truncated = self._total_bytes > self._kept_bytes
            total_bytes = self._total_bytes
            kept_bytes = self._kept_bytes

        output = data.decode("utf-8", errors="replace")
        if truncated:
            notice = f"\n... [output truncated after {kept_bytes} of {total_bytes} bytes; remaining output discarded] ..."
            output += notice
        return output


@dataclass(frozen=True)
class PathMapping:
    """A path mapping from a container path to a local path with optional read-only flag."""

    container_path: str
    local_path: str
    read_only: bool = False


class ResolvedPath(NamedTuple):
    path: str
    mapping: PathMapping | None


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
    def _is_msys_shell(shell: str) -> bool:
        """Return whether the selected shell is a Git Bash/MSYS shell."""
        normalized = shell.replace("\\", "/").lower()
        shell_name = LocalSandbox._shell_name(shell)
        return shell_name in {"sh.exe", "bash.exe"} and any(part in normalized for part in ("/git/", "/mingw", "/msys"))

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

    @staticmethod
    def _format_timeout_duration(timeout: float) -> str:
        seconds = float(timeout)
        if seconds.is_integer():
            amount = str(int(seconds))
        else:
            amount = f"{seconds:g}"
        unit = "second" if seconds == 1 else "seconds"
        return f"{amount} {unit}"

    @staticmethod
    def _format_timeout_notice(timeout: float) -> str:
        return (
            f"Command timed out after {LocalSandbox._format_timeout_duration(timeout)} and was terminated. "
            "To run a long-lived process such as a web server, start it in the background "
            "and redirect its output, e.g. `your-command > /mnt/user-data/workspace/server.log 2>&1 &`."
        )

    @staticmethod
    def _coerce_process_output(value: str | bytes | None) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return value

    @staticmethod
    def _drain_pipe(fd: int, capture: _BoundedPipeCapture) -> None:
        try:
            while chunk := os.read(fd, 8192):
                capture.append(chunk)
        except OSError:
            logger.debug("Subprocess output pipe closed while draining", exc_info=True)
        finally:
            try:
                os.close(fd)
            except OSError:
                # The fd may already be closed during pipe teardown; cleanup is best-effort.
                pass

    @staticmethod
    def _start_pipe_drain(fd: int, name: str) -> tuple[_BoundedPipeCapture, threading.Thread]:
        capture = _BoundedPipeCapture()
        thread = threading.Thread(target=LocalSandbox._drain_pipe, args=(fd, capture), name=name, daemon=True)
        thread.start()
        return capture, thread

    @staticmethod
    def _process_group_exists(pgid: int | None) -> bool:
        if pgid is None:
            return False
        try:
            os.killpg(pgid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False

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

    # ``path_mappings`` is set once in ``__init__`` and never mutated, so the
    # sorted views and compiled path-rewrite patterns below are stable for the
    # sandbox's lifetime. Caching them avoids re-sorting and re-compiling these
    # regexes on every bash/read_file/write_file call (the agent's hot path).

    @cached_property
    def _command_pattern(self) -> re.Pattern[str] | None:
        """Compiled matcher for container paths in shell commands (shell-aware boundaries)."""
        mappings = sorted(self.path_mappings, key=lambda m: len(m.container_path), reverse=True)
        if not mappings:
            return None
        # The lookahead (?=/|$|...) ensures we only match at a path-segment boundary,
        # preventing /mnt/skills from matching inside /mnt/skills-extra.
        patterns = [re.escape(m.container_path) + r"(?=/|$|[\s\"';&|<>()])(?:/[^\s\"';&|<>()]*)?" for m in mappings]
        return re.compile("|".join(f"({p})" for p in patterns))

    @cached_property
    def _content_pattern(self) -> re.Pattern[str] | None:
        """Compiled matcher for container paths in plain file content (text boundaries)."""
        mappings = sorted(self.path_mappings, key=lambda m: len(m.container_path), reverse=True)
        if not mappings:
            return None
        patterns = [re.escape(m.container_path) + r"(?=/|$|[^\w./-])(?:/[^\s\"';&|<>()]*)?" for m in mappings]
        return re.compile("|".join(f"({p})" for p in patterns))

    @cached_property
    def _reverse_output_patterns(self) -> list[re.Pattern[str]]:
        """Compiled matchers for local paths in command output (longest local path first)."""
        # The rule — segment boundary plus path tail — is owned by
        # ``deerflow.sandbox.path_patterns`` and shared with
        # ``sandbox.tools._compiled_mask_patterns``, the other site that rewrites host
        # paths back to virtual ones. Its rationale (why the boundary class is
        # text-oriented rather than shell-oriented like ``_command_pattern``, why ``$``
        # is load-bearing) lives with the owner rather than in a second copy here, which
        # is what let the two drift before (#4035 added the boundary here and missed
        # that site; #4053 added it there).
        #
        # What is specific to this site: without the boundary the regex yields the bare
        # root, which then *equals* the mount root and so satisfies
        # ``_reverse_resolve_path``'s own ``+ "/"`` guard — the sibling is rewritten to a
        # container path that forward resolution refuses to map back. And bases stay
        # separator-*sensitive*: they come from ``Path.resolve()`` and already carry the
        # platform's separator, so relaxing them would widen what this masks.
        return [build_output_mask_pattern(self._resolved_local_paths[m]) for m in self._mappings_by_local_specificity]

    @cached_property
    def _resolved_local_paths(self) -> dict[PathMapping, str]:
        """Filesystem-resolved local root per mapping. ``Path.resolve()`` hits the
        disk, and the mounted directories don't move, so resolve once and reuse."""
        return {m: str(Path(m.local_path).resolve()) for m in self.path_mappings}

    @cached_property
    def _mappings_by_container_specificity(self) -> list[PathMapping]:
        """Mappings ordered most-specific-container-first (for forward resolution)."""
        return sorted(self.path_mappings, key=lambda m: len(m.container_path.rstrip("/") or "/"), reverse=True)

    @cached_property
    def _mappings_by_local_specificity(self) -> list[PathMapping]:
        """Mappings ordered longest-local-path-first (for reverse resolution)."""
        return sorted(self.path_mappings, key=lambda m: len(m.local_path), reverse=True)

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
            local_resolved = self._resolved_local_paths[mapping]
            if resolved == local_resolved or resolved.startswith(local_resolved + os.sep):
                prefix_len = len(local_resolved)
                if prefix_len > best_prefix_len:
                    best_prefix_len = prefix_len
                    best_mapping = mapping

        if best_mapping is None:
            return False

        return best_mapping.read_only

    def _find_path_mapping(self, path: str) -> tuple[PathMapping, str] | None:
        path_str = str(path)

        for mapping in self._mappings_by_container_specificity:
            container_path = mapping.container_path.rstrip("/") or "/"
            if container_path == "/":
                if path_str.startswith("/"):
                    return mapping, path_str.lstrip("/")
                continue

            if path_str == container_path or path_str.startswith(container_path + "/"):
                relative = path_str[len(container_path) :].lstrip("/")
                return mapping, relative

        return None

    def _resolve_path_with_mapping(self, path: str) -> ResolvedPath:
        """
        Resolve container path to actual local path using mappings.

        Args:
            path: Path that might be a container path

        Returns:
            Resolved local path and the matched mapping, if any
        """
        path_str = str(path)

        mapping_match = self._find_path_mapping(path_str)
        if mapping_match is None:
            return ResolvedPath(path_str, None)

        mapping, relative = mapping_match
        local_root = Path(self._resolved_local_paths[mapping])
        resolved_path = (local_root / relative).resolve() if relative else local_root

        try:
            resolved_path.relative_to(local_root)
        except ValueError as exc:
            raise PermissionError(errno.EACCES, "Access denied: path escapes mounted directory", path_str) from exc

        return ResolvedPath(str(resolved_path), mapping)

    def _resolve_path(self, path: str) -> str:
        return self._resolve_path_with_mapping(path).path

    def _is_resolved_path_read_only(self, resolved: ResolvedPath) -> bool:
        return bool(resolved.mapping and resolved.mapping.read_only) or self._is_read_only_path(resolved.path)

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
        for mapping in self._mappings_by_local_specificity:
            local_path_resolved = self._resolved_local_paths[mapping]
            # ``Path.resolve()`` always renders with the native separator
            # (backslash on Windows), regardless of the forward-slash
            # normalization above, so the containment check must compare with
            # ``os.sep`` here too -- mirroring ``_is_read_only_path`` -- instead
            # of a hardcoded "/". A hardcoded "/" can never match a
            # backslash-joined nested path on Windows, so every nested path
            # silently fell through to the "no mapping found" branch below and
            # leaked the raw host path (real username, full directory tree).
            if path_str == local_path_resolved or path_str.startswith(local_path_resolved + os.sep):
                # Replace the local path prefix with container path. Container
                # paths are always POSIX-style, so the extracted relative
                # portion (native-separated on Windows) is normalized to
                # forward slashes before being spliced in.
                relative = path_str[len(local_path_resolved) :].lstrip(os.sep).replace(os.sep, "/")
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
        # Patterns are compiled once per sandbox (longest local path first for
        # correct prefix matching) and reused across calls.
        result = output
        for pattern in self._reverse_output_patterns:

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
        pattern = self._command_pattern
        if pattern is None:
            return command

        def replace_match(match: re.Match) -> str:
            matched_path = match.group(0)
            # Normalize to forward slashes so bash doesn't interpret Windows
            # backslash sequences (\\U, \\a, \\d, \\s, \\n, \\t) as escapes.
            return self._resolve_path(matched_path).replace("\\", "/")

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
        pattern = self._content_pattern
        if pattern is None:
            return content

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

    def execute_command(
        self,
        command: str,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> str:
        # Validate ``env`` keys against the POSIX env-var rule. Defense in
        # depth: ``subprocess.run(env=...)`` does not go through a shell so a
        # metachar in a key here would not actually inject — but the public
        # ``Sandbox.execute_command`` contract is shared with the AIO sandbox,
        # which DOES splice keys into ``export <k>=<v>``. Enforcing the same
        # rule on both implementations keeps the contract consistent and forces
        # any new caller to use safe key names.
        _validate_extra_env(env)
        # Resolve container paths in command before execution
        resolved_command = self._resolve_paths_in_command(command)
        shell = self._get_shell()
        if timeout is None:
            timeout = DEFAULT_COMMAND_TIMEOUT_SECONDS

        # Inherit os.environ minus platform secrets, then layer any injected
        # request-scoped secrets on top (#3861). An explicit env is always passed
        # so platform credentials never leak into skill subprocesses.
        sandbox_env = build_sandbox_env(env)
        timed_out = False
        if os.name == "nt":
            if self._is_powershell(shell):
                args = [shell, "-NoProfile", "-Command", resolved_command]
            elif self._is_cmd_shell(shell):
                args = [shell, "/c", resolved_command]
            else:
                args = [shell, "-c", resolved_command]
                if self._is_msys_shell(shell):
                    sandbox_env = {
                        **sandbox_env,
                        "MSYS_NO_PATHCONV": "1",
                        "MSYS2_ARG_CONV_EXCL": "*",
                    }

            try:
                result = subprocess.run(
                    args,
                    shell=False,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    env=sandbox_env,
                )
                stdout, stderr, returncode = result.stdout, result.stderr, result.returncode
            except subprocess.TimeoutExpired as exc:
                timed_out = True
                stdout = self._coerce_process_output(exc.stdout if exc.stdout is not None else exc.output)
                stderr = self._coerce_process_output(exc.stderr)
                returncode = 0
        else:
            args = [shell, "-c", resolved_command]
            stdout, stderr, returncode, timed_out = self._run_posix_command(args, timeout, sandbox_env)

        output = stdout
        if stderr:
            output += f"\nStd Error:\n{stderr}" if output else stderr
        if timed_out:
            notice = self._format_timeout_notice(timeout)
            output += f"\n{notice}" if output else notice
        elif returncode != 0:
            output += f"\nExit Code: {returncode}"

        final_output = output if output else "(no output)"
        # Reverse resolve local paths back to container paths in output
        return self._reverse_resolve_paths_in_output(final_output)

    @staticmethod
    def _run_posix_command(
        args: list[str],
        timeout: float,
        env: dict[str, str] | None = None,
    ) -> tuple[str, str, int, bool]:
        """Run a command on POSIX with bounded pipe capture.

        ``subprocess.communicate()`` cannot be used here: a backgrounded
        long-lived process (``server &``) inherits stdout/stderr and keeps the
        pipes open, so ``communicate()`` would block until timeout even though
        the foreground shell already returned. Instead, daemon drain threads
        keep the pipes flowing while retaining only bounded output in memory.
        This lets the call return as soon as the foreground shell exits without
        handing backgrounded processes anonymous temp files that can grow
        invisibly. ``stdin`` is taken from ``/dev/null`` so commands that read
        stdin get immediate EOF, and ``start_new_session`` puts the command in
        its own process group so a genuinely blocking foreground command can be
        killed in full (children included) when it times out.

        ``env`` is forwarded to :class:`subprocess.Popen`; ``None`` means
        inherit the current process environment (the common case).

        Returns ``(stdout, stderr, returncode, timed_out)``.
        """
        timed_out = False
        stdout_read_fd, stdout_write_fd = os.pipe()
        stderr_read_fd, stderr_write_fd = os.pipe()
        try:
            process = subprocess.Popen(
                args,
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=stdout_write_fd,
                stderr=stderr_write_fd,
                start_new_session=True,
                env=env,
            )
        except Exception:
            for fd in (stdout_read_fd, stdout_write_fd, stderr_read_fd, stderr_write_fd):
                try:
                    os.close(fd)
                except OSError:
                    # Preserve the original Popen failure; fd cleanup is best-effort.
                    pass
            raise
        finally:
            for fd in (stdout_write_fd, stderr_write_fd):
                try:
                    os.close(fd)
                except OSError:
                    # The write fd may already be closed by the exception cleanup above.
                    pass

        stdout_capture, stdout_thread = LocalSandbox._start_pipe_drain(stdout_read_fd, "deerflow-bash-stdout-drain")
        stderr_capture, stderr_thread = LocalSandbox._start_pipe_drain(stderr_read_fd, "deerflow-bash-stderr-drain")
        try:
            process_group_id = os.getpgid(process.pid)
        except OSError:
            process_group_id = None

        try:
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                LocalSandbox._terminate_process_group(process)
            returncode = process.returncode if process.returncode is not None else 0
        finally:
            join_timeout = 10 if timed_out or not LocalSandbox._process_group_exists(process_group_id) else _PIPE_DRAIN_JOIN_TIMEOUT_SECONDS
            for thread in (stdout_thread, stderr_thread):
                thread.join(timeout=join_timeout)
                if thread.is_alive():
                    logger.debug("Subprocess output drain thread still active after command returned")

        stdout = stdout_capture.read()
        stderr = stderr_capture.read()
        return stdout, stderr, returncode, timed_out

    @staticmethod
    def _terminate_process_group(process: subprocess.Popen) -> None:
        """Kill the command's whole process group, then reap it.

        Falls back to killing just the direct child if the group is already
        gone (e.g. the command exited between the timeout and this call).
        """
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            # The process group is already gone (the command exited in the race
            # between the timeout and this call); fall back to killing just the
            # direct child.
            try:
                process.kill()
            except OSError:
                # Direct child already reaped too — nothing left to kill.
                logger.debug("Process %s already exited before fallback kill", process.pid)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            logger.warning("Process group for pid %s did not exit after SIGKILL", process.pid)

    def list_dir(self, path: str, max_depth=2) -> list[str]:
        resolved_path = self._resolve_path(path)
        entries = list_dir(resolved_path, max_depth)
        # Reverse resolve local paths back to container paths and preserve
        # list_dir's trailing "/" marker for directories.
        result: list[str] = []
        for entry in entries:
            is_dir = entry.endswith(("/", "\\"))
            reversed_entry = self._reverse_resolve_path(entry.rstrip("/\\")) if is_dir else self._reverse_resolve_path(entry)
            result.append(f"{reversed_entry}/" if is_dir and not reversed_entry.endswith("/") else reversed_entry)

        # Virtual sub-directory overlay: when a container path like /mnt/skills
        # has child mappings (public, custom, legacy) whose local_path targets
        # are outside the resolved host directory (symlinks or bind-mount style),
        # the ``list_dir`` utility skips them for security. We patch those
        # missing virtual children back in so the agent can discover them via
        # ``ls /mnt/skills``.
        container_path = path.rstrip("/")
        existing_dirs = {e.rstrip("/") for e in result if e.endswith("/")}
        for mapping in self.path_mappings:
            # A mapping is a virtual child if:
            # 1. Its container_path is a direct child of the requested path
            # 2. It is NOT already present in the result (was skipped by list_dir)
            if mapping.container_path.startswith(container_path + "/"):
                child_rel = mapping.container_path[len(container_path) + 1 :]
                # Only direct children (no further slashes), e.g. "public", "custom".
                # Compare the mapping's full container path -- not the bare child
                # name -- against existing_dirs, which holds full paths (e.g.
                # "/mnt/user-data/workspace"). Comparing the bare name here would
                # never match, so an already-listed mount (the common case: real
                # nested workspace/uploads/outputs subdirectories under
                # /mnt/user-data) would be appended a second time.
                if "/" not in child_rel and mapping.container_path.rstrip("/") not in existing_dirs:
                    # Verify the host path exists so we don't add phantom entries
                    try:
                        if Path(mapping.local_path).resolve().is_dir():
                            result.append(f"{mapping.container_path}/")
                    except OSError:
                        pass

        return sorted(result)

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

    def download_file(self, path: str) -> bytes:
        normalised = path.replace("\\", "/")
        stripped_path = normalised.lstrip("/")
        allowed_prefix = VIRTUAL_PATH_PREFIX.lstrip("/")
        if stripped_path != allowed_prefix and not stripped_path.startswith(f"{allowed_prefix}/"):
            logger.error("Refused download outside allowed directory: path=%s, allowed_prefix=%s", path, VIRTUAL_PATH_PREFIX)
            raise PermissionError(errno.EACCES, f"Access denied: path must be under '{VIRTUAL_PATH_PREFIX}'", path)

        resolved_path = self._resolve_path(path)
        max_download_size = 100 * 1024 * 1024
        try:
            file_size = os.path.getsize(resolved_path)
            if file_size > max_download_size:
                raise OSError(errno.EFBIG, f"File exceeds maximum download size of {max_download_size} bytes", path)
            # TOCTOU note: the file could grow between getsize() and read(); accepted
            # tradeoff since this is a controlled sandbox environment.
            with open(resolved_path, "rb") as f:
                return f.read()
        except OSError as e:
            # Re-raise with the original path for clearer error messages, hiding internal resolved paths
            raise type(e)(e.errno, e.strerror, path) from None

    def write_file(self, path: str, content: str, append: bool = False) -> None:
        resolved = self._resolve_path_with_mapping(path)
        resolved_path = resolved.path
        if self._is_resolved_path_read_only(resolved):
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
        resolved = self._resolve_path_with_mapping(path)
        resolved_path = resolved.path
        if self._is_resolved_path_read_only(resolved):
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
