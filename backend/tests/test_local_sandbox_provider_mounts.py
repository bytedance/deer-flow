import errno
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from deerflow.sandbox.local.local_sandbox import LocalSandbox, PathMapping
from deerflow.sandbox.local.local_sandbox_provider import LocalSandboxProvider


def _symlink_to(target, link, *, target_is_directory=False):
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks are not available: {exc}")


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
        assert resolved == str(Path("/home/user/skills").resolve())

    def test_resolve_path_nested_path(self):
        sandbox = LocalSandbox(
            "test",
            [
                PathMapping(container_path="/mnt/skills", local_path="/home/user/skills"),
            ],
        )
        resolved = sandbox._resolve_path("/mnt/skills/agent/prompt.py")
        assert resolved == str(Path("/home/user/skills/agent/prompt.py").resolve())

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
        assert resolved == str(Path("/home/user/skills/file.py").resolve())

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


class TestSymlinkEscapes:
    def test_read_file_blocks_symlink_escape_from_mount(self, tmp_path):
        mount_dir = tmp_path / "mount"
        mount_dir.mkdir()
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        (outside_dir / "secret.txt").write_text("secret")
        _symlink_to(outside_dir, mount_dir / "escape", target_is_directory=True)

        sandbox = LocalSandbox(
            "test",
            [
                PathMapping(container_path="/mnt/data", local_path=str(mount_dir), read_only=False),
            ],
        )

        with pytest.raises(PermissionError) as exc_info:
            sandbox.read_file("/mnt/data/escape/secret.txt")

        assert exc_info.value.errno == errno.EACCES

    def test_write_file_blocks_symlink_escape_from_mount(self, tmp_path):
        mount_dir = tmp_path / "mount"
        mount_dir.mkdir()
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        victim = outside_dir / "victim.txt"
        victim.write_text("original")
        _symlink_to(outside_dir, mount_dir / "escape", target_is_directory=True)

        sandbox = LocalSandbox(
            "test",
            [
                PathMapping(container_path="/mnt/data", local_path=str(mount_dir), read_only=False),
            ],
        )

        with pytest.raises(PermissionError) as exc_info:
            sandbox.write_file("/mnt/data/escape/victim.txt", "changed")

        assert exc_info.value.errno == errno.EACCES
        assert victim.read_text() == "original"

    def test_write_file_uses_matched_read_only_mount_for_symlink_target(self, tmp_path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        writable_dir = repo_dir / "writable"
        writable_dir.mkdir()
        _symlink_to(writable_dir, repo_dir / "link-to-writable", target_is_directory=True)

        sandbox = LocalSandbox(
            "test",
            [
                PathMapping(container_path="/mnt/repo", local_path=str(repo_dir), read_only=True),
                PathMapping(container_path="/mnt/repo/writable", local_path=str(writable_dir), read_only=False),
            ],
        )

        with pytest.raises(OSError) as exc_info:
            sandbox.write_file("/mnt/repo/link-to-writable/file.txt", "bypass")

        assert exc_info.value.errno == errno.EROFS
        assert not (writable_dir / "file.txt").exists()

    def test_list_dir_does_not_follow_symlink_escape_from_mount(self, tmp_path):
        mount_dir = tmp_path / "mount"
        mount_dir.mkdir()
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        (outside_dir / "secret.txt").write_text("secret")
        _symlink_to(outside_dir, mount_dir / "escape", target_is_directory=True)
        (mount_dir / "visible.txt").write_text("visible")

        sandbox = LocalSandbox(
            "test",
            [
                PathMapping(container_path="/mnt/data", local_path=str(mount_dir), read_only=False),
            ],
        )

        entries = sandbox.list_dir("/mnt/data", max_depth=2)

        assert "/mnt/data/visible.txt" in entries
        assert all("secret.txt" not in entry for entry in entries)
        assert all("outside" not in entry for entry in entries)

    def test_list_dir_formats_internal_directory_symlink_like_directory(self, tmp_path):
        mount_dir = tmp_path / "mount"
        nested_dir = mount_dir / "nested"
        linked_dir = nested_dir / "linked-dir"
        linked_dir.mkdir(parents=True)
        _symlink_to(linked_dir, mount_dir / "dir-link", target_is_directory=True)

        sandbox = LocalSandbox(
            "test",
            [
                PathMapping(container_path="/mnt/data", local_path=str(mount_dir), read_only=False),
            ],
        )

        entries = sandbox.list_dir("/mnt/data", max_depth=1)

        assert "/mnt/data/nested/" in entries
        assert "/mnt/data/nested/linked-dir/" in entries
        assert "/mnt/data/dir-link" not in entries

    def test_write_file_blocks_symlink_into_nested_read_only_mount(self, tmp_path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        protected_dir = repo_dir / "protected"
        protected_dir.mkdir()
        _symlink_to(protected_dir, repo_dir / "link-to-protected", target_is_directory=True)

        sandbox = LocalSandbox(
            "test",
            [
                PathMapping(container_path="/mnt/repo", local_path=str(repo_dir), read_only=False),
                PathMapping(container_path="/mnt/repo/protected", local_path=str(protected_dir), read_only=True),
            ],
        )

        with pytest.raises(OSError) as exc_info:
            sandbox.write_file("/mnt/repo/link-to-protected/file.txt", "bypass")

        assert exc_info.value.errno == errno.EROFS
        assert not (protected_dir / "file.txt").exists()

    def test_update_file_blocks_symlink_into_nested_read_only_mount(self, tmp_path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        protected_dir = repo_dir / "protected"
        protected_dir.mkdir()
        existing = protected_dir / "file.txt"
        existing.write_bytes(b"original")
        _symlink_to(protected_dir, repo_dir / "link-to-protected", target_is_directory=True)

        sandbox = LocalSandbox(
            "test",
            [
                PathMapping(container_path="/mnt/repo", local_path=str(repo_dir), read_only=False),
                PathMapping(container_path="/mnt/repo/protected", local_path=str(protected_dir), read_only=True),
            ],
        )

        with pytest.raises(OSError) as exc_info:
            sandbox.update_file("/mnt/repo/link-to-protected/file.txt", b"changed")

        assert exc_info.value.errno == errno.EROFS
        assert existing.read_bytes() == b"original"


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
            skills=SimpleNamespace(container_path="/custom-skills", get_skills_path=lambda: skills_dir, use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage"),
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
            skills=SimpleNamespace(container_path="/mnt/skills", get_skills_path=lambda: skills_dir, use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage"),
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
            skills=SimpleNamespace(container_path="/mnt/skills", get_skills_path=lambda: skills_dir, use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage"),
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
            skills=SimpleNamespace(container_path="/mnt/skills", get_skills_path=lambda: skills_dir, use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage"),
            sandbox=sandbox_config,
        )

        with patch("deerflow.config.get_app_config", return_value=config):
            provider = LocalSandboxProvider()

        assert [m.container_path for m in provider._path_mappings] == ["/mnt/skills", "/mnt/data"]
