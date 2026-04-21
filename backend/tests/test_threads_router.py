import uuid
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from app.gateway.routers import threads
from deerflow.config.paths import Paths


def test_delete_thread_data_removes_thread_directory(tmp_path):
    paths = Paths(tmp_path)
    thread_dir = paths.thread_dir("thread-cleanup")
    workspace = paths.sandbox_work_dir("thread-cleanup")
    uploads = paths.sandbox_uploads_dir("thread-cleanup")
    outputs = paths.sandbox_outputs_dir("thread-cleanup")

    for directory in [workspace, uploads, outputs]:
        directory.mkdir(parents=True, exist_ok=True)
    (workspace / "notes.txt").write_text("hello", encoding="utf-8")
    (uploads / "report.pdf").write_bytes(b"pdf")
    (outputs / "result.json").write_text("{}", encoding="utf-8")

    assert thread_dir.exists()

    response = threads._delete_thread_data("thread-cleanup", paths=paths)

    assert response.success is True
    assert not thread_dir.exists()


def test_delete_thread_data_is_idempotent_for_missing_directory(tmp_path):
    paths = Paths(tmp_path)

    response = threads._delete_thread_data("missing-thread", paths=paths)

    assert response.success is True
    assert not paths.thread_dir("missing-thread").exists()


def test_delete_thread_data_rejects_invalid_thread_id(tmp_path):
    paths = Paths(tmp_path)

    with pytest.raises(HTTPException) as exc_info:
        threads._delete_thread_data("../escape", paths=paths)

    assert exc_info.value.status_code == 422
    assert "Invalid thread_id" in exc_info.value.detail


def test_delete_thread_route_cleans_thread_directory(tmp_path):
    paths = Paths(tmp_path)
    thread_dir = paths.thread_dir("thread-route")
    paths.sandbox_work_dir("thread-route").mkdir(parents=True, exist_ok=True)
    (paths.sandbox_work_dir("thread-route") / "notes.txt").write_text("hello", encoding="utf-8")

    app = FastAPI()
    app.include_router(threads.router)

    with patch("app.gateway.routers.threads.get_paths", return_value=paths):
        with TestClient(app) as client:
            response = client.delete("/api/threads/thread-route")

    assert response.status_code == 200
    assert response.json() == {"success": True, "message": "Deleted local thread data for thread-route"}
    assert not thread_dir.exists()


def test_delete_thread_route_rejects_invalid_thread_id(tmp_path):
    paths = Paths(tmp_path)

    app = FastAPI()
    app.include_router(threads.router)

    with patch("app.gateway.routers.threads.get_paths", return_value=paths):
        with TestClient(app) as client:
            response = client.delete("/api/threads/../escape")

    assert response.status_code == 404


def test_delete_thread_route_returns_422_for_route_safe_invalid_id(tmp_path):
    paths = Paths(tmp_path)

    app = FastAPI()
    app.include_router(threads.router)

    with patch("app.gateway.routers.threads.get_paths", return_value=paths):
        with TestClient(app) as client:
            response = client.delete("/api/threads/thread.with.dot")

    assert response.status_code == 422
    assert "Invalid thread_id" in response.json()["detail"]


def test_delete_thread_data_returns_generic_500_error(tmp_path):
    paths = Paths(tmp_path)

    with (
        patch.object(paths, "delete_thread_dir", side_effect=OSError("/secret/path")),
        patch.object(threads.logger, "exception") as log_exception,
    ):
        with pytest.raises(HTTPException) as exc_info:
            threads._delete_thread_data("thread-cleanup", paths=paths)

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Failed to delete local thread data."
    assert "/secret/path" not in exc_info.value.detail
    log_exception.assert_called_once_with("Failed to delete thread data for %s", "thread-cleanup")


# ---------------------------------------------------------------------------
# update_thread_state — checkpoint history growth
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_thread_state_creates_new_checkpoint_each_call():
    """Each call to update_thread_state must INSERT a new checkpoint row.

    Before the fix, checkpoint["id"] was copied verbatim from the previous
    checkpoint, causing the SQL ``INSERT OR REPLACE`` to overwrite the
    existing row in-place.  History therefore stayed at exactly 1 entry no
    matter how many updates were applied.

    After the fix a fresh UUID is assigned to checkpoint["id"] before aput,
    so every call produces a distinct row and history grows correctly.
    """
    checkpointer = MemorySaver()
    thread_id = str(uuid.uuid4())

    # Write the initial (empty) checkpoint that create_thread would normally create.
    from langgraph.checkpoint.base import empty_checkpoint

    init_config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    await checkpointer.aput(init_config, empty_checkpoint(), {"step": -1, "source": "input", "writes": None, "parents": {}}, {})

    # Build a minimal fake Request that returns our in-memory checkpointer.
    class _FakeRequest:
        class app:
            class state:
                pass

        app.state.checkpointer = checkpointer
        app.state.store = None

    fake_request = _FakeRequest()

    with (
        patch("app.gateway.routers.threads.get_checkpointer", return_value=checkpointer),
        patch("app.gateway.routers.threads.get_store", return_value=None),
    ):
        body1 = threads.ThreadStateUpdateRequest(values={"title": "First title"})
        await threads.update_thread_state(thread_id, body1, fake_request)

        body2 = threads.ThreadStateUpdateRequest(values={"title": "Second title"})
        await threads.update_thread_state(thread_id, body2, fake_request)

    # Collect all checkpoints for this thread.
    history = [
        cp
        async for cp in checkpointer.alist({"configurable": {"thread_id": thread_id}})
    ]

    # There must be at least 3 entries: the initial one + one per update call.
    # This is the key invariant: each update_thread_state call must INSERT a new
    # checkpoint row instead of overwriting the existing one in-place.
    #
    # Note: MemorySaver stores channel_values as blobs keyed by new_versions entries.
    # Since update_thread_state passes new_versions={}, MemorySaver does not persist
    # channel_values in blobs — only the checkpoint count is meaningful here.
    # In production (SQLite/Postgres) the full checkpoint dict is serialised as a
    # single blob so channel_values are preserved correctly.
    assert len(history) >= 3, (
        f"Expected at least 3 checkpoint entries but got {len(history)}. "
        "update_thread_state may be overwriting the existing checkpoint instead of inserting a new one."
    )

    # Each checkpoint must have a distinct ID.
    checkpoint_ids = [cp.config["configurable"]["checkpoint_id"] for cp in history]
    assert len(checkpoint_ids) == len(set(checkpoint_ids)), (
        f"Duplicate checkpoint IDs found: {checkpoint_ids}"
    )
