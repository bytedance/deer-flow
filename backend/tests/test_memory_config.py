import pytest

from src.config.memory_config import DEPRECATED_FILE_BACKEND_ERROR, MemoryConfig, load_memory_config_from_dict, set_memory_config


def test_load_memory_config_rejects_file_backend():
    with pytest.raises(ValueError, match="memory.backend=file is deprecated"):
        load_memory_config_from_dict({"backend": "file"})


def test_set_memory_config_rejects_file_backend():
    with pytest.raises(ValueError, match="memory.backend=file is deprecated"):
        set_memory_config(MemoryConfig(backend="file"))


def test_load_memory_config_accepts_postgres_backend():
    load_memory_config_from_dict({"backend": "postgres", "database_url": "postgres://memory-db"})


def test_memory_config_defaults_to_postgres_backend():
    config = MemoryConfig()

    assert config.backend == "postgres"


def test_get_memory_config_rejects_deprecated_backend_on_access():
    import src.config.memory_config as memory_config_module

    original = memory_config_module._memory_config
    try:
        memory_config_module._memory_config = MemoryConfig(backend="file")
        with pytest.raises(ValueError, match="memory.backend=file is deprecated"):
            memory_config_module.get_memory_config()
    finally:
        memory_config_module._memory_config = original


def test_deprecated_file_backend_error_message_is_stable():
    assert "postgres" in DEPRECATED_FILE_BACKEND_ERROR