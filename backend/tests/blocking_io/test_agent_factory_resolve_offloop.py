"""Regression tests: the lead-agent assembly import must stay off the event loop.

``resolve_agent_factory`` lazily imports ``deerflow.agents.lead_agent.agent``,
which transitively imports the middlewares, authz, MCP and jsonschema chains —
multiple seconds on a cold start. ``start_run`` is the single choke point every
run-creation path flows through, so resolving it on the Gateway event loop
stalls every other request until the import finishes (the same loop-stall
family as issue #5172). ``start_run`` must therefore resolve the factory on a
dedicated assembly worker; these tests pin that contract with a probe module
whose ``__getattr__`` performs real file IO under the strict Blockbuster gate.
"""

from __future__ import annotations

import asyncio
import contextvars
import sys
import threading
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from blockbuster import BlockingError
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from app.gateway.run_models import RunCreateRequest
from app.gateway.services import resolve_agent_factory, start_run
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


def _install_probe_module(monkeypatch: pytest.MonkeyPatch, probe_file: Path) -> list[int]:
    """Replace the lead-agent module with a probe whose import records the thread.

    ``from deerflow.agents.lead_agent.agent import assemble_lead_agent`` resolves
    attributes through the module-level ``__getattr__`` (PEP 562), so whatever
    thread calls it is the thread that pays the import.
    """
    threads: list[int] = []

    def _getattr(name: str) -> object:
        if name == "assemble_lead_agent":
            assert probe_file.read_text(encoding="utf-8") == "import probe"
            threads.append(threading.get_ident())
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
async def test_start_run_resolves_agent_factory_off_the_event_loop(_stub_app_config, monkeypatch, tmp_path) -> None:
    """``start_run`` must resolve the agent factory on a worker thread."""
    probe_file = tmp_path / "import-probe.txt"
    await asyncio.to_thread(probe_file.write_text, "import probe", encoding="utf-8")
    probe_threads = _install_probe_module(monkeypatch, probe_file)
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
    assert all(thread_id != threading.get_ident() for thread_id in probe_threads), "resolve_agent_factory imported the lead-agent stack on the event loop"


@pytest.mark.asyncio
async def test_inline_factory_resolution_trips_the_blocking_io_gate(monkeypatch, tmp_path) -> None:
    """The import probe must fail if production resolution returns to the loop."""
    probe_file = tmp_path / "import-probe.txt"
    await asyncio.to_thread(probe_file.write_text, "import probe", encoding="utf-8")
    _install_probe_module(monkeypatch, probe_file)

    with pytest.raises(BlockingError):
        resolve_agent_factory(None)


@pytest.mark.asyncio
async def test_slow_factory_resolution_leaves_default_executor_available(_stub_app_config) -> None:
    """A cold import cannot occupy the default pool used by unrelated requests."""
    loop = asyncio.get_running_loop()
    # One worker makes default-executor starvation deterministic. The test's
    # event loop owns this executor and shuts it down during fixture teardown.
    loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
    resolver_started = asyncio.Event()
    release_resolver = threading.Event()
    request_context = contextvars.ContextVar("factory-request-context", default=None)
    token = request_context.set("request-owner")
    factory = object()
    observed_context = []

    def slow_resolver(assistant_id):
        observed_context.append(request_context.get())
        loop.call_soon_threadsafe(resolver_started.set)
        release_resolver.wait(timeout=10)
        return factory

    run_manager = RunManager(store=MemoryRunStore())
    request = _make_start_run_request(run_manager)
    body = RunCreateRequest(input={"messages": [{"role": "user", "content": "hi"}]})

    with (
        patch("app.gateway.services.resolve_agent_factory", side_effect=slow_resolver) as resolver,
        patch("app.gateway.services.run_agent", new_callable=AsyncMock) as worker,
    ):
        admission = asyncio.create_task(start_run(body, "thread-resolve-isolation", request))
        try:
            await asyncio.wait_for(resolver_started.wait(), timeout=5)
            assert await asyncio.wait_for(asyncio.to_thread(lambda: "unrelated-work"), timeout=5) == "unrelated-work"
            assert not admission.done(), "factory resolution must finish before admitting the run"
        finally:
            release_resolver.set()
            try:
                record = await asyncio.wait_for(admission, timeout=5)
                assert record.task is not None
                await asyncio.wait_for(record.task, timeout=5)
            finally:
                request_context.reset(token)

    resolver.assert_called_once_with(body.assistant_id)
    assert observed_context == ["request-owner"]
    assert worker.await_args.kwargs["agent_factory"] is factory


@pytest.mark.asyncio
async def test_factory_resolution_failure_prevents_run_admission(_stub_app_config) -> None:
    """Import errors propagate before any durable run or worker is created."""
    run_manager = RunManager(store=MemoryRunStore())
    request = _make_start_run_request(run_manager)
    body = RunCreateRequest(input={"messages": [{"role": "user", "content": "hi"}]})

    with (
        patch("app.gateway.services.resolve_agent_factory", side_effect=ImportError("factory import failed")),
        patch.object(run_manager, "create_or_reject", new_callable=AsyncMock) as admit,
        patch("app.gateway.services.run_agent", new_callable=AsyncMock) as worker,
    ):
        with pytest.raises(ImportError, match="factory import failed"):
            await start_run(body, "thread-resolve-failure", request)

    admit.assert_not_awaited()
    worker.assert_not_awaited()
