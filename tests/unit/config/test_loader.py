# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import os
import tempfile
from src.config.loader import load_yaml_config, process_dict, replace_env_vars


def test_replace_env_vars_with_env(monkeypatch):
    monkeypatch.setenv("TEST_ENV", "env_value")
    assert replace_env_vars("$TEST_ENV") == "env_value"


def test_replace_env_vars_without_env(monkeypatch):
    monkeypatch.delenv("NOT_SET_ENV", raising=False)
    assert replace_env_vars("$NOT_SET_ENV") == "NOT_SET_ENV"


def test_replace_env_vars_non_string():
    assert replace_env_vars(123) == 123


def test_replace_env_vars_regular_string():
    assert replace_env_vars("no_env") == "no_env"


def test_process_dict_nested(monkeypatch):
    monkeypatch.setenv("FOO", "bar")
    config = {"a": "$FOO", "b": {"c": "$FOO", "d": 42, "e": "$NOT_SET_ENV"}}
    processed = process_dict(config)
    assert processed["a"] == "bar"
    assert processed["b"]["c"] == "bar"
    assert processed["b"]["d"] == 42
    assert processed["b"]["e"] == "NOT_SET_ENV"


def test_process_dict_empty():
    assert process_dict({}) == {}


def test_load_yaml_config_file_not_exist():
    assert load_yaml_config("non_existent_file.yaml") == {}


def test_load_yaml_config(monkeypatch):
    monkeypatch.setenv("MY_ENV", "my_value")
    yaml_content = """
    key1: value1
    key2: $MY_ENV
    nested:
      key3: $MY_ENV
      key4: 123
    """
    with tempfile.NamedTemporaryFile("w+", delete=False) as tmp:
        tmp.write(yaml_content)
        tmp_path = tmp.name

    try:
        config = load_yaml_config(tmp_path)
        assert config["key1"] == "value1"
        assert config["key2"] == "my_value"
        assert config["nested"]["key3"] == "my_value"
        assert config["nested"]["key4"] == 123
    finally:
        os.remove(tmp_path)


def test_load_yaml_config_cache(monkeypatch):
    monkeypatch.setenv("CACHE_ENV", "cache_value")
    yaml_content = "foo: $CACHE_ENV"
    with tempfile.NamedTemporaryFile("w+", delete=False) as tmp:
        tmp.write(yaml_content)
        tmp_path = tmp.name

    try:
        config1 = load_yaml_config(tmp_path)
        config2 = load_yaml_config(tmp_path)
        assert config1 is config2  # Should be cached (same object)
        assert config1["foo"] == "cache_value"
    finally:
        os.remove(tmp_path)
