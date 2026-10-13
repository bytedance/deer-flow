import importlib
import json
from types import SimpleNamespace

import pytest


def _module():
    assert importlib.util.find_spec("app.gateway.browser_control") is not None, "Browser provider contract is missing"
    return importlib.import_module("app.gateway.browser_control")


def test_operator_snapshot_is_read_once_and_invalid_factory_fails_closed(tmp_path, monkeypatch):
    browser_control = _module()
    path = tmp_path / "native.json"
    path.write_text(json.dumps({"enabled": True, "browser_control": {"provider": "missing_module:factory"}}))
    monkeypatch.setenv("ECS_NATIVE_CONFIG", str(path))
    with pytest.raises((ValueError, ImportError)):
        browser_control.load_browser_control_snapshot(SimpleNamespace())


def test_snapshot_without_provider_does_not_grant_affinity(tmp_path, monkeypatch):
    browser_control = _module()
    path = tmp_path / "native.json"
    path.write_text(json.dumps({"enabled": True, "role": "central"}))
    monkeypatch.setenv("ECS_NATIVE_CONFIG", str(path))
    snapshot = browser_control.load_browser_control_snapshot(SimpleNamespace())
    path.write_text("{}")
    assert snapshot.native_config == {"enabled": True, "role": "central"}
    assert not browser_control.has_browser_affinity(snapshot)


def test_provider_requires_actual_hooks_and_validation(monkeypatch, tmp_path):
    import sys

    browser_control = _module()
    path = tmp_path / "native.json"
    path.write_text(json.dumps({"enabled": True, "browser_control": {"provider": "test_browser_factory:build"}}))
    monkeypatch.setenv("ECS_NATIVE_CONFIG", str(path))
    monkeypatch.setitem(sys.modules, "test_browser_factory", SimpleNamespace(build=lambda **kwargs: object()))
    with pytest.raises(ValueError, match="contract"):
        browser_control.load_browser_control_snapshot(SimpleNamespace())
