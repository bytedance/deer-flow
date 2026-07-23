"""Materialized checkpoint-state access and state-only mutation graphs.

:class:`CheckpointStateAccessor` is the single choke point for thread
checkpoint-state reads and writes. It binds a compiled graph (which carries
the mode-matched channel schema), a checkpointer, and the frozen channel mode:
every operation injects the mode marker into the config and passes the
compatibility gate before touching state. Delta checkpoints store no full
``channel_values`` — raw saver reads see sentinels — so consumers must go
through this accessor instead of calling the checkpointer directly.

:func:`build_state_mutation_graph` compiles a state-only graph (one no-op
node, entry = finish) for wholesale state replacement such as rollback
restore and context compaction: it shares the agent graph's checkpoint
machinery but schedules no pending nodes, so the written head stays idle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from deerflow.agents.thread_state import get_thread_state_schema
from deerflow.config.database_config import CheckpointChannelMode
from deerflow.runtime.checkpoint_mode import (
    aensure_checkpoint_mode_compatible,
    ensure_checkpoint_mode_compatible,
    inject_checkpoint_mode,
    raise_if_snapshot_incompatible,
)


def _finish_state_mutation(_state: dict[str, Any]) -> dict[str, Any]:
    return {}


def build_state_mutation_graph(as_node: str, mode: CheckpointChannelMode, state_schema: Any | None = None) -> Any:
    """Compile a state-only graph whose single writer node finishes immediately.

    ``update_state(..., as_node=...)`` requires the node to be registered in
    the graph; a dedicated single-node graph applies reducer writes and
    finishes, so the mutation checkpoint schedules no agent nodes and has no
    pending ``next`` nodes.

    ``state_schema`` must be the thread's *effective* schema (the class the
    assistant graph was compiled with) whenever the write carries materialized
    state: the base ThreadState fallback does not know channels contributed by
    custom middleware, and writes to unknown channels are silently discarded.
    """
    if not as_node:
        raise ValueError("as_node is required for checkpoint state mutation")
    from langgraph.graph import StateGraph

    builder = StateGraph(state_schema if state_schema is not None else get_thread_state_schema(mode))
    builder.add_node(as_node, _finish_state_mutation)
    builder.set_entry_point(as_node)
    builder.set_finish_point(as_node)
    return builder.compile()


def graph_state_schema(graph: Any) -> Any | None:
    """Return the state schema class a compiled graph was built with.

    The schema is the first entry of ``StateGraph.schemas`` (state schema is
    registered before input/output schemas). Returns ``None`` for stub
    accessors in tests that do not wrap a real compiled graph.
    """
    schemas = getattr(getattr(graph, "builder", None), "schemas", None)
    if not schemas:
        return None
    return next(iter(schemas))


def graph_writable_channels(graph: Any) -> frozenset[str] | None:
    """Return the user-visible state channel names of a compiled graph.

    Excludes Pregel-internal channels (``__*``) and branch fan-in channels
    (``branch:*``). Returns ``None`` when the graph does not expose channels
    (stub accessors), so callers can fall back to the base ThreadState set.
    """
    channels = getattr(graph, "channels", None)
    if not channels:
        return None
    return frozenset(name for name in channels if not name.startswith("__") and not name.startswith("branch:"))


def graph_reducer_channels(graph: Any) -> frozenset[str] | None:
    """Return channel names whose writes merge through a reducer.

    Covers classic reducers (``BinaryOperatorAggregate``) and delta channels:
    both require ``Overwrite`` wrapping for replace-style writes, in any mode.
    Returns ``None`` when the graph does not expose channels (stub
    accessors), so callers can fall back to the base ThreadState set.
    """
    from langgraph.channels import BinaryOperatorAggregate, DeltaChannel

    channels = getattr(graph, "channels", None)
    if channels is None:
        return None
    return frozenset(name for name, channel in channels.items() if isinstance(channel, (BinaryOperatorAggregate, DeltaChannel)))


@dataclass
class CheckpointStateAccessor:
    graph: Any
    checkpointer: Any
    mode: CheckpointChannelMode

    @classmethod
    def bind(
        cls,
        graph: Any,
        checkpointer: Any,
        *,
        store: Any | None = None,
        mode: CheckpointChannelMode = "full",
    ) -> CheckpointStateAccessor:
        graph.checkpointer = checkpointer
        if store is not None:
            graph.store = store
        return cls(graph=graph, checkpointer=checkpointer, mode=mode)

    def _prepare_config(self, config: dict[str, Any]) -> dict[str, Any]:
        prepared = {
            **config,
            "configurable": dict(config.get("configurable", {})),
            "metadata": dict(config.get("metadata", {})),
        }
        inject_checkpoint_mode(prepared, self.mode)
        return prepared

    def get(self, config: dict[str, Any]) -> Any:
        prepared = self._prepare_config(config)
        snapshot = self.graph.get_state(prepared)
        raise_if_snapshot_incompatible(snapshot, self.mode)
        return snapshot

    async def aget(self, config: dict[str, Any]) -> Any:
        prepared = self._prepare_config(config)
        snapshot = await self.graph.aget_state(prepared)
        raise_if_snapshot_incompatible(snapshot, self.mode)
        return snapshot

    def history(self, config: dict[str, Any], *, limit: int | None = None) -> list[Any]:
        prepared = self._prepare_config(config)
        if limit is not None and limit <= 0:
            return []
        result = []
        for snapshot in self.graph.get_state_history(prepared, limit=limit):
            raise_if_snapshot_incompatible(snapshot, self.mode)
            result.append(snapshot)
            if limit is not None and len(result) >= limit:
                break
        return result

    async def ahistory(self, config: dict[str, Any], *, limit: int | None = None) -> list[Any]:
        prepared = self._prepare_config(config)
        if limit is not None and limit <= 0:
            return []
        result = []
        async for snapshot in self.graph.aget_state_history(prepared, limit=limit):
            raise_if_snapshot_incompatible(snapshot, self.mode)
            result.append(snapshot)
            if limit is not None and len(result) >= limit:
                break
        return result

    def update(
        self,
        config: dict[str, Any],
        values: dict[str, Any],
        *,
        as_node: str | None = None,
    ) -> dict[str, Any]:
        prepared = self._prepare_config(config)
        ensure_checkpoint_mode_compatible(self.checkpointer, prepared, self.mode)
        return self.graph.update_state(prepared, values, as_node=as_node)

    async def aupdate(
        self,
        config: dict[str, Any],
        values: dict[str, Any],
        *,
        as_node: str | None = None,
    ) -> dict[str, Any]:
        prepared = self._prepare_config(config)
        await aensure_checkpoint_mode_compatible(self.checkpointer, prepared, self.mode)
        return await self.graph.aupdate_state(prepared, values, as_node=as_node)
