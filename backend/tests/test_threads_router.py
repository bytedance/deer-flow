import asyncio
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.base import empty_checkpoint, uuid6
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Overwrite

from app.gateway import services as gateway_services
from app.gateway.routers import thread_runs, threads
from deerflow.config.paths import Paths
from deerflow.persistence.thread_meta import InvalidMetadataFilterError
from deerflow.persistence.thread_meta.memory import THREADS_NS, MemoryThreadMetaStore
from deerflow.runtime.checkpoint_state import CheckpointStateAccessor

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


class _RawStateAccessor:
    def __init__(self, checkpointer: InMemorySaver):
        self.checkpointer = checkpointer

    @staticmethod
    def _snapshot(checkpoint_tuple, fallback_config):
        if checkpoint_tuple is None:
            return SimpleNamespace(
                values={},
                config=fallback_config,
                parent_config=None,
                metadata={},
                next=(),
                tasks=(),
                created_at=None,
            )
        checkpoint = checkpoint_tuple.checkpoint or {}
        metadata = checkpoint_tuple.metadata or {}
        return SimpleNamespace(
            values=dict(checkpoint.get("channel_values", {})),
            config=checkpoint_tuple.config,
            parent_config=checkpoint_tuple.parent_config,
            metadata=metadata,
            next=(),
            tasks=(),
            created_at=checkpoint.get("ts") or metadata.get("created_at"),
        )

    async def aget(self, config):
        checkpoint_tuple = await self.checkpointer.aget_tuple(config)
        return self._snapshot(checkpoint_tuple, config)

    async def ahistory(self, config, *, limit=None):
        snapshots = []
        async for checkpoint_tuple in self.checkpointer.alist(config, limit=limit):
            snapshots.append(self._snapshot(checkpoint_tuple, config))
        return snapshots

    async def aupdate(self, config, values, *, as_node=None):
        checkpoint_tuple = await self.checkpointer.aget_tuple(config)
        checkpoint = dict(checkpoint_tuple.checkpoint if checkpoint_tuple is not None else empty_checkpoint())
        channel_values = dict(checkpoint.get("channel_values", {}))
        channel_values.update({key: value.value if isinstance(value, Overwrite) else value for key, value in values.items()})
        checkpoint["channel_values"] = channel_values
        channel_versions = dict(checkpoint.get("channel_versions", {}))
        new_versions = {}
        for key in values:
            current_version = channel_versions.get(key)
            next_version = current_version + 1 if isinstance(current_version, int) else 1
            channel_versions[key] = next_version
            new_versions[key] = next_version
        checkpoint["channel_versions"] = channel_versions
        checkpoint["id"] = str(uuid6())
        metadata = dict(checkpoint_tuple.metadata if checkpoint_tuple is not None else {})
        metadata.update(
            {
                "source": "update",
                "step": metadata.get("step", -1) + 1,
                "writes": {as_node: values},
            }
        )
        write_config = {
            "configurable": {
                "thread_id": config["configurable"]["thread_id"],
                "checkpoint_ns": config["configurable"].get("checkpoint_ns", ""),
            }
        }
        return await self.checkpointer.aput(write_config, checkpoint, metadata, new_versions)


@pytest.fixture(autouse=True)
def _patch_checkpoint_state_builder(monkeypatch):
    def _builder(request, *, thread_id, assistant_id=None, checkpoint_id=None):
        config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
        if checkpoint_id is not None:
            config["configurable"]["checkpoint_id"] = checkpoint_id
        return _RawStateAccessor(request.app.state.checkpointer), config

    def _mutation_builder(request, *, thread_id, as_node, checkpoint_id=None, state_schema=None):
        config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
        if checkpoint_id is not None:
            config["configurable"]["checkpoint_id"] = checkpoint_id
        return _RawStateAccessor(request.app.state.checkpointer), config

    async def _read_boundary(request, *, thread_id, checkpoint_id=None):
        return _builder(request, thread_id=thread_id, checkpoint_id=checkpoint_id)

    async def _mutation_boundary(request, *, thread_id, as_node, checkpoint_id=None):
        return _mutation_builder(request, thread_id=thread_id, as_node=as_node, checkpoint_id=checkpoint_id)

    monkeypatch.setattr(threads, "build_checkpoint_state_accessor", _builder)
    monkeypatch.setattr(threads, "build_checkpoint_state_mutation_accessor", _mutation_builder)
    monkeypatch.setattr(threads, "build_thread_checkpoint_state_accessor", _read_boundary)
    monkeypatch.setattr(threads, "build_thread_checkpoint_state_mutation_accessor", _mutation_boundary)
    monkeypatch.setattr(thread_runs, "build_thread_checkpoint_state_accessor", _read_boundary)


class _FakeStateAccessor:
    def __init__(self, snapshot: SimpleNamespace):
        self.snapshot = snapshot

    async def aget(self, config):
        return self.snapshot

    async def ahistory(self, config, *, limit=None):
        return [self.snapshot][:limit]


def _materialized_snapshot() -> SimpleNamespace:
    return SimpleNamespace(
        values={
            "messages": [
                HumanMessage(id="h1", content="question"),
                AIMessage(id="a1", content="answer"),
            ]
        },
        config={
            "configurable": {
                "thread_id": "thread-1",
                "checkpoint_ns": "",
                "checkpoint_id": "ckpt-2",
            }
        },
        parent_config={"configurable": {"checkpoint_id": "ckpt-1"}},
        metadata={"step": 2},
        next=(),
        tasks=(),
        created_at=None,
    )


async def _write_checkpoint(
    checkpointer: InMemorySaver,
    thread_id: str,
    checkpoint_id: str,
    messages: list[object],
    *,
    step: int,
    metadata: dict | None = None,
    parent_config: dict | None = None,
) -> dict:
    checkpoint = empty_checkpoint()
    checkpoint["id"] = checkpoint_id
    checkpoint["channel_values"] = {"messages": messages}
    checkpoint["channel_versions"] = {"messages": step}
    checkpoint_metadata = {
        "step": step,
        "source": "loop",
        "writes": {"test": {"messages": messages}},
        "parents": {},
        "created_at": f"2026-07-05T00:00:0{step}+00:00",
    }
    checkpoint_metadata.update(metadata or {})
    return await checkpointer.aput(
        parent_config or {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}},
        checkpoint,
        checkpoint_metadata,
        {"messages": step},
    )


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


def test_delete_thread_route_closes_browser_session(tmp_path):
    """Deleting a thread tears down its live browser session so a later caller
    who reuses the id cannot inherit the retained page/cookies."""
    paths = Paths(tmp_path)

    app = make_authed_test_app()
    app.include_router(threads.router)

    manager = SimpleNamespace(close_session=AsyncMock(return_value=True))
    with (
        patch("app.gateway.routers.threads.get_paths", return_value=paths),
        patch(
            "deerflow.community.browser_automation.get_browser_session_manager",
            return_value=manager,
        ),
    ):
        with TestClient(app) as client:
            response = client.delete("/api/threads/thread-browser")

    assert response.status_code == 200
    manager.close_session.assert_awaited_once_with("thread-browser")


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


def test_create_thread_returns_existing_when_insert_loses_race() -> None:
    """A concurrent create that loses the INSERT race stays idempotent.

    The idempotency ``get`` check and the ``create`` INSERT are not atomic:
    a competing request for the same ``thread_id`` can commit in between, and
    the SQL-backed store then rejects ours on the duplicate primary key. The
    endpoint documents idempotency ("returns the existing record when
    ``thread_id`` already exists"), so it must surface the now-present row
    rather than turning the integrity error into an HTTP 500.
    """
    from sqlalchemy.exc import IntegrityError

    app, store, _checkpointer = _build_thread_app()

    class _RacingThreadMetaStore(_PermissiveThreadMetaStore):
        """First create loses the race: the row is committed by a competing
        request, then our INSERT fails with an integrity violation."""

        def __init__(self, backing):
            super().__init__(backing)
            self._raised = False

        async def create(self, thread_id, *, assistant_id=None, user_id=None, display_name=None, metadata=None):  # type: ignore[override]
            if not self._raised:
                self._raised = True
                await super().create(
                    thread_id,
                    assistant_id=assistant_id,
                    user_id=user_id,
                    display_name=display_name,
                    metadata=metadata,
                )
                raise IntegrityError(
                    "INSERT INTO threads_meta",
                    {},
                    Exception("UNIQUE constraint failed: threads_meta.thread_id"),
                )
            return await super().create(
                thread_id,
                assistant_id=assistant_id,
                user_id=user_id,
                display_name=display_name,
                metadata=metadata,
            )

    app.state.thread_store = _RacingThreadMetaStore(store)

    with TestClient(app) as client:
        response = client.post(
            "/api/threads",
            json={"thread_id": "race-thread", "metadata": {"k": "v"}},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["thread_id"] == "race-thread"
    assert body["metadata"] == {"k": "v"}


def test_insert_race_recovery_claims_unscoped_row_for_trusted_owner() -> None:
    """The insert-race recovery mirrors the fast path's owner reconciliation.

    When a competing request commits a legacy unscoped (``user_id=None``) row
    between our idempotency read and our insert, and our insert then loses the
    duplicate-key race, a trusted internal owner must still claim the row rather
    than return it unowned — otherwise ownership of the same thread would depend
    on whether the fast path or the recovery path resolved it.
    """
    import asyncio

    from sqlalchemy.exc import IntegrityError

    from app.gateway.internal_auth import INTERNAL_OWNER_USER_ID_HEADER_NAME, INTERNAL_SYSTEM_ROLE

    store = InMemoryStore()
    checkpointer = InMemorySaver()

    class _RacingOwnerStore(MemoryThreadMetaStore):
        """Our insert loses to a competing create that already wrote an
        unscoped row, exactly the interleaving the recovery path exists for."""

        async def create(self, thread_id, *, assistant_id=None, user_id=None, display_name=None, metadata=None):  # type: ignore[override]
            # The competing request commits its (owner-less) row here, then our
            # insert loses the primary-key race.
            await super().create(thread_id, user_id=None, metadata=metadata)
            raise IntegrityError(
                "INSERT INTO threads_meta",
                {},
                Exception("UNIQUE constraint failed: threads_meta.thread_id"),
            )

    thread_store = _RacingOwnerStore(store)
    request = SimpleNamespace(
        headers={INTERNAL_OWNER_USER_ID_HEADER_NAME: "owner-1"},
        state=SimpleNamespace(user=SimpleNamespace(id="default", system_role=INTERNAL_SYSTEM_ROLE)),
        app=SimpleNamespace(state=SimpleNamespace(checkpointer=checkpointer, thread_store=thread_store)),
    )

    async def _scenario():
        response = await threads.create_thread(
            threads.ThreadCreateRequest(thread_id="channel-thread", metadata={"k": "v"}),
            request,
        )
        owner_row = await thread_store.get("channel-thread", user_id="owner-1")
        unscoped_lookup = await thread_store.get("channel-thread", user_id=None)
        return response, owner_row, unscoped_lookup

    response, owner_row, unscoped_lookup = asyncio.run(_scenario())

    assert response.thread_id == "channel-thread"
    # Recovery claimed the legacy row for the trusted owner, same as the fast path.
    assert owner_row is not None
    assert owner_row["user_id"] == "owner-1"
    assert unscoped_lookup["user_id"] == "owner-1"


def test_create_thread_does_not_swallow_non_integrity_errors() -> None:
    """A non-race insert failure must surface as 500, even when a row now exists.

    The recovery path only rescues the duplicate-key ``IntegrityError`` race; an
    arbitrary failure that happens to coincide with an existing row must not be
    silently returned as a 200 (previously the broad ``except`` did exactly that).
    """
    app, store, _checkpointer = _build_thread_app()

    class _BrokenAfterWriteStore(_PermissiveThreadMetaStore):
        async def create(self, thread_id, *, assistant_id=None, user_id=None, display_name=None, metadata=None):  # type: ignore[override]
            # A row exists after this call, but the insert failed for a reason
            # unrelated to the idempotency race.
            await super().create(thread_id, metadata=metadata)
            raise RuntimeError("unexpected store failure")

    app.state.thread_store = _BrokenAfterWriteStore(store)

    with TestClient(app) as client:
        response = client.post("/api/threads", json={"thread_id": "broken-thread", "metadata": {}})

    assert response.status_code == 500, response.text


def test_put_goal_creates_missing_thread_checkpoint_and_returns_goal() -> None:
    app, _store, _checkpointer = _build_thread_app()

    with TestClient(app) as client:
        response = client.put(
            "/api/threads/goal-thread/goal",
            json={"objective": "Finish the feature and make all tests pass"},
        )
        state_response = client.get("/api/threads/goal-thread/state")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["goal"]["objective"] == "Finish the feature and make all tests pass"
    assert body["goal"]["status"] == "active"
    assert body["goal"]["continuation_count"] == 0
    assert body["goal"]["max_continuations"] == 8
    assert state_response.status_code == 200, state_response.text
    assert state_response.json()["values"]["goal"]["objective"] == "Finish the feature and make all tests pass"


def test_goal_status_and_clear_round_trip() -> None:
    app, _store, _checkpointer = _build_thread_app()

    with TestClient(app) as client:
        set_response = client.put(
            "/api/threads/goal-thread/goal",
            json={"objective": "Ship it", "max_continuations": 3},
        )
        get_response = client.get("/api/threads/goal-thread/goal")
        clear_response = client.delete("/api/threads/goal-thread/goal")
        after_clear_response = client.get("/api/threads/goal-thread/goal")
        state_response = client.get("/api/threads/goal-thread/state")

    assert set_response.status_code == 200, set_response.text
    assert get_response.status_code == 200, get_response.text
    assert get_response.json()["goal"]["objective"] == "Ship it"
    assert get_response.json()["goal"]["max_continuations"] == 3
    assert clear_response.status_code == 200, clear_response.text
    assert clear_response.json()["goal"] is None
    assert after_clear_response.status_code == 200, after_clear_response.text
    assert after_clear_response.json()["goal"] is None
    assert "goal" not in state_response.json()["values"]


def test_internal_owner_header_assigns_thread_to_owner() -> None:
    import asyncio

    from app.gateway.internal_auth import INTERNAL_OWNER_USER_ID_HEADER_NAME, INTERNAL_SYSTEM_ROLE

    store = InMemoryStore()
    checkpointer = InMemorySaver()
    thread_store = MemoryThreadMetaStore(store)
    request = SimpleNamespace(
        headers={INTERNAL_OWNER_USER_ID_HEADER_NAME: "owner-1"},
        state=SimpleNamespace(user=SimpleNamespace(id="default", system_role=INTERNAL_SYSTEM_ROLE)),
        app=SimpleNamespace(state=SimpleNamespace(checkpointer=checkpointer, thread_store=thread_store)),
    )

    async def _scenario():
        response = await threads.create_thread(
            threads.ThreadCreateRequest(thread_id="channel-thread", metadata={}),
            request,
        )
        owner_row = await thread_store.get("channel-thread", user_id="owner-1")
        internal_row = await thread_store.get("channel-thread", user_id="default")
        return response, owner_row, internal_row

    response, owner_row, internal_row = asyncio.run(_scenario())

    assert response.thread_id == "channel-thread"
    assert owner_row is not None
    assert owner_row["user_id"] == "owner-1"
    assert internal_row is None


def test_goal_thread_creation_uses_internal_owner_header() -> None:
    import asyncio

    from app.gateway.internal_auth import INTERNAL_OWNER_USER_ID_HEADER_NAME, INTERNAL_SYSTEM_ROLE

    store = InMemoryStore()
    checkpointer = InMemorySaver()
    thread_store = MemoryThreadMetaStore(store)
    request = SimpleNamespace(
        headers={INTERNAL_OWNER_USER_ID_HEADER_NAME: "owner-1"},
        state=SimpleNamespace(user=SimpleNamespace(id="default", system_role=INTERNAL_SYSTEM_ROLE)),
        app=SimpleNamespace(state=SimpleNamespace(checkpointer=checkpointer, thread_store=thread_store)),
    )

    async def _scenario():
        await threads._ensure_thread_for_goal("channel-goal-thread", request)
        owner_row = await thread_store.get("channel-goal-thread", user_id="owner-1")
        internal_row = await thread_store.get("channel-goal-thread", user_id="default")
        owner_threads = await thread_store.search(user_id="owner-1")
        return owner_row, internal_row, owner_threads

    owner_row, internal_row, owner_threads = asyncio.run(_scenario())

    assert owner_row is not None
    assert owner_row["user_id"] == "owner-1"
    assert internal_row is None
    assert [thread["thread_id"] for thread in owner_threads] == ["channel-goal-thread"]


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


def test_latest_thread_readers_use_materialized_snapshot_values() -> None:
    app, store, checkpointer = _build_thread_app()
    thread_id = "thread-1"

    async def _seed() -> None:
        await store.aput(
            THREADS_NS,
            thread_id,
            {
                "thread_id": thread_id,
                "status": "idle",
                "created_at": "2026-07-18T00:00:00+00:00",
                "updated_at": "2026-07-18T00:00:00+00:00",
                "metadata": {},
            },
        )
        await checkpointer.aput(
            {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}},
            empty_checkpoint(),
            {"step": 2, "source": "loop", "writes": {}, "parents": {}},
            {},
        )

    asyncio.run(_seed())
    accessor = _FakeStateAccessor(_materialized_snapshot())
    thread_accessor = AsyncMock(return_value=(accessor, {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}))

    with (
        patch(
            "app.gateway.routers.threads.build_checkpoint_state_accessor",
            create=True,
            return_value=(accessor, {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}),
        ),
        patch(
            "app.gateway.routers.threads.build_thread_checkpoint_state_accessor",
            new=thread_accessor,
        ),
        TestClient(app) as client,
    ):
        thread_response = client.get(f"/api/threads/{thread_id}")
        state_response = client.get(f"/api/threads/{thread_id}/state")
        history_response = client.post(f"/api/threads/{thread_id}/history", json={"limit": 10})

    assert thread_response.status_code == 200, thread_response.text
    assert state_response.status_code == 200, state_response.text
    assert history_response.status_code == 200, history_response.text
    assert [message["id"] for message in thread_response.json()["values"]["messages"]] == ["h1", "a1"]
    assert [message["id"] for message in state_response.json()["values"]["messages"]] == ["h1", "a1"]
    assert [message["id"] for message in history_response.json()[0]["values"]["messages"]] == ["h1", "a1"]
    assert [call.kwargs["thread_id"] for call in thread_accessor.await_args_list] == [thread_id, thread_id]


def test_get_thread_status_uses_raw_pending_writes_for_materialized_checkpoint() -> None:
    app, store, _checkpointer = _build_thread_app()
    thread_id = "thread-1"

    async def _seed() -> None:
        await store.aput(
            THREADS_NS,
            thread_id,
            {
                "thread_id": thread_id,
                "status": "idle",
                "created_at": "2026-07-18T00:00:00+00:00",
                "updated_at": "2026-07-18T00:00:00+00:00",
                "metadata": {},
            },
        )

    asyncio.run(_seed())
    requested_configs = []

    class _AdvancingCheckpointer:
        async def aget_tuple(self, config):
            requested_configs.append(config)
            checkpoint_id = config.get("configurable", {}).get("checkpoint_id")
            return SimpleNamespace(
                pending_writes=[] if checkpoint_id == "ckpt-2" else [("task-old", "__error__", "stale")],
            )

    app.state.checkpointer = _AdvancingCheckpointer()
    snapshot = _materialized_snapshot()
    accessor = _FakeStateAccessor(snapshot)

    with (
        patch(
            "app.gateway.routers.threads.build_checkpoint_state_accessor",
            return_value=(accessor, {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}),
        ),
        TestClient(app) as client,
    ):
        response = client.get(f"/api/threads/{thread_id}")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "idle"
    assert requested_configs == [snapshot.config]


@pytest.mark.parametrize("stored_status", ["running", "error"])
def test_get_thread_preserves_metadata_status_without_checkpoint(stored_status: str) -> None:
    app, store, _checkpointer = _build_thread_app()
    thread_id = "thread-without-checkpoint"

    async def _seed() -> None:
        await store.aput(
            THREADS_NS,
            thread_id,
            {
                "thread_id": thread_id,
                "status": stored_status,
                "created_at": "2026-07-18T00:00:00+00:00",
                "updated_at": "2026-07-18T00:00:00+00:00",
                "metadata": {},
            },
        )

    asyncio.run(_seed())
    snapshot = SimpleNamespace(
        values={},
        config={"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}},
        parent_config=None,
        metadata={},
        next=(),
        tasks=(),
        created_at=None,
    )
    accessor = _FakeStateAccessor(snapshot)

    with (
        patch(
            "app.gateway.routers.threads.build_checkpoint_state_accessor",
            return_value=(accessor, snapshot.config),
        ),
        TestClient(app) as client,
    ):
        response = client.get(f"/api/threads/{thread_id}")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == stored_status


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


def test_get_thread_history_associates_tool_messages_from_checkpoint_turn() -> None:
    app, _store, checkpointer = _build_thread_app()
    thread_id = "history-tool-run"
    messages = [
        HumanMessage(id="human-1", content="Use a tool", additional_kwargs={"run_id": "run-1"}),
        AIMessage(
            id="ai-1",
            content="Calling tool",
            tool_calls=[{"name": "lookup", "args": {}, "id": "call-1"}],
        ),
        ToolMessage(id="tool-1", content="result", tool_call_id="call-1"),
        AIMessage(id="ai-2", content="Done"),
    ]

    asyncio.run(
        _write_checkpoint(
            checkpointer,
            thread_id,
            "checkpoint-tool-run",
            messages,
            step=1,
            metadata={"run_durations": {"run-1": 4}},
        )
    )

    with TestClient(app) as client:
        response = client.post(f"/api/threads/{thread_id}/history", json={"limit": 10})

    assert response.status_code == 200, response.text
    history_messages = response.json()[0]["values"]["messages"]
    assert [message.get("run_id") for message in history_messages[1:]] == ["run-1", "run-1", "run-1"]

    assert [message["additional_kwargs"]["turn_duration"] for message in history_messages if message["type"] == "ai"] == [4, 4]


def test_get_thread_history_backfills_legacy_durations_with_exact_event_run_id() -> None:
    app, _store, checkpointer = _build_thread_app()
    thread_id = "legacy-history-run-id"
    messages = [
        HumanMessage(id="human-1", content="Question", additional_kwargs={"run_id": "boundary-run"}),
        AIMessage(id="ai-1", content="Answer"),
        ToolMessage(id="tool-1", content="result", tool_call_id="call-1"),
    ]
    asyncio.run(_write_checkpoint(checkpointer, thread_id, "00000000-0000-6000-8000-000000000001", messages, step=1))

    async def list_by_thread(_: str) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                run_id="boundary-run",
                created_at="2026-07-05T00:00:00+00:00",
                updated_at="2026-07-05T00:00:03+00:00",
            ),
            SimpleNamespace(
                run_id="exact-run",
                created_at="2026-07-05T00:00:00+00:00",
                updated_at="2026-07-05T00:00:07+00:00",
            ),
        ]

    async def list_messages(_: str, *, limit: int) -> list[dict]:
        assert limit == 1000
        return [{"content": {"type": "ai", "id": "ai-1"}, "run_id": "exact-run"}]

    app.state.run_manager = SimpleNamespace(list_by_thread=list_by_thread)
    app.state.run_event_store = SimpleNamespace(list_messages=list_messages)

    with TestClient(app) as client:
        response = client.post(f"/api/threads/{thread_id}/history", json={"limit": 10})

    assert response.status_code == 200, response.text
    entry = response.json()[0]
    history_messages = entry["values"]["messages"]
    assert history_messages[1]["run_id"] == "exact-run"
    assert history_messages[1]["additional_kwargs"]["turn_duration"] == 7
    assert history_messages[2]["run_id"] == "boundary-run"
    assert "run_durations" not in entry["metadata"]

    latest = asyncio.run(checkpointer.aget_tuple({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}))
    assert latest is not None
    assert latest.metadata["run_durations"] == {"boundary-run": 3, "exact-run": 7}


def test_ai_message_lacks_duration_only_for_unannotated_ai_messages() -> None:
    assert threads._ai_message_lacks_duration({"type": "ai"})
    assert threads._ai_message_lacks_duration({"type": "ai", "additional_kwargs": []})
    assert not threads._ai_message_lacks_duration({"type": "tool"})
    assert not threads._ai_message_lacks_duration({"type": "ai", "additional_kwargs": {"turn_duration": 0}})


# ── branch threads from completed assistant turns ─────────────────────────────


def test_branch_thread_can_prepare_regenerate_without_branch_run_events() -> None:
    app, _store, checkpointer = _build_thread_app()
    app.include_router(thread_runs.router)
    source_thread_id = "source-regenerate"
    source_run_id = "source-run"

    async def list_messages(_thread_id: str, *, limit: int, **_kwargs) -> list[dict]:
        assert limit == thread_runs.REGENERATE_HISTORY_SCAN_LIMIT
        return []

    async def list_by_thread(_thread_id: str, *, user_id=None, limit: int = 100) -> list:
        return []

    app.state.run_event_store = SimpleNamespace(list_messages=list_messages)
    app.state.run_manager = SimpleNamespace(list_by_thread=list_by_thread)

    human = HumanMessage(id="human-1", content="Question", additional_kwargs={"run_id": source_run_id})
    ai = AIMessage(id="ai-1", content="Answer")

    with TestClient(app) as client:
        created = client.post("/api/threads", json={"thread_id": source_thread_id, "metadata": {}})
        assert created.status_code == 200, created.text

        initial = asyncio.run(checkpointer.aget_tuple({"configurable": {"thread_id": source_thread_id, "checkpoint_ns": ""}}))
        assert initial is not None
        after_human = asyncio.run(
            _write_checkpoint(
                checkpointer,
                source_thread_id,
                str(uuid6()),
                [human],
                step=1,
                parent_config=initial.config,
            )
        )
        asyncio.run(
            _write_checkpoint(
                checkpointer,
                source_thread_id,
                str(uuid6()),
                [human, ai],
                step=2,
                parent_config=after_human,
            )
        )

        branch_response = client.post(
            f"/api/threads/{source_thread_id}/branches",
            json={"message_id": "ai-1", "message_ids": ["ai-1"]},
        )
        assert branch_response.status_code == 200, branch_response.text
        branch_thread_id = branch_response.json()["thread_id"]

        prepare_response = client.post(
            f"/api/threads/{branch_thread_id}/runs/regenerate/prepare",
            json={"message_id": "ai-1"},
        )

    assert prepare_response.status_code == 200, prepare_response.text
    prepared = prepare_response.json()
    assert prepared["target_run_id"] == source_run_id
    branch_base_id = prepared["checkpoint"]["checkpoint_id"]
    assert prepared["input"]["messages"][0]["id"] == "human-1"
    assert prepared["input"]["messages"][0]["content"] == [{"type": "text", "text": "Question"}]

    branch_base = asyncio.run(
        checkpointer.aget_tuple(
            {
                "configurable": {
                    "thread_id": branch_thread_id,
                    "checkpoint_ns": "",
                    "checkpoint_id": branch_base_id,
                }
            }
        )
    )
    assert branch_base is not None
    assert branch_base.checkpoint.get("channel_values", {}).get("messages", []) == []


def test_branch_thread_from_older_assistant_turn_creates_truncated_thread() -> None:
    app, store, checkpointer = _build_thread_app()
    source_thread_id = "source-thread"

    human_1 = HumanMessage(id="human-1", content="First question")
    ai_1 = AIMessage(id="ai-1", content="First answer")
    human_2 = HumanMessage(id="human-2", content="Second question")
    ai_2 = AIMessage(id="ai-2", content="Second answer")
    human_3 = HumanMessage(id="human-3", content="Third question")
    ai_3 = AIMessage(id="ai-3", content="Third answer")

    async def _seed(parent_config: dict) -> dict:
        after_human_1 = await _write_checkpoint(checkpointer, source_thread_id, str(uuid6()), [human_1], step=1, parent_config=parent_config)
        after_ai_1 = await _write_checkpoint(checkpointer, source_thread_id, str(uuid6()), [human_1, ai_1], step=2, parent_config=after_human_1)
        after_human_2 = await _write_checkpoint(
            checkpointer,
            source_thread_id,
            str(uuid6()),
            [human_1, ai_1, human_2],
            step=3,
            parent_config=after_ai_1,
        )
        after_ai_2 = await _write_checkpoint(
            checkpointer,
            source_thread_id,
            str(uuid6()),
            [human_1, ai_1, human_2, ai_2],
            step=4,
            parent_config=after_human_2,
        )
        after_human_3 = await _write_checkpoint(
            checkpointer,
            source_thread_id,
            str(uuid6()),
            [human_1, ai_1, human_2, ai_2, human_3],
            step=5,
            parent_config=after_ai_2,
        )
        await _write_checkpoint(
            checkpointer,
            source_thread_id,
            str(uuid6()),
            [human_1, ai_1, human_2, ai_2, human_3, ai_3],
            step=6,
            parent_config=after_human_3,
        )
        return after_ai_2

    with TestClient(app) as client:
        created = client.post("/api/threads", json={"thread_id": source_thread_id, "metadata": {}, "assistant_id": "agent"})
        assert created.status_code == 200, created.text
        initial = asyncio.run(checkpointer.aget_tuple({"configurable": {"thread_id": source_thread_id, "checkpoint_ns": ""}}))
        assert initial is not None
        target_checkpoint_config = asyncio.run(_seed(initial.config))
        asyncio.run(
            store.aput(
                THREADS_NS,
                source_thread_id,
                {
                    "thread_id": source_thread_id,
                    "assistant_id": "agent",
                    "user_id": None,
                    "status": "idle",
                    "created_at": "2026-07-05T00:00:00Z",
                    "updated_at": "2026-07-05T00:00:00Z",
                    "display_name": "Original chat",
                    "metadata": {},
                },
            )
        )

        response = client.post(
            f"/api/threads/{source_thread_id}/branches",
            json={"message_id": "ai-2", "message_ids": ["ai-2"]},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        new_thread_id = body["thread_id"]
        state_response = client.get(f"/api/threads/{new_thread_id}/state")
        search_response = client.post("/api/threads/search", json={"limit": 10})

    assert body["parent_thread_id"] == source_thread_id
    assert body["parent_checkpoint_id"] == target_checkpoint_config["configurable"]["checkpoint_id"]
    assert body["branched_from_message_id"] == "ai-2"
    assert body["workspace_clone_mode"] == "skipped_historical_turn"

    assert state_response.status_code == 200, state_response.text
    messages = state_response.json()["values"]["messages"]
    assert [message["id"] for message in messages] == ["human-1", "ai-1", "human-2", "ai-2"]
    assert "Third answer" not in [message.get("content") for message in messages]
    assert search_response.status_code == 200, search_response.text
    branch_entry = next(item for item in search_response.json() if item["thread_id"] == new_thread_id)
    assert branch_entry["values"]["title"] == "Original chat"


def test_branch_thread_uses_materialized_history_and_overwrites_fresh_seed(monkeypatch) -> None:
    app, _store, _checkpointer = _build_thread_app()
    source_thread_id = "source-materialized"
    messages = [
        HumanMessage(id="h1", content="First question"),
        AIMessage(id="a1", content="First answer"),
        HumanMessage(id="h2", content="Second question"),
        AIMessage(id="a2", content="Second answer"),
    ]

    def snapshot(checkpoint_id: str, materialized_messages: list[object], *, parent_id: str | None = None) -> SimpleNamespace:
        return SimpleNamespace(
            values={"messages": materialized_messages, "title": "Materialized title"},
            config={
                "configurable": {
                    "thread_id": source_thread_id,
                    "checkpoint_ns": "",
                    "checkpoint_id": checkpoint_id,
                }
            },
            metadata={"step": int(checkpoint_id[-1])},
            parent_config=(
                {
                    "configurable": {
                        "thread_id": source_thread_id,
                        "checkpoint_ns": "",
                        "checkpoint_id": parent_id,
                    }
                }
                if parent_id is not None
                else None
            ),
        )

    source_accessor = SimpleNamespace()
    source_history = [
        snapshot("ckpt-2", messages, parent_id="ckpt-1"),
        snapshot("ckpt-1", messages[:2], parent_id="ckpt-0"),
        snapshot("ckpt-0", []),
    ]
    branch_updates: list[tuple[dict, dict, str | None]] = []

    async def source_ahistory(config, *, limit=None):
        assert config["configurable"]["thread_id"] == source_thread_id
        assert limit == threads._BRANCH_HISTORY_RAW_SCAN_LIMIT
        return source_history

    async def source_aget(config):
        checkpoint_id = config["configurable"]["checkpoint_id"]
        return next(item for item in source_history if item.config["configurable"]["checkpoint_id"] == checkpoint_id)

    async def branch_aupdate(config, values, *, as_node=None):
        branch_updates.append((config, values, as_node))
        return {
            "configurable": {
                "thread_id": config["configurable"]["thread_id"],
                "checkpoint_ns": "",
                "checkpoint_id": f"branch-{len(branch_updates)}",
            }
        }

    source_accessor.ahistory = source_ahistory
    source_accessor.aget = source_aget
    branch_accessor = SimpleNamespace(aupdate=branch_aupdate)

    def build_accessor(_request, *, thread_id, assistant_id=None, checkpoint_id=None):
        assert thread_id == source_thread_id
        return source_accessor, {
            "configurable": {
                "thread_id": source_thread_id,
                "checkpoint_ns": "",
            }
        }

    def build_mutation_accessor(_request, *, thread_id, as_node, checkpoint_id=None, state_schema=None):
        return branch_accessor, {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": "",
            }
        }

    monkeypatch.setattr(threads, "build_checkpoint_state_accessor", build_accessor)
    monkeypatch.setattr(threads, "build_checkpoint_state_mutation_accessor", build_mutation_accessor)

    with TestClient(app) as client:
        created = client.post(
            "/api/threads",
            json={"thread_id": source_thread_id, "metadata": {}, "assistant_id": "agent"},
        )
        assert created.status_code == 200, created.text
        response = client.post(
            f"/api/threads/{source_thread_id}/branches",
            json={"message_id": "a1", "message_ids": ["a1"]},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["parent_checkpoint_id"] == "ckpt-1"
    assert len(branch_updates) == 2
    replay_config, replay_values, replay_node = branch_updates[0]
    assert isinstance(replay_values["messages"], Overwrite)
    assert replay_values["messages"].value == []
    assert replay_config["configurable"]["thread_id"] == body["thread_id"]
    assert replay_config["metadata"]["source"] == "branch"
    assert replay_node == "branch"

    head_config, head_values, head_node = branch_updates[1]
    assert isinstance(head_values["messages"], Overwrite)
    assert [message.id for message in head_values["messages"].value] == ["h1", "a1"]
    assert head_config["configurable"]["checkpoint_id"] == "branch-1"
    assert head_config["metadata"]["source"] == "branch"
    assert head_node == "branch"


@pytest.mark.parametrize(
    ("include_replay_base", "expected_message_ids"),
    [
        (True, [[], ["h1", "a1"]]),
        (False, [["h1", "a1"]]),
    ],
    ids=["chronological-replay-base", "legacy-single-checkpoint"],
)
def test_branch_thread_preserves_unlinked_legacy_histories(
    monkeypatch,
    include_replay_base: bool,
    expected_message_ids: list[list[str]],
) -> None:
    app, _store, _checkpointer = _build_thread_app()
    source_thread_id = "source-unlinked"
    messages = [
        HumanMessage(id="h1", content="Question"),
        AIMessage(id="a1", content="Answer"),
    ]

    def snapshot(checkpoint_id: str, snapshot_messages: list[object], *, duration_only: bool = False) -> SimpleNamespace:
        return SimpleNamespace(
            values={"messages": snapshot_messages},
            config={
                "configurable": {
                    "thread_id": source_thread_id,
                    "checkpoint_ns": "",
                    "checkpoint_id": checkpoint_id,
                }
            },
            metadata={"writes": {"runtime_run_duration": 1}} if duration_only else {},
            parent_config=None,
        )

    source_history = [snapshot("ckpt-1", messages)]
    if include_replay_base:
        source_history.extend(
            [
                snapshot("ckpt-duration", [], duration_only=True),
                snapshot("ckpt-0", []),
            ]
        )

    history_limits: list[int | None] = []

    async def source_ahistory(config, *, limit=None):
        assert config["configurable"]["thread_id"] == source_thread_id
        history_limits.append(limit)
        return source_history

    async def unexpected_lineage_read(_config):
        raise AssertionError("unlinked checkpoints must use chronological history")

    branch_updates: list[dict] = []

    async def branch_aupdate(config, values, *, as_node=None):
        assert as_node == "branch"
        branch_updates.append(values)
        return {
            "configurable": {
                "thread_id": config["configurable"]["thread_id"],
                "checkpoint_ns": "",
                "checkpoint_id": f"branch-{len(branch_updates)}",
            }
        }

    source_accessor = SimpleNamespace(ahistory=source_ahistory, aget=unexpected_lineage_read)
    branch_accessor = SimpleNamespace(aupdate=branch_aupdate)

    def build_accessor(_request, *, thread_id, assistant_id=None, checkpoint_id=None):
        assert thread_id == source_thread_id
        return source_accessor, {
            "configurable": {
                "thread_id": source_thread_id,
                "checkpoint_ns": "",
            }
        }

    def build_mutation_accessor(_request, *, thread_id, as_node, checkpoint_id=None, state_schema=None):
        return branch_accessor, {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": "",
            }
        }

    monkeypatch.setattr(threads, "build_checkpoint_state_accessor", build_accessor)
    monkeypatch.setattr(threads, "build_checkpoint_state_mutation_accessor", build_mutation_accessor)

    with TestClient(app) as client:
        created = client.post(
            "/api/threads",
            json={"thread_id": source_thread_id, "metadata": {}, "assistant_id": "agent"},
        )
        assert created.status_code == 200, created.text
        response = client.post(
            f"/api/threads/{source_thread_id}/branches",
            json={"message_id": "a1", "message_ids": ["a1"]},
        )

    assert response.status_code == 200, response.text
    assert response.json()["parent_checkpoint_id"] == "ckpt-1"
    assert [[message.id for message in update["messages"].value] for update in branch_updates] == expected_message_ids
    assert history_limits == [
        threads._BRANCH_HISTORY_RAW_SCAN_LIMIT,
        threads._BRANCH_HISTORY_RAW_SCAN_LIMIT,
        threads._BRANCH_HISTORY_RAW_SCAN_LIMIT,
    ]


def test_branch_history_scans_budget_for_duration_only_checkpoints() -> None:
    target = SimpleNamespace(
        values={
            "messages": [
                HumanMessage(id="h1", content="Question"),
                AIMessage(id="a1", content="Answer"),
            ]
        },
        config={
            "configurable": {
                "thread_id": "source-duration-budget",
                "checkpoint_ns": "",
                "checkpoint_id": "target",
            }
        },
        metadata={},
    )
    duration_only = [
        SimpleNamespace(
            values={"messages": []},
            config={
                "configurable": {
                    "thread_id": "source-duration-budget",
                    "checkpoint_ns": "",
                    "checkpoint_id": f"duration-{index}",
                }
            },
            metadata={"writes": {"runtime_run_duration": index}},
        )
        for index in range(threads._BRANCH_HISTORY_SCAN_LIMIT)
    ]
    history = [*duration_only, target]
    limits: list[int | None] = []

    async def ahistory(_config, *, limit=None):
        limits.append(limit)
        return history[:limit]

    accessor = SimpleNamespace(ahistory=ahistory)
    config = {"configurable": {"thread_id": "source-duration-budget", "checkpoint_ns": ""}}

    found = asyncio.run(threads._find_branch_checkpoint(accessor, config, {"a1"}))
    targets_latest = asyncio.run(threads._branch_targets_latest_turn(accessor, config, {"a1"}))

    assert found is target
    assert targets_latest is True
    assert limits == [threads._BRANCH_HISTORY_RAW_SCAN_LIMIT, threads._BRANCH_HISTORY_RAW_SCAN_LIMIT]


def test_branch_thread_real_mutation_graph_finishes_without_scheduling(monkeypatch) -> None:
    app, _store, _checkpointer = _build_thread_app()
    app.state.checkpoint_channel_mode = "delta"
    source_thread_id = "source-real-branch"
    messages = [
        HumanMessage(id="h1", content="First question"),
        AIMessage(id="a1", content="First answer"),
        HumanMessage(id="h2", content="Second question"),
        AIMessage(id="a2", content="Second answer"),
    ]

    def snapshot(checkpoint_id: str, materialized_messages: list[object], *, parent_id: str | None = None) -> SimpleNamespace:
        return SimpleNamespace(
            values={"messages": materialized_messages},
            config={
                "configurable": {
                    "thread_id": source_thread_id,
                    "checkpoint_ns": "",
                    "checkpoint_id": checkpoint_id,
                }
            },
            metadata={},
            parent_config=(
                {
                    "configurable": {
                        "thread_id": source_thread_id,
                        "checkpoint_ns": "",
                        "checkpoint_id": parent_id,
                    }
                }
                if parent_id is not None
                else None
            ),
        )

    source_history = [
        snapshot("ckpt-2", messages, parent_id="ckpt-1"),
        snapshot("ckpt-1", messages[:2], parent_id="ckpt-0"),
        snapshot("ckpt-0", []),
    ]
    source_accessor = SimpleNamespace(
        ahistory=AsyncMock(return_value=source_history),
        aget=AsyncMock(side_effect=lambda config: next(item for item in source_history if item.config["configurable"]["checkpoint_id"] == config["configurable"]["checkpoint_id"])),
    )

    def source_builder(_request, *, thread_id, assistant_id=None, checkpoint_id=None):
        if thread_id != source_thread_id:
            raise AssertionError("fresh branches must use the dedicated mutation graph")
        return source_accessor, {
            "configurable": {
                "thread_id": source_thread_id,
                "checkpoint_ns": "",
            }
        }

    real_mutation_builder = gateway_services.build_checkpoint_state_mutation_accessor
    monkeypatch.setattr(threads, "build_checkpoint_state_accessor", source_builder)
    monkeypatch.setattr(
        threads,
        "build_checkpoint_state_mutation_accessor",
        real_mutation_builder,
        raising=False,
    )

    with TestClient(app) as client:
        created = client.post(
            "/api/threads",
            json={"thread_id": source_thread_id, "metadata": {}, "assistant_id": "agent"},
        )
        assert created.status_code == 200, created.text
        response = client.post(
            f"/api/threads/{source_thread_id}/branches",
            json={"message_id": "a1", "message_ids": ["a1"]},
        )

    assert response.status_code == 200, response.text
    new_thread_id = response.json()["thread_id"]
    accessor, config = real_mutation_builder(
        SimpleNamespace(app=app),
        thread_id=new_thread_id,
        as_node="branch",
    )
    branch_snapshot = asyncio.run(accessor.aget(config))
    assert [message.id for message in branch_snapshot.values["messages"]] == ["h1", "a1"]
    assert branch_snapshot.next == ()
    assert branch_snapshot.metadata["deerflow_branch"] is True
    assert branch_snapshot.metadata["branch_parent_checkpoint_id"] == "ckpt-1"


def _wire_extension_agent(monkeypatch, app, checkpointer, mode):
    """Stub only the infra context + assistant factory; keep builders real.

    The production resolution path stays live: thread record -> assistant_id
    -> resolve_agent_factory -> effective graph (base schema for ``mode`` plus
    a non-identity reducer channel contributed by AgentMiddleware.state_schema).
    """
    import operator
    from typing import Annotated, NotRequired, TypedDict

    from langchain.agents import create_agent
    from langchain.agents.middleware import AgentMiddleware
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel

    from deerflow.agents.thread_state import get_thread_state_schema

    class ExtensionState(TypedDict):
        ext_list: NotRequired[Annotated[list[str], operator.add]]

    class ExtensionMiddleware(AgentMiddleware):
        state_schema = ExtensionState

    app.state.checkpoint_channel_mode = mode
    model = FakeMessagesListChatModel(responses=[AIMessage(content="ok")])

    def custom_factory(*, config=None):
        return create_agent(model, middleware=[ExtensionMiddleware()], state_schema=get_thread_state_schema(mode))

    def default_factory(*, config=None):
        return create_agent(model, state_schema=get_thread_state_schema(mode))

    def selective_factory(assistant_id):
        # Only the thread's recorded assistant yields the extension graph;
        # unresolved assistant_id must materialize with the default schema so
        # the tests actually guard the resolution boundary.
        return custom_factory if assistant_id == "extension-agent" else default_factory

    ctx = SimpleNamespace(checkpointer=checkpointer, store=None, checkpoint_channel_mode=mode, app_config=None)
    monkeypatch.setattr(gateway_services, "get_run_context", lambda _request: ctx)
    monkeypatch.setattr(gateway_services, "resolve_agent_factory", selective_factory)
    monkeypatch.setattr(threads, "build_checkpoint_state_accessor", gateway_services.build_checkpoint_state_accessor)
    monkeypatch.setattr(threads, "build_checkpoint_state_mutation_accessor", gateway_services.build_checkpoint_state_mutation_accessor)
    monkeypatch.setattr(threads, "build_thread_checkpoint_state_accessor", gateway_services.build_thread_checkpoint_state_accessor)
    monkeypatch.setattr(threads, "build_thread_checkpoint_state_mutation_accessor", gateway_services.build_thread_checkpoint_state_mutation_accessor)
    monkeypatch.setattr(thread_runs, "build_thread_checkpoint_state_accessor", gateway_services.build_thread_checkpoint_state_accessor)
    return custom_factory


async def _seed_extension_source(checkpointer, custom_factory, mode, source_thread_id):
    accessor = CheckpointStateAccessor.bind(custom_factory(), checkpointer, mode=mode)
    await accessor.aupdate(
        {"configurable": {"thread_id": source_thread_id, "checkpoint_ns": ""}},
        {"messages": [HumanMessage(id="h1", content="question")], "ext_list": ["merged"]},
        as_node="model",
    )
    await accessor.aupdate(
        {"configurable": {"thread_id": source_thread_id, "checkpoint_ns": ""}},
        {"messages": [AIMessage(id="a1", content="answer")], "ext_list": ["payload"]},
        as_node="model",
    )
    await accessor.aupdate(
        {"configurable": {"thread_id": source_thread_id, "checkpoint_ns": ""}},
        {
            "messages": [
                HumanMessage(
                    id="h2",
                    content="follow-up",
                    additional_kwargs={"run_id": "source-run"},
                )
            ]
        },
        as_node="model",
    )
    await accessor.aupdate(
        {"configurable": {"thread_id": source_thread_id, "checkpoint_ns": ""}},
        {"messages": [AIMessage(id="a2", content="follow-up answer")]},
        as_node="model",
    )


@pytest.mark.parametrize("mode", ["full", "delta"])
def test_state_endpoints_preserve_extension_reducer_channels(monkeypatch, mode) -> None:
    """A non-identity middleware reducer channel survives state endpoints.

    GET /state must return the extension value (resolved via the thread's
    assistant_id), POST /state must replace it, and branch must preserve it
    byte-for-byte by copying reducer channels with Overwrite semantics. The
    copied pre-user checkpoint must also remain materializable for regenerate.
    """
    app, _store, checkpointer = _build_thread_app()
    app.include_router(thread_runs.router)
    custom_factory = _wire_extension_agent(monkeypatch, app, checkpointer, mode)

    async def list_messages(_thread_id: str, *, limit: int, **_kwargs) -> list[dict]:
        assert limit == thread_runs.REGENERATE_HISTORY_SCAN_LIMIT
        return []

    async def list_by_thread(_thread_id: str, *, user_id=None, limit: int = 100) -> list:
        return []

    app.state.run_event_store = SimpleNamespace(list_messages=list_messages)
    app.state.run_manager = SimpleNamespace(list_by_thread=list_by_thread)

    recorded_updates: list[dict] = []
    real_mutation_builder = gateway_services.build_checkpoint_state_mutation_accessor

    def recording_mutation_builder(request, *, thread_id, as_node, checkpoint_id=None, state_schema=None):
        accessor, config = real_mutation_builder(request, thread_id=thread_id, as_node=as_node, checkpoint_id=checkpoint_id, state_schema=state_schema)
        original_aupdate = accessor.aupdate

        async def recording_aupdate(config, values, *, as_node=None):
            recorded_updates.append(dict(values))
            return await original_aupdate(config, values, as_node=as_node)

        accessor.aupdate = recording_aupdate
        return accessor, config

    monkeypatch.setattr(gateway_services, "build_checkpoint_state_mutation_accessor", recording_mutation_builder)
    monkeypatch.setattr(threads, "build_checkpoint_state_mutation_accessor", recording_mutation_builder)

    source_thread_id = "extension-source"

    with TestClient(app) as client:
        created = client.post(
            "/api/threads",
            json={"thread_id": source_thread_id, "metadata": {}, "assistant_id": "extension-agent"},
        )
        assert created.status_code == 200, created.text

        # Seed after creation: create_thread writes an empty head checkpoint.
        asyncio.run(_seed_extension_source(checkpointer, custom_factory, mode, source_thread_id))

        read_response = client.get(f"/api/threads/{source_thread_id}/state")
        assert read_response.status_code == 200, read_response.text
        assert read_response.json()["values"]["ext_list"] == ["merged", "payload"]

        update_response = client.post(
            f"/api/threads/{source_thread_id}/state",
            json={"values": {"ext_list": ["replaced"]}},
        )
        assert update_response.status_code == 200, update_response.text
        assert update_response.json()["values"]["ext_list"] == ["replaced"]

        branch_response = client.post(
            f"/api/threads/{source_thread_id}/branches",
            json={"message_id": "a2", "message_ids": ["a2"]},
        )
        assert branch_response.status_code == 200, branch_response.text
        branch_thread_id = branch_response.json()["thread_id"]

        prepare_response = client.post(
            f"/api/threads/{branch_thread_id}/runs/regenerate/prepare",
            json={"message_id": "a2"},
        )
        assert prepare_response.status_code == 200, prepare_response.text

    # The branch write must copy every reducer channel with replace semantics.
    branch_update = recorded_updates[-1]
    assert isinstance(branch_update["ext_list"], Overwrite)
    assert branch_update["ext_list"].value == ["replaced"]
    assert isinstance(branch_update["messages"], Overwrite)

    async def materialize(thread_id):
        accessor = CheckpointStateAccessor.bind(custom_factory(), checkpointer, mode=mode)
        snapshot = await accessor.aget({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}})
        return snapshot.values

    branch_values = asyncio.run(materialize(branch_thread_id))
    assert branch_values["ext_list"] == ["replaced"]
    assert [message.id for message in branch_values["messages"]] == ["h1", "a1", "h2", "a2"]

    prepared = prepare_response.json()
    assert prepared["target_run_id"] == "source-run"
    assert prepared["input"]["messages"][0]["id"] == "h2"
    base_accessor = CheckpointStateAccessor.bind(custom_factory(), checkpointer, mode=mode)
    base_values = asyncio.run(
        base_accessor.aget(
            {
                "configurable": {
                    "thread_id": branch_thread_id,
                    "checkpoint_ns": prepared["checkpoint"]["checkpoint_ns"],
                    "checkpoint_id": prepared["checkpoint"]["checkpoint_id"],
                }
            }
        )
    ).values
    assert [message.id for message in base_values["messages"]] == ["h1", "a1"]


async def _seed_branch_history_source(checkpointer, custom_factory, mode, source_thread_id):
    """Seed a completed turn whose history includes hidden and tool messages."""
    accessor = CheckpointStateAccessor.bind(custom_factory(), checkpointer, mode=mode)
    config = {"configurable": {"thread_id": source_thread_id, "checkpoint_ns": ""}}
    await accessor.aupdate(
        config,
        {
            "messages": [
                HumanMessage(id="h1", content="question"),
                HumanMessage(id="h-hidden", content="internal", additional_kwargs={"hide_from_ui": True}),
            ]
        },
        as_node="model",
    )
    await accessor.aupdate(
        config,
        {
            "messages": [
                ToolMessage(id="t1", content="tool output", tool_call_id="call-1"),
                AIMessage(id="a1", content="answer"),
            ]
        },
        as_node="model",
    )


@pytest.mark.parametrize("mode", ["full", "delta"])
def test_branch_seeds_run_events_with_parent_history(monkeypatch, mode) -> None:
    """Branching must seed the branch's run-event feed with the parent history.

    The thread feed (``GET /messages`` / ``/messages/page``) reads the
    run-event store, not checkpoints; without seeding, a fresh branch has no
    message rows, so the inherited history vanishes from the UI as soon as
    the branch's first run refreshes the feed (#4380 problem 2).
    """
    from deerflow.runtime.events.store.memory import MemoryRunEventStore

    app, _store, checkpointer = _build_thread_app()
    custom_factory = _wire_extension_agent(monkeypatch, app, checkpointer, mode)
    event_store = MemoryRunEventStore()
    app.state.run_event_store = event_store
    source_thread_id = f"branch-history-source-{mode}"

    with TestClient(app) as client:
        created = client.post(
            "/api/threads",
            json={"thread_id": source_thread_id, "metadata": {}, "assistant_id": "extension-agent"},
        )
        assert created.status_code == 200, created.text

        asyncio.run(_seed_branch_history_source(checkpointer, custom_factory, mode, source_thread_id))

        branch_response = client.post(
            f"/api/threads/{source_thread_id}/branches",
            json={"message_id": "a1", "message_ids": ["a1"]},
        )
        assert branch_response.status_code == 200, branch_response.text
        branch_thread_id = branch_response.json()["thread_id"]

    rows = asyncio.run(event_store.list_messages(branch_thread_id, user_id=None))

    # The visible parent history is seeded in order; hidden messages are not.
    assert [row["content"]["id"] for row in rows] == ["h1", "t1", "a1"]
    assert [row["event_type"] for row in rows] == ["llm.human.input", "llm.tool.result", "llm.ai.response"]
    assert all(row["category"] == "message" for row in rows)
    assert all(row["run_id"] == f"branch-seed-{branch_thread_id}" for row in rows)
    assert all((row.get("metadata") or {}).get("branch_seed") is True for row in rows)
    seqs = [row["seq"] for row in rows]
    assert seqs == sorted(seqs)
    assert branch_response.json()["history_seed_mode"] == "seeded"

    # The parent thread's feed stays untouched.
    assert asyncio.run(event_store.list_messages(source_thread_id, user_id=None)) == []


def test_branch_history_seed_failure_keeps_branch_usable(monkeypatch) -> None:
    """A seeding failure must degrade, not fail the branch (best-effort)."""

    class _ExplodingStore:
        async def put_batch(self, events):
            raise RuntimeError("event store down")

    app, _store, checkpointer = _build_thread_app()
    custom_factory = _wire_extension_agent(monkeypatch, app, checkpointer, "full")
    app.state.run_event_store = _ExplodingStore()
    source_thread_id = "branch-history-source-failure"

    with TestClient(app) as client:
        created = client.post(
            "/api/threads",
            json={"thread_id": source_thread_id, "metadata": {}, "assistant_id": "extension-agent"},
        )
        assert created.status_code == 200, created.text

        asyncio.run(_seed_branch_history_source(checkpointer, custom_factory, "full", source_thread_id))

        branch_response = client.post(
            f"/api/threads/{source_thread_id}/branches",
            json={"message_id": "a1", "message_ids": ["a1"]},
        )

    assert branch_response.status_code == 200, branch_response.text
    assert branch_response.json()["history_seed_mode"] == "failed"


def test_update_thread_state_rejects_unknown_state_fields(monkeypatch) -> None:
    """Unknown fields fail 422 instead of a false-success 200."""
    app, _store, checkpointer = _build_thread_app()
    custom_factory = _wire_extension_agent(monkeypatch, app, checkpointer, "full")
    source_thread_id = "extension-source-422"

    with TestClient(app) as client:
        created = client.post(
            "/api/threads",
            json={"thread_id": source_thread_id, "metadata": {}, "assistant_id": "extension-agent"},
        )
        assert created.status_code == 200, created.text

        asyncio.run(_seed_extension_source(checkpointer, custom_factory, "full", source_thread_id))

        response = client.post(
            f"/api/threads/{source_thread_id}/state",
            json={"values": {"not_a_state_field": 1}},
        )

    assert response.status_code == 422, response.text
    assert "not_a_state_field" in response.json()["detail"]


def test_branch_display_name_strips_legacy_branch_prefix_only_for_branch_sources() -> None:
    assert threads._default_branch_display_name("Original chat") == "Original chat"
    assert threads._default_branch_display_name("Branch: Original chat") == "Branch: Original chat"
    assert threads._default_branch_display_name("Branch: Branch: Original chat", source_is_branch=True) == "Original chat"


def test_branch_thread_rejects_sidecar_threads() -> None:
    app, _store, _checkpointer = _build_thread_app()

    with TestClient(app) as client:
        created = client.post(
            "/api/threads",
            json={"thread_id": "sidecar-thread", "metadata": {"deerflow_sidecar": True}},
        )
        assert created.status_code == 200, created.text

        response = client.post(
            "/api/threads/sidecar-thread/branches",
            json={"message_id": "ai-1", "message_ids": ["ai-1"]},
        )

    assert response.status_code == 409
    assert "main conversation" in response.json()["detail"]


def test_branch_thread_rejects_non_assistant_targets() -> None:
    app, _store, checkpointer = _build_thread_app()
    source_thread_id = "source-human-target"
    human = HumanMessage(id="human-1", content="Question")
    ai = AIMessage(id="ai-1", content="Answer")

    async def _seed(parent_config: dict) -> None:
        after_human = await _write_checkpoint(checkpointer, source_thread_id, str(uuid6()), [human], step=1, parent_config=parent_config)
        await _write_checkpoint(checkpointer, source_thread_id, str(uuid6()), [human, ai], step=2, parent_config=after_human)

    with TestClient(app) as client:
        created = client.post("/api/threads", json={"thread_id": source_thread_id, "metadata": {}})
        assert created.status_code == 200, created.text
        initial = asyncio.run(checkpointer.aget_tuple({"configurable": {"thread_id": source_thread_id, "checkpoint_ns": ""}}))
        assert initial is not None
        asyncio.run(_seed(initial.config))

        response = client.post(
            f"/api/threads/{source_thread_id}/branches",
            json={"message_id": "human-1", "message_ids": ["human-1"]},
        )

    assert response.status_code == 409
    assert "can no longer be branched" in response.json()["detail"]


def test_branch_thread_best_effort_copies_current_workspace(tmp_path) -> None:
    paths = Paths(tmp_path)
    app, _store, checkpointer = _build_thread_app()
    source_thread_id = "source-with-files"
    user_id = "branch-user"

    source_user_data = paths.sandbox_user_data_dir(source_thread_id, user_id=user_id)
    source_outputs = paths.sandbox_outputs_dir(source_thread_id, user_id=user_id)
    source_uploads = paths.sandbox_uploads_dir(source_thread_id, user_id=user_id)
    source_outputs.mkdir(parents=True, exist_ok=True)
    source_uploads.mkdir(parents=True, exist_ok=True)
    (source_outputs / "result.txt").write_text("answer", encoding="utf-8")
    (source_uploads / ".upload-stale.part").write_text("partial", encoding="utf-8")

    human = HumanMessage(id="human-file", content="Make a file")
    ai = AIMessage(id="ai-file", content="Done")

    async def _seed(parent_config: dict) -> None:
        after_human = await _write_checkpoint(checkpointer, source_thread_id, str(uuid6()), [human], step=1, parent_config=parent_config)
        await _write_checkpoint(checkpointer, source_thread_id, str(uuid6()), [human, ai], step=2, parent_config=after_human)

    with (
        patch("app.gateway.routers.threads.get_paths", return_value=paths),
        patch("app.gateway.routers.threads.get_effective_user_id", return_value=user_id),
        TestClient(app) as client,
    ):
        created = client.post("/api/threads", json={"thread_id": source_thread_id, "metadata": {}})
        assert created.status_code == 200, created.text
        initial = asyncio.run(checkpointer.aget_tuple({"configurable": {"thread_id": source_thread_id, "checkpoint_ns": ""}}))
        assert initial is not None
        asyncio.run(_seed(initial.config))

        response = client.post(
            f"/api/threads/{source_thread_id}/branches",
            json={"message_id": "ai-file", "message_ids": ["ai-file"]},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["workspace_clone_mode"] == "current_thread_best_effort"

    target_user_data = paths.sandbox_user_data_dir(body["thread_id"], user_id=user_id)
    assert target_user_data.exists()
    assert (target_user_data / "outputs" / "result.txt").read_text(encoding="utf-8") == "answer"
    assert not (target_user_data / "uploads" / ".upload-stale.part").exists()
    assert source_user_data.exists()


def test_branch_thread_from_historical_turn_skips_workspace_clone(tmp_path) -> None:
    """Branching from a non-latest turn must not clone the current workspace.

    Workspace files are not checkpointed, so cloning them onto a branch rooted at
    an older turn would leak files created after that turn (regression for the
    historical-turn workspace-leak review on PR #3950).
    """
    paths = Paths(tmp_path)
    app, _store, checkpointer = _build_thread_app()
    source_thread_id = "source-historical"
    user_id = "branch-user"

    source_outputs = paths.sandbox_outputs_dir(source_thread_id, user_id=user_id)
    source_outputs.mkdir(parents=True, exist_ok=True)
    # ``future.txt`` only exists in the current (latest) workspace timeline.
    (source_outputs / "future.txt").write_text("future", encoding="utf-8")

    human_1 = HumanMessage(id="human-1", content="First question")
    ai_1 = AIMessage(id="ai-1", content="First answer")
    human_2 = HumanMessage(id="human-2", content="Second question")
    ai_2 = AIMessage(id="ai-2", content="Second answer")

    async def _seed(parent_config: dict) -> dict:
        after_human_1 = await _write_checkpoint(checkpointer, source_thread_id, str(uuid6()), [human_1], step=1, parent_config=parent_config)
        after_ai_1 = await _write_checkpoint(checkpointer, source_thread_id, str(uuid6()), [human_1, ai_1], step=2, parent_config=after_human_1)
        after_human_2 = await _write_checkpoint(
            checkpointer,
            source_thread_id,
            str(uuid6()),
            [human_1, ai_1, human_2],
            step=3,
            parent_config=after_ai_1,
        )
        await _write_checkpoint(
            checkpointer,
            source_thread_id,
            str(uuid6()),
            [human_1, ai_1, human_2, ai_2],
            step=4,
            parent_config=after_human_2,
        )
        return after_ai_1

    with (
        patch("app.gateway.routers.threads.get_paths", return_value=paths),
        patch("app.gateway.routers.threads.get_effective_user_id", return_value=user_id),
        TestClient(app) as client,
    ):
        created = client.post("/api/threads", json={"thread_id": source_thread_id, "metadata": {}})
        assert created.status_code == 200, created.text
        initial = asyncio.run(checkpointer.aget_tuple({"configurable": {"thread_id": source_thread_id, "checkpoint_ns": ""}}))
        assert initial is not None
        target_checkpoint_config = asyncio.run(_seed(initial.config))

        response = client.post(
            f"/api/threads/{source_thread_id}/branches",
            json={"message_id": "ai-1", "message_ids": ["ai-1"]},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["parent_checkpoint_id"] == target_checkpoint_config["configurable"]["checkpoint_id"]
    assert body["workspace_clone_mode"] == "skipped_historical_turn"

    target_user_data = paths.sandbox_user_data_dir(body["thread_id"], user_id=user_id)
    assert not target_user_data.exists()


# ── Metadata filter validation at API boundary ────────────────────────────────


def test_search_threads_rejects_invalid_key_at_api_boundary() -> None:
    """Keys that don't match [A-Za-z0-9_-]+ are rejected by the Pydantic
    validator on ThreadSearchRequest.metadata — 422 from both backends.
    """
    app, _store, _checkpointer = _build_thread_app()

    with TestClient(app) as client:
        response = client.post("/api/threads/search", json={"metadata": {"bad;key": "x"}})

    assert response.status_code == 422


def test_search_threads_rejects_unsupported_value_type_at_api_boundary() -> None:
    """Value types outside (None, bool, int, float, str) are rejected."""
    app, _store, _checkpointer = _build_thread_app()

    with TestClient(app) as client:
        response = client.post("/api/threads/search", json={"metadata": {"env": ["a", "b"]}})

    assert response.status_code == 422


def test_search_threads_returns_400_for_backend_invalid_metadata_filter() -> None:
    """If the backend still raises InvalidMetadataFilterError (defense in
    depth), the handler surfaces it as HTTP 400.
    """
    app, _store, _checkpointer = _build_thread_app()
    thread_store = app.state.thread_store

    async def _raise(**kwargs):
        raise InvalidMetadataFilterError("rejected")

    with TestClient(app) as client:
        with patch.object(thread_store, "search", side_effect=_raise):
            response = client.post("/api/threads/search", json={"metadata": {"valid_key": "x"}})

    assert response.status_code == 400
    assert "rejected" in response.json()["detail"]


def test_search_threads_succeeds_with_valid_metadata() -> None:
    """Sanity check: valid metadata passes through without error."""
    app, _store, _checkpointer = _build_thread_app()

    with TestClient(app) as client:
        response = client.post("/api/threads/search", json={"metadata": {"env": "prod"}})

    assert response.status_code == 200


# ── update_thread_state: each call inserts a new checkpoint (regression) ───────


def test_update_thread_state_overwrites_reducer_fields_and_writes_last_values_directly(monkeypatch) -> None:
    app, _store, _checkpointer = _build_thread_app()
    update_calls: list[tuple[dict, dict, str | None]] = []
    updated_config = {
        "configurable": {
            "thread_id": "state-overwrite",
            "checkpoint_ns": "",
            "checkpoint_id": "ckpt-updated",
        }
    }
    snapshot = SimpleNamespace(
        values={
            "messages": [{"type": "human", "id": "h1", "content": "replacement"}],
            "artifacts": ["artifact-1"],
            "title": "Renamed",
        },
        config=updated_config,
        parent_config={"configurable": {"checkpoint_id": "ckpt-original"}},
        metadata={"source": "update", "step": 1},
        next=(),
        tasks=(),
        created_at="2026-07-18T00:00:00+00:00",
    )

    async def aupdate(config, values, *, as_node=None):
        update_calls.append((config, values, as_node))
        return updated_config

    accessor = SimpleNamespace(
        aupdate=aupdate,
        aget=AsyncMock(return_value=snapshot),
    )

    async def build_accessor(_request, *, thread_id, as_node, checkpoint_id=None):
        assert thread_id == "state-overwrite"
        return accessor, {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": "",
                **({"checkpoint_id": checkpoint_id} if checkpoint_id else {}),
            }
        }

    monkeypatch.setattr(threads, "build_thread_checkpoint_state_mutation_accessor", build_accessor)

    with TestClient(app) as client:
        created = client.post(
            "/api/threads",
            json={"thread_id": "state-overwrite", "metadata": {}},
        )
        assert created.status_code == 200, created.text
        response = client.post(
            "/api/threads/state-overwrite/state",
            json={
                "values": {
                    "messages": [{"type": "human", "id": "h1", "content": "replacement"}],
                    "artifacts": ["artifact-1"],
                    "title": "Renamed",
                }
            },
        )

    assert response.status_code == 200, response.text
    assert len(update_calls) == 1
    read_config, updates, as_node = update_calls[0]
    assert read_config["configurable"]["thread_id"] == "state-overwrite"
    assert isinstance(updates["messages"], Overwrite)
    assert updates["messages"].value[0]["id"] == "h1"
    assert isinstance(updates["artifacts"], Overwrite)
    assert updates["artifacts"].value == ["artifact-1"]
    assert updates["title"] == "Renamed"
    assert as_node == "manual_state_update"
    accessor.aget.assert_awaited_once_with(updated_config)
    assert response.json()["checkpoint_id"] == "ckpt-updated"


def test_update_thread_state_real_mutation_graph_finishes_without_scheduling(monkeypatch) -> None:
    app, _store, _checkpointer = _build_thread_app()
    app.state.checkpoint_channel_mode = "delta"
    real_mutation_builder = gateway_services.build_checkpoint_state_mutation_accessor

    async def mutation_boundary(request, *, thread_id, as_node, checkpoint_id=None):
        # No real assistant graph in this unit context: the boundary falls
        # back to the base schema while writes still use the mutation graph.
        return real_mutation_builder(request, thread_id=thread_id, as_node=as_node, checkpoint_id=checkpoint_id)

    monkeypatch.setattr(threads, "build_thread_checkpoint_state_mutation_accessor", mutation_boundary)

    with TestClient(app) as client:
        created = client.post(
            "/api/threads",
            json={"thread_id": "state-real-mutation", "metadata": {}},
        )
        assert created.status_code == 200, created.text
        response = client.post(
            "/api/threads/state-real-mutation/state",
            json={
                "values": {
                    "messages": [{"type": "human", "id": "h1", "content": "replacement"}],
                    "artifacts": ["artifact-1"],
                    "title": "Renamed",
                }
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [message["id"] for message in body["values"]["messages"]] == ["h1"]
    assert body["values"]["artifacts"] == ["artifact-1"]
    assert body["values"]["title"] == "Renamed"
    assert body["next"] == []


@pytest.mark.parametrize("missing_checkpoint_id", ["does-not-exist", ""])
def test_update_thread_state_rejects_missing_explicit_checkpoint_without_writing(
    missing_checkpoint_id: str,
) -> None:
    app, _store, checkpointer = _build_thread_app()

    with TestClient(app) as client:
        created = client.post(
            "/api/threads",
            json={"thread_id": "state-missing-checkpoint", "metadata": {}},
        )
        assert created.status_code == 200, created.text
        response = client.post(
            "/api/threads/state-missing-checkpoint/state",
            json={
                "checkpoint_id": missing_checkpoint_id,
                "values": {"title": "Must not be written"},
            },
        )

    assert response.status_code == 404, response.text

    async def collect_checkpoint_ids():
        return [
            item.config["configurable"]["checkpoint_id"]
            async for item in checkpointer.alist(
                {
                    "configurable": {
                        "thread_id": "state-missing-checkpoint",
                        "checkpoint_ns": "",
                    }
                }
            )
        ]

    checkpoint_ids = asyncio.run(collect_checkpoint_ids())
    assert missing_checkpoint_id not in checkpoint_ids
    assert len(checkpoint_ids) == 1


def test_update_thread_state_inserts_new_checkpoint_each_call() -> None:
    """Each ``POST /state`` must INSERT a distinct, time-ordered checkpoint.

    Regression for the in-place REPLACE bug: before the fix the new
    checkpoint reused the previous checkpoint["id"], so InMemorySaver/SQLite
    overwrote the existing row and history never grew. The fix assigns a
    fresh uuid6 to checkpoint["id"] before aput.
    """
    app, _store, checkpointer = _build_thread_app()

    with TestClient(app) as client:
        created = client.post("/api/threads", json={"metadata": {}})
        assert created.status_code == 200, created.text
        thread_id = created.json()["thread_id"]

        r1 = client.post(f"/api/threads/{thread_id}/state", json={"values": {"title": "First"}})
        assert r1.status_code == 200, r1.text
        r2 = client.post(f"/api/threads/{thread_id}/state", json={"values": {"title": "Second"}})
        assert r2.status_code == 200, r2.text

    import asyncio

    async def _collect():
        return [cp async for cp in checkpointer.alist({"configurable": {"thread_id": thread_id}})]

    history = asyncio.run(_collect())

    # 1 empty checkpoint from create_thread + 1 per update call.
    assert len(history) >= 3, f"expected >=3 checkpoints, got {len(history)}"

    ids = [cp.config["configurable"]["checkpoint_id"] for cp in history]
    assert len(ids) == len(set(ids)), f"duplicate checkpoint ids: {ids}"
    # alist() returns newest-first; uuid6 is time-ordered so newest > oldest.
    assert ids[0] > ids[-1], f"checkpoint ids not time-ordered (uuid4 instead of uuid6?): {ids}"

    # aput must PRESERVE the endpoint-assigned checkpoint["id"], not mint its own
    # and discard the payload's. If it generated a fresh id internally the fix
    # would be a no-op (the bug would never have existed). Assert the id returned
    # in each response round-tripped into the persisted history, and that the two
    # update writes kept the endpoint's uuid6 time-ordering through aput.
    resp_ids = [r1.json()["checkpoint_id"], r2.json()["checkpoint_id"]]
    assert all(cid is not None for cid in resp_ids), f"response missing checkpoint_id: {resp_ids}"
    assert set(resp_ids) <= set(ids), f"aput discarded endpoint-assigned id: returned {resp_ids}, stored {ids}"
    assert resp_ids[1] > resp_ids[0], f"endpoint-assigned uuid6 not preserved/ordered through aput: {resp_ids}"
