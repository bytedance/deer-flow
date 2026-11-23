"""Worker spans follow the admitted or checkpoint-selected OpenTelemetry parent."""

from __future__ import annotations

import asyncio

import pytest

from deerflow.runtime.runs.manager import RunRecord, RunStartOutcome
from deerflow.runtime.runs.schemas import DisconnectMode, RunStatus
from deerflow.runtime.runs.worker import RunContext, run_agent


class _FakeAgent:
    def __init__(self) -> None:
        self.captured_config: dict | None = None
        self.metadata: dict = {}
        self.checkpointer = None
        self.store = None
        self.interrupt_before_nodes: list[str] = []
        self.interrupt_after_nodes: list[str] = []

    async def astream(self, graph_input, *, config, stream_mode, **kwargs):
        self.captured_config = config
        return
        yield  # pragma: no cover (makes this an async generator)


class _FakeRunManager:
    async def try_start(self, _run_id: str) -> RunStartOutcome:
        return RunStartOutcome.started

    async def wait_for_prior_finalizing(self, *_args, **_kwargs) -> None:
        return None

    async def has_later_run(self, *_args, **_kwargs) -> bool:
        return False

    async def has_later_started_run(self, *_args, **_kwargs) -> bool:
        return False

    async def set_status(self, *_args, **_kwargs) -> None:
        return None

    async def set_status_if_not_cancelled(self, *_args, **_kwargs) -> None:
        return None

    async def update_model_name(self, *_args, **_kwargs) -> None:
        return None

    async def update_run_completion(self, *_args, **_kwargs) -> None:
        return None

    async def cleanup(self, *_args, **_kwargs) -> None:
        return None


class _FakeBridge:
    async def publish(self, _run_id, event, payload) -> None:
        return None

    async def publish_end(self, _run_id) -> None:
        return None

    async def cleanup(self, _run_id, *, delay: int = 0) -> None:
        return None


async def _run(config: dict, *, kwargs: dict | None = None, resume: bool = False, checkpointer=None, run_manager=None) -> dict:
    """Drive ``run_agent`` once and return the config the graph received."""
    fake_agent = _FakeAgent()
    record = RunRecord(
        run_id="run-trace-binding",
        thread_id="thread-trace-binding",
        assistant_id="lead-agent",
        status=RunStatus.pending,
        on_disconnect=DisconnectMode.cancel,
        kwargs=kwargs or {},
    )
    record.abort_event = asyncio.Event()

    await run_agent(
        _FakeBridge(),
        run_manager or _FakeRunManager(),
        record,
        ctx=RunContext(checkpointer=checkpointer),
        agent_factory=lambda **_kwargs: fake_agent,
        graph_input=None if resume else {"messages": []},
        config=config,
    )
    assert fake_agent.captured_config is not None
    return fake_agent.captured_config


@pytest.fixture
def span_exporter(monkeypatch):
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(trace, "get_tracer", provider.get_tracer)
    yield exporter
    provider.shutdown()


@pytest.mark.asyncio
async def test_worker_span_continues_the_admitted_parent_and_stamps_checkpoint(span_exporter):
    from opentelemetry import trace

    parent = "00-11111111111111111111111111111111-2222222222222222-01"
    captured = await _run(
        {"configurable": {"thread_id": "thread-trace-binding"}},
        kwargs={"deerflow_traceparent": parent},
    )
    [span] = span_exporter.get_finished_spans()

    assert span.name == "deerflow.run"
    assert span.parent is not None
    assert span.parent.span_id == 0x2222222222222222
    assert span.context.trace_id == 0x11111111111111111111111111111111
    assert span.attributes["deerflow.run.id"] == "run-trace-binding"
    assert captured["metadata"]["deerflow_traceparent"] == f"00-{span.context.trace_id:032x}-{span.context.span_id:016x}-01"
    assert not trace.get_current_span().get_span_context().is_valid


@pytest.mark.asyncio
@pytest.mark.parametrize("use_checkpoint_map", [False, True])
@pytest.mark.parametrize(
    ("source_thread", "source_user"),
    [("thread-trace-binding", None), ("thread-trace-binding", "another-user"), ("other-thread", None), (None, None)],
)
async def test_resume_uses_only_the_selected_checkpoint_and_its_owner_bound_run(span_exporter, source_thread, source_user, use_checkpoint_map):
    from unittest.mock import AsyncMock

    from langgraph.checkpoint.base import empty_checkpoint
    from langgraph.checkpoint.memory import InMemorySaver

    checkpointer = InMemorySaver()
    selected = empty_checkpoint()
    read_config = {"configurable": {"thread_id": "thread-trace-binding", "checkpoint_ns": ""}}
    forged = "00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01"
    await checkpointer.aput(read_config, selected, {"deerflow_trace_run_id": "previous-run", "deerflow_traceparent": forged}, {})
    latest = empty_checkpoint()
    await checkpointer.aput(read_config, latest, {"deerflow_trace_run_id": "later-run"}, {})
    selector = {"checkpoint_id": latest["id"], "checkpoint_map": {"": selected["id"]}} if use_checkpoint_map else {"checkpoint_id": selected["id"]}
    manager = _FakeRunManager()
    source = RunRecord(
        run_id="previous-run",
        thread_id=source_thread or "thread-trace-binding",
        user_id=source_user,
        assistant_id="lead-agent",
        status=RunStatus.interrupted,
        on_disconnect=DisconnectMode.cancel,
        kwargs={"deerflow_traceparent": "00-11111111111111111111111111111111-2222222222222222-01"},
    )
    manager.get = AsyncMock(return_value=source if source_thread else None)

    captured = await _run(
        {"configurable": {**read_config["configurable"], **selector}},
        resume=True,
        checkpointer=checkpointer,
        run_manager=manager,
    )

    manager.get.assert_awaited_once_with("previous-run", user_id=None)
    [span] = span_exporter.get_finished_spans()
    if source_thread == "thread-trace-binding" and source_user is None:
        assert span.parent is not None and span.parent.span_id == 0x2222222222222222
        assert span.context.trace_id == 0x11111111111111111111111111111111
        assert captured["metadata"]["deerflow_trace_run_id"] == source.run_id
    else:
        assert span.parent is None
        assert "deerflow_trace_run_id" not in captured["metadata"]


@pytest.mark.asyncio
async def test_broken_span_does_not_change_worker_outcome(monkeypatch, caplog):
    from types import SimpleNamespace

    from opentelemetry import trace

    class BrokenSpan(trace.NonRecordingSpan):
        def set_attribute(self, key, value):
            raise RuntimeError("annotation failed")

        def end(self, end_time=None):
            raise RuntimeError("export failed")

    tracer = SimpleNamespace(start_span=lambda *_args, **_kwargs: BrokenSpan(trace.INVALID_SPAN_CONTEXT))
    monkeypatch.setattr(trace, "get_tracer", lambda *_args, **_kwargs: tracer)

    await _run({"configurable": {"thread_id": "thread-trace-binding"}})

    assert "Could not annotate execution span" in caplog.text
    assert "Could not finish deerflow.run span" in caplog.text
