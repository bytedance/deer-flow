"""``run_agent`` stamps the request trace id onto everything it hands the graph.

The trace ContextVar is the only source. These tests pin the other half of
that contract: a ``deerflow_trace_id`` arriving on the run request is a
caller's echo of a past output, not an input, and must not survive into the
runtime context, the run metadata, or the checkpoint. Otherwise a client can
make the most durable surfaces of a run disagree with the ``X-Trace-Id`` and
the log lines the same request produced.
"""

from __future__ import annotations

import asyncio

import pytest

from deerflow.runtime.runs.manager import RunRecord, RunStartOutcome
from deerflow.runtime.runs.schemas import DisconnectMode, RunStatus
from deerflow.runtime.runs.worker import RunContext, _build_runtime_context, run_agent
from deerflow.trace_context import DEERFLOW_TRACE_METADATA_KEY, get_current_trace_id, request_trace_context


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


async def _run(config: dict) -> dict:
    """Drive ``run_agent`` once and return the config the graph received."""
    fake_agent = _FakeAgent()
    record = RunRecord(
        run_id="run-trace-binding",
        thread_id="thread-trace-binding",
        assistant_id="lead-agent",
        status=RunStatus.pending,
        on_disconnect=DisconnectMode.cancel,
    )
    record.abort_event = asyncio.Event()

    await run_agent(
        _FakeBridge(),
        _FakeRunManager(),
        record,
        ctx=RunContext(checkpointer=None),
        agent_factory=lambda **_kwargs: fake_agent,
        graph_input={"messages": []},
        config=config,
    )
    assert fake_agent.captured_config is not None
    return fake_agent.captured_config


@pytest.mark.asyncio
async def test_runtime_context_and_metadata_carry_the_bound_trace_id():
    """Both destinations get the same id: the runtime context carries it across
    boundaries the ContextVar does not cross, the metadata persists with the
    checkpoint."""
    with request_trace_context("gateway-issued"):
        captured = await _run({"configurable": {"thread_id": "thread-trace-binding"}})

    assert captured["context"][DEERFLOW_TRACE_METADATA_KEY] == "gateway-issued"
    assert captured["metadata"][DEERFLOW_TRACE_METADATA_KEY] == "gateway-issued"


@pytest.mark.asyncio
async def test_caller_supplied_metadata_trace_id_is_overwritten():
    with request_trace_context("gateway-issued"):
        captured = await _run(
            {
                "configurable": {"thread_id": "thread-trace-binding"},
                "metadata": {DEERFLOW_TRACE_METADATA_KEY: "forged", "caller_key": "kept"},
            }
        )

    assert captured["metadata"][DEERFLOW_TRACE_METADATA_KEY] == "gateway-issued"
    # Only the server-owned key is replaced.
    assert captured["metadata"]["caller_key"] == "kept"


@pytest.mark.asyncio
async def test_caller_supplied_context_trace_id_is_overwritten():
    """``config['context']`` is a second, separate way in. The Gateway filters
    ``__``-prefixed keys out of it, but ``deerflow_trace_id`` carries no prefix
    and embedded harness callers pass through no such filter at all."""
    with request_trace_context("gateway-issued"):
        captured = await _run(
            {
                "configurable": {"thread_id": "thread-trace-binding"},
                "context": {DEERFLOW_TRACE_METADATA_KEY: "forged", "agent_name": "kept"},
            }
        )

    assert captured["context"][DEERFLOW_TRACE_METADATA_KEY] == "gateway-issued"
    assert captured["context"]["agent_name"] == "kept"


@pytest.mark.asyncio
async def test_both_forks_agree_when_the_caller_forges_both():
    """The failure this rules out is disagreement, not any single wrong value."""
    with request_trace_context("gateway-issued"):
        captured = await _run(
            {
                "configurable": {"thread_id": "thread-trace-binding"},
                "metadata": {DEERFLOW_TRACE_METADATA_KEY: "forged-metadata"},
                "context": {DEERFLOW_TRACE_METADATA_KEY: "forged-context"},
            }
        )

    assert captured["metadata"][DEERFLOW_TRACE_METADATA_KEY] == captured["context"][DEERFLOW_TRACE_METADATA_KEY] == "gateway-issued"


@pytest.mark.asyncio
async def test_run_without_an_ambient_trace_still_gets_one():
    """A run reached outside any entry point -- a standalone harness caller --
    is still correlatable rather than falling back to an absent id."""
    assert get_current_trace_id() is None

    captured = await _run({"configurable": {"thread_id": "thread-trace-binding"}})

    assert captured["metadata"][DEERFLOW_TRACE_METADATA_KEY]
    assert captured["context"][DEERFLOW_TRACE_METADATA_KEY] == captured["metadata"][DEERFLOW_TRACE_METADATA_KEY]


def test_build_runtime_context_drops_a_caller_supplied_trace_id():
    """Pinned on the builder itself, not through ``run_agent``.

    ``_bind_trace_id`` overwrites the key immediately afterwards, so at the one
    current call site this guard is masked. It is the builder's own contract
    that server-owned keys never come from the caller, and a second call site
    added later must inherit that without having to remember the ordering.
    """
    runtime_ctx = _build_runtime_context(
        "thread-1",
        "run-1",
        {DEERFLOW_TRACE_METADATA_KEY: "forged", "agent_name": "kept"},
    )

    assert DEERFLOW_TRACE_METADATA_KEY not in runtime_ctx
    assert runtime_ctx["agent_name"] == "kept"
