"""Tests for LocalSandbox: path resolution, command execution, file I/O."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.sandbox.local.local_sandbox import LocalSandbox


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------
class TestResolvePathLocal:
    """Tests for LocalSandbox._resolve_path()."""

    def test_maps_container_path(self, tmp_path: Path) -> None:
        sandbox = LocalSandbox(id="local", path_mappings={"/mnt/skills": str(tmp_path / "skills")})
        result = sandbox._resolve_path("/mnt/skills/tool.py")
        assert result == str(tmp_path / "skills" / "tool.py")

    def test_unmapped_passthrough(self) -> None:
        sandbox = LocalSandbox(id="local", path_mappings={})
        assert sandbox._resolve_path("/home/user/file.py") == "/home/user/file.py"

    def test_longest_prefix_wins(self, tmp_path: Path) -> None:
        sandbox = LocalSandbox(
            id="local",
            path_mappings={
                "/mnt": str(tmp_path / "mnt"),
                "/mnt/skills": str(tmp_path / "skills"),
            },
        )
        result = sandbox._resolve_path("/mnt/skills/tool.py")
        assert result == str(tmp_path / "skills" / "tool.py")

    def test_exact_prefix_match(self, tmp_path: Path) -> None:
        sandbox = LocalSandbox(id="local", path_mappings={"/mnt/skills": str(tmp_path / "skills")})
        result = sandbox._resolve_path("/mnt/skills")
        assert result == str(tmp_path / "skills")


class TestReverseResolvePath:
    """Tests for LocalSandbox._reverse_resolve_path()."""

    def test_maps_local_to_container(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        sandbox = LocalSandbox(id="local", path_mappings={"/mnt/skills": str(skills_dir)})
        result = sandbox._reverse_resolve_path(str(skills_dir / "tool.py"))
        assert result == "/mnt/skills/tool.py"

    def test_unmapped_passthrough(self, tmp_path: Path) -> None:
        sandbox = LocalSandbox(id="local", path_mappings={})
        path = str(tmp_path / "some" / "file.py")
        result = sandbox._reverse_resolve_path(path)
        # Should return resolved path (since no mapping matches)
        assert "file.py" in result


class TestResolvePathsInCommand:
    """Tests for LocalSandbox._resolve_paths_in_command()."""

    def test_resolves_multiple_paths(self, tmp_path: Path) -> None:
        sandbox = LocalSandbox(
            id="local",
            path_mappings={"/mnt/skills": str(tmp_path / "skills")},
        )
        cmd = "cat /mnt/skills/a.py /mnt/skills/b.py"
        result = sandbox._resolve_paths_in_command(cmd)
        assert str(tmp_path / "skills" / "a.py") in result
        assert str(tmp_path / "skills" / "b.py") in result

    def test_no_mappings_passthrough(self) -> None:
        sandbox = LocalSandbox(id="local", path_mappings={})
        cmd = "echo hello"
        assert sandbox._resolve_paths_in_command(cmd) == cmd


# ---------------------------------------------------------------------------
# Command execution
# ---------------------------------------------------------------------------
class TestExecuteCommand:
    """Tests for LocalSandbox.execute_command()."""

    def test_returns_stdout(self) -> None:
        sandbox = LocalSandbox(id="local")
        result = sandbox.execute_command("echo hello")
        assert "hello" in result

    def test_returns_stderr_on_error(self) -> None:
        sandbox = LocalSandbox(id="local")
        result = sandbox.execute_command("echo error >&2")
        assert "error" in result

    def test_nonzero_exit_code(self) -> None:
        sandbox = LocalSandbox(id="local")
        result = sandbox.execute_command("exit 42")
        assert "Exit Code: 42" in result

    def test_empty_output(self) -> None:
        sandbox = LocalSandbox(id="local")
        result = sandbox.execute_command("true")
        assert result == "(no output)"


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------
class TestFileOperations:
    """Tests for LocalSandbox read_file, write_file, list_dir."""

    def test_read_file_success(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        sandbox = LocalSandbox(id="local")
        assert sandbox.read_file(str(f)) == "hello world"

    def test_read_file_not_found(self, tmp_path: Path) -> None:
        sandbox = LocalSandbox(id="local")
        with pytest.raises(FileNotFoundError):
            sandbox.read_file(str(tmp_path / "missing.txt"))

    def test_write_file_creates(self, tmp_path: Path) -> None:
        target = tmp_path / "output.txt"
        sandbox = LocalSandbox(id="local")
        sandbox.write_file(str(target), "content")
        assert target.read_text() == "content"

    def test_write_file_append(self, tmp_path: Path) -> None:
        target = tmp_path / "output.txt"
        target.write_text("first ")
        sandbox = LocalSandbox(id="local")
        sandbox.write_file(str(target), "second", append=True)
        assert target.read_text() == "first second"

    def test_write_file_creates_parents(self, tmp_path: Path) -> None:
        target = tmp_path / "sub" / "dir" / "file.txt"
        sandbox = LocalSandbox(id="local")
        sandbox.write_file(str(target), "nested")
        assert target.read_text() == "nested"

    def test_update_file_binary(self, tmp_path: Path) -> None:
        target = tmp_path / "data.bin"
        sandbox = LocalSandbox(id="local")
        sandbox.update_file(str(target), b"\x00\x01\x02")
        assert target.read_bytes() == b"\x00\x01\x02"

    def test_list_dir_entries(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").touch()
        (tmp_path / "b.txt").touch()
        sandbox = LocalSandbox(id="local")
        entries = sandbox.list_dir(str(tmp_path))
        assert len(entries) >= 2

    def test_list_dir_empty(self, tmp_path: Path) -> None:
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        sandbox = LocalSandbox(id="local")
        entries = sandbox.list_dir(str(empty_dir))
        assert entries == []


# ---------------------------------------------------------------------------
# Shell detection
# ---------------------------------------------------------------------------
class TestGetShell:
    """Tests for LocalSandbox._get_shell()."""

    def test_returns_valid_shell(self) -> None:
        shell = LocalSandbox._get_shell()
        assert shell.endswith(("sh", "bash", "zsh"))
