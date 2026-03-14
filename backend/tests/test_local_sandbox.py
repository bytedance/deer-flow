"""Tests for LocalSandbox: path resolution, command execution, file I/O."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pytest

import src.sandbox.local.local_sandbox as local_sandbox_mod
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

    @pytest.fixture(autouse=True)
    def _reset_shell_cache(self):
        """Reset the module-level shell cache before and after each test."""
        saved = local_sandbox_mod._cached_shell
        local_sandbox_mod._cached_shell = None
        yield
        local_sandbox_mod._cached_shell = saved

    def test_returns_valid_shell(self) -> None:
        shell = LocalSandbox._get_shell()
        assert shell.endswith(("sh", "bash", "zsh"))

    def test_shell_detection_cached(self) -> None:
        """After first call, filesystem checks should not be repeated."""
        with patch("os.path.isfile", return_value=True) as mock_isfile, patch("os.access", return_value=True):
            first = LocalSandbox._get_shell()
            second = LocalSandbox._get_shell()

        assert first == second
        # os.path.isfile should only be called during the first invocation
        assert mock_isfile.call_count == 1

    def test_shell_cache_populated(self) -> None:
        """After calling _get_shell(), the module-level cache should be set."""
        assert local_sandbox_mod._cached_shell is None
        result = LocalSandbox._get_shell()
        assert local_sandbox_mod._cached_shell is not None
        assert local_sandbox_mod._cached_shell == result


# ---------------------------------------------------------------------------
# Path cache verification (Fix 2)
# ---------------------------------------------------------------------------
class TestPathCaches:
    """Tests for _build_path_caches() — pre-computed sorted mappings and compiled regex."""

    def test_path_caches_built_on_init(self, tmp_path: Path) -> None:
        """Verify all cache attributes are correctly populated with 3 mappings."""
        mappings = {
            "/mnt/a": str(tmp_path / "a"),
            "/mnt/a/deep": str(tmp_path / "a_deep"),
            "/mnt/b": str(tmp_path / "b_local_longer_name"),
        }
        sandbox = LocalSandbox(id="local", path_mappings=mappings)

        # _sorted_by_container_key: sorted by container path length descending
        assert len(sandbox._sorted_by_container_key) == 3
        container_lens = [len(cp) for cp, _ in sandbox._sorted_by_container_key]
        assert container_lens == sorted(container_lens, reverse=True)

        # _sorted_by_local_key: sorted by local path length descending
        assert len(sandbox._sorted_by_local_key) == 3
        local_lens = [len(lp) for _, lp in sandbox._sorted_by_local_key]
        assert local_lens == sorted(local_lens, reverse=True)

        # _reverse_patterns: list of (str, re.Pattern)
        assert len(sandbox._reverse_patterns) == 3
        for container_path, pattern in sandbox._reverse_patterns:
            assert isinstance(container_path, str)
            assert isinstance(pattern, re.Pattern)

        # _forward_pattern: single compiled regex
        assert isinstance(sandbox._forward_pattern, re.Pattern)

    def test_path_caches_empty_mappings(self) -> None:
        """With no mappings, caches should be empty/None."""
        sandbox = LocalSandbox(id="local", path_mappings={})

        assert sandbox._sorted_by_container_key == []
        assert sandbox._sorted_by_local_key == []
        assert sandbox._reverse_patterns == []
        assert sandbox._forward_pattern is None

    def test_sorted_not_called_during_resolve(self, tmp_path: Path) -> None:
        """After init, _resolve_path() should NOT call sorted() — it uses cached lists."""
        mappings = {"/mnt/skills": str(tmp_path / "skills")}
        sandbox = LocalSandbox(id="local", path_mappings=mappings)

        with patch("builtins.sorted") as mock_sorted:
            sandbox._resolve_path("/mnt/skills/tool.py")
            sandbox._resolve_path("/mnt/skills/other.py")
            sandbox._resolve_path("/home/user/file.py")
        mock_sorted.assert_not_called()

    def test_regex_not_recompiled_per_call(self, tmp_path: Path) -> None:
        """After init, _resolve_paths_in_command() should NOT recompile regex patterns."""
        mappings = {"/mnt/skills": str(tmp_path / "skills")}
        sandbox = LocalSandbox(id="local", path_mappings=mappings)

        with patch("re.compile") as mock_compile:
            for _ in range(5):
                sandbox._resolve_paths_in_command("cat /mnt/skills/tool.py")
                sandbox._reverse_resolve_paths_in_output(f"reading {tmp_path}/skills/tool.py")
        mock_compile.assert_not_called()

    def test_resolve_paths_consistency(self, tmp_path: Path) -> None:
        """Cached path resolution produces identical results to expected values."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        mappings = {
            "/mnt/skills": str(skills_dir),
            "/mnt/data": str(data_dir),
        }
        sandbox = LocalSandbox(id="local", path_mappings=mappings)

        # Forward resolution
        assert sandbox._resolve_path("/mnt/skills/tool.py") == str(skills_dir / "tool.py")
        assert sandbox._resolve_path("/mnt/data/file.csv") == str(data_dir / "file.csv")
        assert sandbox._resolve_path("/home/user/other") == "/home/user/other"

        # Reverse resolution
        assert sandbox._reverse_resolve_path(str(skills_dir / "tool.py")) == "/mnt/skills/tool.py"
        assert sandbox._reverse_resolve_path(str(data_dir / "file.csv")) == "/mnt/data/file.csv"

        # Command resolution
        cmd = "cat /mnt/skills/a.py /mnt/data/b.csv"
        resolved = sandbox._resolve_paths_in_command(cmd)
        assert str(skills_dir / "a.py") in resolved
        assert str(data_dir / "b.csv") in resolved

        # Output reverse resolution
        output = f"File at {skills_dir}/tool.py processed"
        reversed_output = sandbox._reverse_resolve_paths_in_output(output)
        assert "/mnt/skills/tool.py" in reversed_output
