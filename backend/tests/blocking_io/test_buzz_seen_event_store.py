"""Regression coverage for Buzz replay-guard persistence on async paths.

Buzz receives and stops channels on the Gateway event loop. Persisting the
seen-event replay guard must therefore stay off that loop while still making a
clean stop durable before it returns.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.channels.buzz_seen_events import BuzzSeenEventStore

pytestmark = pytest.mark.asyncio

_CHANNEL_ID = "136852ee-63e1-49c2-8927-413b5ee8e5f7"


async def test_async_replay_guard_round_trips_without_blocking_the_event_loop(tmp_path: Path) -> None:
    """An async flush makes a recorded event visible to a fresh store."""
    path = tmp_path / "buzz-seen-events.json"
    store = BuzzSeenEventStore(path)

    await store.arecord(_CHANNEL_ID, "event-1")
    await store.aflush()

    restarted = BuzzSeenEventStore(path)
    assert await restarted.aseen(_CHANNEL_ID, "event-1")
