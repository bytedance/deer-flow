"""Config parsing for database.checkpoint_cache."""

from deerflow.config.database_config import CheckpointCacheConfig, DatabaseConfig


def test_checkpoint_cache_defaults():
    cfg = DatabaseConfig()
    assert cfg.checkpoint_cache.type == "memory"
    assert cfg.checkpoint_cache.max_entries == 128
    assert cfg.checkpoint_cache.redis_url is None
    assert cfg.checkpoint_cache.ttl_seconds == 86400
    assert cfg.checkpoint_cache.key_prefix == ""


def test_checkpoint_cache_from_dict_redis():
    cfg = DatabaseConfig.model_validate(
        {
            "backend": "postgres",
            "postgres_url": "postgresql://u:p@h/db",
            "checkpoint_cache": {
                "type": "redis",
                "max_entries": 256,
                "redis_url": "redis://localhost:6379/3",
                "ttl_seconds": 3600,
                "key_prefix": "prod:",
            },
        }
    )
    assert cfg.checkpoint_cache.type == "redis"
    assert cfg.checkpoint_cache.max_entries == 256
    assert cfg.checkpoint_cache.redis_url == "redis://localhost:6379/3"
    assert cfg.checkpoint_cache.ttl_seconds == 3600
    assert cfg.checkpoint_cache.key_prefix == "prod:"


def test_checkpoint_cache_zero_max_entries_means_disabled():
    cfg = CheckpointCacheConfig(max_entries=0)
    assert cfg.max_entries == 0


def test_checkpoint_cache_rejects_negative_max_entries():
    import pydantic
    import pytest

    with pytest.raises(pydantic.ValidationError):
        CheckpointCacheConfig(max_entries=-1)
