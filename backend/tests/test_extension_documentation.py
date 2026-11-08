"""Package-owned copy survives backend-only discovery without importing disabled code."""

import copy
import json
import runpy
from pathlib import Path

import pytest
from deerflow_extension_api.auth import EXTENSION_PRINCIPAL_RESOLVER_KEY, ExtensionPrincipal
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.routers.plugins import router
from deerflow.extensions.documentation import FILENAME, validate_documentation
from deerflow.extensions.loader import ExtensionSpec, load_extensions
from extension_test_fixtures import demo_extensions

SOURCE = "extension_test_fixtures.demo_extensions:install_ok"
PAGE = {
    "schema_version": 1,
    "id": "example.background",
    "locales": {"en-US": {"title": "Background helper", "description": "Keeps tool statistics.", "usage": [{"title": "Run a task", "description": "Statistics are collected automatically."}]}},
}


@pytest.fixture
def package(tmp_path, monkeypatch):
    monkeypatch.setattr(demo_extensions, "__file__", str(tmp_path / "__init__.py"))
    path = tmp_path / FILENAME
    path.write_text(json.dumps(PAGE))
    return path


def test_requirements_are_optional_and_empty_requirements_are_omitted():
    assert "requirements" not in validate_documentation(PAGE)["locales"]["en-US"]
    value = copy.deepcopy(PAGE)
    value["locales"]["en-US"]["requirements"] = []
    assert "requirements" not in validate_documentation(value)["locales"]["en-US"]


@pytest.mark.parametrize("field", ["title", "description", "usage"])
def test_new_documentation_requires_meaningful_copy(field):
    value = copy.deepcopy(PAGE)
    del value["locales"]["en-US"][field]
    with pytest.raises(ValueError):
        validate_documentation(value)


@pytest.mark.parametrize("url", ["javascript:alert(1)", "http://example.org", "https://secret@example.org"])
def test_documentation_links_are_public_https(url):
    with pytest.raises(ValueError):
        validate_documentation({**PAGE, "docs_url": url})


def test_loader_projects_only_public_documentation(package):
    value = copy.deepcopy(PAGE)
    value["private_config"] = {"key": "synthetic-secret"}
    package.write_text(json.dumps(value))
    loaded, diagnostics = load_extensions([ExtensionSpec(use=SOURCE, config={"token": "private"})])
    assert diagnostics == []
    assert loaded.documentation == ((SOURCE, PAGE),)
    # Reads use the loaded snapshot, not mutable files or config on request threads.
    package.unlink()
    app = FastAPI()
    app.state.extensions = loaded
    setattr(app.state, EXTENSION_PRINCIPAL_RESOLVER_KEY, lambda request: ExtensionPrincipal("viewer"))
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get("/api/plugins")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "private, no-store"
        (entry,) = response.json()
        assert entry["namespace"] == PAGE["id"]
        assert entry["documentation"] == PAGE
        assert entry["runtime_only"] is True
        assert entry["module"] is None
        assert entry["settings"] == {"enabled": True}
        assert "private" not in response.text


def test_bad_documentation_does_not_disable_working_extension(package):
    package.write_text('{"secret":"synthetic-secret"}')
    loaded, diagnostics = load_extensions([ExtensionSpec(use=SOURCE)])
    assert loaded.has_middleware_contributors
    assert loaded.documentation == ()
    assert [(item.level, item.source, item.message) for item in diagnostics] == [("warning", SOURCE, "Extension documentation is invalid.")]


def test_missing_documentation_keeps_legacy_behavior(package):
    package.unlink()
    loaded, diagnostics = load_extensions([ExtensionSpec(use=SOURCE)])
    assert loaded.has_middleware_contributors
    assert not loaded.documentation and not diagnostics


def test_disabled_or_failed_install_cannot_publish_documentation(package):
    for spec in [ExtensionSpec(use=SOURCE, enabled=False), ExtensionSpec(use=SOURCE.replace("install_ok", "install_partial_then_raise"))]:
        loaded, _ = load_extensions([spec])
        assert not loaded.documentation
        assert not loaded.has_middleware_contributors


def test_bundled_documentation_snapshot_is_current():
    root = Path(__file__).resolve().parents[2]
    script = runpy.run_path(str(root / "scripts/sync_extension_documentation.py"))
    assert script["DESTINATION"].read_text(encoding="utf-8") == script["render"]()
    assert len(json.loads(script["render"]())) == 15
