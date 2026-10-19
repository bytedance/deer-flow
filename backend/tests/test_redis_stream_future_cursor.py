"""Regression tests for reconnect cursors beyond retained Redis stream history."""

import pytest

from deerflow.runtime import StreamGap
from deerflow.runtime.stream_bridge.redis import RedisStreamBridge


class _SnapshotPipeline:
    def __init__(self, entries):
        self.entries = entries

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def xrange(self, *_args, **_kwargs):
        return self

    def xrevrange(self, *_args, **_kwargs):
        return self

    def xread(self, *_args, **_kwargs):
        return self

    async def execute(self):
        return self.entries[:1], self.entries[-1:], []


class _RetainedStream:
    def __init__(self, entries):
        self.entries = entries

    def pipeline(self, *, transaction=True):
        assert transaction
        return _SnapshotPipeline(self.entries)

    async def xread(self, *_args, **_kwargs):
        raise AssertionError("a future cursor must not enter blocking XREAD")


@pytest.mark.anyio
@pytest.mark.parametrize("ended", [False, True])
async def test_future_last_event_id_reports_gap_without_blocking(ended):
    entries = [("1-0", {"kind": "event", "event": "message", "data": "{}"})]
    if ended:
        entries.append(("2-0", {"kind": "end"}))
    bridge = RedisStreamBridge(redis_url="redis://unused", client=_RetainedStream(entries))
    cursor = "9999999999999-0"
    subscriber = bridge.subscribe("run", last_event_id=cursor)

    assert await anext(subscriber) == StreamGap(
        requested_event_id=cursor,
        earliest_available_event_id=entries[0][0],
        latest_available_event_id=entries[-1][0],
    )
    with pytest.raises(StopAsyncIteration):
        await anext(subscriber)
