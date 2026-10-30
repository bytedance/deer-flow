"""Run tracing references preserve admission identity without carrying credentials."""

from __future__ import annotations

import importlib
import importlib.util
from contextlib import contextmanager
from contextvars import ContextVar
from types import SimpleNamespace

import pytest


def _helpers():
    assert importlib.util.find_spec("deerflow.runtime.tracing_snapshot") is not None, "run tracing snapshot references are not implemented"
    return importlib.import_module("deerflow.runtime.tracing_snapshot")


def test_snapshot_references_never_include_provider_credentials():
    helpers = _helpers()
    snapshot = SimpleNamespace(snapshot_id="frozen-1", agent_name="researcher", providers=[{"api_key": "secret-never-persist"}])

    assert helpers.snapshot_references(snapshot) == {
        "deerflow_tracing_snapshot_id": "frozen-1",
        "deerflow_tracing_agent_name": "researcher",
    }
    assert helpers.snapshot_references(None) == {}


def test_restore_references_uses_original_parent_agent_and_owner(monkeypatch):
    helpers = _helpers()
    profiles = importlib.import_module("deerflow.tracing.profiles")
    calls = []
    frozen = object()

    def resolve(agent_name, user_id, *, snapshot_id=None):
        calls.append((agent_name, user_id, snapshot_id))
        return frozen

    monkeypatch.setattr(profiles, "resolve_run_snapshot", resolve)
    refs = {helpers.TRACING_SNAPSHOT_ID_KEY: "frozen-1", helpers.TRACING_AGENT_NAME_KEY: "parent-agent"}

    assert helpers.restore_snapshot(refs, user_id="alice") is frozen
    assert calls == [("parent-agent", "alice", "frozen-1")]


@pytest.mark.parametrize("refs", [{"deerflow_tracing_snapshot_id": "one"}, {"deerflow_tracing_agent_name": "parent"}, {"deerflow_tracing_snapshot_id": 4, "deerflow_tracing_agent_name": "parent"}])
def test_partial_or_malformed_snapshot_references_fail_closed(refs):
    helpers = _helpers()
    with pytest.raises(ValueError, match="tracing snapshot"):
        helpers.restore_snapshot(refs, user_id="alice")


def test_missing_references_remain_compatible_with_legacy_runs():
    assert _helpers().restore_snapshot({}, user_id="alice") is None


def test_managed_lineage_with_missing_snapshot_fails_closed():
    helpers = _helpers()
    with pytest.raises(ValueError, match="tracing snapshot"):
        helpers.restore_snapshot({"deerflow_tracing_managed": True}, user_id="alice")


def test_request_config_echo_cannot_retain_forged_tracing_authority():
    from deerflow.runtime.secret_context import redact_config_secrets

    authority = {"deerflow_tracing_snapshot_id": "forged", "deerflow_tracing_agent_name": "victim", "deerflow_tracing_pinned": True, "deerflow_tracing_managed": True}
    config = {section: {**authority, "caller": "keep"} for section in ("context", "configurable", "metadata")}
    assert redact_config_secrets(config) == {section: {"caller": "keep"} for section in config}


def test_embedded_stream_binds_frozen_tracing_only_while_advancing(monkeypatch):
    module = importlib.import_module("deerflow.client")
    assert hasattr(module, "TracingSession"), "embedded stream does not bind run tracing"
    active = ContextVar("test_embedded_tracing", default=None)
    frozen = SimpleNamespace(snapshot_id="first", agent_name="researcher")
    resolutions = []

    class Session:
        def __init__(self, snapshot):
            self.snapshot = snapshot

        @contextmanager
        def activate(self):
            token = active.set(self.snapshot)
            try:
                yield
            finally:
                active.reset(token)

        def close(self):
            assert active.get() is None

    def resolve(agent_name, user_id, **kwargs):
        resolutions.append(agent_name)
        return frozen

    observed = []

    def stream_turn(self, *args, **kwargs):
        try:
            observed.append(active.get())
            yield "first"
            observed.append(active.get())
            yield "second"
        finally:
            observed.append(active.get())

    monkeypatch.setattr(module, "TracingSession", Session)
    monkeypatch.setattr(module, "resolve_run_snapshot", resolve)
    monkeypatch.setattr(module.DeerFlowClient, "_stream_turn", stream_turn)
    client = module.DeerFlowClient.__new__(module.DeerFlowClient)
    client._agent_name = "researcher"
    client._app_config = SimpleNamespace(database=SimpleNamespace(backend="memory"))
    stream = client.stream("hello", user_id="alice")

    assert next(stream) == "first"
    assert active.get() is None
    assert next(stream) == "second"
    assert active.get() is None
    stream.close()

    assert observed == [frozen, frozen, frozen]
    assert resolutions == ["researcher"]
