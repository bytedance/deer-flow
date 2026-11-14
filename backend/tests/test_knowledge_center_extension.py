"""The optional page must ship real assets without installing a second backend."""

from pathlib import Path

import pytest

from deerflow.extensions.loader import ExtensionSpec, load_extensions

pytestmark = pytest.mark.bundled_extension


@pytest.fixture
def load_center(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "examples/deerflow-extension-knowledge-center"))

    def load(config):
        return load_extensions([ExtensionSpec(use="deerflow_extension_knowledge_center:install", config=config)])

    return load


@pytest.mark.parametrize("enabled", [False, True])
def test_optional_center_has_packaged_page_and_no_management_backend(load_center, enabled):
    loaded, diagnostics = load_center({"enabled": enabled})
    assert not diagnostics
    ((_, plugin),) = loaded.plugins
    assert plugin.namespace == "knowledge-center"
    assert plugin.enabled is enabled
    assert not plugin.backend and not plugin.tools and not loaded.routers
    assets = plugin.frontend
    assert assets.entry == "static/index.mjs"
    assert set(assets.files) == {"static/index.mjs", "static/center.mjs", "static/styles.css", "static/copy.mjs"}
    assert b"requestBackend" in assets.files["static/center.mjs"].content


@pytest.mark.parametrize("config", [{"enabled": "true"}, {"endpoint": "https://example.invalid"}, {"enabled": True, "token": "secret"}])
def test_page_config_cannot_introduce_credentials_or_provider_configuration(load_center, config):
    loaded, diagnostics = load_center(config)
    assert not loaded.plugins
    assert diagnostics
