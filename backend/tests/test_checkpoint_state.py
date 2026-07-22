from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Annotated, Any, TypedDict

import pytest
from langchain_core.messages import AnyMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.message import add_messages

from deerflow.runtime import CheckpointStateAccessor
from deerflow.runtime.checkpoint_mode import CHECKPOINT_MODE_METADATA_KEY, INTERNAL_CHECKPOINT_MODE_KEY


class FakeCheckpointer:
    def __init__(self) -> None:
        self.sync_configs: list[dict[str, Any]] = []
        self.async_configs: list[dict[str, Any]] = []

    def get_tuple(self, config: dict[str, Any]) -> None:
        self.sync_configs.append(config)
        return None

    async def aget_tuple(self, config: dict[str, Any]) -> None:
        self.async_configs.append(config)
        return None


class FakeGraph:
    def __init__(self) -> None:
        self.checkpointer: Any = None
        self.store: Any = None
        self.calls: list[tuple[Any, ...]] = []
        self.sync_history_yields = 0
        self.async_history_yields = 0

    def get_state(self, config: dict[str, Any]) -> SimpleNamespace:
        self.calls.append(("get", config))
        return SimpleNamespace(values={"messages": ["sync"]})

    def get_state_history(self, config: dict[str, Any], *, limit: int | None = None):
        self.calls.append(("history", config, limit))
        for index in range(4):
            if limit is not None and self.sync_history_yields >= limit:
                return
            self.sync_history_yields += 1
            yield SimpleNamespace(values={"index": index})

    def update_state(self, config: dict[str, Any], values: dict[str, Any], *, as_node: str | None = None) -> dict[str, Any]:
        self.calls.append(("update", config, values, as_node))
        return {"updated": values, "as_node": as_node}

    async def aget_state(self, config: dict[str, Any]) -> SimpleNamespace:
        self.calls.append(("aget", config))
        return SimpleNamespace(values={"messages": ["async"]})

    async def aget_state_history(self, config: dict[str, Any], *, limit: int | None = None):
        self.calls.append(("ahistory", config, limit))
        for index in range(4):
            if limit is not None and self.async_history_yields >= limit:
                return
            self.async_history_yields += 1
            yield SimpleNamespace(values={"index": index})

    async def aupdate_state(
        self,
        config: dict[str, Any],
        values: dict[str, Any],
        *,
        as_node: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append(("aupdate", config, values, as_node))
        return {"updated": values, "as_node": as_node}


def _assert_delta_config_is_copied(original: dict[str, Any], forwarded: dict[str, Any]) -> None:
    assert forwarded is not original
    assert forwarded["configurable"] is not original["configurable"]
    assert forwarded["metadata"] is not original["metadata"]
    assert forwarded["configurable"][INTERNAL_CHECKPOINT_MODE_KEY] == "delta"
    assert forwarded["metadata"][CHECKPOINT_MODE_METADATA_KEY] == "delta"


def test_sync_accessor_binds_persistence_guards_operations_and_preserves_input() -> None:
    graph = FakeGraph()
    saver = FakeCheckpointer()
    store = object()
    accessor = CheckpointStateAccessor.bind(graph, saver, store=store, mode="delta")
    config = {
        "configurable": {"thread_id": "thread-sync", "checkpoint_ns": ""},
        "metadata": {"caller": "test"},
        "tags": ["preserved"],
    }
    original = deepcopy(config)

    snapshot = accessor.get(config)
    history = accessor.history(config, limit=2)
    update = accessor.update(config, {"messages": ["changed"]}, as_node="tools")

    assert snapshot.values == {"messages": ["sync"]}
    assert [item.values for item in history] == [{"index": 0}, {"index": 1}]
    assert graph.sync_history_yields == 2
    assert update == {"updated": {"messages": ["changed"]}, "as_node": "tools"}
    assert graph.checkpointer is saver
    assert graph.store is store
    assert config == original
    for call in graph.calls:
        _assert_delta_config_is_copied(config, call[1])
    assert graph.calls[-1][2:] == ({"messages": ["changed"]}, "tools")


@pytest.mark.anyio
async def test_async_accessor_binds_persistence_guards_operations_and_preserves_input() -> None:
    graph = FakeGraph()
    saver = FakeCheckpointer()
    store = object()
    accessor = CheckpointStateAccessor.bind(graph, saver, store=store, mode="delta")
    config = {
        "configurable": {"thread_id": "thread-async", "checkpoint_ns": ""},
        "metadata": {"caller": "test"},
        "tags": ["preserved"],
    }
    original = deepcopy(config)

    snapshot = await accessor.aget(config)
    history = await accessor.ahistory(config, limit=2)
    update = await accessor.aupdate(config, {"messages": ["changed"]}, as_node="agent")

    assert snapshot.values == {"messages": ["async"]}
    assert [item.values for item in history] == [{"index": 0}, {"index": 1}]
    assert graph.async_history_yields == 2
    assert update == {"updated": {"messages": ["changed"]}, "as_node": "agent"}
    assert graph.checkpointer is saver
    assert graph.store is store
    assert config == original
    for call in graph.calls:
        _assert_delta_config_is_copied(config, call[1])
    assert graph.calls[-1][2:] == ({"messages": ["changed"]}, "agent")


def test_sync_history_zero_limit_guards_without_consuming_a_snapshot() -> None:
    graph = FakeGraph()
    saver = FakeCheckpointer()
    accessor = CheckpointStateAccessor.bind(graph, saver)
    config = {"configurable": {"thread_id": "thread-sync-zero"}}

    assert accessor.history(config, limit=0) == []
    # The read-side gate folds onto the returned snapshot: no standalone tuple fetch.
    assert len(saver.sync_configs) == 0
    assert graph.sync_history_yields == 0


@pytest.mark.anyio
async def test_async_history_zero_limit_guards_without_consuming_a_snapshot() -> None:
    graph = FakeGraph()
    saver = FakeCheckpointer()
    accessor = CheckpointStateAccessor.bind(graph, saver)
    config = {"configurable": {"thread_id": "thread-async-zero"}}

    assert await accessor.ahistory(config, limit=0) == []
    assert len(saver.async_configs) == 0
    assert graph.async_history_yields == 0


@pytest.mark.anyio
async def test_full_accessor_gates_writes_and_checks_reads_on_the_returned_snapshot() -> None:
    """Full mode: only writes pay the pre-write tuple fetch; reads check the
    marker on the materialized snapshot's metadata instead."""
    graph = FakeGraph()
    saver = FakeCheckpointer()
    accessor = CheckpointStateAccessor.bind(graph, saver)
    config = {"configurable": {"thread_id": "thread-full"}}

    accessor.get(config)
    accessor.history(config, limit=1)
    accessor.update(config, {}, as_node=None)
    await accessor.aget(config)
    await accessor.ahistory(config, limit=1)
    await accessor.aupdate(config, {}, as_node=None)

    assert len(saver.sync_configs) == 1
    assert len(saver.async_configs) == 1
    for prepared in [*saver.sync_configs, *saver.async_configs]:
        assert prepared["configurable"][INTERNAL_CHECKPOINT_MODE_KEY] == "full"
        assert CHECKPOINT_MODE_METADATA_KEY not in prepared["metadata"]
    assert config == {"configurable": {"thread_id": "thread-full"}}


@pytest.mark.anyio
async def test_full_accessor_raises_when_the_returned_snapshot_is_delta_marked() -> None:
    """A full-mode accessor must fail closed on a delta checkpoint, detected
    via the returned snapshot metadata (no pre-read tuple fetch)."""
    from deerflow.runtime.checkpoint_mode import CheckpointModeMismatchError

    graph = FakeGraph()
    saver = FakeCheckpointer()
    accessor = CheckpointStateAccessor.bind(graph, saver, mode="full")
    config = {"configurable": {"thread_id": "thread-delta-marked"}}
    graph.get_state = lambda _config: SimpleNamespace(values={}, metadata={CHECKPOINT_MODE_METADATA_KEY: "delta"})

    with pytest.raises(CheckpointModeMismatchError, match="requires delta mode"):
        accessor.get(config)
    assert len(saver.sync_configs) == 0

    async def _delta_history(_config, *, limit=None):
        yield SimpleNamespace(values={"index": 0}, metadata={})
        yield SimpleNamespace(values={"index": 1}, metadata={CHECKPOINT_MODE_METADATA_KEY: "delta"})

    graph.aget_state_history = _delta_history
    with pytest.raises(CheckpointModeMismatchError, match="requires delta mode"):
        await accessor.ahistory(config)
    assert len(saver.async_configs) == 0


@pytest.mark.anyio
async def test_full_accessor_writes_still_check_compatibility_before_writing() -> None:
    """Writes cannot be un-applied, so the pre-write tuple fetch stays."""
    from deerflow.runtime.checkpoint_mode import CheckpointModeMismatchError

    graph = FakeGraph()

    class DeltaMarkedSaver(FakeCheckpointer):
        async def aget_tuple(self, config):
            self.async_configs.append(config)
            return SimpleNamespace(metadata={CHECKPOINT_MODE_METADATA_KEY: "delta"})

    saver = DeltaMarkedSaver()
    accessor = CheckpointStateAccessor.bind(graph, saver, mode="full")
    config = {"configurable": {"thread_id": "thread-delta-write"}}

    with pytest.raises(CheckpointModeMismatchError, match="requires delta mode"):
        await accessor.aupdate(config, {"messages": []}, as_node=None)
    assert len(saver.async_configs) == 1
    assert graph.calls == []


class _CountingSaver(InMemorySaver):
    """InMemorySaver that counts checkpoint round-trips."""

    def __init__(self) -> None:
        super().__init__()
        self.aget_tuple_calls = 0
        self.alist_limits: list[int | None] = []

    async def aget_tuple(self, config):
        self.aget_tuple_calls += 1
        return await super().aget_tuple(config)

    async def alist(self, config, *, filter=None, before=None, limit=None):
        self.alist_limits.append(limit)
        async for item in super().alist(config, filter=filter, before=before, limit=limit):
            yield item


def _build_counting_graph(saver):
    from langchain_core.messages import HumanMessage
    from langgraph.graph import StateGraph

    class _State(TypedDict):
        messages: Annotated[list[AnyMessage], add_messages]

    async def _append(state):
        return {"messages": [HumanMessage(content=f"turn-{len(state.get('messages') or [])}")]}

    builder = StateGraph(_State)
    builder.add_node("append", _append)
    builder.set_entry_point("append")
    builder.set_finish_point("append")
    return builder.compile(checkpointer=saver)


@pytest.mark.anyio
async def test_ahistory_pushes_limit_into_alist_and_reads_each_snapshot_once() -> None:
    """The history limit must reach ``checkpointer.alist`` (SQL LIMIT), and the
    read-side compat gate must not add a standalone tuple fetch per call."""
    saver = _CountingSaver()
    graph = _build_counting_graph(saver)
    accessor = CheckpointStateAccessor.bind(graph, saver, mode="full")
    config = {"configurable": {"thread_id": "thread-counted"}}
    for _ in range(4):
        await graph.ainvoke({}, config)

    saver.aget_tuple_calls = 0
    history = await accessor.ahistory(config, limit=2)

    assert len(history) == 2
    assert saver.alist_limits[-1] == 2
    # get_state_history walks via alist only; no aget_tuple in the read path.
    assert saver.aget_tuple_calls == 0


@pytest.mark.anyio
async def test_aget_fetches_the_checkpoint_exactly_once_in_full_mode() -> None:
    """Full-mode reads: one fetch inside aget_state; the folded gate adds none."""
    saver = _CountingSaver()
    graph = _build_counting_graph(saver)
    accessor = CheckpointStateAccessor.bind(graph, saver, mode="full")
    config = {"configurable": {"thread_id": "thread-counted-get"}}
    await graph.ainvoke({}, config)

    saver.aget_tuple_calls = 0
    snapshot = await accessor.aget(config)

    assert [message.content for message in snapshot.values["messages"]] == ["turn-0"]
    assert saver.aget_tuple_calls == 1
