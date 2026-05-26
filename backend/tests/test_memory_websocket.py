"""Tests for memory WebSocket/SSE event emission."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from deerflow.memory_events import MemoryEventBus


# ---------------------------------------------------------------------------
# MemoryEventBus unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_bus_publish_to_subscriber():
    """Published events are received by subscribers."""
    bus = MemoryEventBus()
    queue = bus.subscribe("tenant-1")

    await bus.publish("tenant-1", "memory_updated", {"layer": "user", "action": "create"})

    message = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert message["event"] == "memory_updated"
    assert message["data"]["layer"] == "user"
    assert message["data"]["action"] == "create"

    bus.unsubscribe("tenant-1", queue)


@pytest.mark.asyncio
async def test_event_bus_tenant_isolation():
    """Events are only delivered to subscribers of the same tenant."""
    bus = MemoryEventBus()
    queue1 = bus.subscribe("tenant-1")
    queue2 = bus.subscribe("tenant-2")

    await bus.publish("tenant-1", "memory_updated", {"layer": "user"})

    assert queue2.empty()
    message = await asyncio.wait_for(queue1.get(), timeout=1.0)
    assert message["data"]["layer"] == "user"

    bus.unsubscribe("tenant-1", queue1)
    bus.unsubscribe("tenant-2", queue2)


@pytest.mark.asyncio
async def test_event_bus_no_subscribers():
    """Publishing to a tenant with no subscribers does not raise."""
    bus = MemoryEventBus()
    await bus.publish("tenant-1", "memory_updated", {"layer": "user"})


@pytest.mark.asyncio
async def test_event_bus_multiple_subscribers():
    """All subscribers of a tenant receive the event."""
    bus = MemoryEventBus()
    q1 = bus.subscribe("tenant-1")
    q2 = bus.subscribe("tenant-1")

    await bus.publish("tenant-1", "memory_updated", {"action": "delete"})

    m1 = await asyncio.wait_for(q1.get(), timeout=1.0)
    m2 = await asyncio.wait_for(q2.get(), timeout=1.0)
    assert m1["data"]["action"] == "delete"
    assert m2["data"]["action"] == "delete"

    bus.unsubscribe("tenant-1", q1)
    bus.unsubscribe("tenant-1", q2)


@pytest.mark.asyncio
async def test_event_bus_unsubscribe():
    """Unsubscribed queues no longer receive events."""
    bus = MemoryEventBus()
    queue = bus.subscribe("tenant-1")
    bus.unsubscribe("tenant-1", queue)

    await bus.publish("tenant-1", "memory_updated", {"layer": "user"})
    assert queue.empty()


@pytest.mark.asyncio
async def test_event_bus_stream_yields_sse():
    """The stream() method yields SSE-formatted strings."""
    bus = MemoryEventBus()

    async def publisher():
        await asyncio.sleep(0.05)
        await bus.publish("tenant-1", "memory_updated", {"fact_id": "f1"})
        await asyncio.sleep(0.05)

    task = asyncio.create_task(publisher())

    count = 0
    async for chunk in bus.stream("tenant-1"):
        assert "event: memory_updated" in chunk
        assert "fact_id" in chunk
        count += 1
        if count >= 1:
            break

    await task


# ---------------------------------------------------------------------------
# Integration: emit_memory_update publishes to bus
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emit_memory_update_publishes_to_bus():
    """emit_memory_update publishes an event to the bus."""
    from app.gateway.routers.memory import emit_memory_update

    bus = MemoryEventBus()
    queue = bus.subscribe("test-tenant")

    with (
        patch("app.gateway.routers.memory.get_current_tenant_id", return_value="test-tenant"),
        patch("deerflow.memory_events.get_memory_event_bus", return_value=bus),
    ):
        await emit_memory_update(layer="user", action="create", fact_id="f1")

    message = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert message["event"] == "memory_updated"
    assert message["data"]["layer"] == "user"
    assert message["data"]["fact_id"] == "f1"

    bus.unsubscribe("test-tenant", queue)
