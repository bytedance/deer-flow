"""Subgraph stream frames must not impersonate root-graph frames (#4399).

The gateway worker drives ``agent.astream(subgraphs=...)`` and publishes each
frame to the StreamBridge. Delegated subagent graphs inherit the parent's
checkpoint namespace (``subagents/executor.py``), so with ``subgraphs=True``
their values snapshots and token chunks arrive interleaved with root frames.
Publishing them under bare event names lets a subagent's values snapshot
replace the whole thread view in SDK clients and floods the parent message
stream with the subagent's token chunks. The namespace must ride the SSE event
name (LangGraph Platform style ``mode|ns1|ns2``) and namespaced frames must
bypass the root-only consumers (file-tool chunk batcher, subagent event
persistence).
"""

import asyncio
import importlib
import sys
from importlib.metadata import version as package_version
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from packaging.version import Version

from deerflow.runtime.runs import worker
from deerflow.runtime.runs.manager import RunRecord
from deerflow.runtime.runs.schemas import DisconnectMode, RunStatus
from deerflow.runtime.runs.worker import (
    _compose_sse_event,
    _publish_stream_item,
    _unpack_stream_item,
)
from deerflow.runtime.stream_bridge.memory import MemoryStreamBridge

SUBAGENT_NS = ("tools:call_subagent_1",)

# Delegated graphs inherit the parent checkpoint namespace (and therefore
# stream as subgraphs) only on LangGraph >= 1.2.6 — same gate as
# tests/test_subagent_executor.py::TestSubagentCheckpointLineage.
_LANGGRAPH_INHERITS_SUBGRAPH_NAMESPACE = Version(package_version("langgraph")) >= Version("1.2.6")


class _FakeBridge:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, object]] = []

    async def publish(self, run_id: str, event: str, payload: object) -> None:
        self.published.append((run_id, event, payload))


class _FakeSubagentEvents:
    def __init__(self) -> None:
        self.added: list[object] = []

    async def add(self, chunk: object) -> None:
        self.added.append(chunk)


class _SpyBatcher:
    """Observable stand-in for _LargeFileToolChunkBatcher."""

    def __init__(self) -> None:
        self.pushed: list[object] = []
        self.finish_calls = 0
        self.flush_calls = 0

    def push(self, chunk: object) -> list[object]:
        self.pushed.append(chunk)
        return [chunk]

    def finish(self) -> list[object]:
        self.finish_calls += 1
        return []

    def flush(self) -> list[object]:
        self.flush_calls += 1
        return []


class TestUnpackStreamItem:
    def test_root_frame_with_subgraphs_has_empty_namespace(self):
        mode, chunk, namespace = _unpack_stream_item(((), "values", {"messages": []}), ["values"], True)
        assert mode == "values"
        assert namespace == ()

    def test_subgraph_frame_preserves_namespace(self):
        mode, chunk, namespace = _unpack_stream_item((SUBAGENT_NS, "values", {"messages": []}), ["values"], True)
        assert mode == "values"
        assert namespace == SUBAGENT_NS

    def test_nested_subgraph_namespace_is_preserved_in_order(self):
        ns = ("tools:call_a", "model_request:xyz")
        _mode, _chunk, namespace = _unpack_stream_item((ns, "messages", object()), ["messages"], True)
        assert namespace == ns

    def test_two_tuple_under_subgraphs_is_root(self):
        mode, _chunk, namespace = _unpack_stream_item(("custom", {"type": "task_started"}), ["custom"], True)
        assert mode == "custom"
        assert namespace == ()

    def test_without_subgraphs_frames_are_root(self):
        mode, _chunk, namespace = _unpack_stream_item(("values", {}), ["values"], False)
        assert mode == "values"
        assert namespace == ()

    def test_single_mode_fallback_is_root(self):
        mode, chunk, namespace = _unpack_stream_item({"messages": []}, ["values"], False)
        assert mode == "values"
        assert chunk == {"messages": []}
        assert namespace == ()

    def test_unparsable_item_under_subgraphs(self):
        mode, chunk, namespace = _unpack_stream_item("garbage", ["values"], True)
        assert mode is None
        assert chunk is None
        assert namespace == ()


class TestComposeSseEvent:
    def test_root_frame_keeps_bare_event_name(self):
        assert _compose_sse_event("values", ()) == "values"

    def test_subgraph_frame_gets_namespace_qualified_name(self):
        assert _compose_sse_event("values", SUBAGENT_NS) == "values|tools:call_subagent_1"

    def test_nested_namespace_joins_all_segments(self):
        assert _compose_sse_event("messages", ("tools:call_a", "model_request:xyz")) == "messages|tools:call_a|model_request:xyz"


class TestPublishStreamItem:
    @pytest.mark.asyncio
    async def test_subagent_values_snapshot_is_never_published_as_bare_values(self):
        # The #4399 regression: a delegated subagent's values snapshot published
        # as bare "values" replaces the whole thread view in SDK clients.
        bridge = _FakeBridge()
        await _publish_stream_item(
            bridge=bridge,
            run_id="run-1",
            mode="values",
            chunk={"messages": [{"type": "human", "content": "subagent task prompt"}]},
            namespace=SUBAGENT_NS,
            file_tool_chunk_batcher=None,
            subagent_events=_FakeSubagentEvents(),
        )
        assert [event for _run, event, _payload in bridge.published] == ["values|tools:call_subagent_1"]

    @pytest.mark.asyncio
    async def test_root_values_snapshot_keeps_bare_event_name(self):
        bridge = _FakeBridge()
        await _publish_stream_item(
            bridge=bridge,
            run_id="run-1",
            mode="values",
            chunk={"messages": []},
            namespace=(),
            file_tool_chunk_batcher=None,
            subagent_events=_FakeSubagentEvents(),
        )
        assert [event for _run, event, _payload in bridge.published] == ["values"]

    @pytest.mark.asyncio
    async def test_subagent_message_chunks_are_namespaced(self):
        bridge = _FakeBridge()
        await _publish_stream_item(
            bridge=bridge,
            run_id="run-1",
            mode="messages",
            chunk=({"content": "token"}, {"langgraph_node": "model"}),
            namespace=SUBAGENT_NS,
            file_tool_chunk_batcher=_SpyBatcher(),
            subagent_events=_FakeSubagentEvents(),
        )
        assert [event for _run, event, _payload in bridge.published] == ["messages|tools:call_subagent_1"]

    @pytest.mark.asyncio
    async def test_root_custom_event_is_persisted_for_subagent_history(self):
        bridge = _FakeBridge()
        subagent_events = _FakeSubagentEvents()
        chunk = {"type": "task_started", "task_id": "call_1"}
        await _publish_stream_item(
            bridge=bridge,
            run_id="run-1",
            mode="custom",
            chunk=chunk,
            namespace=(),
            file_tool_chunk_batcher=None,
            subagent_events=subagent_events,
        )
        assert [event for _run, event, _payload in bridge.published] == ["custom"]
        assert subagent_events.added == [chunk]

    @pytest.mark.asyncio
    async def test_subgraph_custom_event_is_not_persisted(self):
        bridge = _FakeBridge()
        subagent_events = _FakeSubagentEvents()
        await _publish_stream_item(
            bridge=bridge,
            run_id="run-1",
            mode="custom",
            chunk={"type": "noise"},
            namespace=SUBAGENT_NS,
            file_tool_chunk_batcher=None,
            subagent_events=subagent_events,
        )
        assert [event for _run, event, _payload in bridge.published] == ["custom|tools:call_subagent_1"]
        assert subagent_events.added == []

    @pytest.mark.asyncio
    async def test_only_root_frames_drive_the_file_tool_batcher(self):
        bridge = _FakeBridge()
        batcher = _SpyBatcher()
        # A subagent values frame must not finish() a pending root batch...
        await _publish_stream_item(
            bridge=bridge,
            run_id="run-1",
            mode="values",
            chunk={"messages": []},
            namespace=SUBAGENT_NS,
            file_tool_chunk_batcher=batcher,
            subagent_events=_FakeSubagentEvents(),
        )
        assert batcher.finish_calls == 0
        assert batcher.pushed == []
        # ...while a root values frame does.
        await _publish_stream_item(
            bridge=bridge,
            run_id="run-1",
            mode="values",
            chunk={"messages": []},
            namespace=(),
            file_tool_chunk_batcher=batcher,
            subagent_events=_FakeSubagentEvents(),
        )
        assert batcher.finish_calls == 1

    @pytest.mark.asyncio
    async def test_root_message_chunks_go_through_the_batcher(self):
        bridge = _FakeBridge()
        batcher = _SpyBatcher()
        chunk = ({"content": "token"}, {"langgraph_node": "model"})
        await _publish_stream_item(
            bridge=bridge,
            run_id="run-1",
            mode="messages",
            chunk=chunk,
            namespace=(),
            file_tool_chunk_batcher=batcher,
            subagent_events=_FakeSubagentEvents(),
        )
        assert batcher.pushed == [chunk]
        assert [event for _run, event, _payload in bridge.published] == ["messages"]


# ---------------------------------------------------------------------------
# Production-shaped integration: SubagentExecutor -> astream(subgraphs=...)
# -> run_agent stream loop -> StreamBridge. The namespace must originate from
# LangGraph's own delegation routing (checkpoint-namespace inheritance), not
# be hand-fed to the publishing helper — the #4399 regression lived in that
# interaction, not in any helper in isolation.
# ---------------------------------------------------------------------------

_CHILD_MESSAGE_IDS = frozenset(
    {
        "child-task-sentinel",
        "child-ai-sentinel",
        "child-tool-sentinel",
        "child-final-sentinel",
    }
)
_PARENT_FINAL_ID = "parent-final-sentinel"
_THREAD_ID = "thread-subgraph-stream-integration"


@pytest.fixture
def real_executor_module():
    """Swap the conftest MagicMock for the real subagent executor module.

    conftest.py mocks ``deerflow.subagents.executor`` to break a package-init
    import cycle; by the time this fixture runs every other deerflow module is
    already imported, so a fresh import of the real module is safe.
    """
    original = sys.modules.get("deerflow.subagents.executor")
    sys.modules.pop("deerflow.subagents.executor", None)
    subagents_pkg = sys.modules.get("deerflow.subagents")
    if subagents_pkg is not None and hasattr(subagents_pkg, "executor"):
        delattr(subagents_pkg, "executor")

    module = importlib.import_module("deerflow.subagents.executor")
    # Hermetic in CI (no config.yaml) — same defaults as test_subagent_executor.
    module.get_app_config = lambda: SimpleNamespace(tool_search=SimpleNamespace(enabled=False))
    module.build_tracing_callbacks = lambda: []
    yield module

    if original is not None:
        sys.modules["deerflow.subagents.executor"] = original
    else:
        sys.modules.pop("deerflow.subagents.executor", None)
    subagents_pkg = sys.modules.get("deerflow.subagents")
    if subagents_pkg is not None and hasattr(subagents_pkg, "executor"):
        delattr(subagents_pkg, "executor")


class _RecordingStreamBridge(MemoryStreamBridge):
    """Real in-memory bridge that also records (event, payload) pairs."""

    def __init__(self) -> None:
        super().__init__()
        self.published: list[tuple[str, object]] = []

    async def publish(self, run_id: str, event: str, payload: object) -> None:
        self.published.append((event, payload))
        await super().publish(run_id, event, payload)


class _IntegrationRunManager:
    def __init__(self, record: RunRecord) -> None:
        self._record = record

    async def wait_for_prior_finalizing(self, *_args, **_kwargs):
        return None

    async def set_status(self, _run_id, status, **_kwargs):
        self._record.status = status

    async def update_model_name(self, *_args, **_kwargs):
        return None

    async def update_run_completion(self, *_args, **_kwargs):
        return None

    async def has_later_started_run(self, *_args, **_kwargs):
        return False

    async def set_finalizing(self, *_args, **_kwargs):
        return None


def _collect_ids(payload: object) -> set[str]:
    """All string ``id`` values anywhere in a serialized stream payload."""
    ids: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            node_id = node.get("id")
            if isinstance(node_id, str):
                ids.add(node_id)
            for value in node.values():
                walk(value)
        elif isinstance(node, (list, tuple)):
            for value in node:
                walk(value)

    walk(payload)
    return ids


def _build_delegating_parent_graph(executor_module, monkeypatch, *, child_emits_error_fallback: bool = False):
    """Real parent graph whose node delegates a scripted child through the
    real ``SubagentExecutor`` and emits ``task_*`` custom events the way the
    production task tool does (root-graph ``get_stream_writer``).

    With ``child_emits_error_fallback`` the child stream contains an assistant
    message carrying the ``deerflow_error_fallback`` marker (not as its final
    message, so the delegation itself still completes) — the shape whose leak
    would mark the *parent* run as errored (#4399).
    """
    from langgraph.config import get_stream_writer
    from langgraph.graph import END, START, MessagesState, StateGraph

    from deerflow.subagents.config import SubagentConfig

    child_builder = StateGraph(MessagesState)
    child_builder.add_node(
        "child_model",
        lambda _state: {
            "messages": [
                AIMessage(
                    content="",
                    id="child-ai-sentinel",
                    tool_calls=[{"name": "child_tool", "args": {}, "id": "child-tool-call", "type": "tool_call"}],
                )
            ]
        },
    )
    child_builder.add_node(
        "child_tool",
        lambda _state: {"messages": [ToolMessage(content="child tool output", name="child_tool", tool_call_id="child-tool-call", id="child-tool-sentinel")]},
    )
    child_builder.add_node(
        "child_fallback",
        lambda _state: {
            "messages": [
                AIMessage(
                    content="child provider failed after retries",
                    id="child-fallback-sentinel",
                    additional_kwargs={"deerflow_error_fallback": True},
                )
            ]
        },
    )
    child_builder.add_node(
        "child_final",
        lambda _state: {"messages": [AIMessage(content="child final answer", id="child-final-sentinel")]},
    )
    child_builder.add_edge(START, "child_model")
    child_builder.add_edge("child_model", "child_tool")
    if child_emits_error_fallback:
        child_builder.add_edge("child_tool", "child_fallback")
        child_builder.add_edge("child_fallback", "child_final")
    else:
        child_builder.add_edge("child_tool", "child_final")
    child_builder.add_edge("child_final", END)
    child_graph = child_builder.compile(checkpointer=False)

    executor = executor_module.SubagentExecutor(
        config=SubagentConfig(
            name="general-purpose",
            description="Namespace integration test agent",
            system_prompt="You are a namespace integration test agent.",
            max_turns=5,
            timeout_seconds=30,
        ),
        tools=[],
        parent_model="test-model",
        thread_id=_THREAD_ID,
        trace_id="trace-namespace-integration",
    )

    async def build_initial_state(task):
        return ({"messages": [HumanMessage(content=task, id="child-task-sentinel")]}, [], None)

    monkeypatch.setattr(executor, "_build_initial_state", build_initial_state)
    monkeypatch.setattr(executor, "_create_agent", lambda *_args, **_kwargs: child_graph)

    async def delegate(_state):
        writer = get_stream_writer()
        task_id = executor.execute_async("run the delegated child graph")
        writer({"type": "task_started", "task_id": task_id})
        try:
            deadline = asyncio.get_running_loop().time() + 10
            while True:
                result = executor_module.get_background_task_result(task_id)
                if result is not None and result.status.is_terminal:
                    break
                if asyncio.get_running_loop().time() >= deadline:
                    pytest.fail("delegated subagent did not complete")
                await asyncio.sleep(0.001)
            assert result.status.value == "completed", f"delegation failed: {result.error}"
        finally:
            executor_module.cleanup_background_task(task_id)
        writer({"type": "task_completed", "task_id": task_id})
        return {"messages": [AIMessage(content="parent final answer", id=_PARENT_FINAL_ID)]}

    parent_builder = StateGraph(MessagesState)
    parent_builder.add_node("delegate", delegate)
    parent_builder.add_edge(START, "delegate")
    parent_builder.add_edge("delegate", END)
    return parent_builder.compile()


async def _run_delegation_through_worker(executor_module, monkeypatch, *, stream_subgraphs: bool, child_emits_error_fallback: bool = False) -> tuple[RunRecord, _RecordingStreamBridge]:
    from langgraph.checkpoint.memory import InMemorySaver

    parent_graph = _build_delegating_parent_graph(executor_module, monkeypatch, child_emits_error_fallback=child_emits_error_fallback)
    bridge = _RecordingStreamBridge()
    record = RunRecord(
        run_id=f"run-ns-int-{int(stream_subgraphs)}",
        thread_id=_THREAD_ID,
        assistant_id="lead-agent",
        status=RunStatus.pending,
        on_disconnect=DisconnectMode.cancel,
        model_name=None,
    )
    record.abort_event = asyncio.Event()

    await worker.run_agent(
        bridge,
        _IntegrationRunManager(record),
        record,
        ctx=worker.RunContext(checkpointer=InMemorySaver()),
        agent_factory=lambda config: parent_graph,
        graph_input={"messages": [HumanMessage(content="delegate to the subagent")]},
        config={"configurable": {"thread_id": _THREAD_ID}},
        stream_modes=["values", "messages-tuple", "custom"],
        stream_subgraphs=stream_subgraphs,
    )
    return record, bridge


@pytest.mark.skipif(
    not _LANGGRAPH_INHERITS_SUBGRAPH_NAMESPACE,
    reason="delegated graphs stream as namespaced subgraphs only on LangGraph >= 1.2.6",
)
class TestWorkerSubgraphStreamIntegration:
    @pytest.mark.asyncio
    async def test_stream_subgraphs_publishes_delegated_frames_namespaced_never_bare(self, real_executor_module, monkeypatch):
        record, bridge = await _run_delegation_through_worker(real_executor_module, monkeypatch, stream_subgraphs=True)
        assert record.status == RunStatus.success, f"run failed: {bridge.published}"

        events = bridge.published
        bare_values = [payload for event, payload in events if event == "values"]
        bare_messages = [payload for event, payload in events if event == "messages"]
        namespaced_values = [(event, payload) for event, payload in events if event.startswith("values|")]
        namespaced_messages = [(event, payload) for event, payload in events if event.startswith("messages|")]

        # The #4399 takeover: a delegated values snapshot must never be
        # published as bare "values" (SDK clients replace the thread view).
        for payload in bare_values:
            assert not (_collect_ids(payload) & _CHILD_MESSAGE_IDS), f"delegated messages leaked into a bare values frame: {payload}"
        for payload in bare_messages:
            assert not (_collect_ids(payload) & _CHILD_MESSAGE_IDS), f"delegated message chunk leaked into the bare messages stream: {payload}"

        # The delegated frames must actually arrive — namespaced by LangGraph,
        # not silently dropped (guards against a vacuous pass).
        assert any(_collect_ids(payload) & _CHILD_MESSAGE_IDS for _event, payload in namespaced_values), f"expected namespaced delegated values frames, got events: {[event for event, _ in events]}"
        assert any(_collect_ids(payload) & _CHILD_MESSAGE_IDS for _event, payload in namespaced_messages), f"expected namespaced delegated message chunks, got events: {[event for event, _ in events]}"
        for event, _payload in namespaced_values + namespaced_messages:
            segments = event.split("|")[1:]
            assert segments and all(segments), f"namespaced event name has empty namespace segments: {event}"

        # Root frames stay bare and intact.
        assert any(_PARENT_FINAL_ID in _collect_ids(payload) for payload in bare_values)
        custom_types = [payload.get("type") for event, payload in events if event == "custom" and isinstance(payload, dict)]
        assert "task_started" in custom_types and "task_completed" in custom_types

    @pytest.mark.asyncio
    async def test_delegated_error_fallback_does_not_mark_the_parent_run_as_error(self, real_executor_module, monkeypatch):
        record, bridge = await _run_delegation_through_worker(real_executor_module, monkeypatch, stream_subgraphs=True, child_emits_error_fallback=True)

        # A delegated subagent's LLM error fallback is the executor's to map
        # (task_failed); it must not decide the parent run's status.
        assert record.status == RunStatus.success, "delegated error fallback leaked into the parent run status"
        assert not [payload for event, payload in bridge.published if event == "error"]

        # Non-vacuous: the marked child message really rode the stream —
        # namespaced, where the root-only fallback detector must ignore it.
        namespaced_payloads = [payload for event, payload in bridge.published if event.startswith(("values|", "messages|"))]
        assert any("child-fallback-sentinel" in _collect_ids(payload) for payload in namespaced_payloads)

    @pytest.mark.asyncio
    async def test_without_stream_subgraphs_delegated_frames_stay_out_while_task_events_remain(self, real_executor_module, monkeypatch):
        record, bridge = await _run_delegation_through_worker(real_executor_module, monkeypatch, stream_subgraphs=False)
        assert record.status == RunStatus.success, f"run failed: {bridge.published}"

        events = bridge.published
        # No delegated frame of any mode reaches the parent stream...
        for event, payload in events:
            assert not (_collect_ids(payload) & _CHILD_MESSAGE_IDS), f"delegated messages leaked into event {event!r}: {payload}"
        assert not [event for event, _payload in events if "|" in event]

        # ...while the parent's own frames and the task_* progress contract
        # (what the web frontend relies on instead of the flag) still hold.
        bare_values = [payload for event, payload in events if event == "values"]
        assert any(_PARENT_FINAL_ID in _collect_ids(payload) for payload in bare_values)
        custom_types = [payload.get("type") for event, payload in events if event == "custom" and isinstance(payload, dict)]
        assert "task_started" in custom_types and "task_completed" in custom_types
