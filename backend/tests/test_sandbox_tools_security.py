from pathlib import Path
from unittest.mock import patch

import pytest

from deerflow.sandbox.tools import (
    VIRTUAL_PATH_PREFIX,
    _is_skills_path,
    mask_local_paths_in_output,
    replace_virtual_path,
    validate_local_bash_command_paths,
    validate_local_tool_path,
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


# ---------- validate_local_tool_path tests ----------

_THREAD_DATA = {
    "workspace_path": "/tmp/deer-flow/threads/t1/user-data/workspace",
    "uploads_path": "/tmp/deer-flow/threads/t1/user-data/uploads",
    "outputs_path": "/tmp/deer-flow/threads/t1/user-data/outputs",
}


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


# ---------- validate_local_bash_command_paths tests ----------


def test_validate_local_bash_command_paths_blocks_host_paths() -> None:
    with pytest.raises(PermissionError, match="Unsafe absolute paths"):
        validate_local_bash_command_paths("cat /etc/passwd", _THREAD_DATA)


def test_validate_local_bash_command_paths_allows_virtual_and_system_paths() -> None:
    validate_local_bash_command_paths(
        "/bin/echo ok > /mnt/user-data/workspace/out.txt && cat /dev/null",
        _THREAD_DATA,
    )


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
