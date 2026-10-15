"""Tests for the shared-persistence writer (thread_meta visibility).

Uses the in-memory ThreadMetaStore so no SQL engine is required, but exercises
the real async store + background-loop wiring used by the TUI.
"""

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
