import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from deerflow.sandbox.tools import (
    VIRTUAL_PATH_PREFIX,
    _apply_cwd_prefix,
    _is_acp_workspace_path,
    _is_skills_path,
    _reject_path_traversal,
    _resolve_acp_workspace_path,
    _resolve_and_validate_user_data_path,
    _resolve_skills_path,
    bash_tool,
    mask_local_paths_in_output,
    replace_virtual_path,
    replace_virtual_paths_in_command,
    str_replace_tool,
    validate_local_bash_command_paths,
    validate_local_tool_path,
    write_file_tool,
)

_THREAD_DATA = {
    "workspace_path": "/tmp/deer-flow/threads/t1/user-data/workspace",
    "uploads_path": "/tmp/deer-flow/threads/t1/user-data/uploads",
    "outputs_path": "/tmp/deer-flow/threads/t1/user-data/outputs",
}


# ---------- replace_virtual_path ----------


def test_replace_virtual_path_maps_virtual_root_and_subpaths() -> None:
    assert Path(replace_virtual_path("/mnt/user-data/workspace/a.txt", _THREAD_DATA)).as_posix() == "/tmp/deer-flow/threads/t1/user-data/workspace/a.txt"
    assert Path(replace_virtual_path("/mnt/user-data", _THREAD_DATA)).as_posix() == "/tmp/deer-flow/threads/t1/user-data"


# ---------- mask_local_paths_in_output ----------


def test_mask_local_paths_in_output_hides_host_paths() -> None:
    output = "Created: /tmp/deer-flow/threads/t1/user-data/workspace/result.txt"
    masked = mask_local_paths_in_output(output, _THREAD_DATA)

    assert "/tmp/deer-flow/threads/t1/user-data" not in masked
    assert "/mnt/user-data/workspace/result.txt" in masked


def test_mask_local_paths_in_output_hides_skills_host_paths() -> None:
    """Skills host paths in bash output should be masked to virtual paths."""
    with (
        patch("deerflow.sandbox.tools._get_skills_container_path", return_value="/mnt/skills"),
        patch("deerflow.sandbox.tools._get_skills_host_path", return_value="/home/user/deer-flow/skills"),
    ):
        output = "Reading: /home/user/deer-flow/skills/public/bootstrap/SKILL.md"
        masked = mask_local_paths_in_output(output, _THREAD_DATA)

        assert "/home/user/deer-flow/skills" not in masked
        assert "/mnt/skills/public/bootstrap/SKILL.md" in masked


# ---------- _reject_path_traversal ----------


def test_reject_path_traversal_blocks_dotdot() -> None:
    with pytest.raises(PermissionError, match="path traversal"):
        _reject_path_traversal("/mnt/user-data/workspace/../../etc/passwd")


def test_reject_path_traversal_blocks_dotdot_at_start() -> None:
    with pytest.raises(PermissionError, match="path traversal"):
        _reject_path_traversal("../etc/passwd")


def test_reject_path_traversal_blocks_backslash_dotdot() -> None:
    with pytest.raises(PermissionError, match="path traversal"):
        _reject_path_traversal("/mnt/user-data/workspace\\..\\..\\etc\\passwd")


def test_reject_path_traversal_allows_normal_paths() -> None:
    # Should not raise
    _reject_path_traversal("/mnt/user-data/workspace/file.txt")
    _reject_path_traversal("/mnt/skills/public/bootstrap/SKILL.md")
    _reject_path_traversal("/mnt/user-data/workspace/sub/dir/file.py")


# ---------- validate_local_tool_path ----------


def test_validate_local_tool_path_rejects_non_virtual_path() -> None:
    with pytest.raises(PermissionError, match="Only paths under"):
        validate_local_tool_path("/Users/someone/config.yaml", _THREAD_DATA)


def test_validate_local_tool_path_rejects_bare_virtual_root() -> None:
    """The bare /mnt/user-data root without trailing slash is not a valid sub-path."""
    with pytest.raises(PermissionError, match="Only paths under"):
        validate_local_tool_path(VIRTUAL_PATH_PREFIX, _THREAD_DATA)


def test_validate_local_tool_path_allows_user_data_paths() -> None:
    # Should not raise — user-data paths are always allowed
    validate_local_tool_path(f"{VIRTUAL_PATH_PREFIX}/workspace/file.txt", _THREAD_DATA)
    validate_local_tool_path(f"{VIRTUAL_PATH_PREFIX}/uploads/doc.pdf", _THREAD_DATA)
    validate_local_tool_path(f"{VIRTUAL_PATH_PREFIX}/outputs/result.csv", _THREAD_DATA)


def test_validate_local_tool_path_allows_user_data_write() -> None:
    # read_only=False (default) should still work for user-data paths
    validate_local_tool_path(f"{VIRTUAL_PATH_PREFIX}/workspace/file.txt", _THREAD_DATA, read_only=False)


def test_validate_local_tool_path_rejects_traversal_in_user_data() -> None:
    """Path traversal via .. in user-data paths must be rejected."""
    with pytest.raises(PermissionError, match="path traversal"):
        validate_local_tool_path(f"{VIRTUAL_PATH_PREFIX}/workspace/../../etc/passwd", _THREAD_DATA)


def test_validate_local_tool_path_rejects_traversal_in_skills() -> None:
    """Path traversal via .. in skills paths must be rejected."""
    with patch("deerflow.sandbox.tools._get_skills_container_path", return_value="/mnt/skills"):
        with pytest.raises(PermissionError, match="path traversal"):
            validate_local_tool_path("/mnt/skills/../../etc/passwd", _THREAD_DATA, read_only=True)


def test_validate_local_tool_path_rejects_none_thread_data() -> None:
    """Missing thread_data should raise SandboxRuntimeError."""
    from deerflow.sandbox.exceptions import SandboxRuntimeError

    with pytest.raises(SandboxRuntimeError):
        validate_local_tool_path(f"{VIRTUAL_PATH_PREFIX}/workspace/file.txt", None)


# ---------- _resolve_skills_path ----------


def test_resolve_skills_path_resolves_correctly() -> None:
    """Skills virtual path should resolve to host path."""
    with (
        patch("deerflow.sandbox.tools._get_skills_container_path", return_value="/mnt/skills"),
        patch("deerflow.sandbox.tools._get_skills_host_path", return_value="/home/user/deer-flow/skills"),
    ):
        resolved = _resolve_skills_path("/mnt/skills/public/bootstrap/SKILL.md")
        assert resolved == "/home/user/deer-flow/skills/public/bootstrap/SKILL.md"


def test_resolve_skills_path_resolves_root() -> None:
    """Skills container root should resolve to host skills directory."""
    with (
        patch("deerflow.sandbox.tools._get_skills_container_path", return_value="/mnt/skills"),
        patch("deerflow.sandbox.tools._get_skills_host_path", return_value="/home/user/deer-flow/skills"),
    ):
        resolved = _resolve_skills_path("/mnt/skills")
        assert resolved == "/home/user/deer-flow/skills"


def test_resolve_skills_path_raises_when_not_configured() -> None:
    """Should raise FileNotFoundError when skills directory is not available."""
    with (
        patch("deerflow.sandbox.tools._get_skills_container_path", return_value="/mnt/skills"),
        patch("deerflow.sandbox.tools._get_skills_host_path", return_value=None),
    ):
        with pytest.raises(FileNotFoundError, match="Skills directory not available"):
            _resolve_skills_path("/mnt/skills/public/bootstrap/SKILL.md")


# ---------- _resolve_and_validate_user_data_path ----------


def test_resolve_and_validate_user_data_path_resolves_correctly(tmp_path: Path) -> None:
    """Resolved path should land inside the correct thread directory."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    thread_data = {
        "workspace_path": str(workspace),
        "uploads_path": str(tmp_path / "uploads"),
        "outputs_path": str(tmp_path / "outputs"),
    }
    resolved = _resolve_and_validate_user_data_path("/mnt/user-data/workspace/hello.txt", thread_data)
    assert resolved == str(workspace / "hello.txt")


def test_resolve_and_validate_user_data_path_blocks_traversal(tmp_path: Path) -> None:
    """Even after resolution, path must stay within allowed roots."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    thread_data = {
        "workspace_path": str(workspace),
        "uploads_path": str(tmp_path / "uploads"),
        "outputs_path": str(tmp_path / "outputs"),
    }
    # This path resolves outside the allowed roots
    with pytest.raises(PermissionError):
        _resolve_and_validate_user_data_path("/mnt/user-data/workspace/../../../etc/passwd", thread_data)


# ---------- replace_virtual_paths_in_command ----------


def test_replace_virtual_paths_in_command_replaces_skills_paths() -> None:
    """Skills virtual paths in commands should be resolved to host paths."""
    with (
        patch("deerflow.sandbox.tools._get_skills_container_path", return_value="/mnt/skills"),
        patch("deerflow.sandbox.tools._get_skills_host_path", return_value="/home/user/deer-flow/skills"),
    ):
        cmd = "cat /mnt/skills/public/bootstrap/SKILL.md"
        result = replace_virtual_paths_in_command(cmd, _THREAD_DATA)
        assert "/mnt/skills" not in result
        assert "/home/user/deer-flow/skills/public/bootstrap/SKILL.md" in result


def test_replace_virtual_paths_in_command_replaces_both() -> None:
    """Both user-data and skills paths should be replaced in the same command."""
    with (
        patch("deerflow.sandbox.tools._get_skills_container_path", return_value="/mnt/skills"),
        patch("deerflow.sandbox.tools._get_skills_host_path", return_value="/home/user/skills"),
    ):
        cmd = "cat /mnt/skills/public/SKILL.md > /mnt/user-data/workspace/out.txt"
        result = replace_virtual_paths_in_command(cmd, _THREAD_DATA)
        assert "/mnt/skills" not in result
        assert "/mnt/user-data" not in result
        assert "/home/user/skills/public/SKILL.md" in result
        assert "/tmp/deer-flow/threads/t1/user-data/workspace/out.txt" in result


# ---------- validate_local_bash_command_paths ----------


def test_validate_local_bash_command_paths_blocks_host_paths() -> None:
    with pytest.raises(PermissionError, match="Unsafe absolute paths"):
        validate_local_bash_command_paths("cat /etc/passwd", _THREAD_DATA)


def test_validate_local_bash_command_paths_allows_virtual_and_system_paths() -> None:
    validate_local_bash_command_paths(
        "/bin/echo ok > /mnt/user-data/workspace/out.txt && cat /dev/null",
        _THREAD_DATA,
    )


def test_validate_local_bash_command_paths_blocks_traversal_in_user_data() -> None:
    """Bash commands with traversal in user-data paths should be blocked."""
    with pytest.raises(PermissionError, match="path traversal"):
        validate_local_bash_command_paths(
            "cat /mnt/user-data/workspace/../../etc/passwd",
            _THREAD_DATA,
        )


def test_validate_local_bash_command_paths_blocks_traversal_in_skills() -> None:
    """Bash commands with traversal in skills paths should be blocked."""
    with patch("deerflow.sandbox.tools._get_skills_container_path", return_value="/mnt/skills"):
        with pytest.raises(PermissionError, match="path traversal"):
            validate_local_bash_command_paths(
                "cat /mnt/skills/../../etc/passwd",
                _THREAD_DATA,
            )


def test_bash_tool_rejects_host_bash_when_local_sandbox_default(monkeypatch) -> None:
    runtime = SimpleNamespace(
        state={"sandbox": {"sandbox_id": "local"}, "thread_data": _THREAD_DATA.copy()},
        context={"thread_id": "thread-1"},
    )

    monkeypatch.setattr(
        "deerflow.sandbox.tools.ensure_sandbox_initialized",
        lambda runtime: SimpleNamespace(execute_command=lambda command: pytest.fail("host bash should not execute")),
    )
    monkeypatch.setattr("deerflow.sandbox.tools.is_host_bash_allowed", lambda: False)

    result = bash_tool.func(
        runtime=runtime,
        description="run command",
        command="/bin/echo hello",
    )

    assert "Host bash execution is disabled" in result


# ---------- Skills path tests ----------


def test_is_skills_path_recognises_default_prefix() -> None:
    with patch("deerflow.sandbox.tools._get_skills_container_path", return_value="/mnt/skills"):
        assert _is_skills_path("/mnt/skills") is True
        assert _is_skills_path("/mnt/skills/public/bootstrap/SKILL.md") is True
        assert _is_skills_path("/mnt/skills-extra/foo") is False
        assert _is_skills_path("/mnt/user-data/workspace") is False


def test_validate_local_tool_path_allows_skills_read_only() -> None:
    """read_file / ls should be able to access /mnt/skills paths."""
    with patch("deerflow.sandbox.tools._get_skills_container_path", return_value="/mnt/skills"):
        # Should not raise
        validate_local_tool_path(
            "/mnt/skills/public/bootstrap/SKILL.md",
            _THREAD_DATA,
            read_only=True,
        )


def test_validate_local_tool_path_blocks_skills_write() -> None:
    """write_file / str_replace must NOT write to skills paths."""
    with patch("deerflow.sandbox.tools._get_skills_container_path", return_value="/mnt/skills"):
        with pytest.raises(PermissionError, match="Write access to skills path is not allowed"):
            validate_local_tool_path(
                "/mnt/skills/public/bootstrap/SKILL.md",
                _THREAD_DATA,
                read_only=False,
            )


def test_validate_local_bash_command_paths_allows_skills_path() -> None:
    """bash commands referencing /mnt/skills should be allowed."""
    with patch("deerflow.sandbox.tools._get_skills_container_path", return_value="/mnt/skills"):
        validate_local_bash_command_paths(
            "cat /mnt/skills/public/bootstrap/SKILL.md",
            _THREAD_DATA,
        )


def test_validate_local_bash_command_paths_still_blocks_other_paths() -> None:
    """Paths outside virtual and system prefixes must still be blocked."""
    with patch("deerflow.sandbox.tools._get_skills_container_path", return_value="/mnt/skills"):
        with pytest.raises(PermissionError, match="Unsafe absolute paths"):
            validate_local_bash_command_paths("cat /etc/shadow", _THREAD_DATA)


def test_validate_local_tool_path_skills_custom_container_path() -> None:
    """Skills with a custom container_path in config should also work."""
    with patch("deerflow.sandbox.tools._get_skills_container_path", return_value="/custom/skills"):
        # Should not raise
        validate_local_tool_path(
            "/custom/skills/public/my-skill/SKILL.md",
            _THREAD_DATA,
            read_only=True,
        )

        # The default /mnt/skills should not match since container path is /custom/skills
        with pytest.raises(PermissionError, match="Only paths under"):
            validate_local_tool_path(
                "/mnt/skills/public/bootstrap/SKILL.md",
                _THREAD_DATA,
                read_only=True,
            )


# ---------- ACP workspace path tests ----------


def test_is_acp_workspace_path_recognises_prefix() -> None:
    assert _is_acp_workspace_path("/mnt/acp-workspace") is True
    assert _is_acp_workspace_path("/mnt/acp-workspace/hello.py") is True
    assert _is_acp_workspace_path("/mnt/acp-workspace-extra/foo") is False
    assert _is_acp_workspace_path("/mnt/user-data/workspace") is False


def test_validate_local_tool_path_allows_acp_workspace_read_only() -> None:
    """read_file / ls should be able to access /mnt/acp-workspace paths."""
    validate_local_tool_path(
        "/mnt/acp-workspace/hello_world.py",
        _THREAD_DATA,
        read_only=True,
    )


def test_validate_local_tool_path_blocks_acp_workspace_write() -> None:
    """write_file / str_replace must NOT write to ACP workspace paths."""
    with pytest.raises(PermissionError, match="Write access to ACP workspace is not allowed"):
        validate_local_tool_path(
            "/mnt/acp-workspace/hello_world.py",
            _THREAD_DATA,
            read_only=False,
        )


def test_validate_local_bash_command_paths_allows_acp_workspace() -> None:
    """bash commands referencing /mnt/acp-workspace should be allowed."""
    validate_local_bash_command_paths(
        "cp /mnt/acp-workspace/hello_world.py /mnt/user-data/outputs/hello_world.py",
        _THREAD_DATA,
    )


def test_validate_local_bash_command_paths_blocks_traversal_in_acp_workspace() -> None:
    """Bash commands with traversal in ACP workspace paths should be blocked."""
    with pytest.raises(PermissionError, match="path traversal"):
        validate_local_bash_command_paths(
            "cat /mnt/acp-workspace/../../etc/passwd",
            _THREAD_DATA,
        )


def test_resolve_acp_workspace_path_resolves_correctly(tmp_path: Path) -> None:
    """ACP workspace virtual path should resolve to host path."""
    acp_dir = tmp_path / "acp-workspace"
    acp_dir.mkdir()
    with patch("deerflow.sandbox.tools._get_acp_workspace_host_path", return_value=str(acp_dir)):
        resolved = _resolve_acp_workspace_path("/mnt/acp-workspace/hello.py")
        assert resolved == str(acp_dir / "hello.py")


def test_resolve_acp_workspace_path_resolves_root(tmp_path: Path) -> None:
    """ACP workspace root should resolve to host directory."""
    acp_dir = tmp_path / "acp-workspace"
    acp_dir.mkdir()
    with patch("deerflow.sandbox.tools._get_acp_workspace_host_path", return_value=str(acp_dir)):
        resolved = _resolve_acp_workspace_path("/mnt/acp-workspace")
        assert resolved == str(acp_dir)


def test_resolve_acp_workspace_path_raises_when_not_available() -> None:
    """Should raise FileNotFoundError when ACP workspace does not exist."""
    with patch("deerflow.sandbox.tools._get_acp_workspace_host_path", return_value=None):
        with pytest.raises(FileNotFoundError, match="ACP workspace directory not available"):
            _resolve_acp_workspace_path("/mnt/acp-workspace/hello.py")


def test_resolve_acp_workspace_path_blocks_traversal(tmp_path: Path) -> None:
    """Path traversal in ACP workspace paths must be rejected."""
    acp_dir = tmp_path / "acp-workspace"
    acp_dir.mkdir()
    with patch("deerflow.sandbox.tools._get_acp_workspace_host_path", return_value=str(acp_dir)):
        with pytest.raises(PermissionError, match="path traversal"):
            _resolve_acp_workspace_path("/mnt/acp-workspace/../../etc/passwd")


def test_replace_virtual_paths_in_command_replaces_acp_workspace() -> None:
    """ACP workspace virtual paths in commands should be resolved to host paths."""
    acp_host = "/home/user/.deer-flow/acp-workspace"
    with patch("deerflow.sandbox.tools._get_acp_workspace_host_path", return_value=acp_host):
        cmd = "cp /mnt/acp-workspace/hello.py /mnt/user-data/outputs/hello.py"
        result = replace_virtual_paths_in_command(cmd, _THREAD_DATA)
        assert "/mnt/acp-workspace" not in result
        assert f"{acp_host}/hello.py" in result
        assert "/tmp/deer-flow/threads/t1/user-data/outputs/hello.py" in result


def test_mask_local_paths_in_output_hides_acp_workspace_host_paths() -> None:
    """ACP workspace host paths in bash output should be masked to virtual paths."""
    acp_host = "/home/user/.deer-flow/acp-workspace"
    with patch("deerflow.sandbox.tools._get_acp_workspace_host_path", return_value=acp_host):
        output = f"Copied: {acp_host}/hello.py"
        masked = mask_local_paths_in_output(output, _THREAD_DATA)

        assert acp_host not in masked
        assert "/mnt/acp-workspace/hello.py" in masked


# ---------- _apply_cwd_prefix ----------


def test_apply_cwd_prefix_prepends_workspace() -> None:
    """Command is prefixed with cd <workspace> && when workspace_path is set."""
    result = _apply_cwd_prefix("ls -la", _THREAD_DATA)
    assert result.startswith("cd ")
    assert "ls -la" in result
    assert "/tmp/deer-flow/threads/t1/user-data/workspace" in result


def test_apply_cwd_prefix_no_thread_data() -> None:
    """Command is returned unchanged when thread_data is None."""
    assert _apply_cwd_prefix("ls -la", None) == "ls -la"


def test_apply_cwd_prefix_missing_workspace_path() -> None:
    """Command is returned unchanged when workspace_path is absent from thread_data."""
    assert _apply_cwd_prefix("ls -la", {}) == "ls -la"


def test_apply_cwd_prefix_quotes_path_with_spaces() -> None:
    """Workspace path containing spaces is properly shell-quoted."""
    thread_data = {**_THREAD_DATA, "workspace_path": "/tmp/my workspace/t1"}
    result = _apply_cwd_prefix("echo hello", thread_data)
    assert result == "cd '/tmp/my workspace/t1' && echo hello"


def test_validate_local_bash_command_paths_allows_mcp_filesystem_paths() -> None:
    """Bash commands referencing MCP filesystem server paths should be allowed."""
    from deerflow.config.extensions_config import ExtensionsConfig, McpServerConfig

    mock_config = ExtensionsConfig(
        mcp_servers={
            "filesystem": McpServerConfig(
                enabled=True,
                command="npx",
                args=["-y", "@modelcontextprotocol/server-filesystem", "/mnt/d/workspace"],
            )
        }
    )
    with patch("deerflow.config.extensions_config.get_extensions_config", return_value=mock_config):
        # Should not raise - MCP filesystem paths are allowed
        validate_local_bash_command_paths("ls /mnt/d/workspace", _THREAD_DATA)
        validate_local_bash_command_paths("cat /mnt/d/workspace/subdir/file.txt", _THREAD_DATA)

        # Path traversal should still be blocked
        with pytest.raises(PermissionError, match="path traversal"):
            validate_local_bash_command_paths("cat /mnt/d/workspace/../../etc/passwd", _THREAD_DATA)

        # Disabled servers should not expose paths
        disabled_config = ExtensionsConfig(
            mcp_servers={
                "filesystem": McpServerConfig(
                    enabled=False,
                    command="npx",
                    args=["-y", "@modelcontextprotocol/server-filesystem", "/mnt/d/workspace"],
                )
            }
        )
        with patch("deerflow.config.extensions_config.get_extensions_config", return_value=disabled_config):
            with pytest.raises(PermissionError, match="Unsafe absolute paths"):
                validate_local_bash_command_paths("ls /mnt/d/workspace", _THREAD_DATA)


def test_str_replace_parallel_updates_should_preserve_both_edits(monkeypatch) -> None:
    class SharedSandbox:
        def __init__(self) -> None:
            self.content = "alpha\nbeta\n"
            self._active_reads = 0
            self._state_lock = threading.Lock()
            self._overlap_detected = threading.Event()

        def read_file(self, path: str) -> str:
            with self._state_lock:
                self._active_reads += 1
                snapshot = self.content
                if self._active_reads == 2:
                    self._overlap_detected.set()

            self._overlap_detected.wait(0.05)

            with self._state_lock:
                self._active_reads -= 1

            return snapshot

        def write_file(self, path: str, content: str, append: bool = False) -> None:
            self.content = content

    sandbox = SharedSandbox()
    runtimes = [
        SimpleNamespace(state={}, context={"thread_id": "thread-1"}, config={}),
        SimpleNamespace(state={}, context={"thread_id": "thread-1"}, config={}),
    ]
    failures: list[BaseException] = []

    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: sandbox)
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)
    monkeypatch.setattr("deerflow.sandbox.tools.is_local_sandbox", lambda runtime: False)

    def worker(runtime: SimpleNamespace, old_str: str, new_str: str) -> None:
        try:
            result = str_replace_tool.func(
                runtime=runtime,
                description="并发替换同一文件",
                path="/mnt/user-data/workspace/shared.txt",
                old_str=old_str,
                new_str=new_str,
            )
            assert result == "OK"
        except BaseException as exc:  # pragma: no cover - failure is asserted below
            failures.append(exc)

    threads = [
        threading.Thread(target=worker, args=(runtimes[0], "alpha", "ALPHA")),
        threading.Thread(target=worker, args=(runtimes[1], "beta", "BETA")),
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert failures == []
    assert "ALPHA" in sandbox.content
    assert "BETA" in sandbox.content


def test_str_replace_parallel_updates_in_isolated_sandboxes_should_not_share_path_lock(monkeypatch) -> None:
    class IsolatedSandbox:
        def __init__(self, sandbox_id: str, shared_state: dict[str, object]) -> None:
            self.id = sandbox_id
            self.content = "alpha\nbeta\n"
            self._shared_state = shared_state

        def read_file(self, path: str) -> str:
            state_lock = self._shared_state["state_lock"]
            with state_lock:
                active_reads = self._shared_state["active_reads"]
                self._shared_state["active_reads"] = active_reads + 1
                snapshot = self.content
                if self._shared_state["active_reads"] == 2:
                    overlap_detected = self._shared_state["overlap_detected"]
                    overlap_detected.set()

            overlap_detected = self._shared_state["overlap_detected"]
            overlap_detected.wait(0.05)

            with state_lock:
                active_reads = self._shared_state["active_reads"]
                self._shared_state["active_reads"] = active_reads - 1

            return snapshot

        def write_file(self, path: str, content: str, append: bool = False) -> None:
            self.content = content

    shared_state: dict[str, object] = {
        "active_reads": 0,
        "state_lock": threading.Lock(),
        "overlap_detected": threading.Event(),
    }
    sandboxes = {
        "sandbox-a": IsolatedSandbox("sandbox-a", shared_state),
        "sandbox-b": IsolatedSandbox("sandbox-b", shared_state),
    }
    runtimes = [
        SimpleNamespace(state={}, context={"thread_id": "thread-1", "sandbox_key": "sandbox-a"}, config={}),
        SimpleNamespace(state={}, context={"thread_id": "thread-2", "sandbox_key": "sandbox-b"}, config={}),
    ]
    failures: list[BaseException] = []

    monkeypatch.setattr(
        "deerflow.sandbox.tools.ensure_sandbox_initialized",
        lambda runtime: sandboxes[runtime.context["sandbox_key"]],
    )
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)
    monkeypatch.setattr("deerflow.sandbox.tools.is_local_sandbox", lambda runtime: False)

    def worker(runtime: SimpleNamespace, old_str: str, new_str: str) -> None:
        try:
            result = str_replace_tool.func(
                runtime=runtime,
                description="隔离 sandbox 并发替换同一路径",
                path="/mnt/user-data/workspace/shared.txt",
                old_str=old_str,
                new_str=new_str,
            )
            assert result == "OK"
        except BaseException as exc:  # pragma: no cover - failure is asserted below
            failures.append(exc)

    threads = [
        threading.Thread(target=worker, args=(runtimes[0], "alpha", "ALPHA")),
        threading.Thread(target=worker, args=(runtimes[1], "beta", "BETA")),
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert failures == []
    assert sandboxes["sandbox-a"].content == "ALPHA\nbeta\n"
    assert sandboxes["sandbox-b"].content == "alpha\nBETA\n"
    assert shared_state["overlap_detected"].is_set()


def test_str_replace_and_append_on_same_path_should_preserve_both_updates(monkeypatch) -> None:
    class SharedSandbox:
        def __init__(self) -> None:
            self.id = "sandbox-1"
            self.content = "alpha\n"
            self.state_lock = threading.Lock()
            self.str_replace_has_snapshot = threading.Event()
            self.append_finished = threading.Event()

        def read_file(self, path: str) -> str:
            with self.state_lock:
                snapshot = self.content
            self.str_replace_has_snapshot.set()
            self.append_finished.wait(0.05)
            return snapshot

        def write_file(self, path: str, content: str, append: bool = False) -> None:
            with self.state_lock:
                if append:
                    self.content += content
                    self.append_finished.set()
                else:
                    self.content = content

    sandbox = SharedSandbox()
    runtimes = [
        SimpleNamespace(state={}, context={"thread_id": "thread-1"}, config={}),
        SimpleNamespace(state={}, context={"thread_id": "thread-1"}, config={}),
    ]
    failures: list[BaseException] = []

    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: sandbox)
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)
    monkeypatch.setattr("deerflow.sandbox.tools.is_local_sandbox", lambda runtime: False)

    def replace_worker() -> None:
        try:
            result = str_replace_tool.func(
                runtime=runtimes[0],
                description="替换旧内容",
                path="/mnt/user-data/workspace/shared.txt",
                old_str="alpha",
                new_str="ALPHA",
            )
            assert result == "OK"
        except BaseException as exc:  # pragma: no cover - failure is asserted below
            failures.append(exc)

    def append_worker() -> None:
        try:
            sandbox.str_replace_has_snapshot.wait(0.05)
            result = write_file_tool.func(
                runtime=runtimes[1],
                description="追加新内容",
                path="/mnt/user-data/workspace/shared.txt",
                content="tail\n",
                append=True,
            )
            assert result == "OK"
        except BaseException as exc:  # pragma: no cover - failure is asserted below
            failures.append(exc)

    replace_thread = threading.Thread(target=replace_worker)
    append_thread = threading.Thread(target=append_worker)

    replace_thread.start()
    append_thread.start()
    replace_thread.join()
    append_thread.join()

    assert failures == []
    assert sandbox.content == "ALPHA\ntail\n"
