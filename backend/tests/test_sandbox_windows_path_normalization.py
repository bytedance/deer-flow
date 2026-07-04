"""Regression tests for Windows backslash path normalization.

Ensures that replace_virtual_paths_in_command and LocalSandbox._resolve_paths_in_command
return forward-slash paths when the host paths use backslashes (Windows).
"""

from unittest.mock import patch

from deerflow.sandbox.local.local_sandbox import LocalSandbox, PathMapping
from deerflow.sandbox.tools import replace_virtual_paths_in_command

# Windows-style thread data with backslash paths
_WIN_THREAD_DATA = {
    "workspace_path": r"C:\Users\admin\deer-flow\backend\.deer-flow\users\user1\threads\t1\user-data\workspace",
    "uploads_path": r"C:\Users\admin\deer-flow\backend\.deer-flow\users\user1\threads\t1\user-data\uploads",
    "outputs_path": r"C:\Users\admin\deer-flow\backend\.deer-flow\users\user1\threads\t1\user-data\outputs",
}


class TestReplaceVirtualPathsWindows:
    """replace_virtual_paths_in_command must normalize backslashes to forward slashes."""

    def test_user_data_workspace_no_backslash(self) -> None:
        cmd = "cat /mnt/user-data/workspace/data.json"
        result = replace_virtual_paths_in_command(cmd, _WIN_THREAD_DATA)
        assert "\\" not in result, f"Backslash in: {result}"

    def test_user_data_outputs_no_backslash(self) -> None:
        cmd = "ls /mnt/user-data/outputs/report.html"
        result = replace_virtual_paths_in_command(cmd, _WIN_THREAD_DATA)
        assert "\\" not in result, f"Backslash in: {result}"

    def test_user_data_subdir_no_backslash(self) -> None:
        cmd = "cat /mnt/user-data/workspace/subdir/file.txt"
        result = replace_virtual_paths_in_command(cmd, _WIN_THREAD_DATA)
        assert "\\" not in result, f"Backslash in: {result}"

    @patch("deerflow.sandbox.tools._get_skills_host_path", return_value=r"C:\Users\admin\deer-flow\skills")
    @patch("deerflow.sandbox.tools._get_skills_container_path", return_value="/mnt/skills")
    def test_skills_path_no_backslash(self, _mock_container, _mock_host) -> None:
        cmd = "python /mnt/skills/custom/skill/scripts/run.py"
        result = replace_virtual_paths_in_command(cmd, _WIN_THREAD_DATA)
        assert "\\" not in result, f"Backslash in: {result}"

    @patch("deerflow.sandbox.tools._resolve_acp_workspace_path", return_value=r"C:\Users\admin\deer-flow\acp-workspace\data.json")
    @patch("deerflow.sandbox.tools._get_acp_workspace_host_path", return_value=r"C:\Users\admin\deer-flow\acp-workspace")
    def test_acp_workspace_no_backslash(self, _mock_acp_host, _mock_resolve_acp) -> None:
        cmd = "cat /mnt/acp-workspace/data.json"
        result = replace_virtual_paths_in_command(cmd, _WIN_THREAD_DATA)
        assert "\\" not in result, f"Backslash in: {result}"
        assert "C:/Users/admin/deer-flow/acp-workspace/data.json" in result


class TestLocalSandboxResolvePathsInCommandWindows:
    """LocalSandbox._resolve_paths_in_command must normalize backslashes."""

    def test_custom_mount_no_backslash(self) -> None:
        sandbox = LocalSandbox(
            "test",
            path_mappings=[
                PathMapping(container_path="/mnt/models", local_path=r"C:\Users\admin\models", read_only=True),
            ],
        )
        cmd = "cat /mnt/models/weights.bin"
        result = sandbox._resolve_paths_in_command(cmd)
        assert "\\" not in result, f"Backslash in: {result}"
        assert "C:/Users/admin/models/weights.bin" in result

    def test_user_data_no_backslash(self) -> None:
        sandbox = LocalSandbox(
            "test",
            path_mappings=[
                PathMapping(container_path="/mnt/user-data", local_path=r"C:\Users\admin\data"),
            ],
        )
        cmd = "ls /mnt/user-data/workspace/file.txt"
        result = sandbox._resolve_paths_in_command(cmd)
        assert "\\" not in result, f"Backslash in: {result}"
        assert "C:/Users/admin/data/workspace/file.txt" in result
