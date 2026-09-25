"""Clients with no approval surface must auto-approve rather than park.

The tool-approval middleware is registered for every lead-agent build, so
``tools[].interrupt_on`` stays effective and ``DeerFlowClient.resume()`` stays
reachable. The clients that cannot answer a park opt out per run by sending
``disable_tool_approval``; these tests pin that opt-out at each such entry point,
because losing it turns a configured gate into a hung thread with nobody able to
send ``Command(resume=...)``.

Covered here: the Gateway HTTP path (the web UI, which does not consume
``__interrupt__``) and both TUI entry points (interactive + headless). IM
channels have their own coverage alongside ``ChannelManager._apply_channel_policy``.

Lifetime: each downgrade is temporary, so the test that pins it retires with the
client that grows an approval surface — the Gateway/web-UI tests when the browser
consumes ``__interrupt__``, the TUI tests when the app gains an approval prompt
and a resume submission. Two tests are not tied to a client and stay:
``test_non_mapping_context_is_rejected_before_the_downgrade`` (why the Gateway
assigns unconditionally instead of guarding on ``isinstance``) and
``test_gateway_downgrade_stays_out_of_configurable`` (runtime-only keys belong in
``context``, not in the checkpoint-persisted ``configurable``). Delete this file
only once nothing it covers is left.
"""

from __future__ import annotations

import asyncio

import pytest

from deerflow.agents.middlewares.human_in_the_loop import DISABLE_TOOL_APPROVAL_KEY
from deerflow.client import StreamEvent
from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
from deerflow.tui.app import DeerFlowTUI
from deerflow.tui.cli import LaunchPlan

# ----------------------------------------------------------------------
# Gateway HTTP path
# ----------------------------------------------------------------------


@pytest.fixture
def _stub_app_config():
    """Keep the Gateway path independent of a developer-local ``config.yaml``.

    ``start_run`` resolves an ``AppConfig`` per request and turns any failure
    into a 503, so without this these tests only pass on a machine that happens
    to have a config file — CI has none, since it is gitignored.
    """
    set_app_config(AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}}))
    yield
    reset_app_config()


async def _capture_start_run_config(body, *, auth_source=None):
    """Run ``start_run`` with a stubbed agent and return the assembled config."""
    from types import SimpleNamespace
    from unittest.mock import patch

    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.store.memory import InMemoryStore

    from app.gateway.services import start_run
    from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
    from deerflow.runtime import RunManager
    from deerflow.runtime.events.store.memory import MemoryRunEventStore
    from deerflow.runtime.runs.store.memory import MemoryRunStore

    state = SimpleNamespace(
        stream_bridge=SimpleNamespace(),
        run_manager=RunManager(store=MemoryRunStore()),
        checkpointer=InMemorySaver(),
        store=InMemoryStore(),
        run_event_store=MemoryRunEventStore(),
        run_events_config=None,
        thread_store=MemoryThreadMetaStore(InMemoryStore()),
    )
    request = SimpleNamespace(
        headers={},
        state=SimpleNamespace(auth_source=auth_source),
        app=SimpleNamespace(state=state),
    )
    captured: dict[str, object] = {}

    async def fake_run_agent(*args, **kwargs):
        captured["config"] = kwargs["config"]

    with (
        patch("app.gateway.services.resolve_agent_factory", return_value=object()),
        patch("app.gateway.services.run_agent", side_effect=fake_run_agent),
    ):
        record = await start_run(body, "thread-approval-downgrade", request)
        await record.task

    return captured["config"]


def _run_request(**kwargs):
    from app.gateway.run_models import RunCreateRequest

    return RunCreateRequest(input={"messages": [{"role": "user", "content": "hi"}]}, **kwargs)


@pytest.mark.asyncio
async def test_gateway_run_auto_approves_by_default(_stub_app_config):
    config = await _capture_start_run_config(_run_request())

    assert config["context"][DISABLE_TOOL_APPROVAL_KEY] is True


@pytest.mark.asyncio
async def test_gateway_run_auto_approves_on_the_context_path(_stub_app_config):
    """A caller driving the run via ``context`` gets the same downgrade."""
    config = await _capture_start_run_config(_run_request(config={"context": {"model_name": "gpt-4o"}}))

    assert config["context"][DISABLE_TOOL_APPROVAL_KEY] is True


@pytest.mark.asyncio
async def test_gateway_run_auto_approves_on_the_configurable_path(_stub_app_config):
    config = await _capture_start_run_config(_run_request(config={"configurable": {"model_name": "gpt-4o"}}))

    assert config["context"][DISABLE_TOOL_APPROVAL_KEY] is True


@pytest.mark.asyncio
async def test_gateway_run_auto_approves_when_context_is_null(_stub_app_config):
    """``context: null`` becomes ``{}`` upstream, so the downgrade still lands."""
    config = await _capture_start_run_config(_run_request(config={"context": None}))

    assert config["context"][DISABLE_TOOL_APPROVAL_KEY] is True


@pytest.mark.asyncio
async def test_a_resume_is_not_downgraded(_stub_app_config):
    """Posting decisions must keep approval on, or the decisions are discarded.

    Downgrading a resume does not auto-approve it: the middleware returns before
    re-entering ``interrupt()``, so LangGraph drops the posted ``decisions`` with
    no error and leaves the gated calls on the original ``AIMessage``
    unanswered — the tools node then runs them with pre-review args, turning a
    ``reject`` into an execution. A caller posting decisions is the human this
    downgrade exists to protect, so the downgrade must not apply.
    """
    config = await _capture_start_run_config(_run_request(command={"resume": {"decisions": [{"type": "reject"}]}}))

    assert DISABLE_TOOL_APPROVAL_KEY not in config.get("context", {})


@pytest.mark.asyncio
async def test_a_resume_with_no_decisions_is_still_not_downgraded(_stub_app_config):
    """Any ``command.resume`` becomes a ``Command``, whatever it carries."""
    config = await _capture_start_run_config(_run_request(command={"resume": "plain-value"}))

    assert DISABLE_TOOL_APPROVAL_KEY not in config.get("context", {})


@pytest.mark.asyncio
async def test_an_empty_command_still_downgrades(_stub_app_config):
    """``command`` without ``resume`` is an ordinary run, not a resume.

    ``start_run`` only builds a ``Command`` when ``command["resume"]`` is not
    ``None``, so the exclusion must key off the resolved graph input rather than
    the mere presence of a ``command`` field.
    """
    config = await _capture_start_run_config(_run_request(command={"resume": None}))

    assert config["context"][DISABLE_TOOL_APPROVAL_KEY] is True


@pytest.mark.parametrize("bad_context", ["not-a-mapping", 123, [1, 2]])
def test_non_mapping_context_is_rejected_before_the_downgrade(_stub_app_config, bad_context):
    """A non-mapping ``context`` never reaches the downgrade — the run is refused.

    This is why the downgrade assigns unconditionally instead of guarding on
    ``isinstance``: a guard would silently skip it if this validation ever
    stopped holding, turning a rejected request into an ungated run.
    """
    from app.gateway.services import build_run_config

    with pytest.raises(ValueError, match="context"):
        build_run_config("thread-1", {"context": bad_context}, None)


@pytest.mark.parametrize("section", ["context", "configurable"])
@pytest.mark.asyncio
async def test_client_cannot_re_enable_gateway_tool_approval(_stub_app_config, section):
    """A client asking for approval does not get it; the server value wins.

    The key is internal-only, so a client copy is scrubbed for external callers.
    This pins that the Gateway's assignment is not a ``setdefault`` a client
    could pre-empt by sending ``False``.
    """
    config = await _capture_start_run_config(_run_request(config={section: {DISABLE_TOOL_APPROVAL_KEY: False}}))

    assert config["context"][DISABLE_TOOL_APPROVAL_KEY] is True


@pytest.mark.asyncio
async def test_gateway_downgrade_stays_out_of_configurable(_stub_app_config):
    """``configurable`` is persisted in checkpoints; runtime flags do not belong.

    Mirrors the placement rule for the other context-only runtime keys.
    """
    config = await _capture_start_run_config(_run_request())

    assert DISABLE_TOOL_APPROVAL_KEY not in config.get("configurable", {})


# ----------------------------------------------------------------------
# TUI — interactive
# ----------------------------------------------------------------------


class _RecordingClient:
    def __init__(self):
        self.stream_calls: list[tuple] = []

    def list_models(self):
        return {"models": [{"name": "fake-model", "display_name": "Fake Model"}]}

    def list_skills(self, enabled_only=False):
        return {"skills": []}

    def stream(self, message, *, thread_id=None, **kwargs):
        self.stream_calls.append((message, thread_id, kwargs))
        yield StreamEvent(type="end", data={"usage": {"total_tokens": 1}})


class _RecordingSession:
    def __init__(self):
        self.client = _RecordingClient()

    def resolve_thread(self, plan):
        return None


async def _wait_until(predicate, pilot, *, timeout=3.0):
    waited = 0.0
    while waited < timeout:
        await pilot.pause()
        if predicate():
            return True
        await asyncio.sleep(0.02)
        waited += 0.02
    return predicate()


@pytest.mark.asyncio
async def test_interactive_tui_run_auto_approves():
    """The Textual app has no approval prompt, so it must not let a run park."""
    session = _RecordingSession()
    app = DeerFlowTUI(session, LaunchPlan(mode="tui"))

    async with app.run_test() as pilot:
        await pilot.pause()
        for ch in "hi":
            await pilot.press(ch)
        await pilot.press("enter")
        await _wait_until(lambda: session.client.stream_calls, pilot)

    assert session.client.stream_calls, "the app never reached client.stream()"
    _message, _thread_id, kwargs = session.client.stream_calls[0]
    assert kwargs[DISABLE_TOOL_APPROVAL_KEY] is True


# ----------------------------------------------------------------------
# TUI — headless one-shots
# ----------------------------------------------------------------------


class _HeadlessClient:
    def __init__(self):
        self.chat_calls: list[dict] = []
        self.stream_calls: list[dict] = []

    def chat(self, message, *, thread_id=None, **kwargs):
        self.chat_calls.append(kwargs)
        return "done"

    def stream(self, message, *, thread_id=None, **kwargs):
        self.stream_calls.append(kwargs)
        return iter(())


class _HeadlessSession:
    def __init__(self):
        self.client = _HeadlessClient()

    def resolve_thread(self, plan):
        return None


@pytest.fixture
def headless_session(monkeypatch):
    from deerflow.tui import cli

    session = _HeadlessSession()
    monkeypatch.setattr(cli, "_make_session", lambda: session)
    return session


def test_headless_print_run_auto_approves(headless_session, capsys):
    from deerflow.tui import cli

    assert cli._run_print(LaunchPlan(mode="print", message="hi")) == 0
    capsys.readouterr()

    assert headless_session.client.chat_calls
    assert headless_session.client.chat_calls[0][DISABLE_TOOL_APPROVAL_KEY] is True


def test_headless_json_run_auto_approves(headless_session, capsys):
    from deerflow.tui import cli

    assert cli._run_json(LaunchPlan(mode="json", message="hi")) == 0
    capsys.readouterr()

    assert headless_session.client.stream_calls
    assert headless_session.client.stream_calls[0][DISABLE_TOOL_APPROVAL_KEY] is True
