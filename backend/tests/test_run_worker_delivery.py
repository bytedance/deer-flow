"""Worker-level regression tests for the terminal run.delivery event (#4272 slice 1)."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.types import Command

from deerflow.config.app_config import AppConfig
from deerflow.config.paths import Paths
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.config.tool_output_config import ToolOutputConfig
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.journal import RunJournal
from deerflow.runtime.runs.manager import RunManager
from deerflow.runtime.runs.schemas import RunStatus
from deerflow.runtime.runs.store.memory import MemoryRunStore
from deerflow.runtime.runs.worker import (
    _JOURNAL_UNSETTLED_ERROR,
    RunContext,
    _delivery_content_with_outputs,
    run_agent,
)
from deerflow.runtime.user_context import get_effective_user_id


def _make_bridge():
    return SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())


async def _delivery_events(store: MemoryRunEventStore, thread_id: str, run_id: str) -> list[dict]:
    events = await store.list_events(thread_id, run_id)
    return [e for e in events if e["event_type"] == "run.delivery"]


def test_delivery_verification_treats_presented_directory_as_covering_produced_files():
    content = {
        "presented": 1,
        "paths": ["/mnt/user-data/outputs/site"],
        "by_tool": {"present_files": ["/mnt/user-data/outputs/site"]},
    }

    delivery = _delivery_content_with_outputs(
        content,
        [
            "/mnt/user-data/outputs/site/index.html",
            "/mnt/user-data/outputs/site/assets/style.css",
        ],
    )

    assert delivery["matched_paths"] == [
        "/mnt/user-data/outputs/site/index.html",
        "/mnt/user-data/outputs/site/assets/style.css",
    ]
    assert delivery["satisfied"] is True


@pytest.mark.anyio
async def test_delivery_event_records_present_files_paths_on_success():
    run_manager = RunManager()
    record = await run_manager.create("thread-1")
    store = MemoryRunEventStore()

    class DummyAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            journal = config["context"]["__run_journal"]
            ai = AIMessage(content="", tool_calls=[{"id": "call_1", "name": "present_files", "args": {}}])
            journal._remember_current_run_tool_calls(ai, caller="lead_agent")
            journal.on_tool_end(
                Command(
                    update={
                        "artifacts": ["/mnt/user-data/outputs/report.md"],
                        "messages": [ToolMessage("Successfully presented files", tool_call_id="call_1")],
                    }
                ),
                run_id=uuid4(),
            )
            yield {"messages": []}

    await run_agent(
        _make_bridge(),
        run_manager,
        record,
        ctx=RunContext(checkpointer=None, event_store=store),
        agent_factory=lambda *, config: DummyAgent(),
        graph_input={},
        config={},
    )
    await asyncio.sleep(0)

    delivery = await _delivery_events(store, "thread-1", record.run_id)
    assert len(delivery) == 1
    assert delivery[0]["content"]["presented"] == 1
    assert delivery[0]["content"]["paths"] == ["/mnt/user-data/outputs/report.md"]
    assert delivery[0]["content"]["by_tool"] == {"present_files": ["/mnt/user-data/outputs/report.md"]}
    fetched = await run_manager.get(record.run_id)
    assert fetched.status == RunStatus.success


@pytest.mark.anyio
async def test_delivery_event_presented_zero_without_artifact_production():
    run_manager = RunManager()
    record = await run_manager.create("thread-1")
    store = MemoryRunEventStore()

    class DummyAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            yield {"messages": []}

    await run_agent(
        _make_bridge(),
        run_manager,
        record,
        ctx=RunContext(checkpointer=None, event_store=store),
        agent_factory=lambda *, config: DummyAgent(),
        graph_input={},
        config={},
    )
    await asyncio.sleep(0)

    delivery = await _delivery_events(store, "thread-1", record.run_id)
    assert len(delivery) == 1
    assert delivery[0]["content"] == {"presented": 0, "paths": [], "by_tool": {}}
    fetched = await run_manager.get(record.run_id)
    assert fetched.status == RunStatus.success


@pytest.mark.anyio
async def test_changed_outputs_succeed_when_a_produced_output_is_presented(monkeypatch):
    run_manager = RunManager()
    record = await run_manager.create("thread-1")
    store = MemoryRunEventStore()
    monkeypatch.setattr(
        "deerflow.runtime.runs.worker._produced_output_paths",
        AsyncMock(return_value=["/mnt/user-data/outputs/report.md"]),
    )

    class DummyAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            journal = config["context"]["__run_journal"]
            ai = AIMessage(content="", tool_calls=[{"id": "call_1", "name": "present_files", "args": {}}])
            journal._remember_current_run_tool_calls(ai, caller="lead_agent")
            journal.on_tool_end(
                Command(
                    update={
                        "artifacts": ["/mnt/user-data/outputs/report.md"],
                        "messages": [ToolMessage("Successfully presented files", tool_call_id="call_1")],
                    }
                ),
                run_id=uuid4(),
            )
            yield {"messages": []}

    await run_agent(
        _make_bridge(),
        run_manager,
        record,
        ctx=RunContext(checkpointer=None, event_store=store),
        agent_factory=lambda *, config: DummyAgent(),
        graph_input={},
        config={},
    )

    delivery = await _delivery_events(store, "thread-1", record.run_id)
    assert delivery[0]["content"] == {
        "presented": 1,
        "paths": ["/mnt/user-data/outputs/report.md"],
        "by_tool": {"present_files": ["/mnt/user-data/outputs/report.md"]},
        "verification": {
            "source": "outputs_changed",
            "requirement": "present_files_matches_produced_output",
        },
        "produced_paths": ["/mnt/user-data/outputs/report.md"],
        "presented_paths": ["/mnt/user-data/outputs/report.md"],
        "matched_paths": ["/mnt/user-data/outputs/report.md"],
        "stage": "presented",
        "satisfied": True,
    }
    assert record.status == RunStatus.success


@pytest.mark.anyio
async def test_changed_outputs_fail_closed_when_not_presented(monkeypatch):
    run_manager = RunManager()
    record = await run_manager.create("thread-1")
    store = MemoryRunEventStore()
    monkeypatch.setattr(
        "deerflow.runtime.runs.worker._produced_output_paths",
        AsyncMock(return_value=["/mnt/user-data/outputs/report.md"]),
    )

    class ProseOnlyAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            yield {"messages": [AIMessage(content="SESSION SUMMARY")]}

    await run_agent(
        _make_bridge(),
        run_manager,
        record,
        ctx=RunContext(checkpointer=None, event_store=store),
        agent_factory=lambda *, config: ProseOnlyAgent(),
        graph_input={},
        config={},
    )

    delivery = await _delivery_events(store, "thread-1", record.run_id)
    assert delivery[0]["content"] == {
        "presented": 0,
        "paths": [],
        "by_tool": {},
        "verification": {
            "source": "outputs_changed",
            "requirement": "present_files_matches_produced_output",
        },
        "produced_paths": ["/mnt/user-data/outputs/report.md"],
        "presented_paths": [],
        "matched_paths": [],
        "stage": "not_started",
        "satisfied": False,
    }
    assert record.status == RunStatus.error
    assert record.error == "Artifact delivery incomplete: no produced output artifact was presented"
    assert record.stop_reason is None


@pytest.mark.anyio
async def test_externalized_tool_results_do_not_trigger_delivery_verification(tmp_path, monkeypatch):
    """Oversized tool outputs externalized under outputs/.tool-results/ are
    process feedback for the model, not deliverables: a run that only produced
    those files must succeed without any present_files call."""
    paths = Paths(base_dir=tmp_path)
    monkeypatch.setattr("deerflow.workspace_changes.recorder.get_paths", lambda: paths)
    run_manager = RunManager()
    record = await run_manager.create("thread-1")
    store = MemoryRunEventStore()

    class ExternalizingAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            # Simulates ToolOutputBudgetMiddleware persisting an oversized tool
            # output mid-run (default storage_subdir is ".tool-results").
            tool_results = paths.sandbox_outputs_dir("thread-1", user_id=get_effective_user_id()) / ".tool-results"
            tool_results.mkdir(parents=True, exist_ok=True)
            (tool_results / "bash-abcdef123456.log").write_text("x" * 20000, encoding="utf-8")
            yield {"messages": [AIMessage(content="Here is the answer.")]}

    await run_agent(
        _make_bridge(),
        run_manager,
        record,
        ctx=RunContext(checkpointer=None, event_store=store),
        agent_factory=lambda *, config: ExternalizingAgent(),
        graph_input={},
        config={},
    )

    delivery = await _delivery_events(store, "thread-1", record.run_id)
    assert len(delivery) == 1
    assert delivery[0]["content"] == {"presented": 0, "paths": [], "by_tool": {}}
    fetched = await run_manager.get(record.run_id)
    assert fetched.status == RunStatus.success


@pytest.mark.anyio
async def test_custom_tool_output_storage_subdir_does_not_trigger_delivery_verification(tmp_path, monkeypatch):
    """A custom tool_output.storage_subdir is honoured by the exclusion, not
    only the default .tool-results name."""
    paths = Paths(base_dir=tmp_path)
    monkeypatch.setattr("deerflow.workspace_changes.recorder.get_paths", lambda: paths)
    run_manager = RunManager()
    record = await run_manager.create("thread-1")
    store = MemoryRunEventStore()
    app_config = AppConfig(sandbox=SandboxConfig(use="test"), tool_output=ToolOutputConfig(storage_subdir="tool-output-cache"))

    class ExternalizingAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            cache = paths.sandbox_outputs_dir("thread-1", user_id=get_effective_user_id()) / "tool-output-cache"
            cache.mkdir(parents=True, exist_ok=True)
            (cache / "web_fetch-abcdef123456.log").write_text("y" * 20000, encoding="utf-8")
            yield {"messages": [AIMessage(content="Here is the answer.")]}

    await run_agent(
        _make_bridge(),
        run_manager,
        record,
        ctx=RunContext(checkpointer=None, event_store=store, app_config=app_config),
        agent_factory=lambda *, config: ExternalizingAgent(),
        graph_input={},
        config={},
    )

    fetched = await run_manager.get(record.run_id)
    assert fetched.status == RunStatus.success


@pytest.mark.anyio
async def test_changed_outputs_succeed_when_one_of_multiple_outputs_is_presented(monkeypatch):
    run_manager = RunManager()
    record = await run_manager.create("thread-1")
    store = MemoryRunEventStore()
    monkeypatch.setattr(
        "deerflow.runtime.runs.worker._produced_output_paths",
        AsyncMock(
            return_value=[
                "/mnt/user-data/outputs/report.md",
                "/mnt/user-data/outputs/appendix.md",
            ]
        ),
    )

    class PartiallyPresentingAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            journal = config["context"]["__run_journal"]
            journal._remember_current_run_tool_calls(
                AIMessage(content="", tool_calls=[{"id": "call_1", "name": "present_files", "args": {}}]),
                caller="lead_agent",
            )
            journal.on_tool_end(
                Command(
                    update={
                        "artifacts": ["/mnt/user-data/outputs/report.md"],
                        "messages": [ToolMessage("Successfully presented files", tool_call_id="call_1")],
                    }
                ),
                run_id=uuid4(),
            )
            yield {"messages": []}

    await run_agent(
        _make_bridge(),
        run_manager,
        record,
        ctx=RunContext(checkpointer=None, event_store=store),
        agent_factory=lambda *, config: PartiallyPresentingAgent(),
        graph_input={},
        config={},
    )

    delivery = (await _delivery_events(store, "thread-1", record.run_id))[0]["content"]
    assert delivery["stage"] == "presented"
    assert delivery["presented_paths"] == ["/mnt/user-data/outputs/report.md"]
    assert delivery["matched_paths"] == ["/mnt/user-data/outputs/report.md"]
    assert delivery["satisfied"] is True
    assert record.status == RunStatus.success


@pytest.mark.anyio
async def test_changed_outputs_fail_when_present_files_only_presents_an_unrelated_file(monkeypatch):
    run_manager = RunManager()
    record = await run_manager.create("thread-1")
    store = MemoryRunEventStore()
    monkeypatch.setattr(
        "deerflow.runtime.runs.worker._produced_output_paths",
        AsyncMock(return_value=["/mnt/user-data/outputs/report.md"]),
    )

    class UnrelatedPresentingAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            journal = config["context"]["__run_journal"]
            journal._remember_current_run_tool_calls(
                AIMessage(content="", tool_calls=[{"id": "call_1", "name": "present_files", "args": {}}]),
                caller="lead_agent",
            )
            journal.on_tool_end(
                Command(
                    update={
                        "artifacts": ["/mnt/user-data/outputs/old-report.md"],
                        "messages": [ToolMessage("Successfully presented files", tool_call_id="call_1")],
                    }
                ),
                run_id=uuid4(),
            )
            yield {"messages": []}

    await run_agent(
        _make_bridge(),
        run_manager,
        record,
        ctx=RunContext(checkpointer=None, event_store=store),
        agent_factory=lambda *, config: UnrelatedPresentingAgent(),
        graph_input={},
        config={},
    )

    delivery = (await _delivery_events(store, "thread-1", record.run_id))[0]["content"]
    assert delivery["stage"] == "mismatched"
    assert delivery["presented_paths"] == ["/mnt/user-data/outputs/old-report.md"]
    assert delivery["matched_paths"] == []
    assert delivery["satisfied"] is False
    assert record.status == RunStatus.error


@pytest.mark.anyio
async def test_fenced_worker_leaves_delivery_receipt_to_peer_recovery():
    """A stale worker must not finalize the singleton delivery receipt."""
    run_manager = RunManager()
    record = await run_manager.create("thread-lease-lost")
    record.ownership_lost = True
    record.abort_event.set()
    record.status = RunStatus.error
    event_store = MemoryRunEventStore()
    thread_store = SimpleNamespace(
        update_display_name=AsyncMock(),
        update_status=AsyncMock(),
    )
    on_run_completed = AsyncMock()
    agent_factory = MagicMock(side_effect=AssertionError("fenced worker started the agent"))

    await run_agent(
        _make_bridge(),
        run_manager,
        record,
        ctx=RunContext(
            checkpointer=None,
            event_store=event_store,
            thread_store=thread_store,
            on_run_completed=on_run_completed,
        ),
        agent_factory=agent_factory,
        graph_input={},
        config={},
    )

    assert await _delivery_events(event_store, record.thread_id, record.run_id) == []
    agent_factory.assert_not_called()
    thread_store.update_display_name.assert_not_awaited()
    thread_store.update_status.assert_not_awaited()
    on_run_completed.assert_not_awaited()


@pytest.mark.anyio
async def test_delivery_event_is_singleton_across_goal_continuations(monkeypatch):
    run_manager = RunManager()
    record = await run_manager.create("thread-1")
    store = MemoryRunEventStore()
    stream_calls = 0
    continuation_calls = 0

    class ContinuingAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            nonlocal stream_calls
            stream_calls += 1
            journal = config["context"]["__run_journal"]
            tool_call_id = f"call_{stream_calls}"
            journal._remember_current_run_tool_calls(
                AIMessage(content="", tool_calls=[{"id": tool_call_id, "name": "present_files", "args": {}}]),
                caller="lead_agent",
            )
            artifacts = ["/mnt/user-data/outputs/report.md"]
            if stream_calls == 2:
                artifacts.append("/mnt/user-data/outputs/appendix.md")
            journal.on_tool_end(
                Command(
                    update={
                        "artifacts": artifacts,
                        "messages": [ToolMessage("Successfully presented files", tool_call_id=tool_call_id)],
                    }
                ),
                run_id=uuid4(),
            )
            yield {"messages": []}

    async def prepare_continuation(**kwargs):
        nonlocal continuation_calls
        continuation_calls += 1
        if continuation_calls == 1:
            return {"messages": []}
        return None

    monkeypatch.setattr("deerflow.runtime.runs.worker._prepare_goal_continuation_input", prepare_continuation)

    await run_agent(
        _make_bridge(),
        run_manager,
        record,
        ctx=RunContext(checkpointer=None, event_store=store),
        agent_factory=lambda *, config: ContinuingAgent(),
        graph_input={},
        config={},
    )

    delivery = await _delivery_events(store, "thread-1", record.run_id)
    assert stream_calls == 2
    assert len(delivery) == 1
    assert delivery[0]["content"] == {
        "presented": 2,
        "paths": [
            "/mnt/user-data/outputs/report.md",
            "/mnt/user-data/outputs/appendix.md",
        ],
        "by_tool": {
            "present_files": [
                "/mnt/user-data/outputs/report.md",
                "/mnt/user-data/outputs/appendix.md",
            ]
        },
    }


@pytest.mark.anyio
async def test_delivery_event_emitted_exactly_once_on_error_path():
    run_manager = RunManager()
    record = await run_manager.create("thread-1")
    store = MemoryRunEventStore()

    class FailingAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            raise RuntimeError("boom")
            yield  # pragma: no cover - make this an async generator

    await run_agent(
        _make_bridge(),
        run_manager,
        record,
        ctx=RunContext(checkpointer=None, event_store=store),
        agent_factory=lambda *, config: FailingAgent(),
        graph_input={},
        config={},
    )
    await asyncio.sleep(0)

    delivery = await _delivery_events(store, "thread-1", record.run_id)
    assert len(delivery) == 1
    assert delivery[0]["content"]["presented"] == 0
    fetched = await run_manager.get(record.run_id)
    assert fetched.status == RunStatus.error


@pytest.mark.anyio
async def test_delivery_is_durable_before_terminal_run_status():
    events = MemoryRunEventStore()

    class OrderingRunStore(MemoryRunStore):
        async def update_status(self, run_id, status, *, error=None, stop_reason=None):
            if status not in {"pending", "running"}:
                receipt = await events.list_events("thread-1", run_id, event_types=["run.delivery"])
                assert len(receipt) == 1
            return await super().update_status(run_id, status, error=error, stop_reason=stop_reason)

    run_store = OrderingRunStore()
    run_manager = RunManager(store=run_store)
    record = await run_manager.create("thread-1")

    class DummyAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            yield {"messages": []}

    await run_agent(
        _make_bridge(),
        run_manager,
        record,
        ctx=RunContext(checkpointer=None, event_store=events),
        agent_factory=lambda *, config: DummyAgent(),
        graph_input={},
        config={},
    )

    assert (await run_store.get(record.run_id))["status"] == "success"


@pytest.mark.anyio
async def test_delivery_write_retries_before_persisting_success():
    class FlakyReceiptStore(MemoryRunEventStore):
        def __init__(self):
            super().__init__()
            self.attempts = 0

        async def put_if_absent(self, **kwargs):
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("transient event store outage")
            return await super().put_if_absent(**kwargs)

    event_store = FlakyReceiptStore()
    run_store = MemoryRunStore()
    run_manager = RunManager(store=run_store)
    record = await run_manager.create("thread-1")

    class DummyAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            yield {"messages": []}

    await run_agent(
        _make_bridge(),
        run_manager,
        record,
        ctx=RunContext(checkpointer=None, event_store=event_store),
        agent_factory=lambda *, config: DummyAgent(),
        graph_input={},
        config={},
    )

    assert event_store.attempts == 2
    assert len(await _delivery_events(event_store, "thread-1", record.run_id)) == 1
    assert (await run_store.get(record.run_id))["status"] == "success"


@pytest.mark.anyio
async def test_delivery_write_failure_preserves_real_durable_terminal_status():
    class FailingReceiptStore(MemoryRunEventStore):
        def __init__(self):
            super().__init__()
            self.attempts = 0

        async def put_if_absent(self, **kwargs):
            self.attempts += 1
            raise RuntimeError("event store unavailable")

    run_store = MemoryRunStore()
    run_manager = RunManager(store=run_store)
    record = await run_manager.create("thread-1")
    event_store = FailingReceiptStore()

    class DummyAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            yield {"messages": []}

    await run_agent(
        _make_bridge(),
        run_manager,
        record,
        ctx=RunContext(checkpointer=None, event_store=event_store),
        agent_factory=lambda *, config: DummyAgent(),
        graph_input={},
        config={},
    )

    # A receipt outage must not let lease recovery rewrite a genuine success
    # as an error. After bounded retries, preserve the worker's real outcome.
    assert event_store.attempts > 1
    assert record.status == RunStatus.success
    assert (await run_store.get(record.run_id))["status"] == "success"


@pytest.mark.anyio
async def test_produced_artifact_delivery_fails_closed_when_receipt_cannot_be_persisted(monkeypatch):
    class FailingReceiptStore(MemoryRunEventStore):
        async def put_if_absent(self, **kwargs):
            raise RuntimeError("event store unavailable")

    run_store = MemoryRunStore()
    run_manager = RunManager(store=run_store)
    record = await run_manager.create("thread-1")
    monkeypatch.setattr(
        "deerflow.runtime.runs.worker._produced_output_paths",
        AsyncMock(return_value=["/mnt/user-data/outputs/report.md"]),
    )

    class PresentingAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            journal = config["context"]["__run_journal"]
            journal._remember_current_run_tool_calls(
                AIMessage(content="", tool_calls=[{"id": "call_1", "name": "present_files", "args": {}}]),
                caller="lead_agent",
            )
            journal.on_tool_end(
                Command(
                    update={
                        "artifacts": ["/mnt/user-data/outputs/report.md"],
                        "messages": [ToolMessage("Successfully presented files", tool_call_id="call_1")],
                    }
                ),
                run_id=uuid4(),
            )
            yield {"messages": []}

    await run_agent(
        _make_bridge(),
        run_manager,
        record,
        ctx=RunContext(checkpointer=None, event_store=FailingReceiptStore()),
        agent_factory=lambda *, config: PresentingAgent(),
        graph_input={},
        config={},
    )

    assert record.status == RunStatus.error
    assert record.error == "Artifact delivery verification failed: terminal delivery receipt could not be persisted"
    assert (await run_store.get(record.run_id))["status"] == "error"


@pytest.mark.anyio
async def test_delivery_event_emitted_when_checkpoint_preflight_fails(monkeypatch):
    run_manager = RunManager()
    run_manager.update_run_completion = AsyncMock(wraps=run_manager.update_run_completion)
    record = await run_manager.create("thread-1")
    store = MemoryRunEventStore()
    compatibility_check = AsyncMock(side_effect=RuntimeError("incompatible checkpoint"))
    monkeypatch.setattr("deerflow.runtime.runs.worker.aensure_checkpoint_mode_compatible", compatibility_check)

    def unexpected_agent_factory(**kwargs):
        raise AssertionError("agent must not be built after preflight failure")

    await run_agent(
        _make_bridge(),
        run_manager,
        record,
        ctx=RunContext(checkpointer=object(), event_store=store),
        agent_factory=unexpected_agent_factory,
        graph_input={},
        config={},
    )

    delivery = await _delivery_events(store, "thread-1", record.run_id)
    assert len(delivery) == 1
    assert delivery[0]["content"] == {"presented": 0, "paths": [], "by_tool": {}}
    fetched = await run_manager.get(record.run_id)
    assert fetched.status == RunStatus.error
    run_manager.update_run_completion.assert_not_awaited()


@pytest.mark.anyio
async def test_delivery_event_emitted_when_cancelled_waiting_for_prior_finalization(monkeypatch):
    run_manager = RunManager()
    run_manager.update_run_completion = AsyncMock(wraps=run_manager.update_run_completion)
    record = await run_manager.create("thread-1")
    store = MemoryRunEventStore()
    monkeypatch.setattr(
        run_manager,
        "wait_for_prior_finalizing",
        AsyncMock(side_effect=asyncio.CancelledError()),
    )

    def unexpected_agent_factory(**kwargs):
        raise AssertionError("agent must not be built after preflight cancellation")

    await run_agent(
        _make_bridge(),
        run_manager,
        record,
        ctx=RunContext(checkpointer=None, event_store=store),
        agent_factory=unexpected_agent_factory,
        graph_input={},
        config={},
    )

    delivery = await _delivery_events(store, "thread-1", record.run_id)
    assert len(delivery) == 1
    assert delivery[0]["content"] == {"presented": 0, "paths": [], "by_tool": {}}
    fetched = await run_manager.get(record.run_id)
    assert fetched.status == RunStatus.interrupted
    run_manager.update_run_completion.assert_not_awaited()


class _BlockingJournalBatchStore(MemoryRunEventStore):
    """Journal event store whose first ``put_batch`` blocks until released.

    Batch A is the journal's first threshold-sized write; it stays in flight
    until the test releases it, so the worker's bounded ``flush()`` deadline
    expires with A unresolved and B still buffered behind it.
    """

    def __init__(self) -> None:
        super().__init__()
        self.batches: list[list[str]] = []
        self.batch_a_entered = asyncio.Event()
        self.release_batch_a = asyncio.Event()
        self.receipt_attempted = asyncio.Event()

    async def put_batch(self, events):
        self.batches.append([event["event_type"] for event in events])
        if len(self.batches) == 1:
            self.batch_a_entered.set()
            await self.release_batch_a.wait()
        return await super().put_batch(events)

    async def put_if_absent(self, **kwargs):
        self.receipt_attempted.set()
        return await super().put_if_absent(**kwargs)


@pytest.mark.anyio
async def test_terminal_receipt_waits_for_bounded_flush_to_settle(monkeypatch):
    """``flush() == False`` must settle the journal before the terminal receipt.

    The bounded flush only reports whether its deadline was met, so the receipt
    and the durable terminal row have to wait for the batch that missed it:
    otherwise the terminal run outlives journal events that must precede it.
    """
    # The bounded drain deadline is what the worker's barrier observes; shrink it
    # so the test does not wait the production timeout to reach the timeout case.
    monkeypatch.setattr("deerflow.runtime.journal._CANCELLATION_DRAIN_TIMEOUT_SECONDS", 0.05)
    event_store = _BlockingJournalBatchStore()

    bounded_flush_results: list[bool] = []
    bounded_flush_done = asyncio.Event()
    real_flush = RunJournal.flush

    async def spy_flush(journal):
        settled = await real_flush(journal)
        bounded_flush_results.append(settled)
        bounded_flush_done.set()
        return settled

    monkeypatch.setattr(RunJournal, "flush", spy_flush)

    class OrderingRunStore(MemoryRunStore):
        async def update_status(self, run_id, status, *, error=None, stop_reason=None):
            if status not in {"pending", "running"}:
                assert await event_store.list_events("thread-1", run_id, event_types=["run.delivery"]), "durable terminal status landed before the delivery receipt"
            return await super().update_status(run_id, status, error=error, stop_reason=stop_reason)

    run_store = OrderingRunStore()
    run_manager = RunManager(store=run_store)
    record = await run_manager.create("thread-1")

    class JournalingAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            journal = config["context"]["__run_journal"]
            # The default 20-event threshold makes A the first batch while the
            # remaining five events stay buffered as B.
            for index in range(25):
                journal._put(event_type=f"test.step.{index}", category="steps", content={"index": index})
            yield {"messages": []}

    task = asyncio.create_task(
        run_agent(
            _make_bridge(),
            run_manager,
            record,
            ctx=RunContext(checkpointer=None, event_store=event_store),
            agent_factory=lambda *, config: JournalingAgent(),
            graph_input={},
            config={},
        )
    )
    try:
        await asyncio.wait_for(event_store.batch_a_entered.wait(), timeout=2)
        await asyncio.wait_for(bounded_flush_done.wait(), timeout=2)
        assert bounded_flush_results == [False]
        assert event_store.batches == [[f"test.step.{index}" for index in range(20)]]

        # While A is unresolved the worker must not have attempted the receipt ...
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(event_store.receipt_attempted.wait()), timeout=0.2)
        assert not task.done()
        # ... and the durable row must not already claim the staged success.
        assert record.status == RunStatus.success
        assert (await run_store.get(record.run_id))["status"] == "running"
    finally:
        event_store.release_batch_a.set()
        await asyncio.wait_for(task, timeout=5)

    # Releasing A settled the journal: A, then the still-buffered B.
    assert [len(batch) for batch in event_store.batches] == [20, 5]
    events = await event_store.list_events("thread-1", record.run_id)
    journal_seqs = [event["seq"] for event in events if event["event_type"].startswith("test.step.")]
    receipt_seqs = [event["seq"] for event in events if event["event_type"] == "run.delivery"]
    assert len(journal_seqs) == 25
    assert len(receipt_seqs) == 1
    assert max(journal_seqs) < receipt_seqs[0]
    assert (await run_store.get(record.run_id))["status"] == "success"


@pytest.mark.anyio
async def test_cross_thread_middleware_accepted_before_producer_barrier_persists_before_receipt(monkeypatch):
    """A foreign-thread producer accepted before its barrier lands before the receipt.

    Characterization at this BASE: while the journal's first threshold batch A
    is still in flight, a subagent-style producer forwards a middleware event
    from another thread onto the journal owner loop. The callback is accepted
    and executed (B is buffered) before the producer publishes its ``aclose()``
    barrier, so the worker's pre-receipt barrier must settle A and then persist
    B before ``run.delivery``.
    """
    from deerflow.tools.builtins.task_tool import _ParentLoopMiddlewareRecorderProxy

    monkeypatch.setattr("deerflow.runtime.journal._CANCELLATION_DRAIN_TIMEOUT_SECONDS", 0.05)
    event_store = _BlockingJournalBatchStore()

    bounded_flush_results: list[bool] = []
    bounded_flush_done = asyncio.Event()
    real_flush = RunJournal.flush

    async def spy_flush(journal):
        settled = await real_flush(journal)
        bounded_flush_results.append(settled)
        bounded_flush_done.set()
        return settled

    monkeypatch.setattr(RunJournal, "flush", spy_flush)

    class OrderingRunStore(MemoryRunStore):
        async def update_status(self, run_id, status, *, error=None, stop_reason=None):
            if status not in {"pending", "running"}:
                assert await event_store.list_events("thread-1", run_id, event_types=["run.delivery"]), "durable terminal status landed before the delivery receipt"
            return await super().update_status(run_id, status, error=error, stop_reason=stop_reason)

    run_store = OrderingRunStore()
    run_manager = RunManager(store=run_store)
    record = await run_manager.create("thread-1")

    accepted_buffer: list[list[str]] = []

    class JournalingAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            journal = config["context"]["__run_journal"]
            producer = _ParentLoopMiddlewareRecorderProxy(journal, asyncio.get_running_loop())
            # The default 20-event threshold makes A the first batch.
            for index in range(20):
                journal._put(event_type=f"test.step.{index}", category="steps", content={"index": index})
            await asyncio.wait_for(event_store.batch_a_entered.wait(), timeout=2)

            # The producer forwards from another thread; the callback is accepted
            # and executed on the owner loop while A is still blocked.
            await asyncio.to_thread(
                producer.record_middleware,
                tag="tool_progress",
                name="ToolProgressMiddleware",
                hook="wrap_tool_call",
                action="warn",
                changes={"to_phase": "warned"},
            )
            loop = asyncio.get_running_loop()
            accept_deadline = loop.time() + 2
            while not journal._buffer and loop.time() < accept_deadline:
                await asyncio.sleep(0)
            accepted_buffer.append([event["event_type"] for event in journal._buffer])

            # Publish the producer barrier: every accepted callback is ahead of it.
            await producer.aclose()
            yield {"messages": []}

    task = asyncio.create_task(
        run_agent(
            _make_bridge(),
            run_manager,
            record,
            ctx=RunContext(checkpointer=None, event_store=event_store),
            agent_factory=lambda *, config: JournalingAgent(),
            graph_input={},
            config={},
        )
    )
    try:
        await asyncio.wait_for(bounded_flush_done.wait(), timeout=2)
        assert bounded_flush_results == [False]
        assert accepted_buffer == [["middleware:tool_progress"]]
        assert event_store.batches == [[f"test.step.{index}" for index in range(20)]]

        # While A is unresolved the worker must not have attempted the receipt ...
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(event_store.receipt_attempted.wait()), timeout=0.2)
        assert not task.done()
    finally:
        event_store.release_batch_a.set()
        await asyncio.wait_for(task, timeout=5)

    # A, then the cross-thread middleware event B, then the receipt.
    assert event_store.batches == [
        [f"test.step.{index}" for index in range(20)],
        ["middleware:tool_progress"],
    ]
    events = await event_store.list_events("thread-1", record.run_id)
    step_seqs = [event["seq"] for event in events if event["event_type"].startswith("test.step.")]
    middleware_seqs = [event["seq"] for event in events if event["event_type"] == "middleware:tool_progress"]
    receipt_seqs = [event["seq"] for event in events if event["event_type"] == "run.delivery"]
    assert len(step_seqs) == 20
    assert len(middleware_seqs) == 1
    assert len(receipt_seqs) == 1
    assert max(step_seqs) < middleware_seqs[0] < receipt_seqs[0]
    assert (await run_store.get(record.run_id))["status"] == "success"


@pytest.mark.anyio
async def test_definite_journal_write_failure_never_publishes_success(caplog):
    """A journal write that definitely failed must not become a success run."""

    class FailingBatchStore(MemoryRunEventStore):
        def __init__(self) -> None:
            super().__init__()
            self.failed_batches: list[list[str]] = []

        async def put_batch(self, events):
            self.failed_batches.append([event["event_type"] for event in events])
            raise RuntimeError("journal store unavailable")

    event_store = FailingBatchStore()
    run_store = MemoryRunStore()
    run_manager = RunManager(store=run_store)
    record = await run_manager.create("thread-1")

    class JournalingAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            journal = config["context"]["__run_journal"]
            journal._put(event_type="test.step", category="steps", content={"index": 0})
            yield {"messages": []}

    with caplog.at_level(logging.ERROR, logger="deerflow.runtime.runs.worker"):
        await run_agent(
            _make_bridge(),
            run_manager,
            record,
            ctx=RunContext(checkpointer=None, event_store=event_store),
            agent_factory=lambda *, config: JournalingAgent(),
            graph_input={},
            config={},
        )

    assert event_store.failed_batches, "the journal write was never attempted"
    assert await _delivery_events(event_store, "thread-1", record.run_id) == []
    persisted = await event_store.list_events("thread-1", record.run_id)
    assert not any(event["event_type"] == "test.step" for event in persisted)
    assert record.status == RunStatus.error
    assert record.error == "Run event journal did not settle before terminal receipt"
    assert (await run_store.get(record.run_id))["status"] == "error"
    assert "journal did not settle before its terminal receipt" in caplog.text


@pytest.mark.anyio
async def test_cancelled_run_stays_interrupted_when_the_journal_also_fails():
    """D2d: a cancelled run whose journal write fails stays ``interrupted``."""

    class FailingBatchStore(MemoryRunEventStore):
        async def put_batch(self, events):
            raise RuntimeError("journal store unavailable")

    event_store = FailingBatchStore()
    run_store = MemoryRunStore()
    run_manager = RunManager(store=run_store)
    record = await run_manager.create("thread-1")

    class CancelledAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            journal = config["context"]["__run_journal"]
            journal._put(event_type="test.step", category="steps", content={"index": 0})
            record.abort_event.set()
            yield {"messages": []}

    await run_agent(
        _make_bridge(),
        run_manager,
        record,
        ctx=RunContext(checkpointer=None, event_store=event_store),
        agent_factory=lambda *, config: CancelledAgent(),
        graph_input={},
        config={},
    )

    assert record.status == RunStatus.interrupted
    assert record.error is None
    assert await _delivery_events(event_store, "thread-1", record.run_id) == []
    assert (await run_store.get(record.run_id))["status"] == "interrupted"


@pytest.mark.anyio
async def test_store_self_cancellation_is_a_journal_failure_not_host_cancellation(caplog):
    """D2c at the bounded flush: a store cancelling its own write is a journal failure.

    The store raising ``CancelledError`` from ``put_batch`` is not the caller's
    request, so the barrier's bounded ``flush()`` must report it as a durable
    journal failure rather than letting it escape as host cancellation. Before
    the fix the ``CancelledError`` reached the worker's
    ``except asyncio.CancelledError`` arm, was deferred as a host interrupt, and
    was re-raised by ``run_agent`` without ever taking the ordered-completion
    refusal that marks the run ``error``.
    """

    class SelfCancellingBatchStore(MemoryRunEventStore):
        async def put_batch(self, events):
            raise asyncio.CancelledError("store cancelled its own write")

        async def put_if_absent(self, **kwargs):
            # The receipt path stays healthy: only the journal write is broken.
            return await super().put_if_absent(**kwargs)

    event_store = SelfCancellingBatchStore()
    run_store = MemoryRunStore()
    run_manager = RunManager(store=run_store)
    record = await run_manager.create("thread-1")

    class JournalingAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            journal = config["context"]["__run_journal"]
            journal._put(event_type="test.step", category="steps", content={"index": 0})
            yield {"messages": []}

    with caplog.at_level(logging.ERROR, logger="deerflow.runtime.runs.worker"):
        try:
            await run_agent(
                _make_bridge(),
                run_manager,
                record,
                ctx=RunContext(checkpointer=None, event_store=event_store),
                agent_factory=lambda *, config: JournalingAgent(),
                graph_input={},
                config={},
            )
        except asyncio.CancelledError:
            pytest.fail("a store cancelling its own write escaped run_agent as host cancellation")

    assert record.status == RunStatus.error
    assert record.error == _JOURNAL_UNSETTLED_ERROR
    assert (await run_store.get(record.run_id))["status"] == "error"
    assert await _delivery_events(event_store, "thread-1", record.run_id) == []
    assert "journal did not settle before its terminal receipt" in caplog.text
