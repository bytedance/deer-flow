import re
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from app.gateway.routers import threads
from deerflow.config.paths import Paths

_ISO_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def _build_thread_app() -> tuple[FastAPI, InMemoryStore, InMemorySaver]:
    """Build a FastAPI app wired with in-memory store + checkpointer.

    Returns the tuple ``(app, store, checkpointer)`` so tests can pre-seed
    legacy data or inspect post-condition state.
    """
    app = FastAPI()
    store = InMemoryStore()
    checkpointer = InMemorySaver()
    app.state.store = store
    app.state.checkpointer = checkpointer
    app.include_router(threads.router)
    return app, store, checkpointer


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
# ISO 8601 timestamp contract (issue #2594)
# ---------------------------------------------------------------------------
#
# Threads endpoints document ``created_at`` / ``updated_at`` as ISO
# timestamps and that is the format LangGraph Platform uses
# (``langgraph_sdk.schema.Thread.created_at: datetime`` JSON-encodes to
# ISO 8601). The tests below pin that contract end-to-end and also
# exercise the ``coerce_iso`` healing path for legacy unix-timestamp
# records written by older Gateway versions.


def test_create_thread_returns_iso_timestamps() -> None:
    app, _store, _checkpointer = _build_thread_app()

    with TestClient(app) as client:
        response = client.post("/api/threads", json={"metadata": {}})

    assert response.status_code == 200, response.text
    body = response.json()
    assert _ISO_TIMESTAMP_RE.match(body["created_at"]), body["created_at"]
    assert _ISO_TIMESTAMP_RE.match(body["updated_at"]), body["updated_at"]
    assert body["created_at"] == body["updated_at"]


def test_get_thread_returns_iso_for_legacy_unix_record() -> None:
    """A thread record written by older versions stores ``time.time()``
    floats as strings. ``get_thread`` must transparently surface them as
    ISO so the frontend's ``new Date(...)`` parser does not break.
    """
    app, store, checkpointer = _build_thread_app()

    legacy_thread_id = "legacy-thread"
    legacy_ts = "1777252410.411327"

    async def _seed() -> None:
        await store.aput(
            ("threads",),
            legacy_thread_id,
            {
                "thread_id": legacy_thread_id,
                "status": "idle",
                "created_at": legacy_ts,
                "updated_at": legacy_ts,
                "metadata": {},
            },
        )
        from langgraph.checkpoint.base import empty_checkpoint

        await checkpointer.aput(
            {"configurable": {"thread_id": legacy_thread_id, "checkpoint_ns": ""}},
            empty_checkpoint(),
            {"step": -1, "source": "input", "writes": None, "parents": {}},
            {},
        )

    import asyncio

    asyncio.run(_seed())

    with TestClient(app) as client:
        response = client.get(f"/api/threads/{legacy_thread_id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert _ISO_TIMESTAMP_RE.match(body["created_at"]), body["created_at"]
    assert _ISO_TIMESTAMP_RE.match(body["updated_at"]), body["updated_at"]


def test_patch_thread_returns_iso_and_advances_updated_at() -> None:
    app, store, _checkpointer = _build_thread_app()
    thread_id = "patch-target"

    legacy_created = "1777000000.000000"
    legacy_updated = "1777000000.000000"

    async def _seed() -> None:
        await store.aput(
            ("threads",),
            thread_id,
            {
                "thread_id": thread_id,
                "status": "idle",
                "created_at": legacy_created,
                "updated_at": legacy_updated,
                "metadata": {"k": "v0"},
            },
        )

    import asyncio

    asyncio.run(_seed())

    with TestClient(app) as client:
        response = client.patch(f"/api/threads/{thread_id}", json={"metadata": {"k": "v1"}})

    assert response.status_code == 200, response.text
    body = response.json()
    assert _ISO_TIMESTAMP_RE.match(body["created_at"]), body["created_at"]
    assert _ISO_TIMESTAMP_RE.match(body["updated_at"]), body["updated_at"]
    # Patch generates a fresh ``updated_at`` so it must be > the migrated
    # legacy ``created_at`` (both ISO strings sort lexicographically by
    # time when the format is consistent).
    assert body["updated_at"] > body["created_at"]
    assert body["metadata"] == {"k": "v1"}


def test_search_threads_normalizes_and_sorts_mixed_legacy_and_iso() -> None:
    """The store can hold a mix of legacy unix-timestamp strings (from
    older Gateway writes) and modern ISO strings. ``/search`` must
    normalize the wire format to ISO and the resulting list must be
    sorted by real time, not by lexical order of mixed formats.
    """
    app, store, _checkpointer = _build_thread_app()

    async def _seed() -> None:
        # Legacy unix-second string, year ~2026.
        await store.aput(
            ("threads",),
            "legacy",
            {
                "thread_id": "legacy",
                "status": "idle",
                "created_at": "1777000000.0",  # ~2026-04-23
                "updated_at": "1777000000.0",
                "metadata": {},
            },
        )
        # Modern ISO string, slightly later.
        await store.aput(
            ("threads",),
            "modern",
            {
                "thread_id": "modern",
                "status": "idle",
                "created_at": "2026-04-27T00:00:00+00:00",
                "updated_at": "2026-04-27T00:00:00+00:00",
                "metadata": {},
            },
        )

    import asyncio

    asyncio.run(_seed())

    with TestClient(app) as client:
        response = client.post("/api/threads/search", json={"limit": 10})

    assert response.status_code == 200, response.text
    items = response.json()
    assert {item["thread_id"] for item in items} == {"legacy", "modern"}
    for item in items:
        assert _ISO_TIMESTAMP_RE.match(item["created_at"]), item
        assert _ISO_TIMESTAMP_RE.match(item["updated_at"]), item
    # ``sort(... reverse=True)`` on consistently-ISO strings reflects
    # real time order: ``modern`` (2026-04-27) must precede ``legacy``
    # (2026-04-23).
    assert items[0]["thread_id"] == "modern"
    assert items[1]["thread_id"] == "legacy"


def test_store_upsert_writes_iso_and_heals_legacy_created_at() -> None:
    """Internal ``_store_upsert`` is the single write entrypoint for the
    thread store. Tests pin both the new-record path (writes ISO) and
    the update path (heals any pre-existing legacy ``created_at``).
    """
    import asyncio

    store = InMemoryStore()

    async def _scenario() -> tuple[dict, dict]:
        # New record path
        await threads._store_upsert(store, "fresh", metadata={"a": 1})
        new_record = (await store.aget(("threads",), "fresh")).value

        # Update path on a record with legacy timestamps
        await store.aput(
            ("threads",),
            "legacy",
            {
                "thread_id": "legacy",
                "status": "idle",
                "created_at": "1777000000.0",
                "updated_at": "1777000000.0",
                "metadata": {},
            },
        )
        await threads._store_upsert(store, "legacy", metadata={"b": 2})
        healed_record = (await store.aget(("threads",), "legacy")).value
        return new_record, healed_record

    new_record, healed_record = asyncio.run(_scenario())

    assert _ISO_TIMESTAMP_RE.match(new_record["created_at"]), new_record
    assert _ISO_TIMESTAMP_RE.match(new_record["updated_at"]), new_record
    assert _ISO_TIMESTAMP_RE.match(healed_record["created_at"]), healed_record
    assert _ISO_TIMESTAMP_RE.match(healed_record["updated_at"]), healed_record
