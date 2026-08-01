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


def test_create_app_fails_closed_for_required_extension_with_malformed_api_marker(monkeypatch):
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

    config = app_module.get_app_config().model_copy(
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
