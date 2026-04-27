import json

import pytest
import yaml

from deerflow.config.app_config import AppConfig
from deerflow.config.image_model_config import ImageModelConfig


def _base_config() -> dict:
    return {"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}}


def test_image_generate_model_list_is_normalized_to_single_entry():
    config = _base_config()
    config["image_generate_model"] = [
        {
            "name": "doubao-seedream",
            "model": "doubao-seedream-5-0-250415",
            "api_base": "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
            "api_key": "test-key",
        }
    ]

    app_config = AppConfig.model_validate(config)

    assert isinstance(app_config.image_generate_model, ImageModelConfig)
    assert app_config.image_generate_model.name == "doubao-seedream"


def test_image_generate_model_api_key_supports_env_substitution(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"

    config = _base_config()
    config["image_generate_model"] = {
        "name": "doubao-seedream",
        "model": "doubao-seedream-5-0-250415",
        "api_base": "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
        "api_key": "$IMAGE_API_KEY",
    }
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    extensions_path.write_text(json.dumps({"mcpServers": {}, "skills": {}}), encoding="utf-8")

    monkeypatch.setenv("IMAGE_API_KEY", "resolved-test-key")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))

    app_config = AppConfig.from_file()

    assert app_config.image_generate_model is not None
    assert app_config.image_generate_model.api_key == "resolved-test-key"


def test_get_image_generator_returns_none_when_unconfigured():
    app_config = AppConfig.model_validate(_base_config())

    assert app_config.get_image_generator() is None


def test_get_image_generator_raises_for_unsupported_provider():
    config = _base_config()
    config["image_generate_model"] = {
        "name": "unknown-provider",
        "model": "whatever",
        "api_base": "https://example.com",
        "api_key": "test-key",
    }
    app_config = AppConfig.model_validate(config)

    with pytest.raises(ValueError, match="Unsupported image provider"):
        app_config.get_image_generator()
