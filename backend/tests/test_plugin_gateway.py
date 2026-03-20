"""Tests for the plugins gateway API router."""

from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.gateway.routers.plugins import router
from src.plugins.types import Command, PluginManifest


def _make_test_app() -> FastAPI:
    """Create a minimal FastAPI app with the plugins router."""
    app = FastAPI()
    app.include_router(router)
    return app


def _make_manifest(name: str, version: str = "1.0.0", description: str = "Test", enabled: bool = True, skills_count: int = 0, commands: list | None = None, mcp_servers: dict | None = None) -> PluginManifest:
    """Create a PluginManifest for testing."""
    return PluginManifest(
        name=name,
        version=version,
        description=description,
        author={"name": "Test"},
        plugin_dir=Path(f"/tmp/plugins/{name}"),
        skills_count=skills_count,
        commands=commands or [],
        mcp_servers=mcp_servers or {},
        enabled=enabled,
    )


class TestListPlugins:
    """Tests for GET /api/plugins."""

    def test_list_plugins_empty(self):
        """Should return empty list when no plugins are installed."""
        app = _make_test_app()
        client = TestClient(app)

        with patch("src.gateway.routers.plugins.get_plugin_registry") as mock_registry:
            mock_registry.return_value.list_all.return_value = []
            response = client.get("/api/plugins")

        assert response.status_code == 200
        data = response.json()
        assert data["plugins"] == []
        assert data["total"] == 0

    def test_list_plugins_with_data(self):
        """Should return all installed plugins."""
        app = _make_test_app()
        client = TestClient(app)

        manifests = [
            _make_manifest("sales", skills_count=3, commands=[
                Command(name="forecast", description="Forecast", argument_hint="", content="", plugin_name="sales"),
            ]),
            _make_manifest("data", enabled=False),
        ]

        with patch("src.gateway.routers.plugins.get_plugin_registry") as mock_registry:
            mock_registry.return_value.list_all.return_value = manifests
            response = client.get("/api/plugins")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        sales = next(p for p in data["plugins"] if p["name"] == "sales")
        assert sales["skills_count"] == 3
        assert sales["commands_count"] == 1
        assert sales["enabled"] is True


class TestGetPlugin:
    """Tests for GET /api/plugins/{name}."""

    def test_get_existing_plugin(self):
        """Should return plugin details."""
        app = _make_test_app()
        client = TestClient(app)

        manifest = _make_manifest("sales", description="Sales tools", skills_count=2)

        with patch("src.gateway.routers.plugins.get_plugin_registry") as mock_registry:
            mock_registry.return_value.get.return_value = manifest
            response = client.get("/api/plugins/sales")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "sales"
        assert data["description"] == "Sales tools"

    def test_get_nonexistent_plugin(self):
        """Should return 404 for unknown plugin."""
        app = _make_test_app()
        client = TestClient(app)

        with patch("src.gateway.routers.plugins.get_plugin_registry") as mock_registry:
            mock_registry.return_value.get.return_value = None
            response = client.get("/api/plugins/nonexistent")

        assert response.status_code == 404


class TestUpdatePlugin:
    """Tests for PUT /api/plugins/{name}."""

    def test_enable_plugin(self):
        """Should enable a plugin and persist to config."""
        app = _make_test_app()
        client = TestClient(app)

        manifest = _make_manifest("sales", enabled=False)

        with (
            patch("src.gateway.routers.plugins.get_plugin_registry") as mock_registry,
            patch("src.gateway.routers.plugins._update_plugin_state") as mock_update,
        ):
            mock_registry.return_value.get.return_value = manifest
            response = client.put("/api/plugins/sales", json={"enabled": True})

        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is True
        mock_update.assert_called_once_with("sales", True)

    def test_disable_plugin(self):
        """Should disable a plugin."""
        app = _make_test_app()
        client = TestClient(app)

        manifest = _make_manifest("sales", enabled=True)

        with (
            patch("src.gateway.routers.plugins.get_plugin_registry") as mock_registry,
            patch("src.gateway.routers.plugins._update_plugin_state"),
        ):
            mock_registry.return_value.get.return_value = manifest
            response = client.put("/api/plugins/sales", json={"enabled": False})

        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is False

    def test_update_nonexistent_plugin(self):
        """Should return 404 for unknown plugin."""
        app = _make_test_app()
        client = TestClient(app)

        with patch("src.gateway.routers.plugins.get_plugin_registry") as mock_registry:
            mock_registry.return_value.get.return_value = None
            response = client.put("/api/plugins/nonexistent", json={"enabled": True})

        assert response.status_code == 404


class TestGetPluginCommands:
    """Tests for GET /api/plugins/{name}/commands."""

    def test_list_plugin_commands(self):
        """Should return commands for a specific plugin."""
        app = _make_test_app()
        client = TestClient(app)

        commands = [
            Command(name="forecast", description="Forecast", argument_hint="<period>", content="Body", plugin_name="sales"),
            Command(name="call-summary", description="Summary", argument_hint="<notes>", content="Body", plugin_name="sales"),
        ]
        manifest = _make_manifest("sales", commands=commands)

        with patch("src.gateway.routers.plugins.get_plugin_registry") as mock_registry:
            mock_registry.return_value.get.return_value = manifest
            response = client.get("/api/plugins/sales/commands")

        assert response.status_code == 200
        data = response.json()
        assert len(data["commands"]) == 2
        names = {c["name"] for c in data["commands"]}
        assert names == {"forecast", "call-summary"}

    def test_list_commands_nonexistent_plugin(self):
        """Should return 404 for unknown plugin."""
        app = _make_test_app()
        client = TestClient(app)

        with patch("src.gateway.routers.plugins.get_plugin_registry") as mock_registry:
            mock_registry.return_value.get.return_value = None
            response = client.get("/api/plugins/nonexistent/commands")

        assert response.status_code == 404
