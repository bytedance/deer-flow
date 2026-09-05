"""Owner isolation tests for MemoryThreadMetaStore.

Mirrors the SQL-backed tests in test_owner_isolation.py but exercises
the in-memory LangGraph Store backend used when database.backend=memory.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from langgraph.store.memory import InMemoryStore

from deerflow.persistence.projects import ProjectNotAssignableError
from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
from deerflow.runtime.user_context import reset_current_user, set_current_user

USER_A = SimpleNamespace(id="user-a", email="a@test.local")
USER_B = SimpleNamespace(id="user-b", email="b@test.local")


def _as_user(user):
    class _Ctx:
        def __enter__(self):
            self._token = set_current_user(user)
            return user

        def __exit__(self, *exc):
            reset_current_user(self._token)

    return _Ctx()


@pytest.fixture
def store():
    return MemoryThreadMetaStore(InMemoryStore())


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_create_generates_stable_incarnation(store):
    with _as_user(USER_A):
        created = await store.create("incarnation-thread")
        fetched = await store.get("incarnation-thread")

    assert len(created["incarnation"]) == 32
    assert fetched is not None
    assert fetched["incarnation"] == created["incarnation"]


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_concurrent_create_preserves_overwrite_semantics_and_incarnation(store):
    with _as_user(USER_A):
        outcomes = await asyncio.gather(
            store.create("same-thread", display_name="first"),
            store.create("same-thread", display_name="second"),
        )
        fetched = await store.get("same-thread")

    assert {outcome["display_name"] for outcome in outcomes} == {"first", "second"}
    assert len({outcome["incarnation"] for outcome in outcomes}) == 1
    assert fetched is not None
    assert fetched["display_name"] in {"first", "second"}
    assert fetched["incarnation"] == outcomes[0]["incarnation"]
    assert not store._thread_locks._entries_by_loop


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_duplicate_create_overwrites_but_inherits_incarnation(store):
    with _as_user(USER_A):
        original = await store.create("duplicate", display_name="original")
        replacement = await store.create("duplicate", display_name="replacement")
        fetched = await store.get("duplicate")

    assert replacement["incarnation"] == original["incarnation"]
    assert replacement["display_name"] == "replacement"
    assert fetched == replacement


@pytest.mark.anyio
@pytest.mark.no_auto_user
@pytest.mark.parametrize(
    "contender",
    ["create", "update_display_name", "update_status", "update_metadata", "update_owner", "delete"],
)
async def test_all_memory_mutations_share_the_per_thread_lock(contender):
    class PausingGetStore(InMemoryStore):
        def __init__(self):
            super().__init__()
            self.pause_next_get = False
            self.get_entered = asyncio.Event()
            self.allow_get = asyncio.Event()

        async def aget(self, namespace, key):
            item = await super().aget(namespace, key)
            if self.pause_next_get:
                self.pause_next_get = False
                self.get_entered.set()
                await self.allow_get.wait()
            return item

    backend = PausingGetStore()
    store = MemoryThreadMetaStore(backend)
    await store.create("locked-thread", user_id=None)
    backend.pause_next_get = True
    holder = asyncio.create_task(store.update_metadata("locked-thread", {"holder": True}, user_id=None))
    await backend.get_entered.wait()

    operations = {
        "create": lambda: store.create("locked-thread", display_name="replacement", user_id=None),
        "update_display_name": lambda: store.update_display_name("locked-thread", "renamed", user_id=None),
        "update_status": lambda: store.update_status("locked-thread", "busy", user_id=None),
        "update_metadata": lambda: store.update_metadata("locked-thread", {"contender": True}, user_id=None),
        "update_owner": lambda: store.update_owner("locked-thread", "new-owner", user_id=None),
        "delete": lambda: store.delete("locked-thread", user_id=None),
    }
    waiting = asyncio.create_task(operations[contender]())
    await asyncio.sleep(0)
    assert not waiting.done(), f"{contender} bypassed the per-thread lock"

    backend.allow_get.set()
    await asyncio.gather(holder, waiting)
    assert not store._thread_locks._entries_by_loop


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_delete_and_recreate_are_serialized_per_thread():
    class PausingDeleteStore(InMemoryStore):
        def __init__(self):
            super().__init__()
            self.delete_entered = asyncio.Event()
            self.allow_delete = asyncio.Event()

        async def adelete(self, namespace, key):
            self.delete_entered.set()
            await self.allow_delete.wait()
            await super().adelete(namespace, key)

    backend = PausingDeleteStore()
    store = MemoryThreadMetaStore(backend)
    with _as_user(USER_A):
        original = await store.create("replace-me")
        delete_task = asyncio.create_task(store.delete("replace-me"))
        await backend.delete_entered.wait()
        create_task = asyncio.create_task(store.create("replace-me"))
        await asyncio.sleep(0)
        assert not create_task.done()

        backend.allow_delete.set()
        await delete_task
        replacement = await create_task
        fetched = await store.get("replace-me")

    assert replacement["incarnation"] != original["incarnation"]
    assert fetched == replacement
    assert not store._thread_locks._entries_by_loop


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_search_isolation(store):
    """search() returns only threads owned by the current user."""
    with _as_user(USER_A):
        await store.create("t-alpha", display_name="A's thread")
    with _as_user(USER_B):
        await store.create("t-beta", display_name="B's thread")

    with _as_user(USER_A):
        results = await store.search()
        assert [r["thread_id"] for r in results] == ["t-alpha"]

    with _as_user(USER_B):
        results = await store.search()
        assert [r["thread_id"] for r in results] == ["t-beta"]


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_search_matches_nested_thread_metadata(store):
    with _as_user(USER_A):
        await store.create("root", metadata={})
        await store.create("child", metadata={"branch_parent_thread_id": "root"})
        await store.create("other", metadata={"branch_parent_thread_id": "elsewhere"})

        results = await store.search(metadata={"branch_parent_thread_id": "root"})

    assert [record["thread_id"] for record in results] == ["child"]


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_search_metadata_preserves_json_type_and_presence_contract(store):
    with _as_user(USER_A):
        await store.create("missing", metadata={})
        await store.create("null", metadata={"value": None})
        await store.create("bool", metadata={"value": True})
        await store.create("int", metadata={"value": 1})
        await store.create("float", metadata={"value": 1.0})

        null_hits = await store.search(metadata={"value": None})
        bool_hits = await store.search(metadata={"value": True})
        int_hits = await store.search(metadata={"value": 1})
        float_hits = await store.search(metadata={"value": 1.0})

    assert [record["thread_id"] for record in null_hits] == ["null"]
    assert [record["thread_id"] for record in bool_hits] == ["bool"]
    assert [record["thread_id"] for record in int_hits] == ["int"]
    assert {record["thread_id"] for record in float_hits} == {"float", "int"}


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_update_display_name_can_remove_stale_metadata(store):
    with _as_user(USER_A):
        await store.create(
            "branch",
            display_name="Original (2)",
            metadata={"branch_title_sequence": 2, "keep": True},
        )
        await store.update_display_name(
            "branch",
            "Report Q4",
            remove_metadata_keys=("branch_title_sequence",),
        )
        result = await store.get("branch")

    assert result is not None
    assert result["display_name"] == "Report Q4"
    assert result["metadata"] == {"keep": True}


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_get_isolation(store):
    """get() returns None for threads owned by another user."""
    with _as_user(USER_A):
        await store.create("t-alpha", display_name="A's thread")

    with _as_user(USER_B):
        assert await store.get("t-alpha") is None

    with _as_user(USER_A):
        result = await store.get("t-alpha")
        assert result is not None
        assert result["display_name"] == "A's thread"


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_update_display_name_denied(store):
    """User B cannot rename User A's thread."""
    with _as_user(USER_A):
        await store.create("t-alpha", display_name="original")

    with _as_user(USER_B):
        await store.update_display_name("t-alpha", "hacked")

    with _as_user(USER_A):
        row = await store.get("t-alpha")
        assert row is not None
        assert row["display_name"] == "original"


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_update_status_denied(store):
    """User B cannot change status of User A's thread."""
    with _as_user(USER_A):
        await store.create("t-alpha")

    with _as_user(USER_B):
        await store.update_status("t-alpha", "error")

    with _as_user(USER_A):
        row = await store.get("t-alpha")
        assert row is not None
        assert row["status"] == "idle"


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_update_metadata_denied(store):
    """User B cannot modify metadata of User A's thread."""
    with _as_user(USER_A):
        await store.create("t-alpha", metadata={"key": "original"})

    with _as_user(USER_B):
        await store.update_metadata("t-alpha", {"key": "hacked"})

    with _as_user(USER_A):
        row = await store.get("t-alpha")
        assert row is not None
        assert row["metadata"]["key"] == "original"


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_delete_denied(store):
    """User B cannot delete User A's thread."""
    with _as_user(USER_A):
        await store.create("t-alpha")

    with _as_user(USER_B):
        await store.delete("t-alpha")

    with _as_user(USER_A):
        row = await store.get("t-alpha")
        assert row is not None


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_no_context_raises(store):
    """Calling methods without user context raises RuntimeError."""
    with pytest.raises(RuntimeError, match="no user context is set"):
        await store.search()


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_explicit_none_bypasses_filter(store):
    """user_id=None bypasses isolation (migration/CLI escape hatch)."""
    with _as_user(USER_A):
        await store.create("t-alpha")
    with _as_user(USER_B):
        await store.create("t-beta")

    all_rows = await store.search(user_id=None)
    assert {r["thread_id"] for r in all_rows} == {"t-alpha", "t-beta"}

    row = await store.get("t-alpha", user_id=None)
    assert row is not None


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_create_with_project_id_fails_closed(store):
    """Memory mode has no projects backend; a create carrying a project id
    must fail closed (ProjectNotAssignableError) instead of silently
    persisting an unassigned thread — the router maps the error to 404 and
    the frontend keeps the composer for a retry, matching the SQL store's
    missing/foreign/archived project behavior."""
    with _as_user(USER_A):
        with pytest.raises(ProjectNotAssignableError):
            await store.create("t-proj", project_id="p1")

        # Nothing persisted, and the store's project filter fails closed too.
        assert await store.search() == []
        assert await store.search(project_id="p1") == []

        # Unscoped creates still work.
        await store.create("t-plain")
        assert [r["thread_id"] for r in await store.search()] == ["t-plain"]

        # Membership moves report rejection (never a silent unassign).
        assert await store.set_project("t-plain", "p1") is False
