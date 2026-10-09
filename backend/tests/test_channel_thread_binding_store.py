"""Chat-to-thread binding store contract: the legacy JSON file and the shared SQL table.

``ChannelManager`` maps every unbound IM conversation (``channel_name:chat_id[:topic_id]``)
to the DeerFlow thread it runs on. Both stores must implement the semantics the
manager relied on while the mapping was a JSON file: topic keys are independent of
the base chat key, an overwrite keeps ``created_at`` and bumps ``updated_at``,
``remove`` without a topic clears the base mapping and every topic of that chat,
and ``list_entries`` returns the channel/chat/topic components next to the entry.

The SQL store additionally shares that state across every Gateway replica using one
database, which is the whole point of the change (and the red-on-main reproduction
here: two SQL stores over one SQLite file see each other's bindings, two JSON stores
over one file do not — each process loads the file once and clobbers the other's
writes). The one-time import of ``channels/store.json`` into the table is pinned
here too: it runs once, is idempotent, tolerates two replicas importing at the same
time, renames the file afterwards and leaves it alone when the table is already
populated.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import uuid
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from support.postgres import asyncpg_test_url

from app.channels.store import ChannelStore, JsonChannelStore, SqlChannelStore, resolve_channel_store
from deerflow.persistence.base import Base
from deerflow.persistence.channel_thread_bindings import ChannelThreadBinding, ChannelThreadBindingRow, SqlChannelThreadBindingRepository, binding_key, split_binding_key
from deerflow.persistence.channel_thread_bindings.model import CHANNEL_NAME_LENGTH, CHAT_ID_LENGTH, TOPIC_ID_LENGTH, USER_ID_LENGTH
from deerflow.persistence.postgres_schema import build_asyncpg_connect_args

pytestmark = pytest.mark.asyncio


async def _sqlite_engine(path: Path) -> AsyncEngine:
    engine = create_async_engine(f"sqlite+aiosqlite:///{path.as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[ChannelThreadBindingRow.__table__], checkfirst=True)
    return engine


def _sql_store(engine: AsyncEngine, *, legacy_path: Path | None = None) -> SqlChannelStore:
    return SqlChannelStore(async_sessionmaker(engine, expire_on_commit=False), legacy_path=legacy_path)


@pytest_asyncio.fixture(params=["json", "sql"])
async def store(request, tmp_path) -> AsyncIterator[ChannelStore]:
    if request.param == "json":
        yield JsonChannelStore(tmp_path / "store.json")
        return
    engine = await _sqlite_engine(tmp_path / "bindings.db")
    try:
        yield _sql_store(engine)
    finally:
        await engine.dispose()


def _write_legacy(path: Path, entries: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def _legacy_entry(thread_id: str, *, user_id: str = "u", created_at: float = 1_700_000_000.0, updated_at: float | None = None) -> dict:
    return {"thread_id": thread_id, "user_id": user_id, "created_at": created_at, "updated_at": created_at if updated_at is None else updated_at}


# ── key helpers ─────────────────────────────────────────────────────────────


async def test_binding_key_matches_the_legacy_json_key_shape():
    assert binding_key("slack", "C1") == "slack:C1"
    assert binding_key("slack", "C1", "171.1") == "slack:C1:171.1"
    assert binding_key("slack", "C1", "") == "slack:C1"  # an empty topic is "no topic", as the JSON store treated it
    assert binding_key("slack", "C1", None) == "slack:C1"


async def test_split_binding_key_mirrors_the_legacy_list_entries_parsing():
    assert split_binding_key("slack:C1") == ("slack", "C1", None)
    assert split_binding_key("slack:C1:171.1") == ("slack", "C1", "171.1")
    # The legacy format is ambiguous once a chat id carries a colon; the JSON
    # ``list_entries`` split on the first two colons and so does the import.
    assert split_binding_key("github:owner/repo:42:coder") == ("github", "owner/repo", "42:coder")
    assert split_binding_key("broken") == ("broken", "", None)


# ── shared contract ─────────────────────────────────────────────────────────


async def test_set_and_get_thread_id(store):
    await store.set_thread_id("slack", "ch1", "thread-abc", user_id="u1")
    assert await store.get_thread_id("slack", "ch1") == "thread-abc"
    assert await store.get_thread_id("slack", "nonexistent") is None
    assert await store.get_thread_id("slack", "ch1", topic_id="t") is None  # a topic key is not the base key


async def test_topic_mappings_are_independent_of_the_base_mapping(store):
    await store.set_thread_id("test", "chat1", "base-thread")
    await store.set_thread_id("test", "chat1", "topic-thread", topic_id="topic-1")
    await store.set_thread_id("test", "chat1", "topic-thread-2", topic_id="topic-2")
    assert await store.get_thread_id("test", "chat1") == "base-thread"
    assert await store.get_thread_id("test", "chat1", topic_id="topic-1") == "topic-thread"
    assert await store.get_thread_id("test", "chat1", topic_id="topic-2") == "topic-thread-2"
    # An empty topic id means "no topic", exactly as the JSON key builder treated it.
    assert await store.get_thread_id("test", "chat1", topic_id="") == "base-thread"


async def test_overwrite_replaces_thread_and_user_but_preserves_created_at(store):
    await store.set_thread_id("slack", "ch1", "t1", user_id="u1")
    (entry,) = await store.list_entries()
    created_at = entry["created_at"]
    assert entry["updated_at"] == created_at
    await asyncio.sleep(0.002)
    await store.set_thread_id("slack", "ch1", "t2", user_id="u2")
    (entry,) = await store.list_entries()
    assert entry["thread_id"] == "t2"
    assert entry["user_id"] == "u2"
    assert entry["created_at"] == created_at
    assert entry["updated_at"] > created_at


async def test_remove_specific_topic_leaves_the_rest(store):
    await store.set_thread_id("slack", "ch1", "base")
    await store.set_thread_id("slack", "ch1", "topic-a", topic_id="a")
    await store.set_thread_id("slack", "ch1", "topic-b", topic_id="b")
    assert await store.remove("slack", "ch1", topic_id="a") is True
    assert await store.get_thread_id("slack", "ch1", topic_id="a") is None
    assert await store.get_thread_id("slack", "ch1", topic_id="b") == "topic-b"
    assert await store.get_thread_id("slack", "ch1") == "base"
    assert await store.remove("slack", "ch1", topic_id="a") is False


async def test_remove_without_topic_clears_the_base_and_every_topic_of_that_chat_only(store):
    await store.set_thread_id("slack", "ch1", "base")
    await store.set_thread_id("slack", "ch1", "topic-a", topic_id="a")
    await store.set_thread_id("slack", "ch1", "topic-b", topic_id="b:c")
    await store.set_thread_id("slack", "ch10", "other-chat")  # shares the prefix text, not the chat
    await store.set_thread_id("feishu", "ch1", "other-channel")
    assert await store.remove("slack", "ch1") is True
    assert await store.get_thread_id("slack", "ch1") is None
    assert await store.get_thread_id("slack", "ch1", topic_id="a") is None
    assert await store.get_thread_id("slack", "ch1", topic_id="b:c") is None
    assert await store.get_thread_id("slack", "ch10") == "other-chat"
    assert await store.get_thread_id("feishu", "ch1") == "other-channel"
    assert await store.remove("slack", "ch1") is False
    assert await store.remove("slack", "nope") is False


async def test_remove_prefix_treats_like_wildcards_literally(store):
    await store.set_thread_id("slack", "c_1", "underscore")
    await store.set_thread_id("slack", "c%1", "percent")
    await store.set_thread_id("slack", "cx1", "other")
    assert await store.remove("slack", "c_1") is True
    assert await store.get_thread_id("slack", "c_1") is None
    assert await store.get_thread_id("slack", "c%1") == "percent"
    assert await store.get_thread_id("slack", "cx1") == "other"


async def test_list_entries_all_and_filtered_with_the_legacy_shape(store):
    await store.set_thread_id("slack", "ch1", "t1", user_id="u1")
    await store.set_thread_id("feishu", "ch2", "t2", topic_id="om_1", user_id="u2")
    entries = await store.list_entries()
    assert len(entries) == 2
    by_channel = {entry["channel_name"]: entry for entry in entries}
    slack = by_channel["slack"]
    assert set(slack) == {"channel_name", "chat_id", "thread_id", "user_id", "created_at", "updated_at"}
    assert (slack["chat_id"], slack["thread_id"], slack["user_id"]) == ("ch1", "t1", "u1")
    assert isinstance(slack["created_at"], float) and isinstance(slack["updated_at"], float)
    feishu = by_channel["feishu"]
    assert feishu["topic_id"] == "om_1"  # present only for topic mappings
    assert (feishu["chat_id"], feishu["thread_id"], feishu["user_id"]) == ("ch2", "t2", "u2")

    filtered = await store.list_entries(channel_name="slack")
    assert [entry["channel_name"] for entry in filtered] == ["slack"]
    assert await store.list_entries(channel_name="telegram") == []
    assert await store.list_entries() != []


async def test_user_id_defaults_to_an_empty_string(store):
    await store.set_thread_id("slack", "ch1", "t1")
    (entry,) = await store.list_entries()
    assert entry["user_id"] == ""


async def test_entries_survive_a_new_store_instance_over_the_same_storage(tmp_path):
    path = tmp_path / "store.json"
    first = JsonChannelStore(path)
    await first.set_thread_id("slack", "ch1", "t1")
    assert await JsonChannelStore(path).get_thread_id("slack", "ch1") == "t1"

    engine = await _sqlite_engine(tmp_path / "bindings.db")
    try:
        await _sql_store(engine).set_thread_id("slack", "ch1", "t1")
        assert await _sql_store(engine).get_thread_id("slack", "ch1") == "t1"
    finally:
        await engine.dispose()


# ── JSON-specific behaviour kept from the original store ────────────────────


async def test_json_store_corrupt_file_starts_fresh(tmp_path, caplog):
    path = tmp_path / "store.json"
    path.write_text("not json", encoding="utf-8")
    store = JsonChannelStore(path)
    with caplog.at_level(logging.WARNING, logger="app.channels.store"):
        assert await store.get_thread_id("x", "y") is None
    assert "Corrupt channel store" in caplog.text
    await store.set_thread_id("x", "y", "t")
    assert json.loads(path.read_text(encoding="utf-8")) == {"x:y": {"thread_id": "t", "user_id": "", "created_at": pytest.approx(time.time(), abs=60), "updated_at": pytest.approx(time.time(), abs=60)}}


async def test_json_store_construction_is_io_free_and_exposes_the_channels_dir(tmp_path):
    path = tmp_path / "nested" / "channels" / "store.json"
    store = JsonChannelStore(path)
    assert store.channels_dir == path.parent
    assert not path.parent.exists()  # nothing is created or read until the first access


async def test_json_store_concurrent_list_and_mutation(tmp_path, monkeypatch):
    """``list_entries`` snapshots under the lock, so a concurrent writer cannot resize the dict mid-iteration."""
    store = JsonChannelStore(tmp_path / "store.json")
    iteration_started = threading.Event()
    mutation_requested = threading.Event()
    mutation_finished = threading.Event()

    class CoordinatedData(dict):
        def items(self):
            iterator = iter(super().items())
            first = next(iterator)
            iteration_started.set()
            if store._lock.locked():
                assert mutation_requested.wait(timeout=5), "mutation thread never requested the store lock"
            else:
                assert mutation_finished.wait(timeout=5), "mutation thread never changed the unlocked store"
            yield first
            yield from iterator

    store._data = CoordinatedData(
        {
            "slack:ch1": {"thread_id": "t1", "user_id": "u1", "created_at": 1.0, "updated_at": 1.0},
            "feishu:ch2": {"thread_id": "t2", "user_id": "u2", "created_at": 2.0, "updated_at": 2.0},
        }
    )
    monkeypatch.setattr(store, "_save", lambda: None)

    def mutate():
        assert iteration_started.wait(timeout=5), "list_entries never started iterating"
        mutation_requested.set()
        asyncio.run(store.set_thread_id("test", "new", "t3"))
        mutation_finished.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        list_future = executor.submit(lambda: asyncio.run(store.list_entries()))
        mutation_future = executor.submit(mutate)
        mutation_future.result(timeout=5)
        entries = list_future.result(timeout=5)

    assert {(entry["channel_name"], entry["chat_id"]) for entry in entries} == {("slack", "ch1"), ("feishu", "ch2")}


# ── the multi-replica reproduction ──────────────────────────────────────────


async def test_two_json_stores_over_one_file_do_not_see_each_other(tmp_path):
    """Today's bug: each Gateway process loads ``store.json`` once and rewrites the
    whole file on every change, so a binding created on replica A is invisible to
    replica B (B creates a second thread for the same chat) and B's next write
    clobbers A's binding on disk."""
    path = tmp_path / "store.json"
    replica_a = JsonChannelStore(path)
    replica_b = JsonChannelStore(path)
    assert await replica_b.get_thread_id("slack", "C1") is None  # B has loaded (an empty) file

    await replica_a.set_thread_id("slack", "C1", "thread-from-a")
    assert await replica_b.get_thread_id("slack", "C1") is None  # invisible to B

    await replica_b.set_thread_id("slack", "C2", "thread-from-b")
    assert json.loads(path.read_text(encoding="utf-8")).keys() == {"slack:C2"}  # A's binding clobbered on disk
    assert await JsonChannelStore(path).get_thread_id("slack", "C1") is None


async def test_two_sql_stores_over_one_database_share_every_binding(tmp_path):
    engine_a = await _sqlite_engine(tmp_path / "bindings.db")
    engine_b = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'bindings.db').as_posix()}")
    try:
        replica_a, replica_b = _sql_store(engine_a), _sql_store(engine_b)
        assert await replica_b.get_thread_id("slack", "C1") is None

        await replica_a.set_thread_id("slack", "C1", "thread-from-a", user_id="u1")
        assert await replica_b.get_thread_id("slack", "C1") == "thread-from-a"

        await replica_b.set_thread_id("slack", "C2", "thread-from-b")
        assert await replica_a.get_thread_id("slack", "C1") == "thread-from-a"
        assert await replica_a.get_thread_id("slack", "C2") == "thread-from-b"
        assert {entry["chat_id"] for entry in await replica_a.list_entries()} == {"C1", "C2"}

        assert await replica_b.remove("slack", "C1") is True
        assert await replica_a.get_thread_id("slack", "C1") is None
    finally:
        await engine_a.dispose()
        await engine_b.dispose()


async def test_concurrent_set_from_two_sql_stores_keeps_one_row_per_key(tmp_path):
    engine = await _sqlite_engine(tmp_path / "bindings.db")
    try:
        stores = [_sql_store(engine) for _ in range(2)]
        await asyncio.gather(*(store.set_thread_id("slack", "C1", f"thread-{i}", topic_id="t") for i, store in enumerate(stores)))
        entries = await stores[0].list_entries()
        assert len(entries) == 1
        assert entries[0]["thread_id"] in {"thread-0", "thread-1"}
    finally:
        await engine.dispose()


# ── one-time import of channels/store.json ──────────────────────────────────


async def test_import_moves_every_legacy_entry_into_the_table_and_renames_the_file(tmp_path, caplog):
    path = tmp_path / "channels" / "store.json"
    _write_legacy(
        path,
        {
            "slack:C1": _legacy_entry("thread-1", user_id="U1", created_at=1_700_000_000.0, updated_at=1_700_000_100.5),
            "feishu:oc_1:om_1": _legacy_entry("thread-2", user_id="ou_1"),
            "github:owner/repo:42:coder": _legacy_entry("thread-3", user_id=""),
        },
    )
    engine = await _sqlite_engine(tmp_path / "bindings.db")
    try:
        store = _sql_store(engine, legacy_path=path)
        assert store.channels_dir == path.parent
        with caplog.at_level(logging.INFO, logger="app.channels.store"):
            assert await store.import_legacy_json() == 3
        assert "3" in caplog.text and "store.json" in caplog.text

        assert await store.get_thread_id("slack", "C1") == "thread-1"
        assert await store.get_thread_id("feishu", "oc_1", topic_id="om_1") == "thread-2"
        assert await store.get_thread_id("github", "owner/repo", topic_id="42:coder") == "thread-3"
        entries = {binding_key(e["channel_name"], e["chat_id"], e.get("topic_id")): e for e in await store.list_entries()}
        assert entries["slack:C1"]["user_id"] == "U1"
        assert entries["slack:C1"]["created_at"] == 1_700_000_000.0
        assert entries["slack:C1"]["updated_at"] == 1_700_000_100.5  # lossless: the stamps are copied, not regenerated
        assert entries["feishu:oc_1:om_1"]["topic_id"] == "om_1"
        assert entries["github:owner/repo:42:coder"]["chat_id"] == "owner/repo"

        assert not path.exists()
        migrated = path.with_name("store.json.migrated")
        assert set(json.loads(migrated.read_text(encoding="utf-8"))) == {"slack:C1", "feishu:oc_1:om_1", "github:owner/repo:42:coder"}

        # A second start finds no file: nothing to do.
        assert await store.import_legacy_json() == 0
        assert len(await store.list_entries()) == 3
    finally:
        await engine.dispose()


async def test_import_leaves_the_file_alone_when_the_table_is_already_populated(tmp_path, caplog):
    path = tmp_path / "channels" / "store.json"
    _write_legacy(path, {"slack:C1": _legacy_entry("thread-from-file")})
    engine = await _sqlite_engine(tmp_path / "bindings.db")
    try:
        store = _sql_store(engine, legacy_path=path)
        await store.set_thread_id("slack", "C9", "thread-from-db")
        with caplog.at_level(logging.INFO, logger="app.channels.store"):
            assert await store.import_legacy_json() == 0
        assert path.exists()  # kept for the operator; a populated table is the source of truth
        assert not path.with_name("store.json.migrated").exists()
        assert await store.get_thread_id("slack", "C1") is None
        assert "already" in caplog.text
    finally:
        await engine.dispose()


async def test_import_without_a_file_or_without_a_legacy_path_is_a_no_op(tmp_path):
    engine = await _sqlite_engine(tmp_path / "bindings.db")
    try:
        assert await _sql_store(engine, legacy_path=tmp_path / "missing" / "store.json").import_legacy_json() == 0
        assert await _sql_store(engine).import_legacy_json() == 0
        assert await _sql_store(engine).list_entries() == []
    finally:
        await engine.dispose()


async def test_import_keeps_a_corrupt_or_malformed_file_and_skips_bad_entries(tmp_path, caplog):
    engine = await _sqlite_engine(tmp_path / "bindings.db")
    try:
        corrupt = tmp_path / "corrupt" / "store.json"
        corrupt.parent.mkdir(parents=True)
        corrupt.write_text("not json", encoding="utf-8")
        with caplog.at_level(logging.WARNING, logger="app.channels.store"):
            assert await _sql_store(engine, legacy_path=corrupt).import_legacy_json() == 0
        assert corrupt.exists()
        # Import-path wording: nothing "starts fresh" here, the file is kept and the import skipped.
        assert "Corrupt legacy channel store at" in caplog.text and "skipping the import (file kept)" in caplog.text
        assert "starting fresh" not in caplog.text

        partial = tmp_path / "partial" / "store.json"
        _write_legacy(
            partial,
            {
                "slack:C1": _legacy_entry("good"),
                "slack:C2": {"user_id": "no-thread"},  # no thread_id: skipped
                "slack:C3": "not-a-dict",  # skipped
                "slack:C4": {"thread_id": "stampless"},  # missing stamps and user_id get defaults
            },
        )
        store = _sql_store(engine, legacy_path=partial)
        with caplog.at_level(logging.WARNING, logger="app.channels.store"):
            assert await store.import_legacy_json() == 2
        assert "Skipping 2 malformed or oversized entries" in caplog.text
        assert await store.get_thread_id("slack", "C1") == "good"
        assert await store.get_thread_id("slack", "C2") is None
        assert await store.get_thread_id("slack", "C3") is None
        (c4,) = [e for e in await store.list_entries() if e["chat_id"] == "C4"]
        assert c4["user_id"] == "" and c4["created_at"] == pytest.approx(time.time(), abs=60) and c4["updated_at"] == c4["created_at"]
        assert not partial.exists() and partial.with_name("store.json.migrated").exists()
    finally:
        await engine.dispose()


async def test_import_skips_oversized_components_instead_of_failing_the_whole_import(tmp_path, caplog):
    """A key component longer than its column would make PostgreSQL reject the batch
    (``value too long for type character varying``) and take every IM channel down
    with the failed ``ChannelService.start()``; SQLite would silently accept it, so
    the two backends diverged on the same file. Oversized entries are skipped and
    counted with the malformed ones; the rest import and the file is still renamed."""
    path = tmp_path / "channels" / "store.json"
    _write_legacy(
        path,
        {
            "slack:C1": _legacy_entry("thread-1"),
            f"slack:{'c' * (CHAT_ID_LENGTH + 1)}": _legacy_entry("thread-long-chat"),
            f"slack:C2:{'t' * (TOPIC_ID_LENGTH + 1)}": _legacy_entry("thread-long-topic"),
            "slack:C3": _legacy_entry("thread-3"),
            f"{'x' * (CHANNEL_NAME_LENGTH + 1)}:C4": _legacy_entry("thread-long-channel"),
            "slack:C5": _legacy_entry("u" * (USER_ID_LENGTH + 1), user_id="u" * (USER_ID_LENGTH + 1)),
        },
    )
    engine = await _sqlite_engine(tmp_path / "bindings.db")
    try:
        store = _sql_store(engine, legacy_path=path)
        with caplog.at_level(logging.WARNING, logger="app.channels.store"):
            assert await store.import_legacy_json() == 2
        assert "Skipping 4 malformed or oversized entries" in caplog.text
        assert await store.get_thread_id("slack", "C1") == "thread-1"
        assert await store.get_thread_id("slack", "C3") == "thread-3"
        assert await store.get_thread_id("slack", "c" * (CHAT_ID_LENGTH + 1)) is None
        assert await store.get_thread_id("slack", "C2", topic_id="t" * (TOPIC_ID_LENGTH + 1)) is None
        assert len(await store.list_entries()) == 2
        assert not path.exists() and path.with_name("store.json.migrated").exists()
    finally:
        await engine.dispose()


async def test_sqlite_accepts_an_oversized_row_so_the_import_validator_is_the_only_guard(tmp_path):
    """Why the validator matters: SQLite ignores ``String(n)``, so without it the same
    file imports cleanly on SQLite and fails on PostgreSQL."""
    engine = await _sqlite_engine(tmp_path / "bindings.db")
    try:
        repo = SqlChannelThreadBindingRepository(async_sessionmaker(engine, expire_on_commit=False))
        oversized = ChannelThreadBinding.build("slack", "c" * (CHAT_ID_LENGTH + 1), "thread-x", now=1.0)
        assert await repo.insert_missing([oversized]) == 1
        assert await repo.get_thread_id(oversized.key) == "thread-x"
    finally:
        await engine.dispose()


async def test_concurrent_import_from_two_replicas_yields_no_duplicates_and_tolerates_the_lost_rename(tmp_path, caplog):
    path = tmp_path / "channels" / "store.json"
    _write_legacy(path, {f"slack:C{i}": _legacy_entry(f"thread-{i}") for i in range(25)})
    engine_a = await _sqlite_engine(tmp_path / "bindings.db")
    engine_b = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'bindings.db').as_posix()}")
    try:
        replica_a, replica_b = _sql_store(engine_a, legacy_path=path), _sql_store(engine_b, legacy_path=path)
        with caplog.at_level(logging.INFO, logger="app.channels.store"):
            counts = await asyncio.gather(replica_a.import_legacy_json(), replica_b.import_legacy_json())
        assert sum(counts) == 25  # every row inserted exactly once between the two
        assert len(await replica_a.list_entries()) == 25
        assert not path.exists()
        assert path.with_name("store.json.migrated").exists()
        assert "ERROR" not in caplog.text
    finally:
        await engine_a.dispose()
        await engine_b.dispose()


async def test_repository_insert_missing_never_duplicates_or_overwrites(tmp_path):
    """The import primitive: ``INSERT ... ON CONFLICT DO NOTHING`` in batches, reporting only what it inserted."""
    engine = await _sqlite_engine(tmp_path / "bindings.db")
    try:
        repo = SqlChannelThreadBindingRepository(async_sessionmaker(engine, expire_on_commit=False))
        store = _sql_store(engine)
        await store.set_thread_id("slack", "C1", "live-thread", user_id="live")
        rows = [ChannelThreadBinding.build("slack", f"C{i}", f"thread-{i}", user_id="imported", now=1.0) for i in range(1, 1201)]
        assert await repo.insert_missing(rows) == 1199
        assert await repo.insert_missing(rows) == 0
        assert await repo.count() == 1200
        assert await store.get_thread_id("slack", "C1") == "live-thread"  # DO NOTHING: the live row wins
    finally:
        await engine.dispose()


# ── selection ───────────────────────────────────────────────────────────────


class _Config:
    def __init__(self, backend: str) -> None:
        self.database = type("Database", (), {"backend": backend})()


async def test_resolve_channel_store_picks_json_for_memory_and_sql_for_a_database(tmp_path, caplog):
    path = tmp_path / "store.json"
    assert isinstance(resolve_channel_store(None, path=path), JsonChannelStore)
    assert isinstance(resolve_channel_store(_Config("memory"), session_factory=object(), path=path), JsonChannelStore)
    for backend in ("sqlite", "postgres"):
        store = resolve_channel_store(_Config(backend), session_factory=object(), path=path)
        assert isinstance(store, SqlChannelStore)
        assert store.channels_dir == path.parent
    with caplog.at_level(logging.WARNING, logger="app.channels.store"):
        fallback = resolve_channel_store(_Config("sqlite"), session_factory=None, path=path)
    assert isinstance(fallback, JsonChannelStore)
    assert "no persistence engine" in caplog.text


async def test_resolve_channel_store_uses_the_process_engine_by_default(tmp_path, monkeypatch):
    from deerflow.persistence import engine as engine_module

    path = tmp_path / "store.json"
    monkeypatch.setattr(engine_module, "get_session_factory", lambda: object())
    assert isinstance(resolve_channel_store(_Config("postgres"), path=path), SqlChannelStore)
    monkeypatch.setattr(engine_module, "get_session_factory", lambda: None)
    assert isinstance(resolve_channel_store(_Config("postgres"), path=path), JsonChannelStore)


# ── ChannelService wiring ───────────────────────────────────────────────────


async def test_channel_service_start_imports_the_legacy_file_once_for_the_sql_store(tmp_path):
    from app.channels.service import ChannelService

    path = tmp_path / "channels" / "store.json"
    _write_legacy(path, {"slack:C1": _legacy_entry("thread-1", user_id="U1")})
    engine = await _sqlite_engine(tmp_path / "bindings.db")
    try:
        service = ChannelService(channels_config={}, store=_sql_store(engine, legacy_path=path))
        assert service.manager.store is service.store
        await service.start()
        try:
            assert await service.store.get_thread_id("slack", "C1") == "thread-1"
            assert not path.exists() and path.with_name("store.json.migrated").exists()
        finally:
            await service.stop()
        # A restart of the service (or a peer starting later) imports nothing more.
        _write_legacy(path, {"slack:C2": _legacy_entry("thread-2")})
        service = ChannelService(channels_config={}, store=_sql_store(engine, legacy_path=path))
        await service.start()
        try:
            assert await service.store.get_thread_id("slack", "C2") is None
            assert path.exists()
        finally:
            await service.stop()
    finally:
        await engine.dispose()


async def test_channel_service_start_leaves_a_json_store_untouched(tmp_path):
    from app.channels.service import ChannelService

    path = tmp_path / "channels" / "store.json"
    _write_legacy(path, {"slack:C1": _legacy_entry("thread-1")})
    service = ChannelService(channels_config={}, store=JsonChannelStore(path))
    await service.start()
    try:
        assert await service.store.get_thread_id("slack", "C1") == "thread-1"
        assert path.exists()
    finally:
        await service.stop()


async def test_channel_service_defaults_to_the_json_store_without_a_database(tmp_path, monkeypatch):
    from app.channels import store as store_module
    from app.channels.service import ChannelService

    monkeypatch.setattr(store_module, "default_store_path", lambda: tmp_path / "channels" / "store.json")
    service = ChannelService(channels_config={})
    assert isinstance(service.store, JsonChannelStore)
    assert service.store.path == tmp_path / "channels" / "store.json"
    assert isinstance(ChannelService(channels_config={}, app_config=_Config("memory")).store, JsonChannelStore)


# ── PostgreSQL (opt-in) ─────────────────────────────────────────────────────


async def test_sql_store_round_trips_on_postgres(tmp_path):
    uri = os.environ.get("TEST_POSTGRES_URI")
    if not uri:
        pytest.skip("requires TEST_POSTGRES_URI (real Postgres channel_thread_bindings)")
    schema = f"ctb_{uuid.uuid4().hex}"
    engine = create_async_engine(asyncpg_test_url(uri), connect_args=build_asyncpg_connect_args(schema))
    try:
        async with engine.begin() as conn:
            await conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
            await conn.run_sync(Base.metadata.create_all, tables=[ChannelThreadBindingRow.__table__])
        path = tmp_path / "store.json"
        _write_legacy(path, {"slack:C0": _legacy_entry("imported")})
        store = _sql_store(engine, legacy_path=path)
        assert await store.import_legacy_json() == 1
        await store.set_thread_id("slack", "C1", "t1", user_id="u1")
        await store.set_thread_id("slack", "C1", "t2", user_id="u2")
        await store.set_thread_id("slack", "C1", "topic", topic_id="x")
        assert await store.get_thread_id("slack", "C0") == "imported"
        assert await store.get_thread_id("slack", "C1") == "t2"
        assert len(await store.list_entries(channel_name="slack")) == 3
        assert await store.remove("slack", "C1") is True
        assert await store.list_entries() == [{"channel_name": "slack", "chat_id": "C0", "thread_id": "imported", "user_id": "u", "created_at": 1_700_000_000.0, "updated_at": 1_700_000_000.0}]
    finally:
        async with engine.begin() as conn:
            await conn.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()
