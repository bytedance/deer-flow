"""Thread deletion treats configured cache namespaces as literal Redis keys."""

from unittest.mock import AsyncMock, Mock

import pytest

from deerflow.runtime.checkpoint_cache.base import make_history_key
from deerflow.runtime.checkpoint_cache.redis import RedisCheckpointHistoryCache


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("prefix", "thread_id", "sibling_thread_id", "pattern"),
    [
        ("tenant*", "t1", "t10", r"tenant\*:t1:*"),
        ("tenant?", "t1", "t10", r"tenant\?:t1:*"),
        ("tenant[ab]", "t1", "t10", r"tenant\[ab\]:t1:*"),
        (r"tenant\name", "t1", "t10", r"tenant\\name:t1:*"),
        ("plain", "t1", "t10", "plain:t1:*"),
        ("plain", "t1*", "t10", r"plain:t1\*:*"),
    ],
)
async def test_purge_escapes_namespace_and_filters_results(prefix, thread_id, sibling_thread_id, pattern):
    # Exercise the actual purge method without needing a running Redis server.
    # The expected SCAN pattern is a wire-level Redis glob contract; returned
    # keys also include a foreign namespace to pin the final deletion fence.
    cache = RedisCheckpointHistoryCache.__new__(RedisCheckpointHistoryCache)
    client = AsyncMock()
    cache._client = client
    client.connection_pool = Mock()
    client.connection_pool.get_encoder.return_value.encode.side_effect = lambda value: value.encode("utf-8")
    owned = make_history_key(prefix, thread_id, "", "c1", "messages").encode()
    foreign = make_history_key("tenant-other", thread_id, "", "c1", "messages").encode()
    sibling = make_history_key(prefix, sibling_thread_id, "", "c1", "messages").encode()

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
    await cache.adelete_thread(prefix, thread_id)
    assert client.unlink.await_args_list[0].args == (owned,)
    assert client.unlink.await_args_list[1].args == (owned.decode(),)


@pytest.mark.anyio
async def test_purge_does_not_unlink_empty_filtered_page():
    cache = RedisCheckpointHistoryCache.__new__(RedisCheckpointHistoryCache)
    cache._client = AsyncMock()
    cache._client.connection_pool = Mock()
    cache._client.connection_pool.get_encoder.return_value.encode.side_effect = lambda value: value.encode("utf-8")
    cache._client.scan.return_value = (0, [b"other:t1:history"])
    await cache.adelete_thread("owned", "t1")
    cache._client.unlink.assert_not_awaited()


@pytest.mark.anyio
async def test_purge_uses_client_encoding_for_byte_key_fence():
    """A non-UTF-8 Redis client must still unlink its own non-ASCII keys."""
    cache = RedisCheckpointHistoryCache.__new__(RedisCheckpointHistoryCache)
    client = AsyncMock()
    cache._client = client
    client.connection_pool = Mock()
    client.connection_pool.get_encoder.return_value.encode.side_effect = lambda value: value.encode("latin-1")
    owned = make_history_key("café", "t1", "", "c1", "messages").encode("latin-1")
    sibling = make_history_key("café", "t10", "", "c1", "messages").encode("latin-1")
    client.scan.return_value = (0, [owned, sibling])

    await cache.adelete_thread("café", "t1")

    client.scan.assert_awaited_once_with(cursor=0, match="café:t1:*", count=500)
    client.unlink.assert_awaited_once_with(owned)
