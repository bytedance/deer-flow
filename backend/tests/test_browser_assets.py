"""Packaged browser resources remain revisioned, authenticated and package-confined."""

import json
from dataclasses import replace

import pytest
from deerflow_extension_api import BrowserAssets, BrowserModule, PluginContribution
from deerflow_extension_api.auth import EXTENSION_PRINCIPAL_RESOLVER_KEY, ExtensionPrincipal
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.routers.plugins import router
from deerflow.extensions import browser_assets
from deerflow.extensions.browser_assets import load_browser_assets
from deerflow.extensions.registry import ExtensionRegistry


@pytest.fixture
def package(tmp_path):
    (tmp_path / "static").mkdir()
    for name, content in {"index.mjs": 'import "./chunk.mjs";', "chunk.mjs": "export default 1;", "style.css": "body{}", "icon.svg": "<svg/>", "font.woff2": "font", "private.json": "secret"}.items():
        (tmp_path / "static" / name).write_text(content)
    manifest = {"schema_version": 1, "entry": "static/index.mjs", "files": ["static/index.mjs", "static/chunk.mjs", "static/style.css", "static/icon.svg", "static/font.woff2"]}
    (tmp_path / "ui_manifest.json").write_text(json.dumps(manifest))
    return BrowserAssets("example.v1", tmp_path), manifest


def registry_for(declaration):
    registry = ExtensionRegistry()
    with registry.attributed_to("example"):
        registry.plugin(PluginContribution(namespace="community.example", title="Example", enabled=True, frontend=declaration))
    return registry


def test_routes_snapshot_all_files_and_keep_inline_compatibility(package):
    declaration, _ = package
    registry = registry_for(declaration)
    with registry.attributed_to("inline"):
        registry.plugin(PluginContribution(namespace="community.inline", title="Inline", frontend=BrowserModule("inline.v1", "export default {};")))
    app = FastAPI()
    app.state.extensions = registry.build()
    setattr(app.state, EXTENSION_PRINCIPAL_RESOLVER_KEY, lambda request: ExtensionPrincipal("alice"))
    app.include_router(router)
    with TestClient(app) as client:
        descriptor, inline = client.get("/api/plugins").json()
        assert descriptor["transport"] == "assets-v1"
        assert inline["transport"] == "inline-v1"
        assert client.get(inline["entry"]).text == "export default {};"
        assert client.get(descriptor["entry"].replace("community.example", "community.other")).status_code == 404
        base = descriptor["entry"].removesuffix("index.mjs")
        for file, mime in [("index.mjs", "text/javascript"), ("style.css", "text/css"), ("icon.svg", "image/svg+xml"), ("font.woff2", "font/woff2")]:
            response = client.get(base + file)
            assert response.status_code == 200
            assert response.headers["content-type"].startswith(mime)
            assert response.headers["cache-control"] == "private, max-age=31536000, immutable"
            assert response.headers["vary"] == "Cookie, Authorization"
            assert response.headers["x-content-type-options"] == "nosniff"
            assert response.headers["content-security-policy"] == "sandbox"
        for file in ["private.json", "missing.mjs", "%2e%2e%2fui_manifest.json", "%252e%252e/secret", "icon.svg/extra"]:
            assert client.get(base + file).status_code == 404
        original = client.get(descriptor["entry"]).content
        (declaration.root / "static/index.mjs").write_text("changed")
        assert client.get(descriptor["entry"]).content == original
        app.state.extensions = registry_for(declaration).build()
        updated = client.get("/api/plugins").json()[0]
        assert updated["entry"] != descriptor["entry"]
        assert client.get(descriptor["entry"]).status_code == 404
        assert client.get(updated["entry"]).text == "changed"
        setattr(app.state, EXTENSION_PRINCIPAL_RESOLVER_KEY, lambda request: None)
        for entry in [updated["entry"], descriptor["entry"], base + "private.json"]:
            assert client.get(entry).status_code == 401


def test_any_dependency_changes_revision_and_rollback_releases_snapshot(package):
    declaration, _ = package
    before = load_browser_assets(declaration)
    (declaration.root / "static/style.css").write_text("body{color:red}")
    assert load_browser_assets(declaration).revision != before.revision
    assert before.files["static/style.css"].content == b"body{}"
    with pytest.raises(TypeError):
        before.files["static/style.css"] = None
    registry = ExtensionRegistry()
    mark = registry.mark()
    with registry.attributed_to("example"):
        registry.plugin(PluginContribution(namespace="community.example", title="Example", frontend=declaration))
    registry.rollback_to(mark)
    assert not registry.build().plugins


@pytest.mark.parametrize(
    "path", ["../secret.mjs", "/tmp/secret.mjs", "static/../index.mjs", "static//index.mjs", "./static/index.mjs", ".hidden.mjs", "static\\index.mjs", "static/%2e%2e/file.mjs", "static/file.mjs?x", "https://example/file.mjs"]
)
def test_unsafe_manifest_paths_rejected(package, path):
    declaration, manifest = package
    manifest["files"].append(path)
    (declaration.root / "ui_manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        registry_for(declaration)


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": 2},
        {"schema_version": True},
        {"entry": "static/style.css"},
        {"entry": "missing.mjs"},
        {"files": []},
        {"files": ["static/index.mjs", "static/index.mjs"]},
        {"files": "static/index.mjs"},
        {"unknown": True},
        {"files": ["static/index.mjs", "secret.html"]},
    ],
)
def test_invalid_manifests_rejected(package, change):
    declaration, manifest = package
    manifest.update(change)
    (declaration.root / "ui_manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        registry_for(declaration)


def test_missing_symlink_duplicate_keys_and_size_limits(package, monkeypatch):
    declaration, manifest = package
    file = declaration.root / "static/chunk.mjs"
    file.unlink()
    with pytest.raises(FileNotFoundError):
        load_browser_assets(declaration)
    file.symlink_to(declaration.root / "static/index.mjs")
    with pytest.raises(ValueError, match="symlinks"):
        load_browser_assets(declaration)
    file.unlink()
    file.write_text("export default 1;")
    monkeypatch.setattr(browser_assets, "MAX_FILE_BYTES", 4)
    with pytest.raises(ValueError, match="size limit"):
        load_browser_assets(declaration)
    monkeypatch.setattr(browser_assets, "MAX_FILE_BYTES", 4096)
    monkeypatch.setattr(browser_assets, "MAX_PACKAGE_BYTES", 30)
    with pytest.raises(ValueError, match="size limit"):
        load_browser_assets(declaration)
    (declaration.root / "ui_manifest.json").write_text('{"schema_version":1,"schema_version":1}')
    with pytest.raises(ValueError, match="Duplicate"):
        load_browser_assets(declaration)
    with pytest.raises(ValueError, match="Invalid browser asset path"):
        load_browser_assets(replace(declaration, manifest="../ui_manifest.json"))


def test_intermediate_symlink_and_manifest_limits(package, tmp_path, monkeypatch):
    declaration, manifest = package
    directory = tmp_path / "static"
    directory.rename(tmp_path / "real")
    directory.symlink_to(tmp_path / "real", target_is_directory=True)
    with pytest.raises(ValueError, match="symlinks"):
        load_browser_assets(declaration)
    directory.unlink()
    (tmp_path / "real").rename(directory)
    monkeypatch.setattr(browser_assets, "MAX_FILES", 1)
    with pytest.raises(ValueError, match="unique asset paths"):
        load_browser_assets(declaration)
    (tmp_path / "ui_manifest.json").write_bytes(b" " * (64 * 1024 + 1))
    with pytest.raises(ValueError, match="size limit"):
        load_browser_assets(declaration)


@pytest.mark.parametrize("dangling", [False, True])
def test_asset_root_symlink_is_rejected_before_resolution(package, dangling):
    declaration, _ = package
    link = declaration.root / "root-link"
    link.symlink_to(declaration.root / "missing" if dangling else declaration.root, target_is_directory=True)
    with pytest.raises(ValueError, match="root.*symlink"):
        load_browser_assets(replace(declaration, root=link))


def test_asset_root_retains_normal_parent_symlink_resolution(package):
    declaration, _ = package
    # Deployment paths can legitimately traverse aliases such as /var -> /private/var.
    alias = declaration.root / "parent-alias"
    alias.symlink_to(declaration.root.parent, target_is_directory=True)
    via_alias = alias / declaration.root.name
    assert not via_alias.is_symlink()
    assert load_browser_assets(replace(declaration, root=via_alias)).revision == load_browser_assets(declaration).revision
