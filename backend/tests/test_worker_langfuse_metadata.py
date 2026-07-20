"""Integration test: worker.run_agent injects Langfuse trace metadata.

Verifies that the agent factory's resulting graph receives a
``RunnableConfig`` whose ``metadata`` carries the Langfuse reserved keys
(``langfuse_session_id`` / ``langfuse_user_id`` / ``langfuse_trace_name``).
"""

from __future__ import annotations

import asyncio

import pytest

from deerflow.runtime.runs.manager import RunRecord
from deerflow.runtime.runs.schemas import DisconnectMode, RunStatus
from deerflow.runtime.runs.worker import RunContext, run_agent
from deerflow.trace_context import (
    DEERFLOW_TRACE_METADATA_KEY,
    mark_trace_id_from_request_header,
    request_trace_context,
    reset_trace_id_from_request_header,
)


class _FakeAgent:
    """Minimal LangGraph-like graph that captures the runnable config."""

    def __init__(self) -> None:
        self.captured_config: dict | None = None
        self.metadata: dict = {}
        # Worker may assign these attributes; need them to exist.
        self.checkpointer = None
        self.store = None
        self.interrupt_before_nodes: list[str] = []
        self.interrupt_after_nodes: list[str] = []

    async def astream(self, graph_input, *, config, stream_mode, **kwargs):
        self.captured_config = config
        # Empty async generator — no chunks produced.
        return
        yield  # pragma: no cover (makes this an async generator)


class _FakeRunManager:
    async def wait_for_prior_finalizing(self, *_args, **_kwargs) -> None:
        return None

    async def has_later_run(self, *_args, **_kwargs) -> bool:
        return False

    async def has_later_started_run(self, *_args, **_kwargs) -> bool:
        return False

    async def set_status(self, *_args, **_kwargs) -> None:
        return None

    async def update_model_name(self, *_args, **_kwargs) -> None:
        return None

    async def update_run_completion(self, *_args, **_kwargs) -> None:
        return None


class _FakeBridge:
    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []

    async def publish(self, _run_id, event, payload) -> None:
        self.events.append((event, payload))

    async def publish_end(self, _run_id) -> None:
        self.events.append(("end", None))

    async def cleanup(self, _run_id, *, delay: int = 0) -> None:
        return None


@pytest.fixture(autouse=True)
def _clear_tracing_env(monkeypatch):
    from deerflow.config.tracing_config import reset_tracing_config

    for name in ("LANGFUSE_TRACING", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    reset_tracing_config()
    yield
    reset_tracing_config()


@pytest.mark.asyncio
async def test_run_agent_injects_langfuse_metadata(monkeypatch):
    monkeypatch.setenv("LANGFUSE_TRACING", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    from deerflow.config.tracing_config import reset_tracing_config

    reset_tracing_config()

    fake_agent = _FakeAgent()

    def agent_factory(config):
        return fake_agent

    record = RunRecord(
        run_id="run-1",
        thread_id="thread-xyz",
        assistant_id="lead-agent",
        status=RunStatus.pending,
        on_disconnect=DisconnectMode.cancel,
        model_name="gpt-4o",
    )
    record.abort_event = asyncio.Event()
    ctx = RunContext(checkpointer=None)

    with request_trace_context("gateway-trace-1"):
        await run_agent(
            _FakeBridge(),
            _FakeRunManager(),
            record,
            ctx=ctx,
            agent_factory=agent_factory,
            graph_input={"messages": []},
            config={"configurable": {"thread_id": "thread-xyz"}},
        )

    assert fake_agent.captured_config is not None, "astream was not invoked"
    metadata = fake_agent.captured_config.get("metadata") or {}
    assert metadata.get("langfuse_session_id") == "thread-xyz"
    # conftest.py autouse fixture injects ``test-user-autouse`` into the
    # contextvar — the worker should read it via ``get_effective_user_id``.
    user_id = metadata.get("langfuse_user_id")
    assert user_id == "test-user-autouse", f"expected test-user-autouse, got {user_id}"
    assert metadata.get("langfuse_trace_name") == "lead-agent"
    assert metadata.get(DEERFLOW_TRACE_METADATA_KEY) == "gateway-trace-1"
    assert fake_agent.captured_config.get("context", {}).get(DEERFLOW_TRACE_METADATA_KEY) == "gateway-trace-1"
    tags = metadata.get("langfuse_tags") or []
    assert "model:gpt-4o" in tags


@pytest.mark.asyncio
async def test_run_agent_uses_context_user_id_over_contextvar(monkeypatch):
    """A run carrying ``context.user_id`` traces to that user, not the contextvar.

    Internal-token callers invoke a run on behalf of an end user, so the
    ``_current_user`` ContextVar is never that end user. The caller instead
    carries the real owner in the run request's ``config['context']['user_id']``,
    which ``resolve_runtime_user_id(runtime)`` must prefer over the contextvar —
    even though conftest's autouse fixture injects ``test-user-autouse`` into it.
    """
    monkeypatch.setenv("LANGFUSE_TRACING", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    from deerflow.config.tracing_config import reset_tracing_config

    reset_tracing_config()

    fake_agent = _FakeAgent()

    def agent_factory(config):
        return fake_agent

    record = RunRecord(
        run_id="run-ctx-user",
        thread_id="thread-ctx",
        assistant_id="lead-agent",
        status=RunStatus.pending,
        on_disconnect=DisconnectMode.cancel,
    )
    record.abort_event = asyncio.Event()
    ctx = RunContext(checkpointer=None)

    await run_agent(
        _FakeBridge(),
        _FakeRunManager(),
        record,
        ctx=ctx,
        agent_factory=agent_factory,
        graph_input={"messages": []},
        config={
            "configurable": {"thread_id": "thread-ctx"},
            "context": {"user_id": "real-end-user"},
        },
    )

    metadata = fake_agent.captured_config.get("metadata") or {}
    # context.user_id wins over the contextvar's ``test-user-autouse``.
    assert metadata.get("langfuse_user_id") == "real-end-user"


@pytest.mark.asyncio
async def test_run_agent_falls_back_to_default_user_when_unset(monkeypatch):
    """When no user is in the contextvar (and no context.user_id), langfuse_user_id
    falls back to 'default'.

    Uses ``monkeypatch.setattr`` to redirect ``get_effective_user_id`` to return
    ``"default"`` rather than directly mutating the contextvar — direct contextvar
    operations across pytest test boundaries have produced spooky cross-file
    pollution when combined with the langfuse OTel global tracer provider.

    The worker resolves the trace user via ``resolve_runtime_user_id(runtime)``;
    with no ``context.user_id`` it falls back to ``get_effective_user_id()`` — so
    we patch that fallback at its definition module (``user_context``), which is
    the name ``resolve_runtime_user_id`` actually calls.
    """
    monkeypatch.setenv("LANGFUSE_TRACING", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    from deerflow.config.tracing_config import reset_tracing_config
    from deerflow.runtime import user_context as user_context_module
    from deerflow.runtime.user_context import DEFAULT_USER_ID

    reset_tracing_config()
    monkeypatch.setattr(user_context_module, "get_effective_user_id", lambda: DEFAULT_USER_ID)

    fake_agent = _FakeAgent()

    def agent_factory(config):
        return fake_agent

    record = RunRecord(
        run_id="run-fallback",
        thread_id="thread-fb",
        assistant_id="lead-agent",
        status=RunStatus.pending,
        on_disconnect=DisconnectMode.cancel,
    )
    record.abort_event = asyncio.Event()
    ctx = RunContext(checkpointer=None)

    await run_agent(
        _FakeBridge(),
        _FakeRunManager(),
        record,
        ctx=ctx,
        agent_factory=agent_factory,
        graph_input={"messages": []},
        config={"configurable": {"thread_id": "thread-fb"}},
    )

    metadata = fake_agent.captured_config.get("metadata") or {}
    assert metadata.get("langfuse_user_id") == "default"


@pytest.mark.asyncio
async def test_run_agent_preserves_caller_metadata_overrides(monkeypatch):
    """Caller-provided langfuse_* keys must NOT be overridden by the default injection."""
    monkeypatch.setenv("LANGFUSE_TRACING", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    from deerflow.config.tracing_config import reset_tracing_config

    reset_tracing_config()

    fake_agent = _FakeAgent()

    def agent_factory(config):
        return fake_agent

    record = RunRecord(
        run_id="run-2",
        thread_id="thread-default",
        assistant_id="lead-agent",
        status=RunStatus.pending,
        on_disconnect=DisconnectMode.cancel,
    )
    record.abort_event = asyncio.Event()
    ctx = RunContext(checkpointer=None)

    await run_agent(
        _FakeBridge(),
        _FakeRunManager(),
        record,
        ctx=ctx,
        agent_factory=agent_factory,
        graph_input={"messages": []},
        config={
            "configurable": {"thread_id": "thread-default"},
            "metadata": {
                DEERFLOW_TRACE_METADATA_KEY: "explicit-deerflow-trace",
                "langfuse_session_id": "custom-session-id",
                "langfuse_user_id": "explicit-user",
            },
        },
    )

    metadata = fake_agent.captured_config.get("metadata") or {}
    # Caller-supplied keys win.
    assert metadata["langfuse_session_id"] == "custom-session-id"
    assert metadata["langfuse_user_id"] == "explicit-user"
    assert metadata[DEERFLOW_TRACE_METADATA_KEY] == "explicit-deerflow-trace"
    assert fake_agent.captured_config.get("context", {}).get(DEERFLOW_TRACE_METADATA_KEY) == "explicit-deerflow-trace"
    # Worker still fills in keys that the caller didn't set.
    assert metadata["langfuse_trace_name"] == "lead-agent"


@pytest.mark.asyncio
async def test_run_agent_inbound_header_trace_overrides_metadata(monkeypatch):
    """A valid inbound ``X-Trace-Id`` wins over ``config.metadata.deerflow_trace_id``."""
    monkeypatch.setenv("LANGFUSE_TRACING", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    from deerflow.config.tracing_config import reset_tracing_config

    reset_tracing_config()

    fake_agent = _FakeAgent()

    def agent_factory(config):
        return fake_agent

    record = RunRecord(
        run_id="run-header-override",
        thread_id="thread-header",
        assistant_id="lead-agent",
        status=RunStatus.pending,
        on_disconnect=DisconnectMode.cancel,
    )
    record.abort_event = asyncio.Event()
    ctx = RunContext(checkpointer=None)

    with request_trace_context("header-trace-1"):
        header_token = mark_trace_id_from_request_header(from_header=True)
        try:
            await run_agent(
                _FakeBridge(),
                _FakeRunManager(),
                record,
                ctx=ctx,
                agent_factory=agent_factory,
                graph_input={"messages": []},
                config={
                    "configurable": {"thread_id": "thread-header"},
                    "metadata": {
                        DEERFLOW_TRACE_METADATA_KEY: "metadata-trace-ignored",
                    },
                },
            )
        finally:
            reset_trace_id_from_request_header(header_token)

    metadata = fake_agent.captured_config.get("metadata") or {}
    assert metadata[DEERFLOW_TRACE_METADATA_KEY] == "header-trace-1"
    assert fake_agent.captured_config.get("context", {}).get(DEERFLOW_TRACE_METADATA_KEY) == "header-trace-1"


@pytest.mark.asyncio
async def test_run_agent_skips_metadata_when_langfuse_disabled(monkeypatch):
    fake_agent = _FakeAgent()

    def agent_factory(config):
        return fake_agent

    record = RunRecord(
        run_id="run-3",
        thread_id="thread-noop",
        assistant_id="lead-agent",
        status=RunStatus.pending,
        on_disconnect=DisconnectMode.cancel,
    )
    record.abort_event = asyncio.Event()
    ctx = RunContext(checkpointer=None)

    await run_agent(
        _FakeBridge(),
        _FakeRunManager(),
        record,
        ctx=ctx,
        agent_factory=agent_factory,
        graph_input={"messages": []},
        config={"configurable": {"thread_id": "thread-noop"}},
    )

    metadata = fake_agent.captured_config.get("metadata") or {}
    assert "langfuse_session_id" not in metadata
    assert "langfuse_user_id" not in metadata
    assert "langfuse_trace_name" not in metadata
