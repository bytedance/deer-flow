"""Package-owned copy survives backend-only discovery without importing disabled code."""

import copy
import json
import runpy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from deerflow_extension_api.auth import EXTENSION_PRINCIPAL_RESOLVER_KEY, ExtensionPrincipal
from deerflow_extension_api.plugins import PluginContribution
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


@pytest.mark.parametrize("url", ["javascript:alert(1)", "http://example.org", "https://secret@example.org", "https://example.org:bad/docs", "https://example.org:65536/docs", "https://["])
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


@pytest.mark.parametrize(
    "tags,expected",
    [
        (["zh-CN", "en"], "English"),
        (["zh-CN", "en-us"], "English"),
        (["zh-CN", "en-GB"], "English"),
        (["zh-CN", "en", "en-us"], "US English"),
        (["zh-CN", "fr"], "中文"),
    ],
)
def test_backend_only_discovery_prefers_english_language_variants(package, tags, expected):
    page = copy.deepcopy(PAGE)
    page["locales"] = {}
    titles = {"zh-CN": "中文", "fr": "Français"}
    if len(tags) == 3:
        titles["en-us"] = "US English"
    for tag in tags:
        localized = copy.deepcopy(PAGE["locales"]["en-US"])
        localized["title"] = titles.get(tag, "English")
        page["locales"][tag] = localized
    package.write_text(json.dumps(page))
    loaded, diagnostics = load_extensions([ExtensionSpec(use=SOURCE)])
    assert not diagnostics
    app = FastAPI()
    app.state.extensions = loaded
    setattr(app.state, EXTENSION_PRINCIPAL_RESOLVER_KEY, lambda request: ExtensionPrincipal("viewer"))
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get("/api/plugins")
    assert response.status_code == 200
    (entry,) = response.json()
    assert entry["title"] == expected
    assert entry["documentation"] == page


def test_bad_documentation_does_not_disable_working_extension(package):
    package.write_text('{"secret":"synthetic-secret"}')
    loaded, diagnostics = load_extensions([ExtensionSpec(use=SOURCE)])
    assert loaded.has_middleware_contributors
    assert loaded.documentation == ()
    assert [(item.level, item.source, item.message) for item in diagnostics] == [("warning", SOURCE, "Extension documentation is invalid.")]


@pytest.mark.parametrize("field", ["id", "locale", "title", "description", "usage_title", "usage_description", "requirements", "docs_url"])
@pytest.mark.parametrize("surrogate", ["\ud800", "\udfff"])
def test_unencodable_public_documentation_cannot_break_discovery(package, field, surrogate):
    page = copy.deepcopy(PAGE)
    localized = page["locales"]["en-US"]
    if field == "id":
        page["id"] = surrogate
    elif field == "locale":
        page["locales"] = {surrogate: localized}
    elif field.startswith("usage_"):
        localized["usage"][0][field.removeprefix("usage_")] = surrogate
    elif field == "requirements":
        localized["requirements"] = [surrogate]
    elif field == "docs_url":
        page["docs_url"] = "https://example.org/" + surrogate
    else:
        localized[field] = surrogate
    package.write_text(json.dumps(page))
    loaded, diagnostics = load_extensions([ExtensionSpec(use=SOURCE)])
    assert loaded.has_middleware_contributors
    healthy = PluginContribution(namespace="community.bookmarks", title="Bookmarks", enabled=True)
    app = FastAPI()
    app.state.extensions = replace(loaded, plugins=(("healthy:install", healthy),))
    setattr(app.state, EXTENSION_PRINCIPAL_RESOLVER_KEY, lambda request: ExtensionPrincipal("viewer"))
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get("/api/plugins")
    assert response.status_code == 200
    assert [entry["namespace"] for entry in response.json()] == [healthy.namespace]
    assert loaded.documentation == ()
    assert [(item.level, item.source, item.message) for item in diagnostics] == [("warning", SOURCE, "Extension documentation is invalid.")]


def test_unicode_documentation_and_ignored_private_fields_remain_valid():
    page = copy.deepcopy(PAGE)
    page["locales"]["en-US"]["title"] = "指南 🦌"
    page["docs_url"] = "https://example.org:8443/docs"
    expected = copy.deepcopy(page)
    page["private_config"] = {"ignored": "\ud800"}
    assert validate_documentation(page) == expected


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


@pytest.mark.parametrize("collision", [False, True])
def test_plugin_discovery_fences_documentation_identity(collision):
    plugin = PluginContribution(namespace="example.background", title="Plugin", description="Plugin copy")
    page = copy.deepcopy(PAGE)
    page["id"] = plugin.namespace if collision else "another.plugin"
    source = "backend.only:install" if collision else SOURCE
    app = FastAPI()
    app.state.extensions = SimpleNamespace(plugins=((SOURCE, plugin),), documentation=((source, page),))
    setattr(app.state, EXTENSION_PRINCIPAL_RESOLVER_KEY, lambda request: ExtensionPrincipal("viewer"))
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get("/api/plugins")
    assert response.status_code == 200
    (entry,) = response.json()
    assert entry["namespace"] == plugin.namespace
    assert entry["documentation"] is None


def test_bundled_generator_rejects_missing_language_and_shared_size_limit(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    script = runpy.run_path(str(root / "scripts/sync_extension_documentation.py"))
    namespace = script["render"].__globals__
    monkeypatch.setitem(namespace, "ROOT", tmp_path)
    path = tmp_path / "examples/deerflow-extension-test/package/deerflow-extension.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(PAGE))
    with pytest.raises(ValueError, match="English and Chinese"):
        script["render"]()
    value = copy.deepcopy(PAGE)
    value["locales"]["zh"] = copy.deepcopy(value["locales"]["en-US"])
    path.write_text(json.dumps(value))
    assert "deerflow-extension-test" in script["render"]()
    monkeypatch.setitem(namespace, "MAX_BYTES", 1)
    with pytest.raises(ValueError, match="too large"):
        script["render"]()
