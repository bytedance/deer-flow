from copy import deepcopy

import httpx
import pytest
from fastapi import FastAPI, Request
from langgraph_sdk.sse import SSEDecoder, aiter_lines_raw
from starlette.responses import StreamingResponse

from deerflow.runtime.stream_bridge import END_SENTINEL, MemoryStreamBridge


@pytest.mark.asyncio
async def test_publish_captures_each_nested_payload_before_producer_reuses_it():
    bridge = MemoryStreamBridge()
    payload = {"messages": [{"content": [{"text": "first"}]}]}
    first = deepcopy(payload)
    try:
        await bridge.publish("run", "values", payload)
        payload["messages"][0]["content"][0]["text"] = "second"
        second = deepcopy(payload)
        await bridge.publish("run", "values", payload)
        payload["messages"].clear()
        await bridge.publish_end("run")

        events = [entry async for entry in bridge.subscribe("run")]
        assert [entry.data for entry in events[:-1]] == [first, second]
        assert events[-1] is END_SENTINEL
    finally:
        await bridge.close()


@pytest.mark.asyncio
async def test_subscriber_mutation_does_not_reach_another_reader_or_replay():
    bridge = MemoryStreamBridge()
    expected = {"tool_calls": [{"args": {"paths": ["original.txt"]}}]}
    try:
        await bridge.publish("run", "metadata", {"run_id": "run"})
        await bridge.publish("run", "updates", deepcopy(expected))
        await bridge.publish_end("run")
        initial = [entry async for entry in bridge.subscribe("run")]
        initial[1].data["tool_calls"][0]["args"]["paths"].append("reader-edit.txt")

        other = [entry async for entry in bridge.subscribe("run")]
        assert other[1].data == expected
        replay = [entry async for entry in bridge.subscribe("run", last_event_id=initial[0].id)]
        assert replay[0].id == initial[1].id
        assert replay[0].event == "updates"
        assert replay[0].data == expected
        assert other[-1] is replay[-1] is END_SENTINEL
        assert replay[0].data is not other[1].data
    finally:
        await bridge.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("namespace", [(), ("child:task",)], ids=["root", "subgraph"])
async def test_worker_metadata_stays_at_publication_time_in_gateway_sse(namespace):
    from langchain_core.messages import AIMessageChunk

    from app.gateway.services import sse_consumer
    from deerflow.runtime import RunManager, RunStatus
    from deerflow.runtime.runs.worker import _publish_stream_item
    from deerflow.runtime.serialization import serialize

    bridge = MemoryStreamBridge()
    manager = RunManager()
    record = await manager.create("snapshot-sse")
    app = FastAPI()

    @app.get("/stream")
    async def stream(request: Request):
        return StreamingResponse(sse_consumer(bridge, record, request, manager, apply_on_disconnect=False), media_type="text/event-stream")

    try:
        expected = []
        metadata = {"langgraph_node": "model", "tags": [], "langgraph_step": 1}
        for step in (1, 2):
            metadata["langgraph_step"] = step
            metadata["tags"].append(f"step-{step}")
            chunk = (AIMessageChunk(content=f"part-{step}", id="answer"), metadata)
            expected.append(deepcopy(serialize(chunk, mode="messages")))
            await _publish_stream_item(bridge=bridge, run_id=record.run_id, mode="messages", chunk=chunk, namespace=namespace, file_tool_chunk_batcher=None, subagent_events=None)
        metadata["tags"].clear()
        await manager.set_status(record.run_id, RunStatus.success)
        await bridge.publish_end(record.run_id)

        async def decode(response):
            assert response.status_code == 200
            decoder = SSEDecoder()
            frames = []
            async for line in aiter_lines_raw(response):
                if (frame := decoder.decode(line)) is not None:
                    frames.append(frame)
            return frames

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            frames = await decode(await client.get("/stream"))
            event_name = "messages" + ("|" + "|".join(namespace) if namespace else "")
            assert [(frame.event, frame.data) for frame in frames] == [(event_name, data) for data in expected] + [("end", None)]
            replay = await decode(await client.get("/stream", headers={"Last-Event-ID": frames[0].id}))
            assert [(frame.id, frame.event, frame.data) for frame in replay] == [(frame.id, frame.event, frame.data) for frame in frames[1:]]
    finally:
        await manager.shutdown()
        await bridge.close()


def _nested_payload(depth):
    value = ["original"]
    for _ in range(depth):
        value = [value]
    return value


def _payload_leaf(value):
    while isinstance(value, list) and len(value) == 1 and isinstance(value[0], list):
        value = value[0]
    return value


def test_snapshot_preserves_custom_hook_memo_overrides_for_values_and_keys():
    from deerflow.runtime.stream_bridge.memory import _snapshot_payload

    atom = "plain-value"

    class Hook:
        def __deepcopy__(self, memo):
            memo[id(atom)] = "hook-replacement"
            return "hook"

    payload = {"hook": Hook(), "value": atom, atom: 1}
    assert _snapshot_payload(payload) == deepcopy(payload)


@pytest.mark.parametrize("container_type", [list, dict])
def test_snapshot_restores_container_memo_before_copying_aliases(container_type):
    from deerflow.runtime.stream_bridge.memory import _snapshot_payload

    shared = container_type()

    class Hook:
        def __deepcopy__(self, memo):
            memo[id(shared)] = "override"
            return "hook"

    if container_type is list:
        shared.append(Hook())
    else:
        shared["hook"] = Hook()
    payload = {"a": shared, "b": shared}
    copied = _snapshot_payload(payload)
    assert copied == deepcopy(payload)
    assert copied["a"] is copied["b"]


@pytest.mark.asyncio
async def test_deep_snapshot_isolates_producer_readers_and_replay():
    bridge = MemoryStreamBridge()
    payload = {"paths": _nested_payload(1200)}
    try:
        await bridge.publish("run", "metadata", {"run_id": "run"})
        await bridge.publish("run", "updates", payload)
        _payload_leaf(payload["paths"]).append("producer-edit")
        await bridge.publish_end("run")

        first = [entry async for entry in bridge.subscribe("run")]
        assert _payload_leaf(first[1].data["paths"]) == ["original"]
        _payload_leaf(first[1].data["paths"]).append("reader-edit")

        other = [entry async for entry in bridge.subscribe("run")]
        replay = [entry async for entry in bridge.subscribe("run", last_event_id=first[0].id)]
        assert _payload_leaf(other[1].data["paths"]) == ["original"]
        assert _payload_leaf(replay[0].data["paths"]) == ["original"]
        assert replay[0].id == first[1].id
        assert replay[0].data is not other[1].data
        assert first[-1] is other[-1] is replay[-1] is END_SENTINEL
    finally:
        await bridge.close()


@pytest.mark.asyncio
async def test_snapshot_keeps_aliases_cycles_and_custom_deepcopy_behavior():
    class HookedList(list):
        def __deepcopy__(self, memo):
            return ["custom-copy"]

    class HookedInt(int):
        def __deepcopy__(self, memo):
            return "custom-int-copy"

    shared = []
    shared.append(shared)
    payload = {"a": shared, "b": shared, ("key", 1): (HookedList([1]), HookedInt(2))}
    expected = deepcopy(payload)
    bridge = MemoryStreamBridge()
    try:
        await bridge.publish("run", "updates", payload)
        await bridge.publish_end("run")
        entries = [entry async for entry in bridge.subscribe("run")]
        copied = entries[0].data
        assert copied["a"] is copied["b"]
        assert copied["a"][0] is copied["a"]
        assert copied["a"] is not shared
        assert copied[("key", 1)] == expected[("key", 1)]
        assert entries[-1] is END_SENTINEL
    finally:
        await bridge.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["custom", "messages"])
@pytest.mark.parametrize("depth", [600, 1200, 20000])
async def test_deep_worker_frame_survives_real_bridge_and_sdk_replay(mode, depth):
    from langchain_core.messages import AIMessage

    from app.gateway.services import format_sse
    from deerflow.runtime.runs.worker import _publish_stream_item, _SubagentEventBuffer
    from deerflow.subagents.step_events import capture_step_message

    bridge = MemoryStreamBridge()
    message = AIMessage(content="REAL", id="answer", tool_calls=[{"name": "t", "args": {"p": _nested_payload(depth)}, "id": "c1", "type": "tool_call"}])
    captured = []
    assert capture_step_message(message, captured, set())
    chunk = {"type": "task_running", "task_id": "c1", "message": captured[0], "message_index": 1} if mode == "custom" else (message, {})
    try:
        await bridge.publish("run", "metadata", {"run_id": "run"})
        # Exercise wire publication with run-event persistence disabled.
        await _publish_stream_item(bridge=bridge, run_id="run", mode=mode, chunk=chunk, namespace=(), file_tool_chunk_batcher=None, subagent_events=_SubagentEventBuffer(None, "thread", "run"))
        await bridge.publish_end("run")

        entries = [entry async for entry in bridge.subscribe("run")]
        replay = [entry async for entry in bridge.subscribe("run", last_event_id=entries[0].id)]
        for event in (entries[1], replay[0]):
            decoder = SSEDecoder()
            frames = []
            for line in format_sse(event.event, event.data, event_id=event.id).encode().split(b"\n"):
                if (frame := decoder.decode(line)) is not None and frame.event:
                    frames.append(frame)
            [decoded] = frames
            assert decoded.id == entries[1].id
            assert decoded.event == mode
            message_data = decoded.data["message"] if mode == "custom" else decoded.data[0]
            assert message_data["content"] == "REAL"
            assert message_data["id"] == "answer"
            assert message_data["tool_calls"][0]["name"] == "t"
            assert message_data["tool_calls"][0]["id"] == "c1"
            node = message_data["tool_calls"][0]["args"]["p"]
            levels = 0
            while isinstance(node, list):
                assert len(node) == 1
                node = node[0]
                levels += 1
            if depth == 600:
                assert levels == depth + 1
                assert node == "original"
            else:
                assert 0 < levels <= 1000
                assert node is None
        assert entries[-1] is replay[-1] is END_SENTINEL
    finally:
        await bridge.close()
