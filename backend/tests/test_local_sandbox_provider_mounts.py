import errno
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from deerflow.sandbox.exceptions import SandboxPermissionError
from deerflow.sandbox.local.local_sandbox import LocalSandbox, PathMapping
from deerflow.sandbox.local.local_sandbox_provider import LocalSandboxProvider


class TestPathMapping:
    def test_path_mapping_dataclass(self):
        mapping = PathMapping(container_path="/mnt/skills", local_path="/home/user/skills", read_only=True)
        assert mapping.container_path == "/mnt/skills"
        assert mapping.local_path == "/home/user/skills"
        assert mapping.read_only is True

    def test_path_mapping_defaults_to_false(self):
        mapping = PathMapping(container_path="/mnt/data", local_path="/home/user/data")
        assert mapping.read_only is False


class TestLocalSandboxPathResolution:
    def test_resolve_path_exact_match(self):
        sandbox = LocalSandbox(
            "test",
            [
                PathMapping(container_path="/mnt/skills", local_path="/home/user/skills"),
            ],
        )
        resolved = sandbox._resolve_path("/mnt/skills")
        assert resolved.replace("\\", "/") == os.path.realpath("/home/user/skills").replace("\\", "/")

    def test_resolve_path_nested_path(self):
        sandbox = LocalSandbox(
            "test",
            [
                PathMapping(container_path="/mnt/skills", local_path="/home/user/skills"),
            ],
        )
        resolved = sandbox._resolve_path("/mnt/skills/agent/prompt.py")
        assert resolved.replace("\\", "/") == os.path.realpath("/home/user/skills/agent/prompt.py").replace("\\", "/")

    def test_resolve_path_no_mapping(self):
        sandbox = LocalSandbox(
            "test",
            [
                PathMapping(container_path="/mnt/skills", local_path="/home/user/skills"),
            ],
        )
        resolved = sandbox._resolve_path("/mnt/other/file.txt")
        assert resolved == "/mnt/other/file.txt"

    def test_resolve_path_longest_prefix_first(self):
        sandbox = LocalSandbox(
            "test",
            [
                PathMapping(container_path="/mnt/skills", local_path="/home/user/skills"),
                PathMapping(container_path="/mnt", local_path="/var/mnt"),
            ],
        )
        resolved = sandbox._resolve_path("/mnt/skills/file.py")
        # Should match /mnt/skills first (longer prefix)
        assert resolved.replace("\\", "/") == os.path.realpath("/home/user/skills/file.py").replace("\\", "/")

    def test_resolve_path_traversal_dot_dot(self):
        sandbox = LocalSandbox(
            "test",
            [
                PathMapping(container_path="/mnt/workspace", local_path="/tmp/sandbox/123"),
            ],
        )
        # Attempt to escape via ../
        with pytest.raises(SandboxPermissionError, match="escapes sandbox boundary"):
            sandbox._resolve_path("/mnt/workspace/../../../etc/passwd")

    def test_resolve_path_traversal_to_similar_name(self):
        sandbox = LocalSandbox(
            "test",
            [
                PathMapping(container_path="/mnt/workspace", local_path="/tmp/sandbox/workspace"),
            ],
        )
        # Attempting to escape the sandbox directory (/tmp/sandbox/workspace)
        # to a directory with a similar prefix (/tmp/sandbox/workspace-hack)
        # using a path traversal sequence.
        with pytest.raises(SandboxPermissionError, match="escapes sandbox boundary"):
            sandbox._resolve_path("/mnt/workspace/../workspace-hack/file")

    def test_resolve_path_symlink_escape(self, tmp_path):
        # Setup a mock environment with a symlink
        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()

        secret_dir = tmp_path / "secrets"
        secret_dir.mkdir()
        (secret_dir / "passwd").write_text("secret")

        # Create a symlink inside the workspace pointing outside
        symlink_path = workspace_dir / "mylink"
        try:
            os.symlink(str(secret_dir), str(symlink_path))
        except OSError:
            pytest.skip("Symlinks not supported on this OS/filesystem")

        sandbox = LocalSandbox(
            "test",
            [
                PathMapping(container_path="/mnt/workspace", local_path=str(workspace_dir)),
            ],
        )

        # Accessing the symlink should fail because its realpath escapes the workspace
        with pytest.raises(SandboxPermissionError, match="escapes sandbox boundary"):
            sandbox._resolve_path("/mnt/workspace/mylink/passwd")

    def test_resolve_path_returns_realpath_result(self, tmp_path):
        """Test that _resolve_path returns the same result as os.path.realpath."""
        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()

        sandbox = LocalSandbox(
            "test",
            [
                PathMapping(container_path="/mnt/workspace", local_path=str(workspace_dir)),
            ],
        )

        # Resolve a file inside the workspace
        resolved = sandbox._resolve_path("/mnt/workspace/test.txt")

        # The resolved path should match os.path.realpath behavior
        expected_path = os.path.realpath(str(workspace_dir / "test.txt")).replace("\\", "/")
        assert resolved == expected_path

    def test_resolve_path_traversal_includes_context_in_exception(self):
        """Test that SandboxPermissionError includes path and operation context."""
        sandbox = LocalSandbox(
            "test",
            [PathMapping(container_path="/mnt/workspace", local_path="/tmp/workspace")],
        )

        with pytest.raises(SandboxPermissionError) as exc_info:
            sandbox._resolve_path("/mnt/workspace/../etc/passwd")

        assert exc_info.value.path == "/mnt/workspace/../etc/passwd"
        assert exc_info.value.operation == "_resolve_path"
        assert "escapes sandbox boundary" in str(exc_info.value)

    def test_reverse_resolve_path_exact_match(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        sandbox = LocalSandbox(
            "test",
            [
                PathMapping(container_path="/mnt/skills", local_path=str(skills_dir)),
            ],
        )
        resolved = sandbox._reverse_resolve_path(str(skills_dir))
        assert resolved == "/mnt/skills"

    def test_reverse_resolve_path_nested(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        file_path = skills_dir / "agent" / "prompt.py"
        file_path.parent.mkdir()
        file_path.write_text("test")

        sandbox = LocalSandbox(
            "test",
            [
                PathMapping(container_path="/mnt/skills", local_path=str(skills_dir)),
            ],
        )
        resolved = sandbox._reverse_resolve_path(str(file_path))
        assert resolved == "/mnt/skills/agent/prompt.py"


class TestReadOnlyPath:
    def test_is_read_only_true(self):
        sandbox = LocalSandbox(
            "test",
            [
                PathMapping(container_path="/mnt/skills", local_path="/home/user/skills", read_only=True),
            ],
        )
        assert sandbox._is_read_only_path("/home/user/skills/file.py") is True

    def test_is_read_only_false_for_writable(self):
        sandbox = LocalSandbox(
            "test",
            [
                PathMapping(container_path="/mnt/data", local_path="/home/user/data", read_only=False),
            ],
        )
        assert sandbox._is_read_only_path("/home/user/data/file.txt") is False

    def test_is_read_only_false_for_unmapped_path(self):
        sandbox = LocalSandbox(
            "test",
            [
                PathMapping(container_path="/mnt/skills", local_path="/home/user/skills", read_only=True),
            ],
        )
        # Path not under any mapping
        assert sandbox._is_read_only_path("/tmp/other/file.txt") is False

    def test_is_read_only_true_for_exact_match(self):
        sandbox = LocalSandbox(
            "test",
            [
                PathMapping(container_path="/mnt/skills", local_path="/home/user/skills", read_only=True),
            ],
        )
        assert sandbox._is_read_only_path("/home/user/skills") is True

    def test_write_file_blocked_on_read_only(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        sandbox = LocalSandbox(
            "test",
            [
                PathMapping(container_path="/mnt/skills", local_path=str(skills_dir), read_only=True),
            ],
        )
        # Skills dir is read-only, write should be blocked
        with pytest.raises(OSError) as exc_info:
            sandbox.write_file("/mnt/skills/new_file.py", "content")
        assert exc_info.value.errno == errno.EROFS

    def test_write_file_allowed_on_writable_mount(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        sandbox = LocalSandbox(
            "test",
            [
                PathMapping(container_path="/mnt/data", local_path=str(data_dir), read_only=False),
            ],
        )
        sandbox.write_file("/mnt/data/file.txt", "content")
        assert (data_dir / "file.txt").read_text() == "content"

    def test_update_file_blocked_on_read_only(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        existing_file = skills_dir / "existing.py"
        existing_file.write_bytes(b"original")

        sandbox = LocalSandbox(
            "test",
            [
                PathMapping(container_path="/mnt/skills", local_path=str(skills_dir), read_only=True),
            ],
        )
        with pytest.raises(OSError) as exc_info:
            sandbox.update_file("/mnt/skills/existing.py", b"updated")
        assert exc_info.value.errno == errno.EROFS


class TestMultipleMounts:
    def test_multiple_read_write_mounts(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        external_dir = tmp_path / "external"
        external_dir.mkdir()

        sandbox = LocalSandbox(
            "test",
            [
                PathMapping(container_path="/mnt/skills", local_path=str(skills_dir), read_only=True),
                PathMapping(container_path="/mnt/data", local_path=str(data_dir), read_only=False),
                PathMapping(container_path="/mnt/external", local_path=str(external_dir), read_only=True),
            ],
        )

        # Skills is read-only
        with pytest.raises(OSError):
            sandbox.write_file("/mnt/skills/file.py", "content")

        # Data is writable
        sandbox.write_file("/mnt/data/file.txt", "data content")
        assert (data_dir / "file.txt").read_text() == "data content"

        # External is read-only
        with pytest.raises(OSError):
            sandbox.write_file("/mnt/external/file.txt", "content")

    def test_nested_mounts_writable_under_readonly(self, tmp_path):
        """A writable mount nested under a read-only mount should allow writes."""
        ro_dir = tmp_path / "ro"
        ro_dir.mkdir()
        rw_dir = ro_dir / "writable"
        rw_dir.mkdir()

        sandbox = LocalSandbox(
            "test",
            [
                PathMapping(container_path="/mnt/repo", local_path=str(ro_dir), read_only=True),
                PathMapping(container_path="/mnt/repo/writable", local_path=str(rw_dir), read_only=False),
            ],
        )

        # Parent mount is read-only
        with pytest.raises(OSError):
            sandbox.write_file("/mnt/repo/file.txt", "content")

        # Nested writable mount should allow writes
        sandbox.write_file("/mnt/repo/writable/file.txt", "content")
        assert (rw_dir / "file.txt").read_text() == "content"

    def test_execute_command_path_replacement(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        test_file = data_dir / "test.txt"
        test_file.write_text("hello")

        sandbox = LocalSandbox(
            "test",
            [
                PathMapping(container_path="/mnt/data", local_path=str(data_dir)),
            ],
        )

        # Mock subprocess to capture the resolved command
        captured = {}
        original_run = __import__("subprocess").run

        def mock_run(*args, **kwargs):
            if len(args) > 0:
                captured["command"] = args[0]
            return original_run(*args, **kwargs)

        monkeypatch.setattr("deerflow.sandbox.local.local_sandbox.subprocess.run", mock_run)
        monkeypatch.setattr("deerflow.sandbox.local.local_sandbox.LocalSandbox._get_shell", lambda self: "/bin/sh")

        sandbox.execute_command("cat /mnt/data/test.txt")
        # Verify the command received the resolved local path
        command = captured.get("command", [])
        assert isinstance(command, list) and len(command) >= 3
        assert str(data_dir) in command[2]

    def test_reverse_resolve_path_does_not_match_partial_prefix(self, tmp_path):
        foo_dir = tmp_path / "foo"
        foo_dir.mkdir()
        foobar_dir = tmp_path / "foobar"
        foobar_dir.mkdir()
        target = foobar_dir / "file.txt"
        target.write_text("test")

        sandbox = LocalSandbox(
            "test",
            [
                PathMapping(container_path="/mnt/foo", local_path=str(foo_dir)),
            ],
        )

        resolved = sandbox._reverse_resolve_path(str(target))
        assert resolved == str(target.resolve())

    def test_reverse_resolve_paths_in_output_supports_backslash_separator(self, tmp_path):
        mount_dir = tmp_path / "mount"
        mount_dir.mkdir()
        sandbox = LocalSandbox(
            "test",
            [
                PathMapping(container_path="/mnt/data", local_path=str(mount_dir)),
            ],
        )

        output = f"Copied: {mount_dir}\\file.txt"
        masked = sandbox._reverse_resolve_paths_in_output(output)

        assert "/mnt/data/file.txt" in masked
        assert str(mount_dir) not in masked


class TestLocalSandboxProviderMounts:
    def test_setup_path_mappings_uses_configured_skills_container_path_as_reserved_prefix(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        custom_dir = tmp_path / "custom"
        custom_dir.mkdir()

        from deerflow.config.sandbox_config import SandboxConfig, VolumeMountConfig

        sandbox_config = SandboxConfig(
            use="deerflow.sandbox.local:LocalSandboxProvider",
            mounts=[
                VolumeMountConfig(host_path=str(custom_dir), container_path="/custom-skills/nested", read_only=False),
            ],
        )
        config = SimpleNamespace(
            skills=SimpleNamespace(container_path="/custom-skills", get_skills_path=lambda: skills_dir),
            sandbox=sandbox_config,
        )

        with patch("deerflow.config.get_app_config", return_value=config):
            provider = LocalSandboxProvider()

        assert [m.container_path for m in provider._path_mappings] == ["/custom-skills"]

    def test_setup_path_mappings_skips_relative_host_path(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        from deerflow.config.sandbox_config import SandboxConfig, VolumeMountConfig

        sandbox_config = SandboxConfig(
            use="deerflow.sandbox.local:LocalSandboxProvider",
            mounts=[
                VolumeMountConfig(host_path="relative/path", container_path="/mnt/data", read_only=False),
            ],
        )
        config = SimpleNamespace(
            skills=SimpleNamespace(container_path="/mnt/skills", get_skills_path=lambda: skills_dir),
            sandbox=sandbox_config,
        )

        with patch("deerflow.config.get_app_config", return_value=config):
            provider = LocalSandboxProvider()

        assert [m.container_path for m in provider._path_mappings] == ["/mnt/skills"]

    def test_setup_path_mappings_skips_non_absolute_container_path(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        custom_dir = tmp_path / "custom"
        custom_dir.mkdir()

        from deerflow.config.sandbox_config import SandboxConfig, VolumeMountConfig

        sandbox_config = SandboxConfig(
            use="deerflow.sandbox.local:LocalSandboxProvider",
            mounts=[
                VolumeMountConfig(host_path=str(custom_dir), container_path="mnt/data", read_only=False),
            ],
        )
        config = SimpleNamespace(
            skills=SimpleNamespace(container_path="/mnt/skills", get_skills_path=lambda: skills_dir),
            sandbox=sandbox_config,
        )

        with patch("deerflow.config.get_app_config", return_value=config):
            provider = LocalSandboxProvider()

        assert [m.container_path for m in provider._path_mappings] == ["/mnt/skills"]

    def test_write_file_resolves_container_paths_in_content(self, tmp_path):
        """write_file should replace container paths in file content with local paths."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        sandbox = LocalSandbox(
            "test",
            [
                PathMapping(container_path="/mnt/data", local_path=str(data_dir)),
            ],
        )
        sandbox.write_file(
            "/mnt/data/script.py",
            'import pathlib\npath = "/mnt/data/output"\nprint(path)',
        )
        written = (data_dir / "script.py").read_text()
        # Container path should be resolved to local path (forward slashes)
        assert str(data_dir).replace("\\", "/") in written
        assert "/mnt/data/output" not in written

    def test_write_file_uses_forward_slashes_on_windows_paths(self, tmp_path):
        """Resolved paths in content should always use forward slashes."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        sandbox = LocalSandbox(
            "test",
            [
                PathMapping(container_path="/mnt/data", local_path=str(data_dir)),
            ],
        )
        sandbox.write_file(
            "/mnt/data/config.py",
            'DATA_DIR = "/mnt/data/files"',
        )
        written = (data_dir / "config.py").read_text()
        # Must not contain backslashes that could break escape sequences
        assert "\\" not in written.split("DATA_DIR = ")[1].split("\n")[0]

    def test_read_file_reverse_resolves_local_paths_in_agent_written_files(self, tmp_path):
        """read_file should convert local paths back to container paths in agent-written files."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        sandbox = LocalSandbox(
            "test",
            [
                PathMapping(container_path="/mnt/data", local_path=str(data_dir)),
            ],
        )
        # Use write_file so the path is tracked as agent-written
        sandbox.write_file("/mnt/data/info.txt", "File located at: /mnt/data/info.txt")

        content = sandbox.read_file("/mnt/data/info.txt")
        assert "/mnt/data/info.txt" in content

    def test_read_file_does_not_reverse_resolve_non_agent_files(self, tmp_path):
        """read_file should NOT rewrite paths in user-uploaded or external files."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        sandbox = LocalSandbox(
            "test",
            [
                PathMapping(container_path="/mnt/data", local_path=str(data_dir)),
            ],
        )
        # Write directly to filesystem (simulates user upload or external tool output)
        local_path = str(data_dir).replace("\\", "/")
        (data_dir / "config.yml").write_text(f"output_dir: {local_path}/outputs")

        content = sandbox.read_file("/mnt/data/config.yml")
        # Content should be returned as-is, NOT reverse-resolved
        assert local_path in content

    def test_write_then_read_roundtrip(self, tmp_path):
        """Container paths survive a write → read roundtrip."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        sandbox = LocalSandbox(
            "test",
            [
                PathMapping(container_path="/mnt/data", local_path=str(data_dir)),
            ],
        )
        original = 'cfg = {"path": "/mnt/data/config.json", "flag": true}'
        sandbox.write_file("/mnt/data/settings.py", original)
        result = sandbox.read_file("/mnt/data/settings.py")
        # The container path should be preserved through roundtrip
        assert "/mnt/data/config.json" in result

    def test_setup_path_mappings_normalizes_container_path_trailing_slash(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        custom_dir = tmp_path / "custom"
        custom_dir.mkdir()

        from deerflow.config.sandbox_config import SandboxConfig, VolumeMountConfig

        sandbox_config = SandboxConfig(
            use="deerflow.sandbox.local:LocalSandboxProvider",
            mounts=[
                VolumeMountConfig(host_path=str(custom_dir), container_path="/mnt/data/", read_only=False),
            ],
        )
        config = SimpleNamespace(
            skills=SimpleNamespace(container_path="/mnt/skills", get_skills_path=lambda: skills_dir),
            sandbox=sandbox_config,
        )

        with patch("deerflow.config.get_app_config", return_value=config):
            provider = LocalSandboxProvider()

        assert [m.container_path for m in provider._path_mappings] == ["/mnt/skills", "/mnt/data"]
