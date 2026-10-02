"""Regression tests: the lead-agent assembly import must stay off the event loop.

``resolve_agent_factory`` lazily imports ``deerflow.agents.lead_agent.agent``,
which transitively imports the middlewares, authz, MCP and jsonschema chains —
multiple seconds on a cold start. ``start_run`` is the single choke point every
run-creation path flows through, so resolving it on the Gateway event loop
stalls every other request until the import finishes (the same loop-stall
family as issue #5172). ``start_run`` must therefore resolve the factory on a
worker thread; these tests pin that contract with a probe module whose
``__getattr__`` records the thread that performed the attribute import.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import types
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from app.gateway.run_models import RunCreateRequest
from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
from deerflow.runtime import RunManager
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.runs.store.memory import MemoryRunStore

LEAD_AGENT_MODULE = "deerflow.agents.lead_agent.agent"


@pytest.fixture
def _stub_app_config():
    """Keep run tests independent from a developer-local config.yaml."""
    set_app_config(AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}}))
    yield
    reset_app_config()


def _install_probe_module(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Replace the lead-agent module with a probe whose import records the thread.

    ``from deerflow.agents.lead_agent.agent import assemble_lead_agent`` resolves
    attributes through the module-level ``__getattr__`` (PEP 562), so whatever
    thread calls it is the thread that pays the import.
    """
    threads: list[int] = []

    def _getattr(name: str) -> object:
        threads.append(threading.get_ident())
        if name == "assemble_lead_agent":
            return lambda **kwargs: SimpleNamespace(graph=object())
        raise AttributeError(name)

    probe = types.ModuleType(LEAD_AGENT_MODULE)
    probe.__dict__["__getattr__"] = _getattr
    monkeypatch.setitem(sys.modules, LEAD_AGENT_MODULE, probe)
    return threads


def _make_start_run_request(run_manager: RunManager) -> SimpleNamespace:
    return SimpleNamespace(
        headers={},
        state=SimpleNamespace(auth_source=None),
        app=SimpleNamespace(
            state=SimpleNamespace(
                stream_bridge=SimpleNamespace(),
                run_manager=run_manager,
                checkpointer=InMemorySaver(),
                store=InMemoryStore(),
                run_event_store=MemoryRunEventStore(),
                run_events_config=None,
                thread_store=MemoryThreadMetaStore(InMemoryStore()),
            )
        ),
    )


@pytest.mark.asyncio
async def test_start_run_resolves_agent_factory_off_the_event_loop(_stub_app_config, monkeypatch) -> None:
    """``start_run`` must resolve the agent factory on a worker thread."""
    from app.gateway.services import start_run

    probe_threads = _install_probe_module(monkeypatch)
    run_manager = RunManager(store=MemoryRunStore())
    request = _make_start_run_request(run_manager)
    body = RunCreateRequest(input={"messages": [{"role": "user", "content": "hi"}]})

    async def fake_run_agent(*args, **kwargs):
        await asyncio.sleep(0)

    with patch("app.gateway.services.run_agent", side_effect=fake_run_agent):
        record = await start_run(body, "thread-resolve-offloop", request)
        assert record.task is not None
        await asyncio.wait_for(record.task, timeout=5)

    assert probe_threads, "resolve_agent_factory did not import the lead-agent module"
    assert probe_threads[0] != threading.get_ident(), "resolve_agent_factory imported the lead-agent stack on the event loop"
