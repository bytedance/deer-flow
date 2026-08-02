"""Gateway app-construction wiring for configured Python extensions."""

from __future__ import annotations

import pytest

from deerflow.extensions import reset_loaded_extensions, reset_runtime_diagnostics
from deerflow.extensions.loader import ExtensionLoadError, ExtensionSpec
from deerflow.extensions.registry import ExtensionRegistry


@pytest.fixture(autouse=True)
def _reset_extension_process_state():
    reset_loaded_extensions()
    reset_runtime_diagnostics()
    yield
    reset_runtime_diagnostics()
    reset_loaded_extensions()


@pytest.fixture(autouse=True)
def stub_app_config(monkeypatch):
    """Keep ``create_app()`` independent of a real ``config.yaml``.

    The repo-root ``config.yaml`` is gitignored and absent on CI runners, so
    reading it here would make these tests pass locally and fail on every run
    in CI. Tests that need a specific plugin list copy this config instead of
    loading one from disk.
    """
    import app.gateway.app as app_module
    from deerflow.config.app_config import AppConfig
    from deerflow.config.sandbox_config import SandboxConfig

    config = AppConfig(sandbox=SandboxConfig(use="test"))
    monkeypatch.setattr(app_module, "get_app_config", lambda: config)
    return config


def test_create_app_exposes_loaded_extensions_on_app_state_and_process_singleton(monkeypatch):
    import deerflow.extensions as extensions_module

    loaded = ExtensionRegistry().build()
    monkeypatch.setattr(
        extensions_module,
        "load_extensions",
        lambda plugins: (loaded, []),
    )

    from app.gateway.app import create_app

    app = create_app()

    assert app.state.extensions is loaded
    assert extensions_module.get_loaded_extensions() is loaded


def test_create_app_exposes_one_canonical_live_diagnostics_list(monkeypatch):
    import deerflow.extensions as extensions_module

    loaded = ExtensionRegistry().build()
    load_diagnostic = extensions_module.Diagnostic.warning(
        "demo:install",
        "optional extension was skipped",
    )
    monkeypatch.setattr(
        extensions_module,
        "load_extensions",
        lambda plugins: (loaded, [load_diagnostic]),
    )

    from app.gateway.app import create_app

    first_app = create_app()
    second_app = create_app()
    runtime_diagnostic = extensions_module.Diagnostic.error(
        "demo:install",
        "middleware observation failed",
    )
    extensions_module.record_runtime_diagnostic(runtime_diagnostic)

    assert first_app.state.extension_diagnostics is second_app.state.extension_diagnostics
    assert first_app.state.extension_diagnostics == [
        load_diagnostic,
        runtime_diagnostic,
    ]


def test_create_app_fails_open_when_extension_loading_raises_unexpectedly(monkeypatch):
    import deerflow.extensions as extensions_module

    def _raise_unexpectedly(plugins):
        raise RuntimeError("malformed plugins configuration")

    monkeypatch.setattr(extensions_module, "load_extensions", _raise_unexpectedly)

    from app.gateway.app import create_app

    app = create_app()

    assert app.state.extensions is extensions_module.EMPTY_EXTENSIONS
    assert extensions_module.get_loaded_extensions() is extensions_module.EMPTY_EXTENSIONS
    assert app.state.extension_diagnostics == []


def test_create_app_fails_closed_when_a_required_extension_cannot_load(monkeypatch):
    import deerflow.extensions as extensions_module
    from app.gateway.app import create_app

    def _raise_required(plugins):
        raise extensions_module.ExtensionLoadError("required extension acme_policy:install failed to install")

    monkeypatch.setattr(extensions_module, "load_extensions", _raise_required)

    with pytest.raises(extensions_module.ExtensionLoadError):
        create_app()


def test_create_app_tolerates_a_missing_config_file_and_loads_no_extensions(monkeypatch):
    """``create_app()`` runs at import time, so an absent config.yaml must not break it.

    Mirrors ``_resolve_trace_enabled_for_app_construction()``: lifespan still
    performs strict config loading before the Gateway serves traffic.
    """
    import app.gateway.app as app_module
    import deerflow.extensions as extensions_module

    def _missing_config():
        raise FileNotFoundError("`config.yaml` file not found in the project root or legacy backend/repository root locations")

    monkeypatch.setattr(app_module, "get_app_config", _missing_config)

    observed_plugins = []
    loaded = ExtensionRegistry().build()

    def _record(plugins):
        observed_plugins.append(plugins)
        return loaded, []

    monkeypatch.setattr(extensions_module, "load_extensions", _record)

    app = app_module.create_app()

    assert observed_plugins == [[]]
    assert app.state.extensions is loaded


def test_create_app_propagates_config_failures_instead_of_blaming_extension_loading(monkeypatch):
    """A parseable-but-broken config.yaml must not be swallowed by the fail-open guard.

    Extension loading is fail-open for unexpected errors, but resolving the
    plugin list is not part of it: degrading to zero extensions there would
    drop a ``required: true`` extension without failing the boot.
    """
    import app.gateway.app as app_module
    import deerflow.extensions as extensions_module

    def _broken_config():
        raise ValueError("config.yaml failed validation")

    monkeypatch.setattr(app_module, "get_app_config", _broken_config)

    def _must_not_run(plugins):
        raise AssertionError("load_extensions must not run when the plugin list cannot be resolved")

    monkeypatch.setattr(extensions_module, "load_extensions", _must_not_run)

    with pytest.raises(ValueError, match="config.yaml failed validation"):
        app_module.create_app()


def test_create_app_fails_closed_for_required_extension_with_malformed_api_marker(monkeypatch, stub_app_config):
    import app.gateway.app as app_module
    from extension_test_fixtures import demo_extensions

    class _ExplodingAPIMarker:
        def split(self, separator: str) -> list[str]:
            raise RuntimeError("API marker split exploded")

        def __str__(self) -> str:
            return "exploding non-string marker"

    monkeypatch.setattr(
        demo_extensions.install_ok,
        "__deerflow_api__",
        _ExplodingAPIMarker(),
        raising=False,
    )

    config = stub_app_config.model_copy(
        update={
            "plugins": [
                ExtensionSpec(
                    use="extension_test_fixtures.demo_extensions:install_ok",
                    required=True,
                )
            ]
        }
    )
    monkeypatch.setattr(app_module, "get_app_config", lambda: config)

    with pytest.raises(ExtensionLoadError, match="declares invalid api marker"):
        app_module.create_app()
