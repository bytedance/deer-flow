"""Tests for deerflow.config.system_models_config."""

from deerflow.config.system_models_config import (
    SystemModelsConfig,
    get_system_models_config,
    load_system_models_config_from_dict,
    set_system_models_config,
)


class TestSystemModelsConfig:
    def test_default_is_none(self):
        config = SystemModelsConfig()
        assert config.default is None

    def test_accepts_model_name(self):
        config = SystemModelsConfig(default="gpt-4o-mini")
        assert config.default == "gpt-4o-mini"


class TestGetSetSystemModelsConfig:
    def setup_method(self):
        self._original = get_system_models_config()

    def teardown_method(self):
        set_system_models_config(self._original)

    def test_get_returns_current_config(self):
        config = get_system_models_config()
        assert isinstance(config, SystemModelsConfig)

    def test_set_updates_global(self):
        new_config = SystemModelsConfig(default="test-model")
        set_system_models_config(new_config)
        assert get_system_models_config().default == "test-model"

    def test_set_then_reset(self):
        set_system_models_config(SystemModelsConfig(default="first"))
        assert get_system_models_config().default == "first"
        set_system_models_config(SystemModelsConfig(default=None))
        assert get_system_models_config().default is None


class TestLoadSystemModelsConfigFromDict:
    def setup_method(self):
        self._original = get_system_models_config()

    def teardown_method(self):
        set_system_models_config(self._original)

    def test_loads_from_dict_with_default(self):
        load_system_models_config_from_dict({"default": "loaded-model"})
        assert get_system_models_config().default == "loaded-model"

    def test_loads_from_empty_dict(self):
        load_system_models_config_from_dict({})
        assert get_system_models_config().default is None

    def test_loads_overwrites_previous(self):
        load_system_models_config_from_dict({"default": "first"})
        load_system_models_config_from_dict({"default": "second"})
        assert get_system_models_config().default == "second"
