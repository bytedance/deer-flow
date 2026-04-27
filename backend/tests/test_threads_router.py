import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.gateway.routers import threads
from deerflow.config.paths import Paths


class _DummyStore:
    def __init__(self):
        self.records = {}
        self.fail_keys = set()

    async def aget(self, namespace, key):
        value = self.records.get((tuple(namespace), key))
        if value is None:
            return None
        return SimpleNamespace(value=value)

    async def aput(self, namespace, key, value):
        if key in self.fail_keys:
            raise RuntimeError(f"failed to write store record for {key}")
        self.records[(tuple(namespace), key)] = value

    async def adelete(self, namespace, key):
        self.records.pop((tuple(namespace), key), None)

    async def asearch(self, namespace, limit=100):
        items = []
        for (ns, _key), value in self.records.items():
            if ns == tuple(namespace):
                items.append(SimpleNamespace(value=value))
        return items[:limit]


class _DummyCheckpointer:
    def __init__(self):
        self._items = {}
        self.fail_thread_ids = set()

    async def aget_tuple(self, config):
        thread_id = config.get("configurable", {}).get("thread_id")
        checkpoint_id = config.get("configurable", {}).get("checkpoint_id")
        items = self._items.get(thread_id, [])
        if checkpoint_id is None:
            return items[-1] if items else None
        for item in reversed(items):
            if item.config.get("configurable", {}).get("checkpoint_id") == checkpoint_id:
                return item
        return None

    async def aput(self, config, checkpoint, metadata, _writes):
        thread_id = config.get("configurable", {}).get("thread_id")
        if thread_id in self.fail_thread_ids:
            raise RuntimeError(f"failed to write checkpoint for {thread_id}")
        checkpoint_ns = config.get("configurable", {}).get("checkpoint_ns", "")
        existing = self._items.setdefault(thread_id, [])
        checkpoint_id = f"{thread_id}-ckpt-{len(existing) + 1}"
        parent = existing[-1] if existing else None
        item = SimpleNamespace(
            config={
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_id": checkpoint_id,
                    "checkpoint_ns": checkpoint_ns,
                }
            },
            parent_config=parent.config if parent else None,
            metadata=dict(metadata),
            checkpoint=deepcopy(checkpoint),
            tasks=[],
        )
        existing.append(item)
        return item.config

    async def alist(self, config=None, limit=None):
        thread_id = None if config is None else config.get("configurable", {}).get("thread_id")
        if thread_id is None:
            items = [item for entries in self._items.values() for item in entries]
        else:
            items = list(self._items.get(thread_id, []))
        items = list(reversed(items))
        if limit is not None:
            items = items[:limit]
        for item in items:
            yield item

    async def adelete_thread(self, thread_id):
        self._items.pop(thread_id, None)


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


def test_copy_directory_contents_skips_symlinks(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    (source / "real.txt").write_text("copied", encoding="utf-8")
    (source / "link.txt").symlink_to(outside)

    threads._copy_directory_contents(source, destination)

    assert (destination / "real.txt").read_text(encoding="utf-8") == "copied"
    assert not (destination / "link.txt").exists()


def test_create_thread_branch_copies_state_and_uploads(tmp_path):
    paths = Paths(tmp_path)
    parent_thread_id = "parent-thread"
    paths.ensure_thread_dirs(parent_thread_id)
    (paths.sandbox_uploads_dir(parent_thread_id) / "brief.txt").write_text(
        "hello branch",
        encoding="utf-8",
    )

    store = _DummyStore()
    checkpointer = _DummyCheckpointer()

    parent_record = {
        "thread_id": parent_thread_id,
        "status": "idle",
        "created_at": 1.0,
        "updated_at": 1.0,
        "metadata": {"agent_name": "researcher", "branch_depth": "2"},
        "values": {"title": "Main thread"},
    }
    asyncio.run(store.aput(threads.THREADS_NS, parent_thread_id, parent_record))

    source_checkpoint = {
        "v": 2,
        "id": "source",
        "ts": "2026-04-10T00:00:00Z",
        "channel_values": {
            "title": "Main thread",
            "messages": [{"type": "human", "content": "Main question"}],
            "artifacts": ["/mnt/user-data/outputs/report.md"],
        },
        "channel_versions": {},
        "versions_seen": {},
        "pending_sends": [],
        "updated_channels": None,
    }
    asyncio.run(
        checkpointer.aput(
            {"configurable": {"thread_id": parent_thread_id, "checkpoint_ns": ""}},
            source_checkpoint,
            {
                "created_at": 1.0,
                "updated_at": 1.0,
                "step": 1,
                "source": "loop",
                "writes": {},
                "parents": {},
            },
            {},
        )
    )

    app = FastAPI()
    app.include_router(threads.router)
    app.state.checkpointer = checkpointer
    app.state.store = store

    ensure_thread = AsyncMock()
    with (
        patch("app.gateway.routers.threads.get_paths", return_value=paths),
        patch(
            "app.gateway.routers.threads._ensure_langgraph_thread_exists",
            ensure_thread,
        ),
    ):
        with TestClient(app) as client:
            response = client.post(
                f"/api/threads/{parent_thread_id}/branches",
                json={"branch_name": "Side branch"},
            )

    assert response.status_code == 200
    payload = response.json()
    child_thread_id = payload["thread_id"]

    assert child_thread_id != parent_thread_id
    assert payload["parent_thread_id"] == parent_thread_id
    assert payload["root_thread_id"] == parent_thread_id
    assert payload["metadata"]["branch_role"] == "branch"
    assert payload["metadata"]["return_thread_id"] == parent_thread_id
    assert payload["metadata"]["agent_name"] == "researcher"
    assert payload["metadata"]["branch_depth"] == 3
    assert payload["values"]["title"] == "Side branch"
    assert payload["values"]["artifacts"] == []
    ensure_thread.assert_awaited_once_with(
        child_thread_id,
        metadata=payload["metadata"],
    )

    child_checkpoint = asyncio.run(checkpointer.aget_tuple({"configurable": {"thread_id": child_thread_id, "checkpoint_ns": ""}}))
    assert child_checkpoint is not None
    assert child_checkpoint.checkpoint["channel_values"]["artifacts"] == []
    assert child_checkpoint.checkpoint["channel_values"]["messages"] == [{"type": "human", "content": "Main question"}]
    assert child_checkpoint.checkpoint["channel_values"]["title"] == "Side branch"

    assert (paths.sandbox_uploads_dir(child_thread_id) / "brief.txt").read_text(encoding="utf-8") == "hello branch"

    parent_checkpoint = asyncio.run(checkpointer.aget_tuple({"configurable": {"thread_id": parent_thread_id, "checkpoint_ns": ""}}))
    assert parent_checkpoint.checkpoint["channel_values"]["title"] == "Main thread"


def test_create_thread_branch_can_fork_from_explicit_checkpoint(tmp_path):
    paths = Paths(tmp_path)
    parent_thread_id = "parent-thread"

    store = _DummyStore()
    checkpointer = _DummyCheckpointer()

    asyncio.run(
        store.aput(
            threads.THREADS_NS,
            parent_thread_id,
            {
                "thread_id": parent_thread_id,
                "status": "idle",
                "created_at": 1.0,
                "updated_at": 1.0,
                "metadata": {},
                "values": {"title": "Latest"},
            },
        )
    )

    first_config = asyncio.run(
        checkpointer.aput(
            {"configurable": {"thread_id": parent_thread_id, "checkpoint_ns": ""}},
            {
                "v": 2,
                "id": "first",
                "ts": "2026-04-10T00:00:00Z",
                "channel_values": {
                    "title": "Before",
                    "messages": [{"type": "human", "content": "before"}],
                },
                "channel_versions": {},
                "versions_seen": {},
                "pending_sends": [],
                "updated_channels": None,
            },
            {"created_at": 1.0},
            {},
        )
    )
    asyncio.run(
        checkpointer.aput(
            {"configurable": {"thread_id": parent_thread_id, "checkpoint_ns": ""}},
            {
                "v": 2,
                "id": "second",
                "ts": "2026-04-10T00:01:00Z",
                "channel_values": {
                    "title": "After",
                    "messages": [{"type": "human", "content": "after"}],
                },
                "channel_versions": {},
                "versions_seen": {},
                "pending_sends": [],
                "updated_channels": None,
            },
            {"created_at": 2.0},
            {},
        )
    )

    app = FastAPI()
    app.include_router(threads.router)
    app.state.checkpointer = checkpointer
    app.state.store = store

    with (
        patch("app.gateway.routers.threads.get_paths", return_value=paths),
        patch(
            "app.gateway.routers.threads._ensure_langgraph_thread_exists",
            AsyncMock(),
        ),
    ):
        with TestClient(app) as client:
            response = client.post(
                f"/api/threads/{parent_thread_id}/branches",
                json={
                    "checkpoint_id": first_config["configurable"]["checkpoint_id"],
                    "branch_name": "From before",
                },
            )

    assert response.status_code == 200
    child_thread_id = response.json()["thread_id"]
    child_checkpoint = asyncio.run(checkpointer.aget_tuple({"configurable": {"thread_id": child_thread_id, "checkpoint_ns": ""}}))

    assert child_checkpoint.checkpoint["channel_values"]["messages"] == [{"type": "human", "content": "before"}]
    assert child_checkpoint.checkpoint["channel_values"]["title"] == "From before"


def test_create_thread_branch_defaults_invalid_branch_depth_metadata_to_zero(tmp_path):
    paths = Paths(tmp_path)
    parent_thread_id = "parent-thread"

    store = _DummyStore()
    checkpointer = _DummyCheckpointer()

    asyncio.run(
        store.aput(
            threads.THREADS_NS,
            parent_thread_id,
            {
                "thread_id": parent_thread_id,
                "status": "idle",
                "created_at": 1.0,
                "updated_at": 1.0,
                "metadata": {"branch_depth": "oops"},
                "values": {"title": "Latest"},
            },
        )
    )
    asyncio.run(
        checkpointer.aput(
            {"configurable": {"thread_id": parent_thread_id, "checkpoint_ns": ""}},
            {
                "v": 2,
                "id": "source",
                "ts": "2026-04-10T00:00:00Z",
                "channel_values": {"title": "Main thread"},
                "channel_versions": {},
                "versions_seen": {},
                "pending_sends": [],
                "updated_channels": None,
            },
            {"created_at": 1.0},
            {},
        )
    )

    app = FastAPI()
    app.include_router(threads.router)
    app.state.checkpointer = checkpointer
    app.state.store = store

    with (
        patch("app.gateway.routers.threads.get_paths", return_value=paths),
        patch(
            "app.gateway.routers.threads._ensure_langgraph_thread_exists",
            AsyncMock(),
        ),
    ):
        with TestClient(app) as client:
            response = client.post(
                f"/api/threads/{parent_thread_id}/branches",
                json={"branch_name": "Side branch"},
            )

    assert response.status_code == 200
    assert response.json()["metadata"]["branch_depth"] == 1


def test_create_thread_branch_rolls_back_partial_branch_on_checkpoint_failure(tmp_path):
    paths = Paths(tmp_path)
    parent_thread_id = "parent-thread"
    child_thread_id = "child-thread"
    paths.ensure_thread_dirs(parent_thread_id)
    (paths.sandbox_uploads_dir(parent_thread_id) / "brief.txt").write_text(
        "hello branch",
        encoding="utf-8",
    )

    store = _DummyStore()
    checkpointer = _DummyCheckpointer()
    asyncio.run(
        store.aput(
            threads.THREADS_NS,
            parent_thread_id,
            {
                "thread_id": parent_thread_id,
                "status": "idle",
                "created_at": 1.0,
                "updated_at": 1.0,
                "metadata": {},
                "values": {"title": "Main thread"},
            },
        )
    )
    asyncio.run(
        checkpointer.aput(
            {"configurable": {"thread_id": parent_thread_id, "checkpoint_ns": ""}},
            {
                "v": 2,
                "id": "source",
                "ts": "2026-04-10T00:00:00Z",
                "channel_values": {
                    "title": "Main thread",
                    "messages": [{"type": "human", "content": "Main question"}],
                },
                "channel_versions": {},
                "versions_seen": {},
                "pending_sends": [],
                "updated_channels": None,
            },
            {"created_at": 1.0},
            {},
        )
    )
    checkpointer.fail_thread_ids.add(child_thread_id)

    app = FastAPI()
    app.include_router(threads.router)
    app.state.checkpointer = checkpointer
    app.state.store = store

    delete_langgraph_thread = AsyncMock()
    with (
        patch("app.gateway.routers.threads.get_paths", return_value=paths),
        patch(
            "app.gateway.routers.threads._ensure_langgraph_thread_exists",
            AsyncMock(),
        ),
        patch(
            "app.gateway.routers.threads._delete_langgraph_thread",
            delete_langgraph_thread,
        ),
        patch("app.gateway.routers.threads.uuid.uuid4", return_value=child_thread_id),
    ):
        with TestClient(app) as client:
            response = client.post(
                f"/api/threads/{parent_thread_id}/branches",
                json={"branch_name": "Side branch"},
            )

    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to create thread branch"
    assert asyncio.run(store.aget(threads.THREADS_NS, child_thread_id)) is None
    assert not paths.thread_dir(child_thread_id).exists()
    assert asyncio.run(checkpointer.aget_tuple({"configurable": {"thread_id": child_thread_id, "checkpoint_ns": ""}})) is None
    delete_langgraph_thread.assert_awaited_once_with(child_thread_id)


def test_create_thread_branch_rolls_back_partial_branch_on_copy_failure(tmp_path):
    paths = Paths(tmp_path)
    parent_thread_id = "parent-thread"
    child_thread_id = "child-thread"

    store = _DummyStore()
    checkpointer = _DummyCheckpointer()
    asyncio.run(
        checkpointer.aput(
            {"configurable": {"thread_id": parent_thread_id, "checkpoint_ns": ""}},
            {
                "v": 2,
                "id": "source",
                "ts": "2026-04-10T00:00:00Z",
                "channel_values": {"title": "Main thread"},
                "channel_versions": {},
                "versions_seen": {},
                "pending_sends": [],
                "updated_channels": None,
            },
            {"created_at": 1.0},
            {},
        )
    )

    app = FastAPI()
    app.include_router(threads.router)
    app.state.checkpointer = checkpointer
    app.state.store = store

    delete_langgraph_thread = AsyncMock()
    with (
        patch("app.gateway.routers.threads.get_paths", return_value=paths),
        patch(
            "app.gateway.routers.threads._ensure_langgraph_thread_exists",
            AsyncMock(),
        ),
        patch(
            "app.gateway.routers.threads._delete_langgraph_thread",
            delete_langgraph_thread,
        ),
        patch("app.gateway.routers.threads._copy_thread_branch_files", side_effect=RuntimeError("copy failed")),
        patch("app.gateway.routers.threads.uuid.uuid4", return_value=child_thread_id),
    ):
        with TestClient(app) as client:
            response = client.post(
                f"/api/threads/{parent_thread_id}/branches",
                json={"branch_name": "Side branch"},
            )

    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to create thread branch"
    assert asyncio.run(store.aget(threads.THREADS_NS, child_thread_id)) is None
    assert not paths.thread_dir(child_thread_id).exists()
    assert asyncio.run(checkpointer.aget_tuple({"configurable": {"thread_id": child_thread_id, "checkpoint_ns": ""}})) is None
    delete_langgraph_thread.assert_awaited_once_with(child_thread_id)


def test_create_thread_branch_rolls_back_partial_branch_on_store_failure(tmp_path):
    paths = Paths(tmp_path)
    parent_thread_id = "parent-thread"
    child_thread_id = "child-thread"
    paths.ensure_thread_dirs(parent_thread_id)

    store = _DummyStore()
    store.fail_keys.add(child_thread_id)
    checkpointer = _DummyCheckpointer()
    asyncio.run(
        checkpointer.aput(
            {"configurable": {"thread_id": parent_thread_id, "checkpoint_ns": ""}},
            {
                "v": 2,
                "id": "source",
                "ts": "2026-04-10T00:00:00Z",
                "channel_values": {"title": "Main thread"},
                "channel_versions": {},
                "versions_seen": {},
                "pending_sends": [],
                "updated_channels": None,
            },
            {"created_at": 1.0},
            {},
        )
    )

    app = FastAPI()
    app.include_router(threads.router)
    app.state.checkpointer = checkpointer
    app.state.store = store

    delete_langgraph_thread = AsyncMock()
    with (
        patch("app.gateway.routers.threads.get_paths", return_value=paths),
        patch(
            "app.gateway.routers.threads._ensure_langgraph_thread_exists",
            AsyncMock(),
        ),
        patch(
            "app.gateway.routers.threads._delete_langgraph_thread",
            delete_langgraph_thread,
        ),
        patch("app.gateway.routers.threads.uuid.uuid4", return_value=child_thread_id),
    ):
        with TestClient(app) as client:
            response = client.post(
                f"/api/threads/{parent_thread_id}/branches",
                json={"branch_name": "Side branch"},
            )

    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to create thread branch"
    assert asyncio.run(store.aget(threads.THREADS_NS, child_thread_id)) is None
    assert not paths.thread_dir(child_thread_id).exists()
    assert asyncio.run(checkpointer.aget_tuple({"configurable": {"thread_id": child_thread_id, "checkpoint_ns": ""}})) is None
    delete_langgraph_thread.assert_awaited_once_with(child_thread_id)
