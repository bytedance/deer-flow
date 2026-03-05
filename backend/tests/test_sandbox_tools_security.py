from pathlib import Path

import pytest

from src.sandbox.tools import (
    VIRTUAL_PATH_PREFIX,
    mask_local_paths_in_output,
    replace_virtual_path,
    resolve_local_tool_path,
)


def test_replace_virtual_path_maps_virtual_root_and_subpaths() -> None:
    thread_data = {
        "workspace_path": "/tmp/deer-flow/threads/t1/user-data/workspace",
        "uploads_path": "/tmp/deer-flow/threads/t1/user-data/uploads",
        "outputs_path": "/tmp/deer-flow/threads/t1/user-data/outputs",
    }

    assert replace_virtual_path("/mnt/user-data/workspace/a.txt", thread_data) == "/tmp/deer-flow/threads/t1/user-data/workspace/a.txt"
    assert replace_virtual_path("/mnt/user-data", thread_data) == "/tmp/deer-flow/threads/t1/user-data"


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


def test_resolve_local_tool_path_rejects_path_traversal() -> None:
    base = Path("/tmp/deer-flow/threads/t1/user-data")
    thread_data = {
        "workspace_path": str(base / "workspace"),
        "uploads_path": str(base / "uploads"),
        "outputs_path": str(base / "outputs"),
    }

    with pytest.raises(PermissionError, match="path traversal"):
        resolve_local_tool_path(f"{VIRTUAL_PATH_PREFIX}/workspace/../../../../etc/passwd", thread_data)
