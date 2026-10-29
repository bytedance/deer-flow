import asyncio

import httpx
import pytest
from fastapi import FastAPI, Request
from langgraph_sdk.sse import SSEDecoder, aiter_lines_raw
from starlette.responses import StreamingResponse

from deerflow.runtime.stream_bridge import END_SENTINEL, MemoryStreamBridge, StreamEvent, StreamGap


@pytest.mark.asyncio
@pytest.mark.parametrize("capacity", [1, 2, 256])
async def test_reconnect_replays_all_successors_of_last_evicted_event(capacity):
    bridge = MemoryStreamBridge(queue_maxsize=capacity)
    run_id = "complete-reconnect"
    await bridge.publish(run_id, "messages", {"index": 0})
    live = bridge.subscribe(run_id)
    try:
        cursor = await anext(live)
        assert isinstance(cursor, StreamEvent)
        for index in range(1, capacity + 1):
            await bridge.publish(run_id, "messages", {"index": index})
        await bridge.publish_end(run_id)

        live_events = [entry async for entry in live]
        reconnect = bridge.subscribe(run_id, last_event_id=cursor.id)
        try:
            replayed = await asyncio.wait_for(anext(reconnect), timeout=1)
            assert replayed == live_events[0]
            remaining = [entry async for entry in reconnect]
            assert [replayed, *remaining] == live_events
        finally:
            await reconnect.aclose()

        assert [entry.data for entry in live_events[:-1]] == [{"index": index} for index in range(1, capacity + 1)]
        assert live_events[-1] is END_SENTINEL
    finally:
        await live.aclose()
        await bridge.close()


@pytest.mark.asyncio
async def test_reconnect_reports_gap_when_a_successor_was_evicted():
    bridge = MemoryStreamBridge(queue_maxsize=2)
    run_id = "incomplete-reconnect"
    await bridge.publish(run_id, "messages", {"index": 0})
    live = bridge.subscribe(run_id)
    try:
        cursor = await anext(live)
        for index in range(1, 4):
            await bridge.publish(run_id, "messages", {"index": index})
        await bridge.publish_end(run_id)
        live_events = [entry async for entry in live]
        replayed = [entry async for entry in bridge.subscribe(run_id, last_event_id=cursor.id)]
        assert len(replayed) == 1
        assert isinstance(replayed[0], StreamGap)
        assert replayed == live_events
        assert replayed[0].requested_event_id == cursor.id
    finally:
        await live.aclose()
        await bridge.close()


@pytest.mark.asyncio
async def test_foreign_cursor_with_same_evicted_sequence_still_reports_gap():
    bridge = MemoryStreamBridge(queue_maxsize=1)
    run_id = "foreign-reconnect"
    try:
        await bridge.publish(run_id, "messages", {"index": 0})
        stream = bridge.subscribe(run_id)
        try:
            cursor = await anext(stream)
        finally:
            await stream.aclose()
        timestamp, sequence = cursor.id.split("-")
        foreign_cursor = f"{int(timestamp) + 1}-{sequence}"
        await bridge.publish(run_id, "messages", {"index": 1})
        await bridge.publish_end(run_id)
        replayed = [entry async for entry in bridge.subscribe(run_id, last_event_id=foreign_cursor)]
        assert len(replayed) == 1
        assert isinstance(replayed[0], StreamGap)
        assert replayed[0].requested_event_id == foreign_cursor
    finally:
        await bridge.close()


@pytest.mark.asyncio
async def test_gateway_sse_reconnect_preserves_complete_retained_output():
    from langchain_core.messages import AIMessageChunk

    from app.gateway.services import sse_consumer
    from deerflow.runtime import RunManager, RunStatus
    from deerflow.runtime.serialization import serialize

    bridge = MemoryStreamBridge(queue_maxsize=2)
    manager = RunManager()
    record = await manager.create("complete-sse-reconnect")
    await manager.set_status(record.run_id, RunStatus.success)
    app = FastAPI()

    @app.get("/stream")
    async def stream(request: Request):
        return StreamingResponse(sse_consumer(bridge, record, request, manager, apply_on_disconnect=False), media_type="text/event-stream")

    try:
        payloads = [serialize((AIMessageChunk(content=f"part-{index}", id="answer"), {"langgraph_node": "model"}), mode="messages") for index in range(3)]
        await bridge.publish(record.run_id, "messages", payloads[0])
        initial = bridge.subscribe(record.run_id)
        try:
            cursor = await anext(initial)
        finally:
            await initial.aclose()
        for index in (1, 2):
            await bridge.publish(record.run_id, "messages", payloads[index])
        await bridge.publish_end(record.run_id)

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/stream", headers={"Last-Event-ID": cursor.id})
        assert response.status_code == 200
        decoder = SSEDecoder()
        frames = []
        async for line in aiter_lines_raw(response):
            decoded = decoder.decode(line)
            if decoded is not None:
                frames.append(decoded)
        assert [(frame.event, frame.data) for frame in frames] == [
            ("messages", payloads[1]),
            ("messages", payloads[2]),
            ("end", None),
        ]
        assert [frame.id for frame in frames[:-1]] == [entry.id for entry in bridge._streams[record.run_id].events]
    finally:
        await manager.shutdown()
        await bridge.close()
