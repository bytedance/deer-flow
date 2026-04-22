from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.gateway.routers.langgraph import threads as threads
from deerflow.config.paths import Paths


async def _empty_async_iter():
    if False:
        yield None


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

    app = make_authed_test_app()
    app.include_router(threads.router, prefix="/api/threads")
    app.state.persistence = MagicMock(checkpointer=MagicMock())
    app.state.thread_meta_storage = MagicMock(delete_thread=AsyncMock())

    with patch("app.gateway.routers.langgraph.threads.get_paths", return_value=paths):
        with TestClient(app) as client:
            response = client.delete("/api/threads/thread-route")

    assert response.status_code == 200
    assert response.json() == {"success": True, "message": "Deleted local thread data for thread-route"}
    assert not thread_dir.exists()


def test_delete_thread_route_rejects_invalid_thread_id(tmp_path):
    paths = Paths(tmp_path)

    app = make_authed_test_app()
    app.include_router(threads.router, prefix="/api/threads")
    app.state.persistence = MagicMock(checkpointer=MagicMock())
    app.state.thread_meta_storage = MagicMock(delete_thread=AsyncMock())

    with patch("app.gateway.routers.langgraph.threads.get_paths", return_value=paths):
        with TestClient(app) as client:
            response = client.delete("/api/threads/../escape")

    assert response.status_code == 404


def test_delete_thread_route_returns_422_for_route_safe_invalid_id(tmp_path):
    paths = Paths(tmp_path)

    app = make_authed_test_app()
    app.include_router(threads.router, prefix="/api/threads")
    app.state.persistence = MagicMock(checkpointer=MagicMock())
    app.state.thread_meta_storage = MagicMock(delete_thread=AsyncMock())

    with patch("app.gateway.routers.langgraph.threads.get_paths", return_value=paths):
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


def test_get_thread_history_returns_empty_list_when_thread_exists_without_checkpoints():
    app = make_authed_test_app()
    app.include_router(threads.router, prefix="/api/threads")
    app.state.persistence = MagicMock(checkpointer=MagicMock(alist=lambda *args, **kwargs: _empty_async_iter()))
    app.state.thread_meta_storage = MagicMock(get_thread=AsyncMock(return_value=MagicMock(thread_id="thread-empty")))
    app.state.run_store = MagicMock(list_by_thread=AsyncMock(return_value=[]))

    with TestClient(app) as client:
        response = client.post("/api/threads/thread-empty/history", json={"limit": 10})

    assert response.status_code == 200
    assert response.json() == []


def test_get_thread_state_returns_empty_state_when_thread_exists_without_checkpoints():
    app = make_authed_test_app()
    app.include_router(threads.router, prefix="/api/threads")
    app.state.persistence = MagicMock(checkpointer=MagicMock(aget_tuple=AsyncMock(return_value=None)))
    app.state.thread_meta_storage = MagicMock(get_thread=AsyncMock(return_value=MagicMock(thread_id="thread-empty")))
    app.state.run_store = MagicMock(list_by_thread=AsyncMock(return_value=[]))

    with TestClient(app) as client:
        response = client.get("/api/threads/thread-empty/state")

    assert response.status_code == 200
    assert response.json() == {
        "values": {},
        "next": [],
        "tasks": [],
        "checkpoint": {},
        "checkpoint_id": None,
        "parent_checkpoint_id": None,
        "metadata": {},
        "created_at": None,
    }
