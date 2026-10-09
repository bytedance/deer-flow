"""Malformed optional Redis checkpoint cache entries must degrade to misses."""

from __future__ import annotations

from typing import Any

import pytest

from deerflow.runtime.checkpoint_cache import redis as redis_cache


class _RedisClient:
    def __init__(self, values: dict[str, bytes | None]) -> None:
        self.values = values

    async def mget(self, keys: list[str]) -> list[bytes | None]:
        return [self.values.get(key) for key in keys]


class _Serde:
    def loads_typed(self, value: tuple[str, bytes]) -> Any:
        tag, payload = value
        if tag != "json":
            raise ValueError("unknown serializer")
        if payload == b"bad":
            raise ValueError("invalid serialized payload")
        if payload == b"wrong-shape":
            return {"writes": "not a list"}
        if payload == b"ok":
            return {"writes": [], "seed": None}
        raise AssertionError(f"unexpected payload: {payload!r}")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "corrupt",
    [
        b"missing-separator",
        b"\xff\x00ok",
        b"json\x00bad",
        b"json\x00wrong-shape",
    ],
    ids=["missing-separator", "invalid-tag-encoding", "serde-failure", "wrong-shape"],
)
async def test_corrupt_entry_is_miss_while_valid_entry_is_preserved(
    monkeypatch: pytest.MonkeyPatch, corrupt: bytes
) -> None:
    client = _RedisClient({"good": b"json\x00ok", "bad": corrupt, "absent": None})
    monkeypatch.setattr(redis_cache, "_create_client", lambda *args, **kwargs: client)
    cache = redis_cache.RedisCheckpointHistoryCache(
        "redis://unused", serde=_Serde(), ttl_seconds=60
    )

    found = await cache.aget_many(["good", "bad", "absent"])

    assert found == {"good": {"writes": [], "seed": None}}
    stats = cache.stats()
    assert stats.hits == 1
    assert stats.misses == 2
