"""HTTP/runtime lifecycle E2E tests for the Gateway-owned runs API.

These tests keep the external model out of scope while exercising the real
FastAPI app, auth middleware, lifespan-created runtime dependencies,
``start_run()``, ``run_agent()``, StreamBridge, checkpointer, run store, and
thread metadata store.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import queue
import threading
import time
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from _agent_e2e_helpers import FakeToolCallingModel, build_single_tool_call_model
from langchain_core.messages import AIMessage, HumanMessage

pytestmark = pytest.mark.no_auto_user


_MINIMAL_CONFIG_YAML = """\
log_level: info
models:
  - name: fake-test-model
    display_name: Fake Test Model
    use: langchain_openai:ChatOpenAI
    model: gpt-4o-mini
    api_key: $OPENAI_API_KEY
    base_url: $OPENAI_API_BASE
sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
agents_api:
  enabled: true
title:
  enabled: false
memory:
  enabled: false
database:
  backend: sqlite
run_events:
  backend: memory
"""


class _RunController:
    """Cross-thread controls for the fake async agent."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.checkpoint_written = threading.Event()
        self.cancelled = threading.Event()
        self.release = threading.Event()
        self.instances: list[_ScriptedAgent] = []


class _ScriptedAgent:
    """Deterministic runtime double for lifecycle-only tests.

    This is intentionally not a full LangGraph graph. Tests that need
    controllable blocking, cancellation, and rollback checkpoints use the small
    ``run_agent`` surface they exercise: ``astream()``, checkpointer/store
    attachment, metadata, and interrupt node attributes. The real lead-agent
    graph/tool dispatch path is covered separately by
    ``test_stream_run_executes_real_lead_agent_setup_agent_business_path``.
    """

    def __init__(
        self,
        controller: _RunController,
        *,
        title: str,
        answer: str,
        block_after_first_chunk: bool = False,
        block_before_checkpoint: bool = False,
        write_title: bool = True,
    ) -> None:
        self.controller = controller
        self.title = title
        self.answer = answer
        self.block_after_first_chunk = block_after_first_chunk
        self.block_before_checkpoint = block_before_checkpoint
        self.write_title = write_title
        self.checkpointer: Any | None = None
        self.store: Any | None = None
        self.metadata = {"model_name": "fake-test-model"}
        self.interrupt_before_nodes = None
        self.interrupt_after_nodes = None
        self.model = FakeToolCallingModel(responses=[AIMessage(content=self.answer)])

    async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
        del subgraphs
        self.controller.started.set()

        try:
            thread_id = _thread_id_from_config(config)
            if self.block_before_checkpoint:
                while not self.controller.release.is_set():
                    await asyncio.sleep(0.05)
            human_text = _last_human_text(graph_input)
            human = HumanMessage(content=human_text)
            ai = await self.model.ainvoke([human], config=config)
            state = {"messages": [human.model_dump(), ai.model_dump()]}
            if self.write_title:
                state["title"] = self.title

            if self.checkpointer is not None:
                await _write_checkpoint(self.checkpointer, thread_id=thread_id, state=state)
            self.controller.checkpoint_written.set()

            yield _stream_item_for_mode(stream_mode, state)

            if self.block_after_first_chunk:
                while not self.controller.release.is_set():
                    await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            # Catch cancellation arriving anywhere in the body — including the
            # `await ainvoke()` / `_write_checkpoint()` / `yield` points between
            # ``started.set()`` and the original inner ``try`` — so tests that
            # wait for ``cancelled`` after issuing ``POST /cancel`` no longer
            # race with cancellation arriving early.
            self.controller.cancelled.set()
            raise


def _make_agent_factory(controller: _RunController, **agent_kwargs):
    def factory(*, config):
        del config
        agent = _ScriptedAgent(controller, **agent_kwargs)
        controller.instances.append(agent)
        return agent

    return factory


def _build_fake_setup_agent_model(agent_name: str):
    """Patch target for lead_agent.agent.create_chat_model.

    The graph, tool registry, ToolNode dispatch, and setup_agent implementation
    remain production code; this fake only replaces the external LLM call.
    """

    def fake_create_chat_model(*args: Any, **kwargs: Any) -> FakeToolCallingModel:
        del args, kwargs
        return build_single_tool_call_model(
            tool_name="setup_agent",
            tool_args={
                "soul": f"# Runtime Business E2E\n\nAgent name: {agent_name}",
                "description": "runtime lifecycle business path",
            },
            tool_call_id="call_runtime_business_1",
            final_text=f"Created {agent_name} through the real setup_agent tool.",
        )

    return fake_create_chat_model


@pytest.fixture
def isolated_deer_flow_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "deer-flow-home"
    home.mkdir()
    monkeypatch.setenv("DEER_FLOW_HOME", str(home))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-key-not-used")
    monkeypatch.setenv("OPENAI_API_BASE", "https://example.invalid")

    staged_config = tmp_path / "config.yaml"
    staged_config.write_text(_MINIMAL_CONFIG_YAML, encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(staged_config))

    staged_extensions_config = tmp_path / "extensions_config.json"
    staged_extensions_config.write_text('{"mcpServers": {}, "skills": {}}', encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(staged_extensions_config))
    return home


def _reset_process_singletons(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear runtime singletons that depend on this test's temporary config.

    The Gateway app/lifespan path reads process-wide caches before wiring
    request-scoped dependencies. These E2E tests stage a temporary
    ``config.yaml``/``extensions_config.json`` and ``DEER_FLOW_HOME``, so the
    caches below must be reset before app creation:

    - app_config / extensions_config: parsed config file caches.
    - paths: ``DEER_FLOW_HOME``-derived filesystem paths.
    - persistence.engine: SQLAlchemy engine/session factory for the sqlite dir.
    - app.gateway.deps: cached local auth provider/repository.

    A shared public reset helper would be cleaner long-term; this test keeps
    the reset boundary explicit because the PR is focused on runtime lifecycle
    coverage rather than config-cache API cleanup.
    """

    from app.gateway import deps as deps_module
    from deerflow.config import app_config as app_config_module
    from deerflow.config import extensions_config as extensions_config_module
    from deerflow.config import paths as paths_module
    from deerflow.persistence import engine as engine_module

    for module, attr, value in (
        (app_config_module, "_app_config", None),
        (app_config_module, "_app_config_path", None),
        (app_config_module, "_app_config_mtime", None),
        (app_config_module, "_app_config_is_custom", False),
        (extensions_config_module, "_extensions_config", None),
        (paths_module, "_paths_singleton", None),
        (paths_module, "_paths", None),
        (engine_module, "_engine", None),
        (engine_module, "_session_factory", None),
        (deps_module, "_cached_local_provider", None),
        (deps_module, "_cached_repo", None),
    ):
        monkeypatch.setattr(module, attr, value, raising=False)


def _preserve_process_config_singletons(monkeypatch: pytest.MonkeyPatch) -> None:
    """Restore config singletons mutated as a side effect of AppConfig loading.

    ``AppConfig.from_file()`` calls ``_apply_singleton_configs()``, which pushes
    nested config sections into module-level caches used by middlewares, tool
    selection, and runtime providers. Snapshotting those attributes with
    ``monkeypatch`` lets pytest restore the pre-test values during teardown, so
    loading the isolated test config does not leak into later tests.
    """

    from deerflow.config import (
        acp_config,
        agents_api_config,
        checkpointer_config,
        guardrails_config,
        memory_config,
        stream_bridge_config,
        subagents_config,
        summarization_config,
        title_config,
        tool_search_config,
    )

    for module, attr in (
        (title_config, "_title_config"),
        (summarization_config, "_summarization_config"),
        (memory_config, "_memory_config"),
        (agents_api_config, "_agents_api_config"),
        (subagents_config, "_subagents_config"),
        (tool_search_config, "_tool_search_config"),
        (guardrails_config, "_guardrails_config"),
        (checkpointer_config, "_checkpointer_config"),
        (stream_bridge_config, "_stream_bridge_config"),
        (acp_config, "_acp_agents"),
    ):
        monkeypatch.setattr(module, attr, getattr(module, attr), raising=False)


@pytest.fixture
def isolated_app(isolated_deer_flow_home: Path, monkeypatch: pytest.MonkeyPatch):
    _preserve_process_config_singletons(monkeypatch)
    _reset_process_singletons(monkeypatch)

    from deerflow.config import app_config as app_config_module

    cfg = app_config_module.get_app_config()
    cfg.database.sqlite_dir = str(isolated_deer_flow_home / "db")

    from app.gateway.app import create_app

    return create_app()


def test_lifespan_uses_sqlite_store_from_database_config(isolated_app):
    """Gateway startup must bind LangGraph Store to the unified database backend."""
    from langgraph.store.sqlite.aio import AsyncSqliteStore
    from starlette.testclient import TestClient

    with TestClient(isolated_app):
        assert isinstance(isolated_app.state.store, AsyncSqliteStore)


@pytest.fixture
def isolated_app_with_title(isolated_deer_flow_home: Path, monkeypatch: pytest.MonkeyPatch):
    config_path = isolated_deer_flow_home.parent / "config-title-enabled.yaml"
    config_path.write_text(_MINIMAL_CONFIG_YAML.replace("title:\n  enabled: false", "title:\n  enabled: true"), encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))

    _preserve_process_config_singletons(monkeypatch)
    _reset_process_singletons(monkeypatch)

    from deerflow.config import app_config as app_config_module

    cfg = app_config_module.get_app_config()
    cfg.database.sqlite_dir = str(isolated_deer_flow_home / "db")

    from app.gateway.app import create_app

    return create_app()


def _register_user(client, *, email: str = "runtime-e2e@example.com") -> str:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "very-strong-password-123"},
    )
    assert response.status_code == 201, response.text
    csrf_token = client.cookies.get("csrf_token")
    assert csrf_token
    return csrf_token


def _create_thread(client, csrf_token: str) -> str:
    thread_id = str(uuid.uuid4())
    response = client.post(
        "/api/threads",
        json={"thread_id": thread_id, "metadata": {"purpose": "runtime-lifecycle-e2e"}},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert response.status_code == 200, response.text
    return thread_id


def _run_body(**overrides) -> dict[str, Any]:
    body: dict[str, Any] = {
        "assistant_id": "lead_agent",
        "input": {"messages": [{"role": "user", "content": "Run lifecycle E2E prompt"}]},
        "config": {"recursion_limit": 50},
        "stream_mode": ["values"],
    }
    body.update(overrides)
    return body


def _drain_stream(response, *, timeout: float = 10.0, max_bytes: int = 1024 * 1024) -> str:
    chunks: queue.Queue[bytes | BaseException | object] = queue.Queue()
    sentinel = object()

    def read_stream() -> None:
        try:
            for chunk in response.iter_bytes():
                chunks.put(chunk)
                if b"event: end" in chunk:
                    break
        except BaseException as exc:  # pragma: no cover - reported in the main test thread
            chunks.put(exc)
        finally:
            chunks.put(sentinel)

    reader = threading.Thread(target=read_stream, daemon=True)
    reader.start()

    deadline = time.monotonic() + timeout
    body = b""
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AssertionError(f"SSE stream did not finish within {timeout}s; transcript tail={body[-4000:].decode('utf-8', errors='replace')}")
        try:
            chunk = chunks.get(timeout=remaining)
        except queue.Empty as exc:
            raise AssertionError(f"SSE stream did not produce data within {timeout}s; transcript tail={body[-4000:].decode('utf-8', errors='replace')}") from exc
        if chunk is sentinel:
            break
        if isinstance(chunk, BaseException):
            raise AssertionError("SSE reader failed") from chunk
        body += chunk
        if b"event: end" in body:
            break
        if len(body) >= max_bytes:
            raise AssertionError(f"SSE stream exceeded {max_bytes} bytes without event: end")
    if b"event: end" not in body:
        raise AssertionError(f"SSE stream closed before event: end; transcript tail={body[-4000:].decode('utf-8', errors='replace')}")
    return body.decode("utf-8", errors="replace")


def _parse_sse(transcript: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for raw_frame in transcript.split("\n\n"):
        frame = raw_frame.strip()
        if not frame or frame.startswith(":"):
            continue
        parsed: dict[str, Any] = {}
        for line in frame.splitlines():
            if line.startswith("event: "):
                parsed["event"] = line.removeprefix("event: ")
            elif line.startswith("data: "):
                payload = line.removeprefix("data: ")
                parsed["data"] = json.loads(payload)
            elif line.startswith("id: "):
                parsed["id"] = line.removeprefix("id: ")
        if parsed:
            events.append(parsed)
    return events


def _run_id_from_response(response) -> str:
    location = response.headers.get("content-location", "")
    assert location, "run stream response must include Content-Location"
    return location.rstrip("/").split("/")[-1]


def _wait_for_status(client, thread_id: str, run_id: str, status: str, *, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    last: dict | None = None
    while time.monotonic() < deadline:
        response = client.get(f"/api/threads/{thread_id}/runs/{run_id}")
        assert response.status_code == 200, response.text
        last = response.json()
        if last["status"] == status:
            return last
        time.sleep(0.05)
    raise AssertionError(f"Run {run_id} did not reach {status!r}; last={last!r}")


def _wait_for_thread_title(client, thread_id: str, expected_title: str, *, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    last: dict | None = None
    while time.monotonic() < deadline:
        response = client.get(f"/api/threads/{thread_id}")
        assert response.status_code == 200, response.text
        last = response.json()
        if last.get("values", {}).get("title") == expected_title:
            return last
        time.sleep(0.05)
    raise AssertionError(f"Thread {thread_id} did not reach title {expected_title!r}; last={last!r}")


def _wait_for_search_title(client, csrf_token: str, thread_id: str, expected_title: str, *, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    last_match: dict | None = None
    while time.monotonic() < deadline:
        response = client.post("/api/threads/search", json={"limit": 20}, headers={"X-CSRF-Token": csrf_token})
        assert response.status_code == 200, response.text
        matching = [item for item in response.json() if item["thread_id"] == thread_id]
        if matching:
            last_match = matching[0]
            if last_match.get("values", {}).get("title") == expected_title:
                return last_match
        time.sleep(0.05)
    raise AssertionError(f"Search result for {thread_id} did not reach title {expected_title!r}; last={last_match!r}")


def _thread_id_from_config(config: dict | None) -> str:
    config = config or {}
    context = config.get("context") if isinstance(config.get("context"), dict) else {}
    configurable = config.get("configurable") if isinstance(config.get("configurable"), dict) else {}
    thread_id = context.get("thread_id") or configurable.get("thread_id")
    assert thread_id, f"runtime config did not contain thread_id: {config!r}"
    return str(thread_id)


def _last_human_text(graph_input: dict) -> str:
    messages = graph_input.get("messages") or []
    if not messages:
        return ""
    last = messages[-1]
    content = getattr(last, "content", last)
    if isinstance(content, str):
        return content
    return str(content)


async def _write_checkpoint(checkpointer: Any, *, thread_id: str, state: dict[str, Any]) -> None:
    from langgraph.checkpoint.base import empty_checkpoint

    checkpoint = empty_checkpoint()
    checkpoint["channel_values"] = dict(state)
    checkpoint["channel_versions"] = {key: 1 for key in state}
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    metadata = {
        "source": "loop",
        "step": 1,
        "writes": {"scripted_agent": {"title": state.get("title"), "message_count": len(state.get("messages", []))}},
        "parents": {},
    }

    result = checkpointer.aput(config, checkpoint, metadata, {})
    if inspect.isawaitable(result):
        await result


def _stream_item_for_mode(stream_mode: Any, state: dict[str, Any]) -> Any:
    if isinstance(stream_mode, list):
        # ``run_agent`` passes a list when multiple modes/subgraphs are active.
        return stream_mode[0], state
    return state


def test_stream_run_completes_and_persists_runtime_state(isolated_app):
    """A streaming run should traverse the real runtime and leave state behind."""
    from starlette.testclient import TestClient

    controller = _RunController()
    factory = _make_agent_factory(
        controller,
        title="Lifecycle E2E",
        answer="Lifecycle complete.",
    )

    with (
        patch("app.gateway.services.resolve_agent_factory", return_value=factory),
        TestClient(isolated_app) as client,
    ):
        csrf_token = _register_user(client)
        thread_id = _create_thread(client, csrf_token)

        with client.stream(
            "POST",
            f"/api/threads/{thread_id}/runs/stream",
            json=_run_body(),
            headers={"X-CSRF-Token": csrf_token},
        ) as response:
            assert response.status_code == 200, response.read().decode()
            run_id = _run_id_from_response(response)
            transcript = _drain_stream(response)

        events = _parse_sse(transcript)
        assert [event["event"] for event in events] == ["metadata", "values", "end"]
        assert events[0]["data"] == {"run_id": run_id, "thread_id": thread_id}
        assert events[1]["data"]["title"] == "Lifecycle E2E"
        assert events[1]["data"]["messages"][-1]["content"] == "Lifecycle complete."

        run = client.get(f"/api/threads/{thread_id}/runs/{run_id}")
        assert run.status_code == 200, run.text
        assert run.json()["status"] == "success"

        thread = client.get(f"/api/threads/{thread_id}")
        assert thread.status_code == 200, thread.text
        assert thread.json()["status"] == "idle"
        assert thread.json()["values"]["title"] == "Lifecycle E2E"

        messages = client.get(f"/api/threads/{thread_id}/runs/{run_id}/messages")
        assert messages.status_code == 200, messages.text
        message_events = messages.json()["data"]
        event_types = [row["event_type"] for row in message_events]
        assert "llm.human.input" in event_types
        assert "llm.ai.response" in event_types
        assert any(row["content"]["content"] == "Run lifecycle E2E prompt" for row in message_events if row["event_type"] == "llm.human.input")
        assert any(row["content"]["content"] == "Lifecycle complete." for row in message_events if row["event_type"] == "llm.ai.response")


def test_stream_run_executes_real_lead_agent_setup_agent_business_path(isolated_app, isolated_deer_flow_home: Path):
    """A runtime stream should execute real lead-agent business code and tools."""
    from starlette.testclient import TestClient

    agent_name = "runtime-business-agent"

    with (
        patch(
            "deerflow.agents.lead_agent.agent.create_chat_model",
            new=_build_fake_setup_agent_model(agent_name),
        ),
        TestClient(isolated_app) as client,
    ):
        csrf_token = _register_user(client, email="business-e2e@example.com")
        auth_user_id = client.get("/api/v1/auth/me").json()["id"]
        thread_id = _create_thread(client, csrf_token)

        body = _run_body(
            input={
                "messages": [
                    {
                        "role": "user",
                        "content": f"Create a custom agent named {agent_name}.",
                    }
                ]
            },
            context={
                "agent_name": agent_name,
                "is_bootstrap": True,
                "thinking_enabled": False,
                "is_plan_mode": False,
                "subagent_enabled": False,
            },
        )

        with client.stream(
            "POST",
            f"/api/threads/{thread_id}/runs/stream",
            json=body,
            headers={"X-CSRF-Token": csrf_token},
        ) as response:
            assert response.status_code == 200, response.read().decode()
            run_id = _run_id_from_response(response)
            transcript = _drain_stream(response, timeout=20.0)

        events = _parse_sse(transcript)
        event_names = [event["event"] for event in events]
        assert "metadata" in event_names
        assert "error" not in event_names, transcript
        assert event_names[-1] == "end"

        run = _wait_for_status(client, thread_id, run_id, "success", timeout=10.0)
        assert run["assistant_id"] == "lead_agent"

        expected_soul = isolated_deer_flow_home / "users" / auth_user_id / "agents" / agent_name / "SOUL.md"
        assert expected_soul.exists(), f"setup_agent did not write SOUL.md. tmp tree: {sorted(str(p.relative_to(isolated_deer_flow_home)) for p in isolated_deer_flow_home.rglob('SOUL.md'))}"
        assert f"Agent name: {agent_name}" in expected_soul.read_text(encoding="utf-8")
        assert not (isolated_deer_flow_home / "users" / "default" / "agents" / agent_name).exists()


def test_cancel_interrupt_stops_running_background_run(isolated_app):
    """HTTP cancel?action=interrupt should stop the worker and persist interruption."""
    from starlette.testclient import TestClient

    controller = _RunController()
    factory = _make_agent_factory(
        controller,
        title="Interrupt candidate",
        answer="This run should be interrupted.",
        block_after_first_chunk=True,
    )

    with (
        patch("app.gateway.services.resolve_agent_factory", return_value=factory),
        TestClient(isolated_app) as client,
    ):
        csrf_token = _register_user(client, email="interrupt-e2e@example.com")
        thread_id = _create_thread(client, csrf_token)

        created = client.post(
            f"/api/threads/{thread_id}/runs",
            json=_run_body(),
            headers={"X-CSRF-Token": csrf_token},
        )
        assert created.status_code == 200, created.text
        run_id = created.json()["run_id"]
        assert controller.started.wait(5), "fake agent never started"

        cancelled = client.post(
            f"/api/threads/{thread_id}/runs/{run_id}/cancel?wait=true&action=interrupt",
            headers={"X-CSRF-Token": csrf_token},
        )
        assert cancelled.status_code == 204, cancelled.text
        assert controller.cancelled.wait(5), "fake agent task was not cancelled"

        run = _wait_for_status(client, thread_id, run_id, "interrupted")
        assert run["status"] == "interrupted"

        thread = client.get(f"/api/threads/{thread_id}")
        assert thread.status_code == 200, thread.text
        assert thread.json()["status"] == "idle"


def test_cancel_interrupt_generates_missing_title_from_checkpoint(isolated_app_with_title):
    """Interrupted first-turn runs should still persist an automatic thread title."""
    from starlette.testclient import TestClient

    controller = _RunController()
    factory = _make_agent_factory(
        controller,
        title="",
        answer="This run should be interrupted before a title is written.",
        block_after_first_chunk=True,
        write_title=False,
    )

    with (
        patch("app.gateway.services.resolve_agent_factory", return_value=factory),
        TestClient(isolated_app_with_title) as client,
    ):
        csrf_token = _register_user(client, email="interrupt-title-e2e@example.com")
        thread_id = _create_thread(client, csrf_token)

        created = client.post(
            f"/api/threads/{thread_id}/runs",
            json=_run_body(),
            headers={"X-CSRF-Token": csrf_token},
        )
        assert created.status_code == 200, created.text
        run_id = created.json()["run_id"]
        assert controller.checkpoint_written.wait(5), "fake agent never wrote checkpoint"

        cancelled = client.post(
            f"/api/threads/{thread_id}/runs/{run_id}/cancel?wait=true&action=interrupt",
            headers={"X-CSRF-Token": csrf_token},
        )
        assert cancelled.status_code == 204, cancelled.text

        thread = client.get(f"/api/threads/{thread_id}")
        assert thread.status_code == 200, thread.text
        assert thread.json()["values"]["title"] == "Run lifecycle E2E prompt"

        search = client.post("/api/threads/search", json={"limit": 20}, headers={"X-CSRF-Token": csrf_token})
        assert search.status_code == 200, search.text
        matching = [item for item in search.json() if item["thread_id"] == thread_id]
        assert matching[0]["values"]["title"] == "Run lifecycle E2E prompt"


def test_cancel_wait_false_generates_title_from_graph_input_before_checkpoint(isolated_app_with_title):
    """Fire-and-forget cancel should title early interruptions before checkpoint."""
    from starlette.testclient import TestClient

    controller = _RunController()
    factory = _make_agent_factory(
        controller,
        title="",
        answer="This answer should never be checkpointed.",
        block_before_checkpoint=True,
        write_title=False,
    )

    with (
        patch("app.gateway.services.resolve_agent_factory", return_value=factory),
        TestClient(isolated_app_with_title) as client,
    ):
        csrf_token = _register_user(client, email="interrupt-title-early-e2e@example.com")
        thread_id = _create_thread(client, csrf_token)

        created = client.post(
            f"/api/threads/{thread_id}/runs",
            json=_run_body(),
            headers={"X-CSRF-Token": csrf_token},
        )
        assert created.status_code == 200, created.text
        run_id = created.json()["run_id"]
        assert controller.started.wait(5), "fake agent never started"
        assert not controller.checkpoint_written.is_set()

        cancelled = client.post(
            f"/api/threads/{thread_id}/runs/{run_id}/cancel?wait=false&action=interrupt",
            headers={"X-CSRF-Token": csrf_token},
        )
        assert cancelled.status_code == 202, cancelled.text
        assert controller.cancelled.wait(5), "fake agent task was not cancelled"
        assert not controller.checkpoint_written.is_set()

        run = _wait_for_status(client, thread_id, run_id, "interrupted")
        assert run["status"] == "interrupted"

        thread = _wait_for_thread_title(client, thread_id, "Run lifecycle E2E prompt")
        assert thread["values"]["title"] == "Run lifecycle E2E prompt"

        matching = _wait_for_search_title(client, csrf_token, thread_id, "Run lifecycle E2E prompt")
        assert matching["values"]["title"] == "Run lifecycle E2E prompt"


@pytest.mark.anyio
async def test_sse_consumer_disconnect_cancels_inflight_run():
    """A disconnected SSE request should cancel an in-flight run when configured."""
    from app.gateway.services import sse_consumer
    from deerflow.runtime import DisconnectMode, MemoryStreamBridge, RunManager, RunStatus

    bridge = MemoryStreamBridge()
    run_manager = RunManager()
    record = await run_manager.create("thread-disconnect", on_disconnect=DisconnectMode.cancel)
    await run_manager.set_status(record.run_id, RunStatus.running)
    await bridge.publish(record.run_id, "metadata", {"run_id": record.run_id, "thread_id": record.thread_id})
    worker_started = asyncio.Event()
    worker_cancelled = asyncio.Event()

    async def _pending_worker() -> None:
        try:
            worker_started.set()
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            worker_cancelled.set()
            raise

    record.task = asyncio.create_task(_pending_worker())
    await asyncio.wait_for(worker_started.wait(), timeout=1.0)

    class _DisconnectedRequest:
        headers: dict[str, str] = {}

        async def is_disconnected(self) -> bool:
            return True

    try:
        frames = []
        async for frame in sse_consumer(bridge, record, _DisconnectedRequest(), run_manager):
            frames.append(frame)

        assert frames == []
        assert record.abort_event.is_set()
        assert record.status == RunStatus.interrupted
        await asyncio.wait_for(worker_cancelled.wait(), timeout=1.0)
        assert record.task.cancelled()
    finally:
        if record.task is not None and not record.task.done():
            record.task.cancel()
            with suppress(asyncio.CancelledError):
                await record.task


def test_cancel_rollback_restores_pre_run_checkpoint(isolated_app):
    """HTTP cancel?action=rollback should restore the checkpoint captured before run start."""
    from starlette.testclient import TestClient

    controller = _RunController()
    factory = _make_agent_factory(
        controller,
        title="During rollback run",
        answer="This answer should be rolled back.",
        block_after_first_chunk=True,
    )

    with (
        patch("app.gateway.services.resolve_agent_factory", return_value=factory),
        TestClient(isolated_app) as client,
    ):
        csrf_token = _register_user(client, email="rollback-e2e@example.com")
        thread_id = _create_thread(client, csrf_token)

        before = client.post(
            f"/api/threads/{thread_id}/state",
            json={
                "values": {
                    "title": "Before rollback",
                    "messages": [{"type": "human", "content": "before"}],
                },
                "as_node": "test_seed",
            },
            headers={"X-CSRF-Token": csrf_token},
        )
        assert before.status_code == 200, before.text
        assert before.json()["values"]["title"] == "Before rollback"

        created = client.post(
            f"/api/threads/{thread_id}/runs",
            json=_run_body(),
            headers={"X-CSRF-Token": csrf_token},
        )
        assert created.status_code == 200, created.text
        run_id = created.json()["run_id"]
        assert controller.checkpoint_written.wait(5), "fake agent did not write in-run checkpoint"

        during = client.get(f"/api/threads/{thread_id}/state")
        assert during.status_code == 200, during.text
        assert during.json()["values"]["title"] == "During rollback run"

        rolled_back = client.post(
            f"/api/threads/{thread_id}/runs/{run_id}/cancel?wait=true&action=rollback",
            headers={"X-CSRF-Token": csrf_token},
        )
        assert rolled_back.status_code == 204, rolled_back.text
        assert controller.cancelled.wait(5), "rollback did not cancel the worker task"

        run = _wait_for_status(client, thread_id, run_id, "error")
        assert run["status"] == "error"

        after = client.get(f"/api/threads/{thread_id}/state")
        assert after.status_code == 200, after.text
        assert after.json()["values"]["title"] == "Before rollback"
        assert after.json()["values"]["messages"] == [{"type": "human", "content": "before"}]
