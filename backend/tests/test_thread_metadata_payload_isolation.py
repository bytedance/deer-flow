"""Native thread metadata owns producer payloads and returned read views."""

from copy import deepcopy

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from test_thread_create_idempotency import USER, app_for
from test_thread_create_idempotency import thread_store as _thread_store

from deerflow.persistence.thread_meta.base import (
    THREAD_ARCHIVED_METADATA_KEY,
    THREAD_PINNED_METADATA_KEY,
)

thread_store = _thread_store
OWNER = str(USER.id)


@pytest.fixture
def anyio_backend():
    return "asyncio"


def metadata():
    return {
        "nested": {"items": ["original"]},
        THREAD_PINNED_METADATA_KEY: False,
        THREAD_ARCHIVED_METADATA_KEY: False,
    }


def mutate(payload, field):
    if field == "nested":
        payload["nested"]["items"].append("leaked")
    else:
        payload[field] = True


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["create_input", "create_result", "get", "search", "update_input"])
@pytest.mark.parametrize("field", ["nested", THREAD_PINNED_METADATA_KEY, THREAD_ARCHIVED_METADATA_KEY])
async def test_payload_mutation_does_not_change_thread_or_other_views(thread_store, path, field):
    payload = metadata()
    created = await thread_store.create("subject", user_id=OWNER, metadata=payload)
    if path == "create_input":
        exposed = payload
    elif path == "create_result":
        exposed = created["metadata"]
    elif path == "get":
        exposed = (await thread_store.get("subject", user_id=OWNER))["metadata"]
    elif path == "search":
        exposed = (await thread_store.search(user_id=OWNER))[0]["metadata"]
    else:
        assert path == "update_input"
        exposed = metadata()
        await thread_store.update_metadata("subject", exposed, touch=False, user_id=OWNER)
    expected = deepcopy(await thread_store.get("subject", user_id=OWNER))
    peer = await thread_store.get("subject", user_id=OWNER)

    mutate(exposed, field)

    assert await thread_store.get("subject", user_id=OWNER) == expected
    assert peer == expected
    rows = await thread_store.search(archived=False, metadata={THREAD_PINNED_METADATA_KEY: False}, user_id=OWNER)
    assert [row["thread_id"] for row in rows] == ["subject"]
    assert rows[0]["metadata"] == expected["metadata"]


@pytest.mark.anyio
@pytest.mark.parametrize("reader", ["get", "search"])
async def test_http_search_ignores_pin_archive_annotations_on_a_store_view(thread_store, reader):
    await thread_store.create("a-subject", user_id=OWNER, metadata=metadata())
    await thread_store.create("z-other", user_id=OWNER, metadata=metadata())
    app = app_for(thread_store, InMemorySaver())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        before = await client.post("/api/threads/search", json={"archived": False})
        assert before.status_code == 200
        assert [row["thread_id"] for row in before.json()] == ["z-other", "a-subject"]
        if reader == "get":
            view = await thread_store.get("a-subject", user_id=OWNER)
        else:
            view = next(row for row in await thread_store.search(user_id=OWNER) if row["thread_id"] == "a-subject")
        view["metadata"][THREAD_ARCHIVED_METADATA_KEY] = True
        view["metadata"][THREAD_PINNED_METADATA_KEY] = True

        after = await client.post("/api/threads/search", json={"archived": False})
        all_rows = await client.post("/api/threads/search", json={})

        assert after.status_code == all_rows.status_code == 200
        assert after.json() == before.json()
        assert [row["thread_id"] for row in all_rows.json()] == ["z-other", "a-subject"]


class CloneFailure(RuntimeError):
    pass


@pytest.mark.anyio
@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("stage", ["input", "receipt"])
async def test_create_copy_failure_preserves_row_and_releases_lock(monkeypatch, existing, stage):
    from langgraph.store.memory import InMemoryStore

    from deerflow.persistence.thread_meta import memory

    store = memory.MemoryThreadMetaStore(InMemoryStore())
    if existing:
        await store.create("subject", user_id=OWNER, metadata={"retained": {"items": ["old"]}})
        await store.update_status("subject", "busy", user_id=OWNER)
    before = deepcopy(await store.get("subject", user_id=OWNER))
    payload = metadata()
    failure = CloneFailure(stage)

    def controlled_copy(value):
        if (stage == "input" and value is payload) or (stage == "receipt" and isinstance(value, dict) and value.get("thread_id") == "subject"):
            raise failure
        return deepcopy(value)

    with monkeypatch.context() as patcher:
        patcher.setattr(memory, "deepcopy", controlled_copy, raising=False)
        with pytest.raises(CloneFailure) as raised:
            await store.create("subject", user_id=OWNER, metadata=payload)
        assert raised.value is failure
    assert await store.get("subject", user_id=OWNER) == before
    assert not store._thread_locks._entries_by_loop
    retried = await store.create("subject", user_id=OWNER, metadata=payload)
    assert retried["metadata"] == payload
    assert not store._thread_locks._entries_by_loop


@pytest.mark.anyio
async def test_update_copy_failure_preserves_row_and_allows_retry(monkeypatch):
    from langgraph.store.memory import InMemoryStore

    from deerflow.persistence.thread_meta import memory

    store = memory.MemoryThreadMetaStore(InMemoryStore())
    await store.create("subject", user_id=OWNER, metadata=metadata())
    before = deepcopy(await store.get("subject", user_id=OWNER))
    patch = {"nested": {"items": ["replacement"]}}
    failure = CloneFailure("update")

    def controlled_copy(value):
        if value is patch:
            raise failure
        return deepcopy(value)

    with monkeypatch.context() as patcher:
        patcher.setattr(memory, "deepcopy", controlled_copy, raising=False)
        with pytest.raises(CloneFailure) as raised:
            await store.update_metadata("subject", patch, user_id=OWNER)
        assert raised.value is failure
    assert await store.get("subject", user_id=OWNER) == before
    assert not store._thread_locks._entries_by_loop
    await store.update_metadata("subject", patch, user_id=OWNER)
    assert (await store.get("subject", user_id=OWNER))["metadata"]["nested"] == patch["nested"]
    assert not store._thread_locks._entries_by_loop


@pytest.mark.anyio
@pytest.mark.parametrize("method", ["get", "search"])
async def test_read_copy_failure_preserves_storage(monkeypatch, method):
    from langgraph.store.memory import InMemoryStore

    from deerflow.persistence.thread_meta import memory

    store = memory.MemoryThreadMetaStore(InMemoryStore())
    await store.create("subject", user_id=OWNER, metadata=metadata())
    before = deepcopy(await store.get("subject", user_id=OWNER))
    failure = CloneFailure(method)

    def controlled_copy(value):
        if isinstance(value, dict) and value.get("thread_id") == "subject":
            raise failure
        return deepcopy(value)

    with monkeypatch.context() as patcher:
        patcher.setattr(memory, "deepcopy", controlled_copy, raising=False)
        with pytest.raises(CloneFailure) as raised:
            if method == "get":
                await store.get("subject", user_id=OWNER)
            else:
                await store.search(user_id=OWNER)
        assert raised.value is failure
    assert await store.get("subject", user_id=OWNER) == before
    assert not store._thread_locks._entries_by_loop


@pytest.mark.anyio
async def test_foreign_rows_are_rejected_before_copy_callbacks(monkeypatch):
    from langgraph.store.memory import InMemoryStore

    from deerflow.persistence.thread_meta import ThreadOwnershipConflictError, memory

    store = memory.MemoryThreadMetaStore(InMemoryStore())
    await store.create("subject", user_id=OWNER, metadata=metadata())

    def unexpected_copy(_value):
        raise AssertionError("foreign data reached a copy callback")

    with monkeypatch.context() as patcher:
        patcher.setattr(memory, "deepcopy", unexpected_copy, raising=False)
        assert await store.get("subject", user_id="other-owner") is None
        assert await store.search(user_id="other-owner") == []
        with pytest.raises(ThreadOwnershipConflictError):
            await store.create("subject", user_id="other-owner", metadata=metadata())
    assert not store._thread_locks._entries_by_loop


@pytest.mark.anyio
async def test_search_copies_only_the_selected_page(monkeypatch):
    from langgraph.store.memory import InMemoryStore

    from deerflow.persistence.thread_meta import memory

    store = memory.MemoryThreadMetaStore(InMemoryStore())
    for identifier in ("a-excluded", "b-selected", "c-offset"):
        await store.create(identifier, user_id=OWNER, metadata=metadata())
    failure = CloneFailure("excluded row copied")

    def selected_only(value):
        if isinstance(value, dict) and value.get("thread_id") in {"a-excluded", "c-offset"}:
            raise failure
        return deepcopy(value)

    with monkeypatch.context() as patcher:
        patcher.setattr(memory, "deepcopy", selected_only, raising=False)
        rows = await store.search(limit=1, offset=1, user_id=OWNER)
    assert [row["thread_id"] for row in rows] == ["b-selected"]
    rows[0]["metadata"]["nested"]["items"].append("local")
    assert (await store.get("b-selected", user_id=OWNER))["metadata"] == metadata()


@pytest.mark.anyio
async def test_metadata_view_stays_stable_after_later_writes(thread_store):
    await thread_store.create("subject", user_id=OWNER, metadata=metadata())
    before = await thread_store.get("subject", user_id=OWNER)
    await thread_store.update_metadata("subject", {"nested": {"items": ["later"]}}, user_id=OWNER)
    await thread_store.update_status("subject", "busy", user_id=OWNER)
    assert before["metadata"] == metadata()
    assert before["status"] == "idle"
    assert (await thread_store.get("subject", user_id=OWNER))["metadata"]["nested"] == {"items": ["later"]}
