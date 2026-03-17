from pathlib import Path
from unittest.mock import patch

import pytest

from deerflow.sandbox.tools import (
    VIRTUAL_PATH_PREFIX,
    mask_local_paths_in_output,
    replace_virtual_path,
    resolve_local_skills_path,
    resolve_local_tool_path,
    validate_local_bash_command_paths,
)


def test_replace_virtual_path_maps_virtual_root_and_subpaths() -> None:
    thread_data = {
        "workspace_path": "/tmp/deer-flow/threads/t1/user-data/workspace",
        "uploads_path": "/tmp/deer-flow/threads/t1/user-data/uploads",
        "outputs_path": "/tmp/deer-flow/threads/t1/user-data/outputs",
    }

    assert Path(replace_virtual_path("/mnt/user-data/workspace/a.txt", thread_data)).as_posix() == "/tmp/deer-flow/threads/t1/user-data/workspace/a.txt"
    assert Path(replace_virtual_path("/mnt/user-data", thread_data)).as_posix() == "/tmp/deer-flow/threads/t1/user-data"


def test_mask_local_paths_in_output_hides_host_paths() -> None:
    thread_data = {
        "workspace_path": "/tmp/deer-flow/threads/t1/user-data/workspace",
        "uploads_path": "/tmp/deer-flow/threads/t1/user-data/uploads",
        "outputs_path": "/tmp/deer-flow/threads/t1/user-data/outputs",
    }

    output = "Created: /tmp/deer-flow/threads/t1/user-data/workspace/result.txt"
    masked = mask_local_paths_in_output(output, thread_data)

    assert "/tmp/deer-flow/threads/t1/user-data" not in masked
    assert "/mnt/user-data/workspace/result.txt" in masked


def test_resolve_local_tool_path_rejects_non_virtual_path() -> None:
    thread_data = {
        "workspace_path": "/tmp/deer-flow/threads/t1/user-data/workspace",
        "uploads_path": "/tmp/deer-flow/threads/t1/user-data/uploads",
        "outputs_path": "/tmp/deer-flow/threads/t1/user-data/outputs",
    }

    with pytest.raises(PermissionError, match="Only paths under"):
        resolve_local_tool_path("/Users/someone/config.yaml", thread_data)


def test_resolve_local_tool_path_rejects_virtual_root_with_clear_message() -> None:
    """Passing the bare virtual root /mnt/user-data should be rejected early with a
    clear 'Only paths under' message, not the misleading 'path traversal detected'
    error that would result from the root mapping to a common parent directory."""
    thread_data = {
        "workspace_path": "/tmp/deer-flow/threads/t1/user-data/workspace",
        "uploads_path": "/tmp/deer-flow/threads/t1/user-data/uploads",
        "outputs_path": "/tmp/deer-flow/threads/t1/user-data/outputs",
    }

    with pytest.raises(PermissionError, match="Only paths under"):
        resolve_local_tool_path(VIRTUAL_PATH_PREFIX, thread_data)
        
        
def test_resolve_local_tool_path_returns_host_path_for_valid_virtual_path() -> None:
    base = Path("/tmp/deer-flow/threads/t1/user-data")
    thread_data = {
        "workspace_path": str(base / "workspace"),
        "uploads_path": str(base / "uploads"),
        "outputs_path": str(base / "outputs"),
    }

    result = resolve_local_tool_path(f"{VIRTUAL_PATH_PREFIX}/workspace/file.txt", thread_data)

    expected = str((base / "workspace" / "file.txt").resolve())
    assert result == expected


def test_resolve_local_tool_path_rejects_path_traversal() -> None:
    base = Path("/tmp/deer-flow/threads/t1/user-data")
    thread_data = {
        "workspace_path": str(base / "workspace"),
        "uploads_path": str(base / "uploads"),
        "outputs_path": str(base / "outputs"),
    }

    with pytest.raises(PermissionError, match="path traversal"):
        resolve_local_tool_path(f"{VIRTUAL_PATH_PREFIX}/workspace/../../../../etc/passwd", thread_data)


def test_validate_local_bash_command_paths_blocks_host_paths() -> None:
    thread_data = {
        "workspace_path": "/tmp/deer-flow/threads/t1/user-data/workspace",
        "uploads_path": "/tmp/deer-flow/threads/t1/user-data/uploads",
        "outputs_path": "/tmp/deer-flow/threads/t1/user-data/outputs",
    }

    with pytest.raises(PermissionError, match="Unsafe absolute paths"):
        validate_local_bash_command_paths("cat /etc/passwd", thread_data)


def test_validate_local_bash_command_paths_allows_virtual_and_system_paths() -> None:
    thread_data = {
        "workspace_path": "/tmp/deer-flow/threads/t1/user-data/workspace",
        "uploads_path": "/tmp/deer-flow/threads/t1/user-data/uploads",
        "outputs_path": "/tmp/deer-flow/threads/t1/user-data/outputs",
    }

    validate_local_bash_command_paths(
        "/bin/echo ok > /mnt/user-data/workspace/out.txt && cat /dev/null",
        thread_data,
    )


# ── Skills path tests ────────────────────────────────────────────────────


def _patch_skills(tmp_path: Path):
    """Patch helpers to point at a temp skills directory."""
    return (
        patch("deerflow.sandbox.tools._get_skills_container_prefix", return_value="/mnt/skills"),
        patch("deerflow.sandbox.tools._get_skills_local_path", return_value=tmp_path),
    )


def test_resolve_local_skills_path_resolves_valid_path(tmp_path: Path) -> None:
    skill_file = tmp_path / "public" / "my-skill" / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.touch()

    p1, p2 = _patch_skills(tmp_path)
    with p1, p2:
        result = resolve_local_skills_path("/mnt/skills/public/my-skill/SKILL.md")

    assert result == str(skill_file.resolve())


def test_resolve_local_skills_path_rejects_traversal(tmp_path: Path) -> None:
    p1, p2 = _patch_skills(tmp_path)
    with p1, p2:
        with pytest.raises(PermissionError, match="path traversal"):
            resolve_local_skills_path("/mnt/skills/../../../etc/passwd")


def test_resolve_local_skills_path_rejects_when_no_skills_dir() -> None:
    with (
        patch("deerflow.sandbox.tools._get_skills_container_prefix", return_value="/mnt/skills"),
        patch("deerflow.sandbox.tools._get_skills_local_path", return_value=None),
    ):
        with pytest.raises(Exception, match="Skills directory not configured"):
            resolve_local_skills_path("/mnt/skills/public/my-skill/SKILL.md")


def test_validate_local_bash_command_paths_blocks_skills_paths() -> None:
    """bash commands must NOT be allowed to access /mnt/skills (prevents write via shell)."""
    thread_data = {
        "workspace_path": "/tmp/deer-flow/threads/t1/user-data/workspace",
        "uploads_path": "/tmp/deer-flow/threads/t1/user-data/uploads",
        "outputs_path": "/tmp/deer-flow/threads/t1/user-data/outputs",
    }

    with pytest.raises(PermissionError, match="Unsafe absolute paths"):
        validate_local_bash_command_paths(
            "cat /mnt/skills/public/my-skill/SKILL.md",
            thread_data,
        )


def test_resolve_local_skills_path_resolves_bare_prefix(tmp_path: Path) -> None:
    """Exact /mnt/skills (no trailing slash) should resolve to skills root."""
    p1, p2 = _patch_skills(tmp_path)
    with p1, p2:
        result = resolve_local_skills_path("/mnt/skills")

    assert result == str(tmp_path.resolve())


def test_resolve_local_skills_path_rejects_non_skills_prefix() -> None:
    """Paths not under skills prefix must be rejected even if called directly."""
    with (
        patch("deerflow.sandbox.tools._get_skills_container_prefix", return_value="/mnt/skills"),
        patch("deerflow.sandbox.tools._get_skills_local_path", return_value=Path("/tmp/fake")),
    ):
        with pytest.raises(PermissionError, match="Only paths under"):
            resolve_local_skills_path("/tmp/evil/path")


def test_resolve_local_tool_path_still_rejects_skills_path() -> None:
    """write_file / str_replace use resolve_local_tool_path which must NOT accept skills paths."""
    thread_data = {
        "workspace_path": "/tmp/deer-flow/threads/t1/user-data/workspace",
        "uploads_path": "/tmp/deer-flow/threads/t1/user-data/uploads",
        "outputs_path": "/tmp/deer-flow/threads/t1/user-data/outputs",
    }

    with pytest.raises(PermissionError, match="Only paths under"):
        resolve_local_tool_path("/mnt/skills/public/my-skill/SKILL.md", thread_data)
