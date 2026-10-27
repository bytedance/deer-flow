"""Tests for the shared-persistence writer (thread_meta visibility).

Uses the in-memory ThreadMetaStore so no SQL engine is required, but exercises
the real async store + background-loop wiring used by the TUI.
"""

import asyncio
import threading

import pytest
from langgraph.store.memory import InMemoryStore

from deerflow.persistence.thread_meta import make_thread_store
from deerflow.tui.persistence import ThreadMetaWriter, _LoopThread


@pytest.fixture
def writer_store_loop():
    loop = _LoopThread()
    store = make_thread_store(None, store=InMemoryStore())
    writer = ThreadMetaWriter(loop, store)
    try:
        yield writer, store, loop
    finally:
        loop.close()


def test_writer_is_enabled_with_a_store(writer_store_loop):
    writer, _store, _loop = writer_store_loop
    assert writer.enabled is True
    assert writer.user_id == "default"


def test_ensure_created_writes_row_owned_by_default_user(writer_store_loop):
    writer, store, loop = writer_store_loop
    writer.ensure_created("th-1", assistant_id="lead-agent", metadata={"source": "tui"})
    rows = loop.run(store.search(user_id="default"))
    assert "th-1" in [r["thread_id"] for r in rows]


def test_ensure_created_is_idempotent(writer_store_loop):
    writer, store, loop = writer_store_loop
    writer.ensure_created("th-1")
    writer.ensure_created("th-1")
    rows = loop.run(store.search(user_id="default"))
    assert sum(1 for r in rows if r["thread_id"] == "th-1") == 1


def test_set_title_updates_display_name(writer_store_loop):
    writer, store, loop = writer_store_loop
    writer.ensure_created("th-1")
    writer.set_title("th-1", "Refactor the bridge")
    row = loop.run(store.get("th-1", user_id="default"))
    assert row["display_name"] == "Refactor the bridge"


def test_disabled_writer_is_a_silent_noop():
    loop = _LoopThread()
    try:
        writer = ThreadMetaWriter(loop, None)
        assert writer.enabled is False
        # Must not raise even though there is no store.
        writer.ensure_created("x", assistant_id="lead-agent")
        writer.set_title("x", "title")
    finally:
        loop.close()


def test_loop_timeout_cancels_pending_coroutine():
    loop = _LoopThread()
    release = asyncio.Event()
    started = threading.Event()
    cancelled = threading.Event()
    finished = threading.Event()

    async def pending_write():
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        finally:
            finished.set()

    try:
        with pytest.raises(TimeoutError):
            loop.run(pending_write(), timeout=0.1)
        assert started.wait(2)
        assert cancelled.wait(2), "the timed-out coroutine is still running"
    finally:
        loop._loop.call_soon_threadsafe(release.set)
        assert finished.wait(2)
        loop.run(asyncio.sleep(0))
        loop.close()
        loop._thread.join(timeout=2)
        assert not loop._thread.is_alive()
        loop._loop.close()


def test_timed_out_title_write_cannot_resume_after_newer_title(writer_store_loop, monkeypatch):
    writer, store, loop = writer_store_loop
    writer.ensure_created("th-timeout")
    release = asyncio.Event()
    started = threading.Event()
    finished = threading.Event()
    original_update = store.update_display_name
    original_run = loop.run

    async def delayed_update(thread_id, title, **kwargs):
        if title == "old title":
            started.set()
            try:
                await release.wait()
                return await original_update(thread_id, title, **kwargs)
            finally:
                finished.set()
        return await original_update(thread_id, title, **kwargs)

    def short_run(coro):
        return original_run(coro, timeout=0.1)

    monkeypatch.setattr(store, "update_display_name", delayed_update)
    monkeypatch.setattr(loop, "run", short_run)
    try:
        # ThreadMetaWriter intentionally swallows the bridge timeout.
        writer.set_title("th-timeout", "old title")
        assert started.wait(2)
        writer.set_title("th-timeout", "new title")
        loop._loop.call_soon_threadsafe(release.set)
        assert finished.wait(2)
        row = original_run(store.get("th-timeout", user_id="default"))
        assert row["display_name"] == "new title"
    finally:
        loop._loop.call_soon_threadsafe(release.set)
        assert finished.wait(2)
        original_run(asyncio.sleep(0))


@pytest.mark.parametrize("error_type", [TimeoutError, ValueError])
def test_loop_preserves_coroutine_errors(error_type):
    loop = _LoopThread()
    error = error_type("operation failed")

    async def fail():
        raise error

    try:
        with pytest.raises(error_type) as exc:
            loop.run(fail())
        assert str(exc.value) == "operation failed"
        assert loop.run(asyncio.sleep(0, result="still usable")) == "still usable"
    finally:
        loop.close()
        loop._thread.join(timeout=2)
        assert not loop._thread.is_alive()
        loop._loop.close()
