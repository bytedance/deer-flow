"""Cross-user thread cleanup regression tests.

These tests strengthen acceptance item 24.5 by proving that deleting one
user's thread data does not leak or erase another user's persisted state.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

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


async def _make_engines(tmp_path):
    from deerflow.persistence.engine import close_engine, init_engine

    url = f"sqlite+aiosqlite:///{tmp_path / 'cleanup_isolation.db'}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    return close_engine


@pytest.mark.anyio
@pytest.mark.no_auto_user
async def test_thread_delete_is_user_isolated(tmp_path):
    from deerflow.persistence.engine import get_session_factory
    from deerflow.persistence.run import RunRepository
    from deerflow.persistence.thread_meta import ThreadMetaRepository
    from deerflow.runtime.events.store.db import DbRunEventStore

    cleanup = await _make_engines(tmp_path)
    try:
        thread_repo = ThreadMetaRepository(get_session_factory())
        run_repo = RunRepository(get_session_factory())
        event_store = DbRunEventStore(get_session_factory())

        with _as_user(USER_A):
            await thread_repo.create("thread-a", display_name="A thread")
            await run_repo.put("run-a", thread_id="thread-a")
            await event_store.put(
                thread_id="thread-a",
                run_id="run-a",
                event_type="human_message",
                category="message",
                content="A private message",
            )

        with _as_user(USER_B):
            await thread_repo.create("thread-b", display_name="B thread")
            await run_repo.put("run-b", thread_id="thread-b")
            await event_store.put(
                thread_id="thread-b",
                run_id="run-b",
                event_type="human_message",
                category="message",
                content="B private message",
            )

        with _as_user(USER_A):
            await thread_repo.delete("thread-a")
            await run_repo.delete("run-a")
            removed = await event_store.delete_by_thread("thread-a")
            assert removed == 1

        with _as_user(USER_A):
            assert await thread_repo.get("thread-a") is None
            assert await run_repo.get("run-a") is None
            assert await event_store.list_messages("thread-a") == []

        with _as_user(USER_B):
            row = await thread_repo.get("thread-b")
            assert row is not None
            assert row["display_name"] == "B thread"
            run = await run_repo.get("run-b")
            assert run is not None
            msgs = await event_store.list_messages("thread-b")
            assert len(msgs) == 1
            assert msgs[0]["content"] == "B private message"
    finally:
        await cleanup()
