import re
from unittest.mock import patch

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from app.gateway.routers import threads
from deerflow.config.paths import Paths
from deerflow.persistence.thread_meta.memory import THREADS_NS, MemoryThreadMetaStore

_ISO_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


class _PermissiveThreadMetaStore(MemoryThreadMetaStore):
    """Memory store that skips user-id filtering for router tests.

    Owner isolation is exercised separately in
    ``test_memory_thread_meta_isolation.py``. Router tests need to drive
    the FastAPI surface end-to-end with a single fixed app user, but the
    stub auth middleware in ``_router_auth_helpers`` stamps a fresh UUID
    on every request, so the production filtering would reject every
    pre-seeded record. Bypass that filter so the test can focus on the
    timestamp wire format.
    """

    async def _get_owned_record(self, thread_id, user_id, method_name):  # type: ignore[override]
        item = await self._store.aget(THREADS_NS, thread_id)
        return dict(item.value) if item is not None else None

    async def check_access(self, thread_id, user_id, *, require_existing=False):  # type: ignore[override]
        item = await self._store.aget(THREADS_NS, thread_id)
        if item is None:
            return not require_existing
        return True

    async def create(self, thread_id, *, assistant_id=None, user_id=None, display_name=None, metadata=None):  # type: ignore[override]
        return await super().create(thread_id, assistant_id=assistant_id, user_id=None, display_name=display_name, metadata=metadata)

    async def search(self, *, metadata=None, status=None, limit=100, offset=0, user_id=None):  # type: ignore[override]
        return await super().search(metadata=metadata, status=status, limit=limit, offset=offset, user_id=None)


def _build_thread_app() -> tuple[FastAPI, InMemoryStore, InMemorySaver]:
    """Build a stub-authed FastAPI app wired with an in-memory ThreadMetaStore.

    The thread_store on ``app.state`` is a permissive subclass of
    ``MemoryThreadMetaStore`` so tests can drive ``/api/threads``
    end-to-end and pre-seed legacy records via the underlying BaseStore.

    Returns ``(app, store, checkpointer)`` for direct seeding/inspection.
    """
    app = make_authed_test_app()
    store = InMemoryStore()
    checkpointer = InMemorySaver()
    app.state.store = store
    app.state.checkpointer = checkpointer
    app.state.thread_store = _PermissiveThreadMetaStore(store)
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
    from deerflow.runtime.user_context import get_effective_user_id

    paths = Paths(tmp_path)
    user_id = get_effective_user_id()
    thread_dir = paths.thread_dir("thread-route", user_id=user_id)
    paths.sandbox_work_dir("thread-route", user_id=user_id).mkdir(parents=True, exist_ok=True)
    (paths.sandbox_work_dir("thread-route", user_id=user_id) / "notes.txt").write_text("hello", encoding="utf-8")

    app = make_authed_test_app()
    app.include_router(threads.router)

    with patch("app.gateway.routers.threads.get_paths", return_value=paths):
        with TestClient(app) as client:
            response = client.delete("/api/threads/thread-route")

    assert response.status_code == 200
    assert response.json() == {"success": True, "message": "Deleted local thread data for thread-route"}
    assert not thread_dir.exists()


def test_delete_thread_route_rejects_invalid_thread_id(tmp_path):
    paths = Paths(tmp_path)

    app = make_authed_test_app()
    app.include_router(threads.router)

    with patch("app.gateway.routers.threads.get_paths", return_value=paths):
        with TestClient(app) as client:
            response = client.delete("/api/threads/../escape")

    assert response.status_code == 404


def test_delete_thread_route_returns_422_for_route_safe_invalid_id(tmp_path):
    paths = Paths(tmp_path)

    app = make_authed_test_app()
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


# ── Server-reserved metadata key stripping ──────────────────────────────────


def test_strip_reserved_metadata_removes_user_id():
    """Client-supplied user_id is dropped to prevent reflection attacks."""
    out = threads._strip_reserved_metadata({"user_id": "victim-id", "title": "ok"})
    assert out == {"title": "ok"}


def test_strip_reserved_metadata_passes_through_safe_keys():
    """Non-reserved keys are preserved verbatim."""
    md = {"title": "ok", "tags": ["a", "b"], "custom": {"x": 1}}
    assert threads._strip_reserved_metadata(md) == md


def test_strip_reserved_metadata_empty_input():
    """Empty / None metadata returns same object — no crash."""
    assert threads._strip_reserved_metadata({}) == {}


def test_strip_reserved_metadata_strips_all_reserved_keys():
    out = threads._strip_reserved_metadata({"user_id": "x", "keep": "me"})
    assert out == {"keep": "me"}


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
    floats. ``get_thread`` must transparently surface them as ISO so the
    frontend's ``new Date(...)`` parser does not break.
    """
    app, store, checkpointer = _build_thread_app()

    legacy_thread_id = "legacy-thread"
    legacy_ts = "1777252410.411327"

    async def _seed() -> None:
        await store.aput(
            THREADS_NS,
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
            THREADS_NS,
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
    # Patch issues a fresh ``updated_at`` via ``MemoryThreadMetaStore.update_metadata``,
    # so it must be > the migrated legacy ``created_at`` (both ISO strings
    # sort lexicographically by time when the format is consistent).
    assert body["updated_at"] > body["created_at"]
    assert body["metadata"] == {"k": "v1"}


def test_search_threads_normalizes_legacy_unix_seconds_to_iso() -> None:
    """``MemoryThreadMetaStore`` may hold legacy ``time.time()`` floats
    written by older Gateway versions. ``/search`` must surface them as
    ISO via ``coerce_iso`` so the frontend's ``new Date(...)`` parser
    does not break.
    """
    app, store, _checkpointer = _build_thread_app()

    async def _seed() -> None:
        # Legacy unix-second float (the literal value from issue #2594).
        await store.aput(
            THREADS_NS,
            "legacy",
            {
                "thread_id": "legacy",
                "status": "idle",
                "created_at": 1777000000.0,
                "updated_at": 1777000000.0,
                "metadata": {},
            },
        )
        # Modern ISO string, slightly later.
        await store.aput(
            THREADS_NS,
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


def test_memory_thread_meta_store_writes_iso_on_create() -> None:
    """``MemoryThreadMetaStore.create`` must emit ISO so newly created
    threads serialize correctly without depending on the router's
    ``coerce_iso`` heal path.
    """
    import asyncio

    store = InMemoryStore()
    repo = MemoryThreadMetaStore(store)

    async def _scenario() -> dict:
        await repo.create("fresh", user_id=None, metadata={"a": 1})
        record = (await store.aget(THREADS_NS, "fresh")).value
        return record

    record = asyncio.run(_scenario())
    assert _ISO_TIMESTAMP_RE.match(record["created_at"]), record
    assert _ISO_TIMESTAMP_RE.match(record["updated_at"]), record


def test_get_thread_state_returns_iso_for_legacy_checkpoint_metadata() -> None:
    """Checkpoints written by older Gateway versions stored
    ``created_at`` as a unix-second float in their metadata. The
    ``/state`` endpoint must surface that value as ISO so the frontend's
    ``new Date(...)`` parser does not break — same root cause as the
    thread-record bug fixed in #2594, but on the checkpoint side.
    """
    app, _store, checkpointer = _build_thread_app()
    thread_id = "legacy-state"

    async def _seed() -> None:
        from langgraph.checkpoint.base import empty_checkpoint

        await checkpointer.aput(
            {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}},
            empty_checkpoint(),
            {"step": -1, "source": "input", "writes": None, "parents": {}, "created_at": 1777252410.411327},
            {},
        )

    import asyncio

    asyncio.run(_seed())

    with TestClient(app) as client:
        response = client.get(f"/api/threads/{thread_id}/state")

    assert response.status_code == 200, response.text
    body = response.json()
    assert _ISO_TIMESTAMP_RE.match(body["created_at"]), body["created_at"]
    assert _ISO_TIMESTAMP_RE.match(body["checkpoint"]["ts"]), body["checkpoint"]


def test_get_thread_history_returns_iso_for_legacy_checkpoint_metadata() -> None:
    """``/history`` walks ``checkpointer.alist`` and emits one entry per
    checkpoint. Each entry's ``created_at`` must come out as ISO even if
    older checkpoints stored a unix-second float in their metadata.
    """
    app, _store, checkpointer = _build_thread_app()
    thread_id = "legacy-history"

    async def _seed() -> None:
        from langgraph.checkpoint.base import empty_checkpoint

        await checkpointer.aput(
            {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}},
            empty_checkpoint(),
            {"step": -1, "source": "input", "writes": None, "parents": {}, "created_at": 1777252410.411327},
            {},
        )

    import asyncio

    asyncio.run(_seed())

    with TestClient(app) as client:
        response = client.post(f"/api/threads/{thread_id}/history", json={"limit": 10})

    assert response.status_code == 200, response.text
    entries = response.json()
    assert entries, "expected at least one history entry"
    for entry in entries:
        assert _ISO_TIMESTAMP_RE.match(entry["created_at"]), entry
