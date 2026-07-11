"""Tests for Monocle telemetry setup.

Covers the config gate (``MONOCLE_TRACING`` default off / toggle on), the setup
helper's behavior (off-box exporter warning, Langfuse-conflict warning, exporter
validation, idempotency), and the regression that importing ``deerflow.agents``
no longer sets up telemetry at import time.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import textwrap

import pytest

from deerflow.config import is_monocle_tracing_enabled
from deerflow.config.tracing_config import get_tracing_config, reset_tracing_config
from deerflow.tracing.monocle import setup_monocle_tracing_if_enabled

_TRACING_ENV = (
    "MONOCLE_TRACING",
    "MONOCLE_EXPORTERS",
    "OKAHU_API_KEY",
    "LANGFUSE_TRACING",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
)


@pytest.fixture(autouse=True)
def clear_monocle_env(monkeypatch):
    for name in _TRACING_ENV:
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


def test_warns_on_non_file_exporter(monkeypatch, caplog):
    monkeypatch.setenv("MONOCLE_TRACING", "true")
    monkeypatch.setenv("MONOCLE_EXPORTERS", "file,s3")
    reset_tracing_config()
    monkeypatch.setattr("monocle_apptrace.setup_monocle_telemetry", lambda **kw: None)

    with caplog.at_level(logging.WARNING):
        assert setup_monocle_tracing_if_enabled() is True

    warnings = [r.message for r in caplog.records if "beyond the local" in r.message]
    assert warnings, "expected an off-box exporter warning"
    assert "s3" in warnings[0]


def test_no_off_box_warning_for_file_exporter(monkeypatch, caplog):
    monkeypatch.setenv("MONOCLE_TRACING", "true")  # default exporter is file
    reset_tracing_config()
    monkeypatch.setattr("monocle_apptrace.setup_monocle_telemetry", lambda **kw: None)

    with caplog.at_level(logging.WARNING):
        assert setup_monocle_tracing_if_enabled() is True

    assert not any("beyond the local" in r.message for r in caplog.records)


def test_warns_when_langfuse_also_enabled(monkeypatch, caplog):
    monkeypatch.setenv("MONOCLE_TRACING", "true")
    monkeypatch.setenv("LANGFUSE_TRACING", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    reset_tracing_config()
    monkeypatch.setattr("monocle_apptrace.setup_monocle_telemetry", lambda **kw: None)

    with caplog.at_level(logging.WARNING):
        assert setup_monocle_tracing_if_enabled() is True

    assert any("Langfuse" in r.message and "OpenTelemetry" in r.message for r in caplog.records)


def test_no_langfuse_warning_when_only_monocle(monkeypatch, caplog):
    monkeypatch.setenv("MONOCLE_TRACING", "true")
    reset_tracing_config()
    monkeypatch.setattr("monocle_apptrace.setup_monocle_telemetry", lambda **kw: None)

    with caplog.at_level(logging.WARNING):
        assert setup_monocle_tracing_if_enabled() is True

    assert not any("Langfuse" in r.message for r in caplog.records)


def test_rejects_unknown_exporter(monkeypatch):
    monkeypatch.setenv("MONOCLE_TRACING", "true")
    monkeypatch.setenv("MONOCLE_EXPORTERS", "fle")
    reset_tracing_config()
    with pytest.raises(ValueError, match="unknown exporter"):
        setup_monocle_tracing_if_enabled()


def test_okahu_exporter_requires_api_key(monkeypatch):
    monkeypatch.setenv("MONOCLE_TRACING", "true")
    monkeypatch.setenv("MONOCLE_EXPORTERS", "okahu")
    reset_tracing_config()
    with pytest.raises(ValueError, match="OKAHU_API_KEY"):
        setup_monocle_tracing_if_enabled()


def test_okahu_exporter_with_api_key_ok(monkeypatch):
    monkeypatch.setenv("MONOCLE_TRACING", "true")
    monkeypatch.setenv("MONOCLE_EXPORTERS", "okahu")
    monkeypatch.setenv("OKAHU_API_KEY", "okh_test")
    reset_tracing_config()
    monkeypatch.setattr("monocle_apptrace.setup_monocle_telemetry", lambda **kw: None)

    assert setup_monocle_tracing_if_enabled() is True


def test_no_import_time_setup(monkeypatch):
    """Regression: importing deerflow.agents must not install telemetry.

    The setup call used to live at module import in ``deerflow/agents/__init__``.
    It now happens only via the gateway lifespan, so re-importing the package
    must neither expose ``setup_monocle_telemetry`` nor replace the global OTel
    ``TracerProvider`` (which is what ``setup_monocle_telemetry`` does).
    """
    from opentelemetry import trace

    provider_before = trace.get_tracer_provider()

    # Force a fresh import so ``__init__`` actually re-executes.
    for name in [m for m in list(sys.modules) if m == "deerflow.agents" or m.startswith("deerflow.agents.")]:
        monkeypatch.delitem(sys.modules, name, raising=False)
    import deerflow.agents as agents

    assert not hasattr(agents, "setup_monocle_telemetry")
    assert trace.get_tracer_provider() is provider_before


def test_double_invoke_is_idempotent():
    """Calling setup twice must not double-instrument.

    Exercises upstream ``check_duplicate_setup`` with the real tracer (no mock).
    Run in a subprocess so the process-global OTel provider it installs never
    leaks into the rest of the suite.
    """
    script = textwrap.dedent(
        """
        import os
        os.environ["MONOCLE_TRACING"] = "true"
        os.environ["MONOCLE_EXPORTERS"] = "console"  # avoid writing .monocle/ files
        from deerflow.tracing.monocle import setup_monocle_tracing_if_enabled
        from monocle_apptrace.instrumentation.common.instrumentor import get_monocle_instrumentor

        assert setup_monocle_tracing_if_enabled() is True
        first = get_monocle_instrumentor()
        assert first is not None
        assert setup_monocle_tracing_if_enabled() is True
        assert get_monocle_instrumentor() is first  # no second provider installed
        print("IDEMPOTENT_OK")
        """
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "IDEMPOTENT_OK" in result.stdout
