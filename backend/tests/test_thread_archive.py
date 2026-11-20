"""Archive is an owner-scoped list filter, never deletion or run state."""

import pytest
from langgraph.store.memory import InMemoryStore

from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
from deerflow.persistence.thread_meta.sql import ThreadMetaRepository

ARCHIVED = "deerflow_archived"


@pytest.fixture(params=["memory", "sqlite"])
async def archive_store(request, tmp_path):
    if request.param == "memory":
        yield MemoryThreadMetaStore(InMemoryStore())
        return
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'archive.db'}", sqlite_dir=str(tmp_path))
    try:
        yield ThreadMetaRepository(get_session_factory())
    finally:
        await close_engine()


@pytest.mark.anyio
async def test_archive_filter_precedes_pagination_and_includes_legacy(archive_store):
    store = archive_store
    for name, metadata in [("legacy", {}), ("false", {ARCHIVED: False}), ("null", {ARCHIVED: None}), ("string", {ARCHIVED: "true"}), ("integer", {ARCHIVED: 1})]:
        await store.create(name, user_id="owner", metadata=metadata)
    for index in range(4):
        await store.create(f"archived-{index}", user_id="owner", metadata={ARCHIVED: True})
    await store.create("other", user_id="other", metadata={ARCHIVED: True})

    active = await store.search(archived=False, user_id="owner")
    assert {row["thread_id"] for row in active} == {"legacy", "false", "null", "string", "integer"}
    first = await store.search(archived=False, limit=2, user_id="owner")
    second = await store.search(archived=False, limit=3, offset=2, user_id="owner")
    assert first + second == active
    archived = await store.search(archived=True, user_id="owner")
    assert {row["thread_id"] for row in archived} == {f"archived-{index}" for index in range(4)}
    assert len(await store.search(user_id="owner")) == 9


@pytest.mark.anyio
async def test_restore_preserves_thread_metadata_status_and_timestamps(archive_store):
    store = archive_store
    original = await store.create("chat", user_id="owner", display_name="Report", metadata={"deerflow_pinned": True})
    await store.update_metadata("chat", {ARCHIVED: True}, touch=False, user_id="owner")
    assert await store.search(archived=False, user_id="owner") == []
    await store.update_metadata("chat", {ARCHIVED: False}, touch=False, user_id="other")
    assert (await store.get("chat", user_id="owner"))["metadata"][ARCHIVED] is True
    await store.update_metadata("chat", {ARCHIVED: False}, touch=False, user_id="owner")
    restored = await store.get("chat", user_id="owner")
    assert restored["updated_at"] == original["updated_at"]
    assert restored["display_name"] == "Report"
    assert restored["status"] == original["status"]
    assert restored["metadata"] == {"deerflow_pinned": True, ARCHIVED: False}
    assert len(await store.search(archived=False, user_id="owner")) == 1
