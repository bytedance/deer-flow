"""Tests for config version check and upgrade logic."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import yaml

from deerflow.config.app_config import AppConfig


def _make_config_files(tmpdir: Path, user_config: dict, example_config: dict) -> Path:
    """Write user config.yaml and config.example.yaml to a temp dir, return config path."""
    config_path = tmpdir / "config.yaml"
    example_path = tmpdir / "config.example.yaml"

    # Minimal valid config needs sandbox
    defaults = {
        "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
    }
    for cfg in (user_config, example_config):
        for k, v in defaults.items():
            cfg.setdefault(k, v)

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(user_config, f)
    with open(example_path, "w", encoding="utf-8") as f:
        yaml.dump(example_config, f)

    return config_path


def test_missing_version_treated_as_zero(caplog):
    """Config without config_version should be treated as version 0."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = _make_config_files(
            Path(tmpdir),
            user_config={},  # no config_version
            example_config={"config_version": 1},
        )
        with caplog.at_level(logging.WARNING, logger="deerflow.config.app_config"):
            AppConfig._check_config_version(
                {"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}},
                config_path,
            )
        assert "outdated" in caplog.text
        assert "version 0" in caplog.text
        assert "version is 1" in caplog.text


def test_matching_version_no_warning(caplog):
    """Config with matching version should not emit a warning."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = _make_config_files(
            Path(tmpdir),
            user_config={"config_version": 1},
            example_config={"config_version": 1},
        )
        with caplog.at_level(logging.WARNING, logger="deerflow.config.app_config"):
            AppConfig._check_config_version(
                {"config_version": 1},
                config_path,
            )
        assert "outdated" not in caplog.text


def test_outdated_version_emits_warning(caplog):
    """Config with lower version should emit a warning."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = _make_config_files(
            Path(tmpdir),
            user_config={"config_version": 1},
            example_config={"config_version": 2},
        )
        with caplog.at_level(logging.WARNING, logger="deerflow.config.app_config"):
            AppConfig._check_config_version(
                {"config_version": 1},
                config_path,
            )
        assert "outdated" in caplog.text
        assert "version 1" in caplog.text
        assert "version is 2" in caplog.text


def test_no_example_file_no_warning(caplog):
    """If config.example.yaml doesn't exist, no warning should be emitted."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "config.yaml"
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump({"sandbox": {"use": "test"}}, f)
        # No config.example.yaml created

        with caplog.at_level(logging.WARNING, logger="deerflow.config.app_config"):
            AppConfig._check_config_version({}, config_path)
        assert "outdated" not in caplog.text


def test_string_config_version_does_not_raise_type_error(caplog):
    """config_version stored as a YAML string should not raise TypeError on comparison."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = _make_config_files(
            Path(tmpdir),
            user_config={"config_version": "1"},  # string, as YAML can produce
            example_config={"config_version": 2},
        )
        # Must not raise TypeError: '<' not supported between instances of 'str' and 'int'
        AppConfig._check_config_version({"config_version": "1"}, config_path)


def test_newer_user_version_no_warning(caplog):
    """If user has a newer version than example (edge case), no warning."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = _make_config_files(
            Path(tmpdir),
            user_config={"config_version": 3},
            example_config={"config_version": 2},
        )
        with caplog.at_level(logging.WARNING, logger="deerflow.config.app_config"):
            AppConfig._check_config_version(
                {"config_version": 3},
                config_path,
            )
        assert "outdated" not in caplog.text
