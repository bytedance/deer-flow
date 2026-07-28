"""Contract tests for the thread-lookup anti-corruption layer.

The port asks one question -- "does this thread exist AND may this user use
it?" -- and deliberately answers both halves with a single bool, so a caller
cannot probe for the existence of threads they cannot see. These tests pin that
the adapter does not accidentally widen it back into two answers.
"""

from __future__ import annotations

import pytest

from app.adapters.schedule.thread_lookup import ThreadStoreThreadLookup


class _RecordingThreadStore:
    """Stands in for `ThreadMetaStore`, recording how it was asked."""

    def __init__(self, owners: dict[str, str] | None = None) -> None:
        self._owners = dict(owners or {})
        self.calls: list[tuple[str, str, bool]] = []

    async def check_access(self, thread_id: str, user_id: str, *, require_existing: bool = False) -> bool:
        self.calls.append((thread_id, user_id, require_existing))
        owner = self._owners.get(thread_id)
        if owner is None:
            # Mirrors the real store: absent rows pass a non-strict check.
            return not require_existing
        return owner == user_id


class TestTheOneQuestion:
    @pytest.mark.asyncio
    async def test_an_owned_thread_exists_for_its_user(self):
        lookup = ThreadStoreThreadLookup(_RecordingThreadStore({"thread-1": "user-1"}))
        assert await lookup.exists_for_user("thread-1", "user-1") is True

    @pytest.mark.asyncio
    async def test_someone_elses_thread_does_not(self):
        lookup = ThreadStoreThreadLookup(_RecordingThreadStore({"thread-1": "user-1"}))
        assert await lookup.exists_for_user("thread-1", "user-2") is False

    @pytest.mark.asyncio
    async def test_a_missing_thread_does_not(self):
        """This is the half `require_existing` buys: without it the store
        treats an absent row as accessible, and a task could be bound to a
        thread that does not exist."""
        lookup = ThreadStoreThreadLookup(_RecordingThreadStore())
        assert await lookup.exists_for_user("thread-nope", "user-1") is False

    @pytest.mark.asyncio
    async def test_missing_and_forbidden_are_indistinguishable(self):
        lookup = ThreadStoreThreadLookup(_RecordingThreadStore({"thread-1": "user-1"}))
        missing = await lookup.exists_for_user("thread-nope", "user-2")
        forbidden = await lookup.exists_for_user("thread-1", "user-2")
        assert missing == forbidden is False


class TestHowTheStoreIsAsked:
    @pytest.mark.asyncio
    async def test_require_existing_is_always_set(self):
        store = _RecordingThreadStore({"thread-1": "user-1"})
        await ThreadStoreThreadLookup(store).exists_for_user("thread-1", "user-1")
        assert store.calls == [("thread-1", "user-1", True)]

    @pytest.mark.asyncio
    async def test_the_result_is_a_real_bool(self):
        """The port is typed `bool`; a truthy row object leaking through would
        satisfy the domain's `if` and still be the wrong contract."""
        store = _RecordingThreadStore({"thread-1": "user-1"})
        assert await ThreadStoreThreadLookup(store).exists_for_user("thread-1", "user-1") is True
