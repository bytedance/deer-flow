"""Gateway resolves new run profiles and restores resumed snapshots from storage."""

import importlib
import importlib.util
from types import SimpleNamespace

import pytest


def _admission():
    assert importlib.util.find_spec("app.gateway.tracing_admission") is not None, "Gateway tracing admission is not implemented"
    return importlib.import_module("app.gateway.tracing_admission")


@pytest.mark.asyncio
async def test_new_admission_replaces_every_forged_tracing_reference(monkeypatch):
    module = _admission()
    frozen = SimpleNamespace(snapshot_id="new-snapshot", agent_name="researcher")
    seen = []

    def resolve(agent_name, user_id):
        seen.append((agent_name, user_id))
        return frozen

    monkeypatch.setattr(module, "resolve_run_snapshot", resolve)
    config = {section: {"deerflow_tracing_snapshot_id": "forged", "deerflow_tracing_agent_name": "victim"} for section in ("context", "configurable", "metadata")}
    metadata = {"deerflow_tracing_snapshot_id": "forged", "deerflow_tracing_pinned": True, "caller": "keep"}

    await module.admit_run_tracing(None, config, metadata, thread_id="thread-1", agent_name="researcher", user_id="alice")

    assert seen == [("researcher", "alice")]
    assert metadata == {"caller": "keep", "deerflow_tracing_snapshot_id": "new-snapshot", "deerflow_tracing_agent_name": "researcher", "deerflow_tracing_managed": True}
    assert config["metadata"]["deerflow_tracing_snapshot_id"] == "new-snapshot"
    assert config["context"]["deerflow_tracing_snapshot_id"] == "new-snapshot"
    assert "deerflow_tracing_snapshot_id" not in config["configurable"]


@pytest.mark.asyncio
async def test_resume_restores_the_selected_checkpoint_snapshot(monkeypatch):
    module = _admission()
    refs = {"deerflow_tracing_snapshot_id": "old-snapshot", "deerflow_tracing_agent_name": "researcher"}
    frozen = SimpleNamespace(snapshot_id="old-snapshot", agent_name="researcher")
    loads = []

    class Checkpointer:
        async def aget_tuple(self, config):
            assert config["configurable"]["checkpoint_id"] == "interrupt-checkpoint"
            return SimpleNamespace(metadata=refs)

    def restore(references, **kwargs):
        loads.append((references, kwargs))
        return frozen

    monkeypatch.setattr(module, "get_checkpointer", lambda request: Checkpointer())
    monkeypatch.setattr(module, "restore_snapshot", restore)
    monkeypatch.setattr(module, "resolve_run_snapshot", lambda *args, **kwargs: pytest.fail("resume must not re-resolve current profile"))
    config = {"configurable": {"thread_id": "thread-1", "checkpoint_id": "interrupt-checkpoint"}}
    metadata = {}

    await module.admit_run_tracing(object(), config, metadata, thread_id="thread-1", agent_name="researcher", user_id="alice", resume=True)

    assert loads == [(refs, {"user_id": "alice", "agent_name": "researcher"})]
    assert metadata == {**refs, "deerflow_tracing_managed": True, "deerflow_tracing_pinned": True}


@pytest.mark.asyncio
async def test_queued_occurrence_keeps_its_admission_snapshot(monkeypatch):
    module = _admission()
    refs = {"deerflow_tracing_snapshot_id": "queued-before-edit", "deerflow_tracing_agent_name": "researcher"}
    frozen = SimpleNamespace(snapshot_id="queued-before-edit", agent_name="researcher")
    monkeypatch.setattr(module, "restore_snapshot", lambda references, **kwargs: frozen if references == refs else pytest.fail("lost queued snapshot"))
    monkeypatch.setattr(module, "resolve_run_snapshot", lambda *args, **kwargs: pytest.fail("queued dispatch must not resolve current profile"))
    metadata = {}

    await module.admit_run_tracing(None, {}, metadata, thread_id="thread-1", agent_name="researcher", user_id="alice", scheduled_references=refs)

    assert metadata == {**refs, "deerflow_tracing_managed": True, "deerflow_tracing_pinned": True}


@pytest.mark.asyncio
async def test_scalar_snapshot_identity_survives_actual_langgraph_checkpoint(monkeypatch):
    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, MessagesState, StateGraph

    module = _admission()
    refs = {"deerflow_tracing_snapshot_id": "frozen-checkpoint", "deerflow_tracing_agent_name": "researcher"}
    checkpointer = InMemorySaver()
    builder = StateGraph(MessagesState)
    builder.add_node("work", lambda state: {})
    builder.add_edge(START, "work")
    builder.add_edge("work", END)
    graph = builder.compile(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "thread-checkpoint"}, "metadata": dict(refs)}
    await graph.ainvoke({"messages": [HumanMessage(content="hello")]}, config=config)
    checkpoint = await checkpointer.aget_tuple(config)
    assert {key: checkpoint.metadata[key] for key in refs} == refs
    monkeypatch.setattr(module, "get_checkpointer", lambda request: checkpointer)
    monkeypatch.setattr(module, "restore_snapshot", lambda references, **kwargs: SimpleNamespace(snapshot_id=references["deerflow_tracing_snapshot_id"], agent_name="researcher"))
    admitted_metadata = {}
    await module.admit_run_tracing(None, {"configurable": checkpoint.config["configurable"]}, admitted_metadata, thread_id="thread-checkpoint", agent_name="researcher", user_id="alice", resume=True)
    assert admitted_metadata == {**refs, "deerflow_tracing_managed": True, "deerflow_tracing_pinned": True}
