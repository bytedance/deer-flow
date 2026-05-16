"""Owner isolation tests for MemoryThreadMetaStore.

Mirrors the SQL-backed tests in test_owner_isolation.py but exercises
the in-memory LangGraph Store backend used when database.backend=memory.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from langgraph.store.memory import InMemoryStore

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
