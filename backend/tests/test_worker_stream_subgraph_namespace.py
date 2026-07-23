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

import pytest

from deerflow.runtime.runs.worker import (
    _compose_sse_event,
    _publish_stream_item,
    _unpack_stream_item,
)

SUBAGENT_NS = ("tools:call_subagent_1",)


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
