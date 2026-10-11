"""Thread deletion treats configured cache namespaces as literal Redis keys."""

from unittest.mock import AsyncMock

import pytest

from deerflow.runtime.checkpoint_cache.base import make_history_key
from deerflow.runtime.checkpoint_cache.redis import RedisCheckpointHistoryCache


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("prefix", "pattern"),
    [
        ("tenant*", r"tenant\*:t1:*"),
        ("tenant?", r"tenant\?:t1:*"),
        ("tenant[ab]", r"tenant\[ab\]:t1:*"),
        (r"tenant\name", r"tenant\\name:t1:*"),
        ("plain", "plain:t1:*"),
    ],
)
async def test_purge_escapes_namespace_and_filters_results(prefix, pattern):
    # Exercise the actual purge method without needing a running Redis server.
    # The expected SCAN pattern is a wire-level Redis glob contract; returned
    # keys also include a foreign namespace to pin the final deletion fence.
    cache = RedisCheckpointHistoryCache.__new__(RedisCheckpointHistoryCache)
    client = AsyncMock()
    cache._client = client
    owned = make_history_key(prefix, "t1", "", "c1", "messages").encode()
    foreign = make_history_key("tenant-other", "t1", "", "c1", "messages").encode()
    sibling = make_history_key(prefix, "t10", "", "c1", "messages").encode()

    async def scan(*, cursor, match, count):
        assert match == pattern
        assert count == 500
        # Mixed byte/string results and multiple pages exercise redis clients
        # with either response mode and preserve the scan cursor protocol.
        if cursor == 0:
            return 7, [owned, foreign, sibling]
        assert cursor == 7
        return 0, [owned.decode()]

    client.scan.side_effect = scan
    await cache.adelete_thread(prefix, "t1")
    assert client.unlink.await_args_list[0].args == (owned,)
    assert client.unlink.await_args_list[1].args == (owned.decode(),)


@pytest.mark.anyio
async def test_purge_does_not_unlink_empty_filtered_page():
    cache = RedisCheckpointHistoryCache.__new__(RedisCheckpointHistoryCache)
    cache._client = AsyncMock()
    cache._client.scan.return_value = (0, [b"other:t1:history"])
    await cache.adelete_thread("owned", "t1")
    cache._client.unlink.assert_not_awaited()
