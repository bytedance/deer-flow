"""Redis backend and provider factory for the checkpoint history cache."""

from typing import Any

import pytest
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from deerflow.config.app_config import AppConfig
from deerflow.runtime.checkpoint_cache.provider import (
    checkpoint_cache_db_hash,
    checkpoint_cache_key_prefix,
    make_checkpoint_cache,
)


class _FakeRedis:
    """Minimal async redis stand-in: mget / set / pipeline / scan / unlink."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.ttls: dict[str, int | None] = {}
        self.unlinked: list[tuple[str, ...]] = []

    async def mget(self, keys: list[str]) -> list[bytes | None]:
        return [self.store.get(k) for k in keys]

    def set(self, key: str, value: bytes, ex: int | None = None) -> None:
        self.store[key] = value
        self.ttls[key] = ex

    async def scan(self, cursor: int = 0, match: str | None = None, count: int = 500) -> tuple[int, list[str]]:
        import fnmatch

        keys = sorted(self.store)
        batch = keys[cursor : cursor + count]
        if match is not None:
            batch = [k for k in batch if fnmatch.fnmatchcase(k, match)]
        next_cursor = cursor + count
        return (0 if next_cursor >= len(keys) else next_cursor), batch

    async def unlink(self, *keys: str) -> int:
        self.unlinked.append(tuple(keys))
        removed = 0
        for key in keys:
            removed += self.store.pop(key, None) is not None
        return removed

    def pipeline(self, transaction: bool = False) -> "_FakePipeline":
        return _FakePipeline(self)

    async def aclose(self) -> None:
        pass


class _FakePipeline:
    def __init__(self, client: _FakeRedis) -> None:
        self._client = client

    def set(self, key: str, value: bytes, ex: int | None = None) -> "_FakePipeline":
        self._client.set(key, value, ex=ex)
        return self

    async def execute(self) -> None:
        pass


class _FailingRedis(_FakeRedis):
    """Simulates a redis outage: every operation raises RedisError."""

    async def mget(self, keys: list[str]) -> list[bytes | None]:
        from redis.exceptions import RedisError

        raise RedisError("connection refused")

    async def scan(self, cursor: int = 0, match: str | None = None, count: int = 500) -> tuple[int, list[str]]:
        from redis.exceptions import RedisError

        raise RedisError("connection refused")

    def pipeline(self, transaction: bool = False) -> "_FakePipeline":
        from redis.exceptions import RedisError

        raise RedisError("connection refused")


def _make_cache(monkeypatch: pytest.MonkeyPatch, fake: _FakeRedis, ttl_seconds: int = 60, **kwargs: Any):
    import deerflow.runtime.checkpoint_cache.redis as redis_mod

    monkeypatch.setattr(redis_mod, "_create_client", lambda *a, **k: fake)
    return redis_mod.RedisCheckpointHistoryCache("redis://unused", serde=JsonPlusSerializer(), ttl_seconds=ttl_seconds, **kwargs)


def _entry(i: int) -> dict:
    # Real message-like payloads to prove serde fidelity beyond plain dicts.
    from langchain_core.messages import AIMessage

    return {"writes": [("task-1", "messages", AIMessage(content=f"m{i}", id=f"ai-{i}"))], "seed": [AIMessage(content="s", id="ai-s")]}


# AppConfig requires the sandbox section (no default); the rest of the config
# is optional. Mirrors test_checkpoint_mode.py's construction pattern.
def _app_config(database: dict) -> AppConfig:
    return AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local.provider:LocalSandboxProvider"},
            "database": database,
        }
    )


@pytest.mark.anyio
async def test_redis_roundtrip_preserves_types(monkeypatch: pytest.MonkeyPatch):
    fake = _FakeRedis()
    cache = _make_cache(monkeypatch, fake)
    await cache.aset_many({"k1": _entry(1), "k2": {"writes": []}})
    hit = await cache.aget_many(["k1", "k2", "k3"])
    assert set(hit) == {"k1", "k2"}
    msg = hit["k1"]["writes"][0][2]
    assert msg.content == "m1" and msg.id == "ai-1" and msg.type == "ai"
    assert "seed" not in hit["k2"]
    assert cache.stats().hits == 2 and cache.stats().misses == 1


@pytest.mark.anyio
async def test_redis_keys_land_verbatim_and_ttl_set(monkeypatch: pytest.MonkeyPatch):
    fake = _FakeRedis()
    cache = _make_cache(monkeypatch, fake)
    await cache.aset_many({"k1": _entry(1)})
    assert list(fake.store) == ["k1"]
    assert fake.ttls["k1"] == 60


@pytest.mark.anyio
async def test_redis_outage_degrades_to_all_miss(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    fake = _FailingRedis()
    cache = _make_cache(monkeypatch, fake)
    with caplog.at_level("WARNING"):
        assert await cache.aget_many(["k1", "k2"]) == {}
    assert cache.stats().misses == 2 and cache.stats().hits == 0
    assert "mget failed" in caplog.text


@pytest.mark.anyio
async def test_redis_outage_skips_write(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    fake = _FailingRedis()
    cache = _make_cache(monkeypatch, fake)
    with caplog.at_level("WARNING"):
        await cache.aset_many({"k1": _entry(1)})  # must not raise
    assert fake.store == {}
    assert "write failed" in caplog.text


@pytest.mark.anyio
async def test_zero_ttl_disables_expiry_explicitly(monkeypatch: pytest.MonkeyPatch):
    fake = _FakeRedis()
    cache = _make_cache(monkeypatch, fake, ttl_seconds=0)
    await cache.aset_many({"k1": _entry(1)})
    assert cache._ttl is None
    assert fake.ttls["k1"] is None  # SET without EX: redis maxmemory policy only


@pytest.mark.anyio
async def test_adelete_thread_purges_matching_keys_only(monkeypatch: pytest.MonkeyPatch):
    fake = _FakeRedis()
    cache = _make_cache(monkeypatch, fake)
    prefix = "ckpt-hist:v1:db0"
    await cache.aset_many(
        {
            f"{prefix}:t1:aaa": _entry(1),
            f"{prefix}:t1:bbb": _entry(2),
            f"{prefix}:t10:ccc": _entry(3),  # 't1' stem must not over-match 't10'
            f"{prefix}:t2:ddd": _entry(4),
        }
    )

    await cache.adelete_thread(prefix, "t1")

    assert sorted(fake.store) == [f"{prefix}:t10:ccc", f"{prefix}:t2:ddd"]
    assert fake.unlinked  # UNLINK, not DEL: non-blocking on big histories


@pytest.mark.anyio
async def test_adelete_thread_outage_degrades_without_raising(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    fake = _FailingRedis()
    cache = _make_cache(monkeypatch, fake)
    with caplog.at_level("WARNING"):
        await cache.adelete_thread("p", "t1")  # must not raise
    assert "thread purge failed" in caplog.text


@pytest.mark.anyio
async def test_provider_memory_default():
    from deerflow.runtime.checkpoint_cache.memory import MemoryCheckpointHistoryCache

    async with make_checkpoint_cache(_app_config({"backend": "sqlite"}), serde=JsonPlusSerializer()) as cache:
        assert isinstance(cache, MemoryCheckpointHistoryCache)
        assert cache.enabled is True


@pytest.mark.anyio
async def test_provider_zero_max_entries_disables_any_type():
    app_config = _app_config({"backend": "sqlite", "checkpoint_cache": {"type": "redis", "max_entries": 0}})
    from deerflow.runtime.checkpoint_cache.memory import MemoryCheckpointHistoryCache

    async with make_checkpoint_cache(app_config, serde=JsonPlusSerializer()) as cache:
        assert isinstance(cache, MemoryCheckpointHistoryCache)
        assert cache.enabled is False


def test_db_hash_distinguishes_backends_and_targets():
    from deerflow.config.database_config import DatabaseConfig

    sqlite_cfg = DatabaseConfig.model_validate({"backend": "sqlite", "sqlite_dir": "/tmp/a"})
    pg_cfg = DatabaseConfig.model_validate({"backend": "postgres", "postgres_url": "postgresql://u:p@h/db"})
    pg_cfg2 = DatabaseConfig.model_validate({"backend": "postgres", "postgres_url": "postgresql://u:p@h/other"})
    assert checkpoint_cache_db_hash(sqlite_cfg) != checkpoint_cache_db_hash(pg_cfg)
    assert checkpoint_cache_db_hash(pg_cfg) != checkpoint_cache_db_hash(pg_cfg2)
    assert len(checkpoint_cache_db_hash(pg_cfg)) == 12


def test_db_hash_stable_across_credential_rotation():
    """Same database, rotated user/password -> same cache namespace."""
    from deerflow.config.database_config import DatabaseConfig

    before = DatabaseConfig.model_validate({"backend": "postgres", "postgres_url": "postgresql://alice:secret1@pg.internal:5432/deerflow"})
    rotated = DatabaseConfig.model_validate({"backend": "postgres", "postgres_url": "postgresql://bob:secret2@pg.internal:5432/deerflow"})
    driver_suffix = DatabaseConfig.model_validate({"backend": "postgres", "postgres_url": "postgresql+asyncpg://alice:secret1@pg.internal:5432/deerflow"})
    other_db = DatabaseConfig.model_validate({"backend": "postgres", "postgres_url": "postgresql://alice:secret1@pg.internal:5432/other"})
    assert checkpoint_cache_db_hash(before) == checkpoint_cache_db_hash(rotated)
    assert checkpoint_cache_db_hash(before) == checkpoint_cache_db_hash(driver_suffix)
    assert checkpoint_cache_db_hash(before) != checkpoint_cache_db_hash(other_db)


def test_db_hash_unparseable_url_falls_back_to_raw():
    from deerflow.config.database_config import DatabaseConfig

    cfg = DatabaseConfig.model_validate({"backend": "postgres", "postgres_url": "not-a-url"})
    assert len(checkpoint_cache_db_hash(cfg)) == 12  # stable, never raises


def test_key_prefix_override_wins():
    app_config = _app_config({"backend": "sqlite", "checkpoint_cache": {"key_prefix": "custom:"}})
    assert checkpoint_cache_key_prefix(app_config) == "custom:"
    default = checkpoint_cache_key_prefix(_app_config({"backend": "sqlite"}))
    assert default.startswith("ckpt-hist:v1:")
