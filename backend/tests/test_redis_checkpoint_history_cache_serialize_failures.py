"""Redis checkpoint-cache writes stay best-effort on serialization errors."""

import pytest

from deerflow.runtime.checkpoint_cache import redis as redis_mod


class _Serde:
    def dumps_typed(self, entry):
        if entry.get("bad"):
            raise TypeError("sensitive serializer detail")
        return "json", b"encoded"


class _Pipeline:
    def __init__(self):
        self.writes = []
        self.executed = False

    def set(self, key, value, ex=None):
        self.writes.append((key, value, ex))
        return self

    async def execute(self):
        self.executed = True


class _Redis:
    def __init__(self):
        self.pipe = _Pipeline()

    def pipeline(self, *, transaction=False):
        assert transaction is False
        return self.pipe


@pytest.mark.anyio
async def test_redis_cache_skips_unserializable_entry_but_writes_other_entries(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake = _Redis()
    monkeypatch.setattr(redis_mod, "_create_client", lambda *_args, **_kwargs: fake)
    cache = redis_mod.RedisCheckpointHistoryCache("redis://unused", serde=_Serde(), ttl_seconds=60)

    with caplog.at_level("WARNING"):
        await cache.aset_many(
            {
                "before": {"writes": []},
                "broken": {"writes": [], "bad": True},
                "after": {"writes": []},
            }
        )

    assert fake.pipe.executed
    assert fake.pipe.writes == [
        ("before", b"json\x00encoded", 60),
        ("after", b"json\x00encoded", 60),
    ]
    assert "broken" in caplog.text
    assert "TypeError" in caplog.text
    assert "sensitive serializer detail" not in caplog.text
    assert cache.stats().write_serialization_failures == 1
    assert cache.stats().as_dict()["write_serialization_failures"] == 1
