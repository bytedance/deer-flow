"""Select the plugin-owned storage backend through extension installation."""

from pathlib import Path

import pytest

from deerflow.extensions.loader import ExtensionSpec, load_extensions

pytestmark = pytest.mark.bundled_extension


@pytest.fixture(autouse=True)
def extension_path(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "examples/deerflow-extension-agent-teams"))


def install(config):
    return load_extensions([ExtensionSpec(use="deerflow_extension_agent_teams:install", config={"enabled": True, **config})])


def test_postgres_configuration_loads_without_opening_a_connection():
    loaded, diagnostics = install({"storage_url": "postgresql://unused:5432/teams", "storage_schema": "team_data"})
    assert not diagnostics
    ((_, plugin),) = loaded.plugins
    service = next(action.handler.__self__ for action in plugin.backend if action.name == "list")
    assert type(service.store).__name__ == "PostgresStore"
    assert service.process_lock is None


def test_sqlite_configuration_selects_the_existing_store(tmp_path):
    path = tmp_path / "teams.sqlite"
    loaded, diagnostics = install({"storage_path": str(path)})
    assert not diagnostics
    ((_, plugin),) = loaded.plugins
    service = next(action.handler.__self__ for action in plugin.backend if action.name == "list")
    assert service.store.path == path


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"storage_url": "postgresql://unused/teams", "storage_path": "/tmp/teams.sqlite"},
        {"storage_url": None},
        {"storage_url": ""},
        {"storage_path": "relative.sqlite"},
        {"storage_path": "/tmp/teams.sqlite", "storage_schema": "teams"},
        {"storage_url": "sqlite:///tmp/teams.sqlite"},
        {"storage_url": "postgresql://unused/teams", "storage_schema": "public; DROP SCHEMA public"},
        {"storage_url": "postgresql://unused/teams", "enabled": "yes"},
    ],
)
def test_invalid_storage_configuration_fails_during_install(config, tmp_path):
    if config.get("storage_path") == "/tmp/teams.sqlite":
        config = {**config, "storage_path": str(tmp_path / "teams.sqlite")}
    loaded, diagnostics = install(config)
    assert not loaded.plugins
    assert len(diagnostics) == 1


def test_configuration_errors_do_not_disclose_database_credentials():
    secret_url = "postgresql://operator:private-credential@unused/teams"
    loaded, diagnostics = install({"storage_url": secret_url, "storage_schema": "invalid-schema"})
    assert not loaded.plugins
    assert diagnostics
    assert "private-credential" not in str(diagnostics)
