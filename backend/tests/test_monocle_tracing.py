"""Tests for Monocle telemetry setup.

Covers the config gate (``MONOCLE_TRACING`` default off / toggle on), the setup
helper's behavior, and the regression that importing ``deerflow.agents`` no
longer sets up telemetry at import time.
"""

from __future__ import annotations

import pytest

from deerflow.config import is_monocle_tracing_enabled
from deerflow.config.tracing_config import get_tracing_config, reset_tracing_config
from deerflow.tracing.monocle import setup_monocle_tracing_if_enabled


@pytest.fixture(autouse=True)
def clear_monocle_env(monkeypatch):
    for name in ("MONOCLE_TRACING", "MONOCLE_EXPORTERS"):
        monkeypatch.delenv(name, raising=False)
    reset_tracing_config()
    yield
    reset_tracing_config()


def test_disabled_by_default():
    assert is_monocle_tracing_enabled() is False
    assert get_tracing_config().monocle.enabled is False


def test_setup_noop_when_disabled(monkeypatch):
    called = False

    def _fail(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr("monocle_apptrace.setup_monocle_telemetry", _fail)
    assert setup_monocle_tracing_if_enabled() is False
    assert called is False


def test_toggles_on_and_sets_up(monkeypatch):
    monkeypatch.setenv("MONOCLE_TRACING", "true")
    reset_tracing_config()

    captured: dict = {}
    monkeypatch.setattr("monocle_apptrace.setup_monocle_telemetry", lambda **kw: captured.update(kw))

    assert is_monocle_tracing_enabled() is True
    assert setup_monocle_tracing_if_enabled() is True
    assert captured == {"workflow_name": "deer-flow", "monocle_exporters_list": "file"}


def test_custom_exporters(monkeypatch):
    monkeypatch.setenv("MONOCLE_TRACING", "true")
    monkeypatch.setenv("MONOCLE_EXPORTERS", "file,console")
    reset_tracing_config()

    captured: dict = {}
    monkeypatch.setattr("monocle_apptrace.setup_monocle_telemetry", lambda **kw: captured.update(kw))

    assert setup_monocle_tracing_if_enabled() is True
    assert captured["monocle_exporters_list"] == "file,console"


def test_no_import_time_setup():
    """Regression: importing deerflow.agents must not install telemetry.

    The setup call used to live at module import in ``deerflow/agents/__init__``.
    It now happens only via the gateway lifespan, so the package namespace must
    not even carry ``setup_monocle_telemetry``.
    """
    import deerflow.agents as agents

    assert not hasattr(agents, "setup_monocle_telemetry")
