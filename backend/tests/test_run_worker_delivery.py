"""Worker-level regression tests for the terminal run.delivery event (#4272 slice 1)."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Interrupt, interrupt

from deerflow.config.app_config import AppConfig
from deerflow.config.paths import Paths
from deerflow.config.run_ownership_config import RunOwnershipConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.config.tool_output_config import ToolOutputConfig
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.runs.manager import RunManager
from deerflow.runtime.runs.schemas import RunStatus
from deerflow.runtime.runs.store.memory import MemoryRunStore
from deerflow.runtime.runs.worker import RunContext, _delivery_content_with_outputs, run_agent
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.workspace_changes import WorkspaceChangeLimits, capture_workspace_snapshot
from deerflow.workspace_changes.api import get_workspace_changes_response


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
@pytest.mark.parametrize("disappear_during", ["before-run", "after-run"])
async def test_vanished_scratch_file_does_not_discard_run_file_changes(tmp_path, monkeypatch, disappear_during):
    import deerflow.workspace_changes.scanner as scanner

    paths = Paths(base_dir=tmp_path)
    monkeypatch.setattr("deerflow.workspace_changes.recorder.get_paths", lambda: paths)
    user_id = get_effective_user_id()
    workspace = paths.sandbox_work_dir("thread-1", user_id=user_id)
    outputs = paths.sandbox_outputs_dir("thread-1", user_id=user_id)
    workspace.mkdir(parents=True)
    outputs.mkdir(parents=True)
    scratch = workspace / "scratch.txt"
    if disappear_during == "before-run":
        scratch.write_text("temporary\n", encoding="utf-8")
    removed = []
    real_hash = scanner._sha256_file

    def remove_before_hash(path):
        if path == scratch:
            path.unlink()
            removed.append(path)
        return real_hash(path)

    monkeypatch.setattr(scanner, "_sha256_file", remove_before_hash)
    run_manager = RunManager()
    record = await run_manager.create("thread-1")
    store = MemoryRunEventStore()

    class ProducingAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            if disappear_during == "after-run":
                scratch.write_text("temporary\n", encoding="utf-8")
            (outputs / "report.md").write_text("Report ready\n", encoding="utf-8")
            yield {"messages": [AIMessage(content="Created report.md.")]}

    await run_agent(
        _make_bridge(),
        run_manager,
        record,
        ctx=RunContext(checkpointer=None, event_store=store),
        agent_factory=lambda *, config: ProducingAgent(),
        graph_input={},
        config={},
    )

    assert removed == [scratch]
    changes = await get_workspace_changes_response(store, "thread-1", record.run_id)
    assert changes["available"] is True
    assert [(change["path"], change["status"]) for change in changes["files"]] == [("/mnt/user-data/outputs/report.md", "created")]
    assert "+Report ready" in changes["files"][0]["diff"]
    delivery = await _delivery_events(store, "thread-1", record.run_id)
    assert delivery[0]["content"]["produced_paths"] == ["/mnt/user-data/outputs/report.md"]
    assert delivery[0]["content"]["satisfied"] is False
    assert record.status == RunStatus.error
    assert record.error == "Artifact delivery incomplete: no produced output artifact was presented"


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
            "requirement": "verified_presentation_matches_produced_output",
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
            "requirement": "verified_presentation_matches_produced_output",
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
@pytest.mark.parametrize("modify_existing", [False, True], ids=["unproven-new-output", "observed-modified-output"])
@pytest.mark.parametrize("terminal_outcome", ["success", "error", "cancelled"])
async def test_truncated_snapshots_limit_output_delivery_verification(tmp_path, monkeypatch, modify_existing, terminal_outcome):
    paths = Paths(base_dir=tmp_path)
    monkeypatch.setattr("deerflow.workspace_changes.recorder.get_paths", lambda: paths)
    run_manager = RunManager()
    record = await run_manager.create("thread-1")
    store = MemoryRunEventStore()
    outputs = paths.sandbox_outputs_dir("thread-1", user_id=get_effective_user_id())
    outputs.mkdir(parents=True)
    for name in ["b.txt", "c.txt", "d.txt"]:
        (outputs / name).write_text("before\n", encoding="utf-8")

    snapshots = []

    async def capture_bounded_snapshot(*args, **kwargs):
        snapshot = await capture_workspace_snapshot(*args, limits=WorkspaceChangeLimits(max_scanned_files=2), **kwargs)
        snapshots.append(snapshot)
        return snapshot

    monkeypatch.setattr("deerflow.runtime.runs.worker.capture_workspace_snapshot", capture_bounded_snapshot)

    class ProducingAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            (outputs / "a.txt").write_text("new output\n", encoding="utf-8")
            if modify_existing:
                (outputs / "b.txt").write_text("modified\n", encoding="utf-8")
            if terminal_outcome == "error":
                raise RuntimeError("Agent failed after producing output")
            if terminal_outcome == "cancelled":
                raise asyncio.CancelledError
            yield {"messages": [AIMessage(content="Created the output.")]}

    await run_agent(
        _make_bridge(),
        run_manager,
        record,
        ctx=RunContext(checkpointer=None, event_store=store),
        agent_factory=lambda *, config: ProducingAgent(),
        graph_input={},
        config={},
    )

    assert snapshots[0].truncated is True
    assert snapshots[-1].truncated is True
    assert "/mnt/user-data/outputs/a.txt" not in snapshots[0].files
    assert "/mnt/user-data/outputs/a.txt" in snapshots[-1].files
    assert (outputs / "a.txt").is_file()
    delivery = await _delivery_events(store, "thread-1", record.run_id)
    assert len(delivery) == 1
    content = delivery[0]["content"]
    if modify_existing:
        assert content["produced_paths"] == ["/mnt/user-data/outputs/b.txt"]
        assert content["verification"]["source"] == "outputs_changed"
        assert content["satisfied"] is False
        assert "verification_skipped" not in content
    else:
        assert content == {"presented": 0, "paths": [], "by_tool": {}, "verification_skipped": "truncated_pre_run_snapshot"}
    if terminal_outcome == "error":
        assert record.status == RunStatus.error
        assert record.error == "Agent failed after producing output"
    elif terminal_outcome == "cancelled":
        assert record.status == RunStatus.interrupted
    elif modify_existing:
        assert record.status == RunStatus.error
        assert record.error == "Artifact delivery incomplete: no produced output artifact was presented"
    else:
        assert record.status == RunStatus.success
        assert record.error is None


@pytest.mark.anyio
@pytest.mark.parametrize("failure_stage", ["before", "after"])
async def test_snapshot_capture_failure_does_not_claim_truncated_verification(tmp_path, monkeypatch, failure_stage):
    paths = Paths(base_dir=tmp_path)
    monkeypatch.setattr("deerflow.workspace_changes.recorder.get_paths", lambda: paths)
    run_manager = RunManager()
    record = await run_manager.create("thread-1")
    store = MemoryRunEventStore()
    outputs = paths.sandbox_outputs_dir("thread-1", user_id=get_effective_user_id())
    outputs.mkdir(parents=True)
    captures = 0

    async def capture_or_fail(*args, **kwargs):
        nonlocal captures
        captures += 1
        if captures == (1 if failure_stage == "before" else 2):
            raise OSError("Snapshot capture unavailable")
        return await capture_workspace_snapshot(*args, **kwargs)

    monkeypatch.setattr("deerflow.runtime.runs.worker.capture_workspace_snapshot", capture_or_fail)

    class ProducingAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            (outputs / "report.md").write_text("Report ready\n", encoding="utf-8")
            yield {"messages": [AIMessage(content="Created report.md.")]}

    await run_agent(
        _make_bridge(),
        run_manager,
        record,
        ctx=RunContext(checkpointer=None, event_store=store),
        agent_factory=lambda *, config: ProducingAgent(),
        graph_input={},
        config={},
    )

    assert captures == (1 if failure_stage == "before" else 2)
    assert (outputs / "report.md").is_file()
    delivery = await _delivery_events(store, "thread-1", record.run_id)
    assert len(delivery) == 1
    assert delivery[0]["content"] == {"presented": 0, "paths": [], "by_tool": {}}
    assert record.status == RunStatus.success
    assert record.error is None


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
async def test_deferred_error_stream_frames_follow_durable_terminal_status():
    events = MemoryRunEventStore()
    order: list[str] = []

    class OrderingRunStore(MemoryRunStore):
        async def update_status(self, run_id, status, *, error=None, stop_reason=None):
            result = await super().update_status(
                run_id,
                status,
                error=error,
                stop_reason=stop_reason,
            )
            if status == "error":
                order.append("durable-error")
            return result

    class OrderingBridge:
        async def publish(self, _run_id, event, _data):
            if event == "error":
                order.append("stream-error")

        async def publish_end(self, _run_id):
            order.append("stream-end")

        async def cleanup(self, _run_id, *, delay=0):
            del delay

    class FailingAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            del graph_input, config, stream_mode, subgraphs
            raise RuntimeError("boom")
            yield  # pragma: no cover - make this an async generator

    run_store = OrderingRunStore()
    run_manager = RunManager(store=run_store)
    record = await run_manager.create("thread-1")

    await run_agent(
        OrderingBridge(),
        run_manager,
        record,
        ctx=RunContext(checkpointer=None, event_store=events),
        agent_factory=lambda *, config: FailingAgent(),
        graph_input={},
        config={},
    )

    assert order == ["durable-error", "stream-error", "stream-end"]


@pytest.mark.anyio
async def test_delivery_write_retries_before_persisting_success():
    class FlakyReceiptStore(MemoryRunEventStore):
        def __init__(self):
            super().__init__()
            self.attempts = 0

        async def put_if_absent(self, **kwargs):
            if kwargs["event_type"] == "run.delivery":
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


@pytest.mark.anyio
async def test_pending_snapshot_failure_cannot_complete_run_successfully():
    from langgraph.checkpoint.memory import InMemorySaver

    run_store = MemoryRunStore()
    run_manager = RunManager(store=run_store)
    record = await run_manager.create("thread-snapshot-failure")
    app_config = AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}})
    app_config.hitl_approval.enabled = True

    class SnapshotFailureAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            yield {"messages": []}

        async def aget_state(self, _config):
            raise RuntimeError("checkpoint snapshot unavailable")

    await run_agent(
        _make_bridge(),
        run_manager,
        record,
        ctx=RunContext(checkpointer=InMemorySaver(), app_config=app_config),
        agent_factory=lambda *, config: SnapshotFailureAgent(),
        graph_input={},
        config={},
    )

    assert record.status == RunStatus.error
    assert record.error == "checkpoint snapshot unavailable"
    assert (await run_store.get(record.run_id))["status"] == "error"


@pytest.mark.anyio
async def test_paused_metadata_is_not_written_after_ownership_loss():
    from langgraph.checkpoint.memory import InMemorySaver

    run_store = MemoryRunStore()
    run_manager = RunManager(
        store=run_store,
        worker_id="owner",
        run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True, lease_seconds=30, grace_seconds=0),
    )
    record = await run_manager.create_or_reject("thread-paused-ownership")
    app_config = AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}})
    app_config.hitl_approval.enabled = True
    original_finalize = run_store.finalize_if_not_cancelled

    async def finalize_then_lose_ownership(*args, **kwargs):
        result = await original_finalize(*args, **kwargs)
        run_store._runs[record.run_id].update(status="error", error="peer takeover", owner_worker_id="peer", metadata={"owner": "peer"})
        await run_manager._mark_ownership_lost(record, reason="Test peer takeover", require_active=False)
        return result

    run_store.finalize_if_not_cancelled = finalize_then_lose_ownership
    run_store.put = AsyncMock(wraps=run_store.put)
    run_manager.persist_metadata = AsyncMock(wraps=run_manager.persist_metadata)
    payload = {"kind": "hitl_approval", "request_id": "approval-1"}

    class PausedAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            yield {"messages": []}

        async def aget_state(self, _config):
            return SimpleNamespace(
                values={"messages": []},
                config={},
                metadata={},
                next=("agent",),
                tasks=(SimpleNamespace(interrupts=(SimpleNamespace(value=payload),)),),
            )

    await run_agent(
        _make_bridge(),
        run_manager,
        record,
        ctx=RunContext(checkpointer=InMemorySaver(), app_config=app_config),
        agent_factory=lambda *, config: PausedAgent(),
        graph_input={},
        config={},
    )

    run_manager.persist_metadata.assert_not_awaited()
    run_store.put.assert_not_awaited()
    row = await run_store.get(record.run_id)
    assert row["status"] == "error"
    assert row["error"] == "peer takeover"
    assert row["metadata"] == {"owner": "peer"}


@pytest.mark.anyio
@pytest.mark.parametrize("stream_modes", [None, ["messages-tuple"]], ids=["values", "messages-only"])
async def test_generic_interrupt_is_waiting_even_when_hitl_is_disabled(stream_modes):
    from langgraph.checkpoint.memory import InMemorySaver

    run_store = MemoryRunStore()
    run_manager = RunManager(store=run_store)
    record = await run_manager.create("thread-generic-pause" if stream_modes is None else "thread-generic-pause-messages")
    app_config = AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}})

    class GenericPausedAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            yield {"messages": [], "__interrupt__": (Interrupt(value={"question": "Continue?"}, id="generic-pause"),)}

        async def aget_state(self, _config):
            return SimpleNamespace(
                values={"messages": []},
                config={},
                metadata={},
                next=("answer",),
                tasks=(SimpleNamespace(interrupts=(SimpleNamespace(value={"question": "Continue?"}),)),),
            )

    await run_agent(
        _make_bridge(),
        run_manager,
        record,
        ctx=RunContext(checkpointer=InMemorySaver(), app_config=app_config),
        agent_factory=lambda *, config: GenericPausedAgent(),
        graph_input={},
        config={},
        stream_modes=stream_modes,
    )

    row = await run_store.get(record.run_id)
    assert row["status"] == "waiting_for_input"
    assert "hitl_approval" not in row["metadata"]


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["full", "delta"])
async def test_approval_pause_bypasses_terminal_goal_delivery_and_batch_completion(tmp_path, monkeypatch, mode):
    from langgraph.checkpoint.memory import InMemorySaver

    from app.subagent_batches.continuation import BatchContinuations
    from deerflow.agents.thread_state import ThreadState
    from deerflow.extensions.registry import ExtensionRegistry
    from deerflow.runtime.goal import build_goal_state, read_thread_goal, write_thread_goal

    paths = Paths(base_dir=tmp_path)
    monkeypatch.setattr("deerflow.workspace_changes.recorder.get_paths", lambda: paths)
    user_id = get_effective_user_id()
    thread_id = f"thread-approval-pause-{mode}"
    checkpointer = InMemorySaver()
    event_store = MemoryRunEventStore()
    run_store = MemoryRunStore()
    run_manager = RunManager(store=run_store)
    record = await run_manager.create(thread_id, user_id=user_id)
    await write_thread_goal(checkpointer, thread_id, build_goal_state("Finish the report"), create_if_missing=True)

    output_dir = paths.sandbox_outputs_dir(thread_id, user_id=user_id)
    payload = {"kind": "hitl_approval", "request_id": f"approval-{mode}", "pending_tool_call_ids": ["call-write"]}

    def produce_output(_state):
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "report.md").write_text("Ready for review\n", encoding="utf-8")
        return {}

    def request_approval(_state):
        interrupt(payload)

    builder = StateGraph(ThreadState)
    builder.add_node("produce_output", produce_output)
    builder.add_node("request_approval", request_approval)
    builder.add_edge(START, "produce_output")
    builder.add_edge("produce_output", "request_approval")
    builder.add_edge("request_approval", END)
    graph = builder.compile(checkpointer=checkpointer)

    requested_followups = {"batch-1": "requested"}

    class BatchRepo:
        async def list_continuation_batches_for_run(self, run_id):
            assert run_id == record.run_id
            return [{"id": "batch-1", "user_id": user_id}]

        async def suppress_thread_continuations(self, _thread_id, *, goal_created_at):
            requested_followups["batch-1"] = f"suppressed:{goal_created_at}"

    class BatchService:
        async def cancel_batch(self, *, batch_id, user_id):
            assert batch_id == "batch-1"
            assert user_id == record.user_id
            requested_followups.pop(batch_id, None)

    batch_app = SimpleNamespace(
        state=SimpleNamespace(
            subagent_batch_repo=BatchRepo(),
            subagent_batch_service=BatchService(),
            checkpointer=checkpointer,
        )
    )
    batch_continuations = BatchContinuations(batch_app)

    class LifecycleRecorder:
        def __init__(self):
            self.events = []

        async def on_task_start(self, _app_store, _task_store, info):
            self.events.append(("start", info.run_id))

        async def on_task_stop(self, _app_store, _task_store, info, outcome):
            self.events.append(("stop", info.run_id, outcome.value))

    recorder = LifecycleRecorder()
    registry = ExtensionRegistry()
    with registry.attributed_to("test:hitl-pause"):
        registry.task_lifecycle(recorder)

    app_config = AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}})
    app_config.hitl_approval.enabled = True
    app_config.title.enabled = app_config.memory.enabled = app_config.memory.injection_enabled = False

    await run_agent(
        _make_bridge(),
        run_manager,
        record,
        ctx=RunContext(
            checkpointer=checkpointer,
            event_store=event_store,
            app_config=app_config,
            extensions=registry.build(),
            checkpoint_channel_mode=mode,
            on_run_completed=batch_continuations.source_finished,
        ),
        agent_factory=lambda *, config: graph,
        graph_input={"messages": [HumanMessage(content="Write the report")]},
        config={"configurable": {"thread_id": thread_id}},
    )

    row = await run_store.get(record.run_id)
    assert row["status"] == "waiting_for_input"
    assert row["error"] is None
    assert row["metadata"]["hitl_approval"] == payload
    paused_goal = await read_thread_goal(checkpointer, thread_id)
    assert paused_goal["status"] == "active"
    assert paused_goal["continuation_count"] == paused_goal["no_progress_count"] == 0
    assert "last_evaluation" not in paused_goal
    assert requested_followups == {"batch-1": "requested"}
    assert recorder.events == [("start", record.run_id), ("stop", record.run_id, "failed")]

    delivery = await _delivery_events(event_store, thread_id, record.run_id)
    assert len(delivery) == 1
    assert delivery[0]["content"]["produced_paths"] == ["/mnt/user-data/outputs/report.md"]
    assert delivery[0]["content"]["satisfied"] is False
    terminal = await event_store.list_events(thread_id, record.run_id, event_types=["run.terminal"])
    assert [event["content"] for event in terminal] == [{"status": "waiting_for_input"}]


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["full", "delta"])
async def test_disabled_hitl_does_not_materialize_pending_approval_snapshot(mode):
    from langgraph.checkpoint.memory import InMemorySaver

    from deerflow.agents.thread_state import ThreadState

    checkpointer = InMemorySaver()
    run_manager = RunManager()
    record = await run_manager.create(f"thread-disabled-hitl-{mode}")

    def finish(_state):
        return {"messages": [AIMessage(content="Done")]}

    builder = StateGraph(ThreadState)
    builder.add_node("finish", finish)
    builder.add_edge(START, "finish")
    builder.add_edge("finish", END)
    compiled = builder.compile(checkpointer=checkpointer)

    class SnapshotTrackingGraph:
        def __init__(self):
            self.stream_finished = False
            self.post_stream_running_snapshots = 0

        def __getattr__(self, name):
            return getattr(compiled, name)

        async def astream(self, *args, **kwargs):
            async for item in compiled.astream(*args, **kwargs):
                yield item
            self.stream_finished = True

        async def aget_state(self, config):
            if self.stream_finished and record.status == RunStatus.running:
                self.post_stream_running_snapshots += 1
            return await compiled.aget_state(config)

    graph = SnapshotTrackingGraph()
    app_config = AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}})
    app_config.hitl_approval.enabled = False
    app_config.title.enabled = app_config.memory.enabled = app_config.memory.injection_enabled = False

    await run_agent(
        _make_bridge(),
        run_manager,
        record,
        ctx=RunContext(checkpointer=checkpointer, app_config=app_config, checkpoint_channel_mode=mode),
        agent_factory=lambda *, config: graph,
        graph_input={"messages": [HumanMessage(content="Finish normally")]},
        config={"configurable": {"thread_id": record.thread_id}},
    )

    assert record.status == RunStatus.success
    assert graph.post_stream_running_snapshots == 0
