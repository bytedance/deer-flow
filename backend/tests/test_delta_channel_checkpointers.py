"""DeltaChannel migration, replay, and storage-shape contracts on real saver backends.

These tests pin the LangGraph 1.2 DeltaChannel upgrade path that production
relies on:

- full -> delta migration on the same thread (old plain-value blobs seed the
  delta channel transparently),
- deterministic materialization with stable message ids (ids are stamped into
  the persisted writes by ``put_writes``/``ensure_message_ids``),
- the on-disk storage shape (non-snapshot checkpoints omit ``messages`` from
  ``channel_values``; snapshot checkpoints store a ``_DeltaSnapshot`` blob),
- non-Delta raw writers (goal / run-duration metadata / interrupted-title
  helper) preserving Delta ancestry and the downgrade markers.

Every contract runs against InMemorySaver, AsyncSqliteSaver, and - when
``TEST_POSTGRES_URI`` is set - AsyncPostgresSaver, because each backend
implements blob/version handling slightly differently.

Two further tests pin currently-unfixed upstream defects (langgraph #8382
parallel-superstep replay order, #8448 Postgres paginated delta walk). They
assert the correct contract and trip - skip, naming the issue - while the
defect is present, becoming live gates once a dependency bump lands a fix. The
#8448 trip is scoped to the Postgres parameter, the only backend that pages its
stage-1 scan: on memory/sqlite it stays a live differential assertion against
``InMemorySaver``, so a regression there fails instead of blaming the
Postgres-only upstream issue.
"""

from __future__ import annotations

import os
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from types import SimpleNamespace
from typing import Annotated, Any, TypedDict
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, RemoveMessage
from langgraph.channels import DeltaChannel
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.types import _DeltaSnapshot
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Overwrite

from deerflow.agents.goal_state import GoalState
from deerflow.agents.thread_state import DeltaThreadState, merge_message_writes
from deerflow.config.database_config import DEFAULT_CHECKPOINT_SNAPSHOT_FREQUENCY
from deerflow.persistence.postgres_schema import dsn_with_search_path, normalize_libpq_dsn
from deerflow.runtime.checkpoint_mode import CHECKPOINT_MODE_METADATA_KEY, checkpoint_tuple_uses_delta
from deerflow.runtime.checkpoint_state import CheckpointStateAccessor
from deerflow.runtime.goal import write_thread_goal
from deerflow.runtime.runs.worker import _ensure_interrupted_title, persist_run_durations


class FullState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


class DeltaState(TypedDict):
    messages: Annotated[
        list[AnyMessage],
        DeltaChannel(merge_message_writes, snapshot_frequency=2),
    ]


def _thread_id() -> str:
    return f"delta-contract-{uuid4().hex}"


def _config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


def _noop(state: dict[str, Any]) -> dict[str, Any]:
    return {}


def _build_graph(schema: Any, checkpointer: Any) -> Any:
    builder = StateGraph(schema)
    builder.add_node("noop", _noop)
    builder.set_entry_point("noop")
    builder.set_finish_point("noop")
    return builder.compile(checkpointer=checkpointer)


def _goal(objective: str) -> GoalState:
    return {
        "objective": objective,
        "status": "active",
        "created_at": "2026-07-18T00:00:00+00:00",
        "updated_at": "2026-07-18T00:00:00+00:00",
        "continuation_count": 0,
        "max_continuations": 3,
        "no_progress_count": 0,
        "max_no_progress_continuations": 2,
    }


class _SaverEnv:
    """One saver instance with a reopen() that simulates a process restart.

    Reopening swaps in a brand-new saver over the same bytes (SQLite file or
    Postgres schema) so replay-after-reopen contracts prove persistence, not
    in-process caching. InMemorySaver keeps no external bytes, so reopen is a
    no-op stand-in there.
    """

    def __init__(self, kind: str, open_saver: Callable[[], Any]) -> None:
        self.kind = kind
        self._open_saver = open_saver
        self._cm: Any | None = None
        self.saver: Any | None = None

    async def __aenter__(self) -> _SaverEnv:
        self._cm = self._open_saver()
        self.saver = await self._cm.__aenter__()
        setup = getattr(self.saver, "setup", None)
        if setup is not None:
            await setup()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._cm is not None:
            await self._cm.__aexit__(*exc)
            self._cm = None
            self.saver = None

    async def reopen(self) -> None:
        if self.kind == "memory":
            return
        await self._cm.__aexit__(None, None, None)
        self._cm = self._open_saver()
        self.saver = await self._cm.__aenter__()


@asynccontextmanager
async def _open_sqlite(db_path: Any) -> AsyncIterator[Any]:
    async with AsyncSqliteSaver.from_conn_string(str(db_path)) as saver:
        await saver.setup()
        yield saver


@asynccontextmanager
async def _open_postgres(uri: str) -> AsyncIterator[Any]:
    aio = pytest.importorskip("langgraph.checkpoint.postgres.aio", reason="postgres extra not installed")
    async with aio.AsyncPostgresSaver.from_conn_string(uri) as saver:
        await saver.setup()
        yield saver


@asynccontextmanager
async def _owned_postgres_schema(uri: str) -> AsyncIterator[str]:
    import psycopg
    from psycopg import sql

    postgres_uri = normalize_libpq_dsn(uri)
    schema = f"delta_contract_{uuid4().hex}"
    creation_attempted = False
    try:
        async with await psycopg.AsyncConnection.connect(postgres_uri, autocommit=True) as conn:
            creation_attempted = True
            await conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        yield dsn_with_search_path(postgres_uri, schema)
    finally:
        original_error = sys.exception()
        try:
            if creation_attempted:
                async with await psycopg.AsyncConnection.connect(postgres_uri, autocommit=True) as conn:
                    await conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
        except BaseException as cleanup_error:
            if original_error is not None:
                raise BaseExceptionGroup("Delta fixture schema cleanup failures", [original_error, cleanup_error])
            raise


@pytest.fixture(params=["memory", "sqlite", "postgres"])
async def saver_env(request: pytest.FixtureRequest, tmp_path: Any) -> AsyncIterator[_SaverEnv]:
    async with AsyncExitStack() as resources:
        kind = request.param
        if kind == "memory":
            saver = InMemorySaver()

            @asynccontextmanager
            async def open_memory() -> AsyncIterator[Any]:
                yield saver

            open_saver = open_memory
        elif kind == "sqlite":
            db_path = tmp_path / "delta-contract.sqlite"

            def open_sqlite() -> Any:
                return _open_sqlite(db_path)

            open_saver = open_sqlite
        else:
            uri = os.environ.get("TEST_POSTGRES_URI")
            if not uri:
                pytest.skip("TEST_POSTGRES_URI is not set")

            scoped_uri = await resources.enter_async_context(_owned_postgres_schema(uri))

            def open_postgres() -> Any:
                return _open_postgres(scoped_uri)

            open_saver = open_postgres

        async with _SaverEnv(kind, open_saver) as env:
            yield env


@pytest.mark.anyio
async def test_full_to_delta_migration_replays_on_same_thread(saver_env: _SaverEnv) -> None:
    """A thread written by a full (pre-delta) graph must keep replaying after
    the process swaps to a delta graph: the old plain-value ``messages`` blob
    seeds the delta channel, and later delta writes append on top."""
    thread_id = _thread_id()
    config = _config(thread_id)

    full_graph = _build_graph(FullState, saver_env.saver)
    await full_graph.ainvoke({"messages": [HumanMessage(id="h1", content="seed from full mode")]}, config)

    delta_graph = _build_graph(DeltaState, saver_env.saver)
    delta_accessor = CheckpointStateAccessor.bind(delta_graph, saver_env.saver, mode="delta")

    migrated = await delta_accessor.aget(config)
    assert [m.id for m in migrated.values["messages"]] == ["h1"]
    assert migrated.values["messages"][0].content == "seed from full mode"

    await delta_graph.ainvoke({"messages": [AIMessage(id="a1", content="delta reply")]}, config)

    await saver_env.reopen()
    delta_graph = _build_graph(DeltaState, saver_env.saver)
    delta_accessor = CheckpointStateAccessor.bind(delta_graph, saver_env.saver, mode="delta")

    replayed = await delta_accessor.aget(config)
    assert [m.id for m in replayed.values["messages"]] == ["h1", "a1"]
    assert [m.content for m in replayed.values["messages"]] == ["seed from full mode", "delta reply"]


@pytest.mark.anyio
async def test_materialization_is_deterministic_and_message_ids_are_stable(saver_env: _SaverEnv) -> None:
    """Materializing the same thread twice - and once more after a saver
    reopen - must produce identical values, and the id LangGraph stamps onto
    an id-less message must survive persistence so it can drive RemoveMessage."""
    thread_id = _thread_id()
    config = _config(thread_id)
    graph = _build_graph(DeltaState, saver_env.saver)
    accessor = CheckpointStateAccessor.bind(graph, saver_env.saver, mode="delta")

    await graph.ainvoke({"messages": [HumanMessage(content="no id on purpose")]}, config)

    first = await accessor.aget(config)
    second = await accessor.aget(config)
    assert first.values == second.values

    persisted_id = first.values["messages"][0].id
    assert persisted_id

    await saver_env.reopen()
    graph = _build_graph(DeltaState, saver_env.saver)
    accessor = CheckpointStateAccessor.bind(graph, saver_env.saver, mode="delta")

    reopened = await accessor.aget(config)
    assert reopened.values == first.values
    assert reopened.values["messages"][0].id == persisted_id

    await graph.ainvoke({"messages": [RemoveMessage(id=persisted_id)]}, config)
    after_remove = await accessor.aget(config)
    assert after_remove.values["messages"] == []


@pytest.mark.anyio
async def test_delta_storage_shape_and_snapshot_cadence(saver_env: _SaverEnv) -> None:
    """Non-snapshot checkpoints must not carry ``messages`` in channel_values
    (that is the whole storage win); every ``snapshot_frequency`` updates the
    checkpoint carries a ``_DeltaSnapshot`` blob instead, and materialization
    stays correct across both shapes."""
    thread_id = _thread_id()
    config = _config(thread_id)
    graph = _build_graph(DeltaState, saver_env.saver)
    accessor = CheckpointStateAccessor.bind(graph, saver_env.saver, mode="delta")

    await graph.ainvoke({"messages": [HumanMessage(id="m1", content="one")]}, config)
    first_tuple = await saver_env.saver.aget_tuple(config)
    assert first_tuple is not None
    assert "messages" not in first_tuple.checkpoint["channel_values"]
    # The node's output persists as pending writes attached to the checkpoint
    # saved *before* its superstep (an ancestor of the latest checkpoint).
    chain_has_messages_write = False
    async for chain_tuple in saver_env.saver.alist(config):
        if any(channel == "messages" for _, channel, _ in chain_tuple.pending_writes or []):
            chain_has_messages_write = True
            break
    assert chain_has_messages_write

    # Second update crosses snapshot_frequency=2 -> one checkpoint on the
    # chain carries a _DeltaSnapshot blob for messages. (Which checkpoint
    # reassembles it into channel_values differs per saver: InMemorySaver
    # resolves the versioned blob on the latest checkpoint, AsyncSqliteSaver
    # on its parent. The cadence contract is that the snapshot exists.)
    await graph.ainvoke({"messages": [AIMessage(id="m2", content="two")]}, config)
    snapshot_found = False
    async for chain_tuple in saver_env.saver.alist(config):
        if isinstance(chain_tuple.checkpoint["channel_values"].get("messages"), _DeltaSnapshot):
            snapshot_found = True
            break
    assert snapshot_found

    snapshot = await accessor.aget(config)
    assert [m.id for m in snapshot.values["messages"]] == ["m1", "m2"]
    assert [m.content for m in snapshot.values["messages"]] == ["one", "two"]


@pytest.mark.anyio
async def test_non_delta_writers_preserve_delta_messages_and_markers(saver_env: _SaverEnv) -> None:
    """Raw checkpoint writers that never touch the messages channel (thread
    goal, run-duration metadata, interrupted-title helper) must not sever the
    Delta parent lineage or drop the downgrade markers. Regression: a raw
    ``aput`` whose write_config omits ``checkpoint_id`` stores a parentless
    checkpoint; replay from it then walks an empty ancestor chain and the
    whole message history silently disappears."""
    thread_id = _thread_id()
    config = _config(thread_id)
    write_config = {**config, "metadata": {CHECKPOINT_MODE_METADATA_KEY: "delta"}}
    graph = _build_graph(DeltaThreadState, saver_env.saver)
    accessor = CheckpointStateAccessor.bind(graph, saver_env.saver, mode="delta")

    await graph.ainvoke({"messages": Overwrite([HumanMessage(id="u1", content="hello goal writer")])}, write_config)
    await graph.ainvoke({"messages": [AIMessage(id="a1", content="reply")]}, write_config)

    await write_thread_goal(saver_env.saver, thread_id, _goal("keep messages alive"))
    durations_written = await persist_run_durations(
        checkpointer=saver_env.saver,
        thread_id=thread_id,
        durations={"run-1": 7},
    )
    assert durations_written
    # Delta checkpoints carry no messages in channel_values, so the title
    # helper has nothing to derive from and must stay inert (no write).
    title = await _ensure_interrupted_title(checkpointer=saver_env.saver, thread_id=thread_id, app_config=None)
    assert title is None

    await saver_env.reopen()
    graph = _build_graph(DeltaThreadState, saver_env.saver)
    accessor = CheckpointStateAccessor.bind(graph, saver_env.saver, mode="delta")

    latest_tuple = await saver_env.saver.aget_tuple(config)
    assert latest_tuple is not None

    # Production materialized read path (same one the Gateway uses).
    snapshot = await accessor.aget(config)
    assert [m.id for m in snapshot.values["messages"]] == ["u1", "a1"]
    assert [m.content for m in snapshot.values["messages"]] == ["hello goal writer", "reply"]

    assert checkpoint_tuple_uses_delta(latest_tuple)
    assert latest_tuple.metadata.get(CHECKPOINT_MODE_METADATA_KEY) == "delta"
    assert latest_tuple.metadata.get("run_durations", {}).get("run-1") == 7


# ---------------------------------------------------------------------------
# Known-unfixed upstream DeltaChannel defects.
#
# langgraph #8382 (parallel-superstep delta replay order) and #8448 (Postgres
# paginated delta-walk cursor) are both still open against the pinned
# langgraph-checkpoint 4.2.0 / langgraph-checkpoint-postgres 3.1.2, with fixes
# (PR #8544 / PR #8556) unmerged and no released version carrying them. Each
# test below asserts the CORRECT contract; while the defect is present it trips
# (skips, naming the upstream issue) instead of failing, so a later dependency
# bump that lands the fix flips it into a live gate. The contract is never
# asserted as buggy behaviour.
# ---------------------------------------------------------------------------

_PARALLEL_LABELS = tuple("abcdefgh")
_PAGINATION_STEPS = 12
# Shrink the Postgres stage-1 page so a dozen checkpoints cross it. The defect
# is decided by which page the target lands on, not the absolute count; upstream
# PR #8556 makes the same substitution in its own regression rather than writing
# 1024+ real checkpoints.
_PAGINATION_PAGE_SIZE = 3


class LongChainState(TypedDict):
    """Delta ``messages`` at the production snapshot cadence (long walks)."""

    messages: Annotated[
        list[AnyMessage],
        DeltaChannel(merge_message_writes, snapshot_frequency=DEFAULT_CHECKPOINT_SNAPSHOT_FREQUENCY),
    ]


def _message_digest(values: dict[str, Any]) -> list[tuple[str, str, str | None]]:
    return [(m.type, m.content, m.id) for m in values["messages"]]


def _append_node(index: int) -> Any:
    def node(state: dict[str, Any]) -> dict[str, Any]:
        return {"messages": [AIMessage(id=f"l{index}", content=f"long-{index}")]}

    return node


def _build_linear_graph(saver: Any, steps: int) -> Any:
    builder = StateGraph(LongChainState)
    for i in range(steps):
        builder.add_node(f"l{i}", _append_node(i))
    builder.set_entry_point("l0")
    for i in range(steps - 1):
        builder.add_edge(f"l{i}", f"l{i + 1}")
    builder.set_finish_point(f"l{steps - 1}")
    return builder.compile(checkpointer=saver)


def _expected_long_chain(steps: int) -> list[tuple[str, str, str]]:
    return [("human", "kickoff", "h0"), *[("ai", f"long-{i}", f"l{i}") for i in range(steps)]]


async def _long_chain_history(saver: Any, thread_id: str, steps: int) -> list[tuple[list, tuple]]:
    """Materialize every checkpoint of a linear delta chain (newest first)."""
    graph = _build_linear_graph(saver, steps)
    config = _config(thread_id)
    await graph.ainvoke({"messages": [HumanMessage(id="h0", content="kickoff")]}, config)
    accessor = CheckpointStateAccessor.bind(graph, saver, mode="delta")
    return [(_message_digest(s.values), tuple(s.next)) for s in await accessor.ahistory(config)]


@pytest.mark.anyio
async def test_long_chain_history_survives_pagination(saver_env: _SaverEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every checkpoint of a long delta chain must materialize its own ancestor
    prefix. Postgres resolves the history through a stage-1 scan paged
    newest-first; when the target checkpoint is not on the first page the
    unpatched cursor is derived from a not-yet-loaded parent and parks at
    ``None`` for good, so old checkpoints hydrate empty (upstream #8448)."""
    if saver_env.kind == "postgres":
        pg_aio = pytest.importorskip("langgraph.checkpoint.postgres.aio", reason="postgres extra not installed")
        monkeypatch.setattr(pg_aio, "_DELTA_PAGE_SIZE", _PAGINATION_PAGE_SIZE)

    got = await _long_chain_history(saver_env.saver, _thread_id(), _PAGINATION_STEPS)
    oracle = await _long_chain_history(InMemorySaver(), _thread_id(), _PAGINATION_STEPS)

    # Reference sanity: newest-first, the head carries the whole chain, and
    # only the pre-input root checkpoint is empty.
    assert oracle[0] == (_expected_long_chain(_PAGINATION_STEPS), ())
    assert all(digest for digest, next_key in oracle if next_key != ("__start__",))

    if saver_env.kind == "postgres" and got != oracle:
        pytest.skip("upstream langgraph#8448 unfixed in langgraph-checkpoint-postgres 3.1.2: the paged delta walk poisons the channel cursor for a target past the first stage-1 page, hydrating old checkpoints empty")
    assert got == oracle


def _fanout_node(label: str) -> Any:
    def node(state: dict[str, Any]) -> dict[str, Any]:
        return {"messages": [AIMessage(id=f"fan-{label}", content=label)]}

    return node


def _build_fanout_graph(saver: Any) -> Any:
    builder = StateGraph(LongChainState)
    for label in _PARALLEL_LABELS:
        builder.add_node(label, _fanout_node(label))
        builder.add_edge(START, label)
        builder.add_edge(label, END)
    return builder.compile(checkpointer=saver)


@pytest.mark.anyio
async def test_parallel_superstep_replay_matches_live_write_order(saver_env: _SaverEnv) -> None:
    """When several parallel tasks write the same delta channel in one
    superstep, the live ``apply_writes`` order is path-sorted, but the delta
    history replay sorts by the hashed ``(task_id, idx)`` - an unrelated order
    (upstream #8382). ``get_state`` on the same thread must report the order the
    run actually produced."""
    graph = _build_fanout_graph(saver_env.saver)
    config = _config(_thread_id())
    live = await graph.ainvoke({"messages": []}, config)
    live_order = [m.content for m in live["messages"]]

    # Live superstep writes are deterministic and path-sorted, so the fan-out
    # lands in label order regardless of task completion order.
    assert live_order == list(_PARALLEL_LABELS)

    replayed = await graph.aget_state(config)
    replayed_order = [m.content for m in replayed.values["messages"]]

    if replayed_order != live_order:
        pytest.skip("upstream langgraph#8382 unfixed in langgraph-checkpoint 4.2.0: delta replay orders writes by hashed (task_id, idx) instead of the path order apply_writes used live, so get_state/resume reorders same-superstep writes")
    assert replayed_order == live_order


@pytest.mark.anyio
@pytest.mark.parametrize("saver_env", ["postgres"], indirect=True)
async def test_postgres_saver_reopen_retains_owned_schema(saver_env: _SaverEnv) -> None:
    async with saver_env.saver.conn.cursor() as cursor:
        await cursor.execute("SELECT current_schema()")
        original_schema = (await cursor.fetchone())["current_schema"]
        await cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name")
        public_before = await cursor.fetchall()
    assert original_schema.startswith("delta_contract_")
    await saver_env.reopen()
    async with saver_env.saver.conn.cursor() as cursor:
        await cursor.execute("SELECT current_schema()")
        assert (await cursor.fetchone())["current_schema"] == original_schema
        await cursor.execute(
            "SELECT table_schema FROM information_schema.tables WHERE table_schema = %s AND table_name = 'checkpoints'",
            (original_schema,),
        )
        assert await cursor.fetchall() == [{"table_schema": original_schema}]
        await cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name")
        assert await cursor.fetchall() == public_before


@pytest.mark.anyio
async def test_postgres_schema_creation_close_failure_still_cleans_owned_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    import psycopg

    uri = os.environ.get("TEST_POSTGRES_URI")
    if not uri:
        pytest.skip("TEST_POSTGRES_URI is not set")
    token = uuid4().hex
    schema = f"delta_contract_{token}"
    monkeypatch.setattr(sys.modules[__name__], "uuid4", lambda: SimpleNamespace(hex=token))
    original_connect = psycopg.AsyncConnection.connect
    primary = RuntimeError("Owned creation connection close failed after actual close")
    connections = 0

    class CloseFailureConnection:
        def __init__(self, connection: Any) -> None:
            self.connection = connection

        async def __aenter__(self) -> Any:
            return await self.connection.__aenter__()

        async def __aexit__(self, *exc: Any) -> None:
            await self.connection.__aexit__(*exc)
            assert self.connection.closed
            raise primary

    async def connect(*args: Any, **kwargs: Any) -> Any:
        nonlocal connections
        connection = await original_connect(*args, **kwargs)
        connections += 1
        return CloseFailureConnection(connection) if connections == 1 else connection

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    with pytest.raises(RuntimeError) as caught:
        async with _owned_postgres_schema(uri):
            pytest.fail("Creation close failure must prevent entering the saver")
    assert caught.value is primary
    assert connections == 2
    postgres_uri = normalize_libpq_dsn(uri)
    async with await original_connect(postgres_uri, autocommit=True) as conn:
        cursor = await conn.execute("SELECT schema_name FROM information_schema.schemata WHERE schema_name = %s", (schema,))
        assert await cursor.fetchall() == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    "uri",
    [
        "postgresql+asyncpg://user:synthetic@localhost/db?options=-c%20statement_timeout%3D30000",
        "postgresql+asyncpg://user:synthetic@localhost/db?options=-c%20statement_timeout%3D30000&application_name=a%2Bb&options=-c%20lock_timeout%3D1000",
        "postgresql://user:p%2Bass@localhost/db?application_name=a%2Bb&options=-c%20statement_timeout%3D30000",
        "host=localhost dbname=synthetic user=synthetic password=synthetic options='-c statement_timeout=30000' application_name='a+b'",
        "postgresql+asyncpg://user:synthetic@localhost/db",
    ],
)
async def test_owned_postgres_schema_preserves_parent_libpq_encoding(uri: str, monkeypatch: pytest.MonkeyPatch) -> None:
    import psycopg
    from psycopg.conninfo import conninfo_to_dict

    from deerflow.persistence.postgres_schema import normalize_libpq_dsn

    expected = normalize_libpq_dsn(uri)
    assert conninfo_to_dict(expected)["dbname"] in {"db", "synthetic"}
    if "a%2Bb" in uri or "application_name='a+b'" in uri:
        assert conninfo_to_dict(expected)["application_name"] == "a+b"
    if "options=" in uri:
        assert "+statement_timeout" not in conninfo_to_dict(expected)["options"]
    observed = []
    original_failure = RuntimeError("Synthetic connector stops before any network or schema mutation")

    async def connect(dsn: str, **kwargs: Any) -> Any:
        observed.append(dsn)
        raise original_failure

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    with pytest.raises(BaseException) as caught:
        async with _owned_postgres_schema(uri):
            pytest.fail("Synthetic connector must prevent schema creation")
    assert observed == [expected]
    assert caught.value is original_failure


@pytest.mark.anyio
async def test_postgres_encoded_parent_options_survive_schema_and_reopen() -> None:
    from urllib.parse import quote, unquote, urlsplit, urlunsplit

    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    from deerflow.persistence.postgres_schema import normalize_libpq_dsn

    uri = os.environ.get("TEST_POSTGRES_URI")
    if not uri:
        pytest.skip("TEST_POSTGRES_URI is not set")
    normalized = normalize_libpq_dsn(uri)
    parts = urlsplit(normalized)
    if parts.scheme:
        original_options = " ".join(unquote(pair.partition("=")[2]) for pair in parts.query.split("&") if unquote(pair.partition("=")[0]) == "options")
        raw_query = "&".join(pair for pair in parts.query.split("&") if unquote(pair.split("=", 1)[0]) != "options")
        options = (original_options + " -c statement_timeout=30000").strip()
        encoded_options = "options=" + quote(options, safe="")
        parent_uri = urlunsplit(parts._replace(query=(raw_query + "&" if raw_query else "") + encoded_options))
    else:
        parameters = conninfo_to_dict(normalized)
        parameters["options"] = (parameters.get("options", "") + " -c statement_timeout=30000").strip()
        parent_uri = make_conninfo(**parameters)
    async with _owned_postgres_schema(parent_uri) as scoped_uri:
        async with _SaverEnv("postgres", lambda: _open_postgres(scoped_uri)) as env:
            async with env.saver.conn.cursor() as cursor:
                await cursor.execute("SELECT current_schema(), current_setting('statement_timeout') AS statement_timeout")
                original = await cursor.fetchone()
            assert original["current_schema"].startswith("delta_contract_")
            assert original["statement_timeout"] == "30s"
            await env.reopen()
            async with env.saver.conn.cursor() as cursor:
                await cursor.execute("SELECT current_schema(), current_setting('statement_timeout') AS statement_timeout")
                assert await cursor.fetchone() == original


@pytest.mark.anyio
@pytest.mark.parametrize(
    "parent,expected_options",
    [
        ("postgresql+asyncpg://user:synthetic@localhost/db?options=-c%20lock_timeout%3D1000&application_name=a%2Bb", ["-c", "lock_timeout=1000"]),
        ("host=localhost dbname=synthetic user=synthetic password=synthetic options='-c lock_timeout=1000' application_name='a+b'", ["-c", "lock_timeout=1000"]),
        (
            "postgresql+asyncpg://user:p%2Bass@localhost/db?options=-c%20lock_timeout%3D1000&application_name=a%2Bb&options=-c%20search_path%3Dparent_schema%20-c%20statement_timeout%3D1000",
            ["-c", "lock_timeout=1000", "-c", "search_path=parent_schema", "-c", "statement_timeout=1000"],
        ),
        (
            "host=localhost dbname=synthetic user=synthetic password='p+ass' options='-c search_path=parent_schema -c lock_timeout=1000 -c statement_timeout=1000' application_name='a+b'",
            ["-c", "search_path=parent_schema", "-c", "lock_timeout=1000", "-c", "statement_timeout=1000"],
        ),
        (
            "postgresql+asyncpg://user:p%2Bass@localhost/db?options=-c%20application_name%3Da+b&application_name=a%2Bb",
            ["-c", "application_name=a+b"],
        ),
    ],
    ids=["uri", "keyword", "uri-multiple-options", "keyword-search-path-existing-timeout", "uri-options-literal-plus"],
)
async def test_encoded_options_actual_test_caller_preserves_parent_form(parent: str, expected_options: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    import shlex

    from psycopg.conninfo import conninfo_to_dict

    monkeypatch.setenv("TEST_POSTGRES_URI", parent)
    original = conninfo_to_dict(normalize_libpq_dsn(parent))
    observed = []
    sentinel = RuntimeError("Owned-schema interception ends before network or schema mutation")

    @asynccontextmanager
    async def capture(parent_dsn: str) -> AsyncIterator[str]:
        parsed = conninfo_to_dict(parent_dsn)
        observed.append(parsed)
        raise sentinel
        yield parent_dsn

    monkeypatch.setattr(sys.modules[__name__], "_owned_postgres_schema", capture)
    with pytest.raises(RuntimeError) as caught:
        await test_postgres_encoded_parent_options_survive_schema_and_reopen()
    assert caught.value is sentinel
    assert len(observed) == 1
    assert {key: value for key, value in observed[0].items() if key != "options"} == {key: value for key, value in original.items() if key != "options"}
    assert shlex.split(observed[0]["options"]) == expected_options + ["-c", "statement_timeout=30000"]
