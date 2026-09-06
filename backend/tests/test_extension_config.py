"""Tests for extension configuration and the process-wide singleton."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from deerflow.config.app_config import AppConfig
from deerflow.config.reload_boundary import STARTUP_ONLY_FIELDS
from deerflow.extensions import (
    EMPTY_EXTENSIONS,
    ExtensionRegistry,
    get_loaded_extensions,
    reset_loaded_extensions,
    set_loaded_extensions,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_loaded_extensions()
    yield
    reset_loaded_extensions()


class _Marker:
    """Sentinel written into an app_store to detect state leaking across resets."""

    def __init__(self, tag: str = "") -> None:
        self.tag = tag


# AppConfig.sandbox has no default (see app_config.py's
# `_drop_null_config_sections`: "Required sections without a default
# (sandbox) intentionally still error when null"), so every AppConfig
# construction below supplies it, matching the pattern already used in
# test_app_config_reload.py.
_SANDBOX = {"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}}


def test_app_config_defaults_to_no_plugins():
    assert AppConfig.model_validate(_SANDBOX).plugins == []


def test_app_config_parses_plugin_entries():
    config = AppConfig.model_validate(
        {
            **_SANDBOX,
            "plugins": [
                {"use": "acme_observability:install", "config": {"enabled": True}},
                {"use": "acme_policy:install", "required": True},
            ],
        }
    )
    assert [e.use for e in config.plugins] == ["acme_observability:install", "acme_policy:install"]
    assert config.plugins[0].config == {"enabled": True}
    assert config.plugins[0].required is False
    assert config.plugins[1].required is True


def test_plugin_entries_reject_unknown_fields_instead_of_weakening_required():
    with pytest.raises(ValidationError, match="require"):
        AppConfig.model_validate(
            {
                **_SANDBOX,
                "plugins": [
                    {
                        "use": "acme_policy:install",
                        "require": True,
                    }
                ],
            }
        )


def test_new_field_does_not_disturb_the_existing_extensions_field():
    """AppConfig.extensions is a pre-existing, unrelated field (MCP servers,
    skills, config-declared middlewares) backed by extensions_config.json.
    The plugin list is deliberately a separate top-level key: that file is
    writable through an HTTP endpoint, and a code-loading list must not be."""
    config = AppConfig.model_validate({**_SANDBOX, "plugins": [{"use": "a:install"}]})
    assert config.plugins[0].use == "a:install"
    assert hasattr(config.extensions, "mcp_servers")
    assert hasattr(config.extensions, "middlewares")


def test_plugins_is_registered_as_startup_only():
    """Plugins load once in create_app(); a config.yaml edit needs a restart.
    Registering here is what surfaces that to operators."""
    assert "plugins" in STARTUP_ONLY_FIELDS
    assert "restart" in STARTUP_ONLY_FIELDS["plugins"].lower()


def test_singleton_defaults_to_empty():
    loaded = get_loaded_extensions()
    assert loaded.has_middleware_contributors is False
    assert loaded.has_task_lifecycle is False
    assert loaded.has_system_model_observers is False
    assert loaded.needs_task_store is False


def test_singleton_roundtrips():
    loaded = ExtensionRegistry().build()
    set_loaded_extensions(loaded)
    assert get_loaded_extensions() is loaded


def test_reset_gives_a_fresh_instance():
    """Reset must not hand back a shared object. EMPTY_EXTENSIONS owns a
    mutable app_store, so resetting to it would carry writes forward."""
    populated = ExtensionRegistry().build()
    set_loaded_extensions(populated)
    reset_loaded_extensions()
    after = get_loaded_extensions()
    assert after is not populated
    assert after is not EMPTY_EXTENSIONS
    assert after.has_middleware_contributors is False
    assert after.has_task_lifecycle is False
    assert after.has_system_model_observers is False


def test_reset_does_not_leak_app_store_writes():
    """The regression the fresh-build reset exists to prevent."""
    reset_loaded_extensions()
    get_loaded_extensions().app_store.set(_Marker("dirty"))
    reset_loaded_extensions()
    assert get_loaded_extensions().app_store.get(_Marker) is None


def test_runtime_diagnostics_are_bounded_without_replacing_the_live_list(monkeypatch):
    import deerflow.extensions as extensions_module

    monkeypatch.setattr(extensions_module, "_MAX_RUNTIME_DIAGNOSTICS", 3)
    extensions_module.reset_runtime_diagnostics()
    live = extensions_module.initialize_runtime_diagnostics([])
    try:
        for index in range(5):
            extensions_module.record_runtime_diagnostic(extensions_module.Diagnostic.error("demo:install", f"error-{index}"))

        assert [diagnostic.message for diagnostic in live] == [
            "error-2",
            "error-3",
            "error-4",
        ]
    finally:
        extensions_module.reset_runtime_diagnostics()
