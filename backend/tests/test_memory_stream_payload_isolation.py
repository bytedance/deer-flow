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
