"""Tests for DeerFlowClient's graph-root tracing wiring.

Regression coverage for the Copilot review on PR #2944: when the title
and summarization middlewares request ``attach_tracing=False`` we must
make sure ``DeerFlowClient`` injects the tracing callbacks at the graph
invocation root instead, otherwise those middlewares produce untraced
LLM calls.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from deerflow.client import DeerFlowClient


class _FakeAgent:
    """Capture the ``config`` handed to ``agent.stream``."""

    def __init__(self) -> None:
        self.captured_config: dict | None = None
        self.checkpointer = None
        self.store = None

    def stream(self, state, *, config, context, stream_mode):
        self.captured_config = config
        return iter(())  # empty stream


@pytest.fixture(autouse=True)
def _clear_langfuse_env(monkeypatch):
    from deerflow.config.tracing_config import reset_tracing_config

    for name in ("LANGFUSE_TRACING", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    reset_tracing_config()
    yield
    reset_tracing_config()


def _stub_agent_creation(monkeypatch, fake_agent: _FakeAgent) -> dict[str, Any]:
    """Short-circuit the heavy parts of ``_ensure_agent`` so we can drive
    ``stream()`` against a fake graph without touching real models, tools
    or middleware factories.
    """
    captured: dict[str, Any] = {}

    def _stub_ensure_agent(self, config):
        captured["config"] = config
        self._agent = fake_agent
        self._agent_config_key = ("stub",)

    monkeypatch.setattr(DeerFlowClient, "_ensure_agent", _stub_ensure_agent)
    return captured


def _make_client(_monkeypatch) -> DeerFlowClient:
    """Build a client without going through ``__init__`` so we never load
    config.yaml or perform any other side-effectful startup work."""
    fake_app_config = SimpleNamespace(models=[SimpleNamespace(name="stub-model")])
    client = DeerFlowClient.__new__(DeerFlowClient)
    client._app_config = fake_app_config
    client._extensions_config = None
    client._model_name = "stub-model"
    client._thinking_enabled = False
    client._plan_mode = False
    client._subagent_enabled = False
    client._agent_name = None
    client._available_skills = None
    client._middlewares = None
    client._checkpointer = None
    client._agent = None
    client._agent_config_key = None
    client._environment = None
    return client


def test_stream_injects_langfuse_metadata_when_enabled(monkeypatch):
    monkeypatch.setenv("LANGFUSE_TRACING", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    from deerflow.config.tracing_config import reset_tracing_config

    reset_tracing_config()

    class _SentinelHandler:
        pass

    sentinel = _SentinelHandler()
    monkeypatch.setattr("deerflow.client.build_tracing_callbacks", lambda: [sentinel])

    fake_agent = _FakeAgent()
    captured = _stub_agent_creation(monkeypatch, fake_agent)
    client = _make_client(monkeypatch)

    list(client.stream("hi", thread_id="thread-client-1"))

    config = captured["config"]
    metadata = config.get("metadata") or {}
    assert metadata.get("langfuse_session_id") == "thread-client-1"
    assert metadata.get("langfuse_trace_name") == "lead-agent"
    # Default no-auth context falls back to ``"default"`` user.
    assert metadata.get("langfuse_user_id") in {"default", "test-user-autouse"}
    callbacks = config.get("callbacks") or []
    assert sentinel in callbacks


def test_stream_is_inert_when_langfuse_disabled(monkeypatch):
    monkeypatch.setattr("deerflow.client.build_tracing_callbacks", lambda: [])

    fake_agent = _FakeAgent()
    captured = _stub_agent_creation(monkeypatch, fake_agent)
    client = _make_client(monkeypatch)

    list(client.stream("hi", thread_id="thread-client-2"))

    config = captured["config"]
    assert "callbacks" not in config or not config["callbacks"]
    metadata = config.get("metadata") or {}
    assert "langfuse_session_id" not in metadata
    assert "langfuse_user_id" not in metadata


def test_stream_preserves_caller_metadata_overrides(monkeypatch):
    monkeypatch.setenv("LANGFUSE_TRACING", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    from deerflow.config.tracing_config import reset_tracing_config

    reset_tracing_config()
    monkeypatch.setattr("deerflow.client.build_tracing_callbacks", lambda: [])

    fake_agent = _FakeAgent()
    captured = _stub_agent_creation(monkeypatch, fake_agent)
    client = _make_client(monkeypatch)

    # Drive stream with a pre-populated metadata so the worker-equivalent
    # ``setdefault`` semantics are exercised.
    original_get_config = DeerFlowClient._get_runnable_config

    def patched_get_runnable_config(self, thread_id, **overrides):
        cfg = original_get_config(self, thread_id, **overrides)
        cfg["metadata"] = {
            "langfuse_session_id": "explicit-session-override",
            "langfuse_user_id": "explicit-user",
        }
        return cfg

    monkeypatch.setattr(DeerFlowClient, "_get_runnable_config", patched_get_runnable_config)
    list(client.stream("hi", thread_id="thread-client-3"))

    metadata = captured["config"].get("metadata") or {}
    assert metadata["langfuse_session_id"] == "explicit-session-override"
    assert metadata["langfuse_user_id"] == "explicit-user"
    # ``trace_name`` was not supplied by caller so the worker still fills it.
    assert metadata["langfuse_trace_name"] == "lead-agent"
