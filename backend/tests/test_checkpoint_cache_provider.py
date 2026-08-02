"""Provider wiring: mode-gated wrapping in async and sync checkpointer factories."""

import pytest

from deerflow.config.app_config import AppConfig, set_app_config
from deerflow.runtime.checkpoint_mode import freeze_checkpoint_channel_mode
from deerflow.runtime.checkpointer.async_provider import make_checkpointer
from deerflow.runtime.checkpointer.cached_saver import CachedHistorySaver
from deerflow.runtime.checkpointer.provider import checkpointer_context, reset_checkpointer


# AppConfig requires the sandbox section (no default); the rest of the config
# is optional. Mirrors test_checkpoint_cache_redis.py's construction pattern.
def _app_config(mode: str, cache: dict | None = None) -> AppConfig:
    database: dict = {"backend": "memory", "checkpoint_channel_mode": mode}
    if cache is not None:
        database["checkpoint_cache"] = cache
    return AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local.provider:LocalSandboxProvider"},
            "database": database,
        }
    )


@pytest.mark.anyio
async def test_delta_mode_wraps_with_cached_saver():
    set_app_config(_app_config("delta"))
    freeze_checkpoint_channel_mode("delta")
    async with make_checkpointer() as saver:
        assert isinstance(saver, CachedHistorySaver)
        assert saver.stats()["entries"] == 0


@pytest.mark.anyio
async def test_full_mode_yields_raw_saver():
    set_app_config(_app_config("full"))
    freeze_checkpoint_channel_mode("full")
    async with make_checkpointer() as saver:
        assert not isinstance(saver, CachedHistorySaver)


@pytest.mark.anyio
async def test_zero_max_entries_disables_but_still_wraps():
    set_app_config(_app_config("delta", {"max_entries": 0}))
    freeze_checkpoint_channel_mode("delta")
    async with make_checkpointer() as saver:
        assert isinstance(saver, CachedHistorySaver)
        # Disabled cache -> every history call is a full walk on the inner saver.
        assert saver._cache.enabled is False


def test_sync_delta_mode_wraps_memory():
    set_app_config(_app_config("delta"))
    freeze_checkpoint_channel_mode("delta")
    reset_checkpointer()
    with checkpointer_context() as saver:
        assert isinstance(saver, CachedHistorySaver)


def test_sync_redis_cache_type_is_config_error():
    set_app_config(_app_config("delta", {"type": "redis"}))
    freeze_checkpoint_channel_mode("delta")
    reset_checkpointer()
    with pytest.raises(ValueError, match="redis"):
        with checkpointer_context():
            pass


def test_sync_full_mode_unwrapped():
    set_app_config(_app_config("full"))
    freeze_checkpoint_channel_mode("full")
    reset_checkpointer()
    with checkpointer_context() as saver:
        assert not isinstance(saver, CachedHistorySaver)


def test_sync_cache_recreated_when_key_prefix_changes():
    """The singleton must not outlive its namespace: a prefix change without
    a process restart leaves old-prefix entries unreachable and unpurgeable."""
    reset_checkpointer()
    set_app_config(_app_config("delta", {"key_prefix": "ns-a"}))
    freeze_checkpoint_channel_mode("delta")
    with checkpointer_context() as saver:
        saver._cache.set_many({"ns-a:t1:x": {"writes": []}})
        first_cache = saver._cache
    # Same prefix: singleton is reused (warm across wrappers).
    with checkpointer_context() as saver:
        assert saver._cache is first_cache
        assert saver._cache.stats().entries == 1
    # Prefix change: fresh cache, stale namespace gone with the old instance.
    set_app_config(_app_config("delta", {"key_prefix": "ns-b"}))
    with checkpointer_context() as saver:
        assert saver._cache is not first_cache
        assert saver._cache.stats().entries == 0
    reset_checkpointer()
