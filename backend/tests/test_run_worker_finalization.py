"""Worker finalization wires terminal-record eviction into the RunManager.

Issue #5009 called out that the older ``RunManager.cleanup()`` tests did not
cover the normal worker-finalization path. This pins the replacement wiring:
after ``run_agent`` finishes a run, it must call ``RunManager.schedule_cleanup``
for that run id so store-backed managers evict the terminal record. Deleting or
relocating the ``run_manager.schedule_cleanup(run_id)`` call in ``worker.py``
fails this test.
"""

from __future__ import annotations

import asyncio

import pytest

from deerflow.runtime.runs.manager import RunRecord, RunStartOutcome
from deerflow.runtime.runs.schemas import DisconnectMode, RunStatus
from deerflow.runtime.runs.worker import RunContext, run_agent


class _FakeAgent:
    """Minimal LangGraph-like graph that completes without producing chunks."""

    def __init__(self) -> None:
        self.checkpointer = None
        self.store = None
        self.interrupt_before_nodes: list[str] = []
        self.interrupt_after_nodes: list[str] = []

    async def astream(self, graph_input, *, config, stream_mode, **kwargs):
        return
        yield  # pragma: no cover (makes this an async generator)


class _SpyRunManager:
    """Run manager stub that records ``schedule_cleanup`` invocations."""

    def __init__(self) -> None:
        self.cleanup_calls: list[tuple[str, dict]] = []

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
        await self.set_status(*_args, **_kwargs)
        return None

    async def update_model_name(self, *_args, **_kwargs) -> None:
        return None

    async def update_run_completion(self, *_args, **_kwargs) -> None:
        return None

    def schedule_cleanup(self, run_id: str, **kwargs):
        self.cleanup_calls.append((run_id, kwargs))
        return None


class _FakeBridge:
    async def publish(self, _run_id, event, payload) -> None:
        return None

    async def publish_end(self, _run_id) -> None:
        return None

    async def cleanup(self, _run_id, *, delay: int = 0) -> None:
        return None


@pytest.mark.asyncio
async def test_run_agent_finalization_schedules_eviction():
    """A completed run schedules terminal-record eviction on finalization."""
    run_manager = _SpyRunManager()
    record = RunRecord(
        run_id="run-finalize",
        thread_id="thread-finalize",
        assistant_id="lead-agent",
        status=RunStatus.pending,
        on_disconnect=DisconnectMode.cancel,
    )
    record.abort_event = asyncio.Event()
    ctx = RunContext(checkpointer=None)

    await run_agent(
        _FakeBridge(),
        run_manager,
        record,
        ctx=ctx,
        agent_factory=lambda config: _FakeAgent(),
        graph_input={"messages": []},
        config={"configurable": {"thread_id": "thread-finalize"}},
    )

    scheduled_ids = [run_id for run_id, _kwargs in run_manager.cleanup_calls]
    assert scheduled_ids == ["run-finalize"], f"run_agent finalization must schedule eviction for the run exactly once; got {run_manager.cleanup_calls!r}"
