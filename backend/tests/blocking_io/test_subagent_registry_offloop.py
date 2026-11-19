"""Regression: subagent registry reads resolve off the event loop.

``_managed_definitions`` sweeps the managed-definition store for its cache
signature on every TTL miss (one second): the file store globs and stats the
definitions directory, the SQL store runs a per-row query, and
``get_available_subagent_names`` may additionally read config files through
``is_host_bash_allowed``. The ``task`` and ``batch_task`` tools run on the
streaming event loop, so those reads must be dispatched to the assembly pool
like every other blocking hop (issue #5172).

Under the strict Blockbuster context (this directory's conftest), the real
``FileManagedSubagentStore`` signature sweep raises ``BlockingError`` when it
runs on the loop, so the anchors below fail against a plain synchronous
registry call and pass only when the dispatch survives. The meta-check at the
end proves the probe has teeth by calling the store directly on the loop.
"""

from __future__ import annotations

import importlib
import threading
from enum import Enum
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import ToolMessage

from deerflow.config.subagents_config import SubagentsAppConfig
from deerflow.persistence.managed_subagents import ManagedSubagentDefinition
from deerflow.persistence.managed_subagents.file import FileManagedSubagentStore
from deerflow.subagents import registry
from deerflow.tools.builtins.batch_task_tool import BatchTaskItem

# importlib.import_module binds the real module: the package attribute
# ``deerflow.tools.builtins.task_tool`` is shadowed by the StructuredTool.
task_tool_module = importlib.import_module("deerflow.tools.builtins.task_tool")
batch_task_tool_module = importlib.import_module("deerflow.tools.builtins.batch_task_tool")

pytestmark = pytest.mark.asyncio


class _FakeSubagentStatus(Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    RUNNING = "running"

    @property
    def is_terminal(self) -> bool:
        return self is not _FakeSubagentStatus.RUNNING


def _managed_definition_payload() -> str:
    return ManagedSubagentDefinition(
        name="researcher",
        description="Managed researcher",
        system_prompt="You are researcher.",
        enabled=True,
    ).model_dump_json()


def _observe_file_store(observed_threads: list) -> FileManagedSubagentStore:
    class _ObservingFileStore(FileManagedSubagentStore):
        def signature(self):
            observed_threads.append(threading.current_thread())
            # Real production blocking read (glob + stat inside a deerflow
            # frame): trips the strict gate when it runs on the loop.
            return super().signature()

        def list(self):
            observed_threads.append(threading.current_thread())
            return super().list()

    return _ObservingFileStore()


def _install_real_file_store(monkeypatch, tmp_path: Path, observed_threads: list) -> FileManagedSubagentStore:
    # Patch the file store's own get_paths binding instead of constructing a
    # Paths(base_dir=...) here: resolving the base dir does blocking IO and
    # this helper runs inside the strict gate, in async test bodies.
    root = tmp_path / "managed-subagents"
    root.mkdir(parents=True, exist_ok=True)
    (root / "researcher.json").write_text(_managed_definition_payload(), encoding="utf-8")
    store = _observe_file_store(observed_threads)
    monkeypatch.setattr(
        "deerflow.persistence.managed_subagents.file.get_paths",
        lambda: SimpleNamespace(managed_subagents_dir=root),
    )
    monkeypatch.setattr(registry, "get_managed_subagent_store", lambda _config=None: store)
    # Keep the per-agent override resolution off the real config files: the
    # sweep under test is the managed-definition store, not AppConfig loading.
    monkeypatch.setattr(registry, "_resolve_subagents_app_config", lambda _app_config=None: SubagentsAppConfig())
    registry._clear_managed_definitions_cache()
    return store


def _completed_result() -> SimpleNamespace:
    return SimpleNamespace(
        status=_FakeSubagentStatus.COMPLETED,
        ai_messages=[],
        result="done",
        error=None,
        stop_reason=None,
        token_usage_records=[],
        usage_reported=False,
        tool_receipts=None,
        bash_executions=None,
    )


class _DummyExecutor:
    def __init__(self, **_kwargs):
        pass

    def execute_async(self, _prompt, task_id=None):
        return task_id or "generated-task-id"


async def test_task_tool_registry_reads_resolve_off_loop(monkeypatch, tmp_path):
    """task_tool resolves the subagent registry on a worker thread."""
    observed_threads: list = []
    _install_real_file_store(monkeypatch, tmp_path, observed_threads)
    monkeypatch.setattr(task_tool_module, "SubagentStatus", _FakeSubagentStatus)
    monkeypatch.setattr(task_tool_module, "SubagentExecutor", _DummyExecutor)
    # Host-bash policy and the inherit-path app-config fallback read
    # AppConfig files; neither is the probe target here.
    monkeypatch.setattr(task_tool_module, "is_host_bash_allowed", lambda *_a, **_k: True)
    monkeypatch.setattr(task_tool_module, "get_app_config", lambda: SimpleNamespace(models=[SimpleNamespace(name="default-model")]))
    # Tool assembly is already anchored in test_tool_assembly_offloop.py; stub
    # it here so the probe target stays the registry sweep.
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **_kwargs: [])
    monkeypatch.setattr(task_tool_module, "get_background_task_result", lambda _task_id: _completed_result())
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: lambda _event: None)

    async def _no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)

    tool = task_tool_module.task_tool
    invoke = getattr(tool, "coroutine", None) or getattr(tool, "func", None)
    assert invoke is not None
    command = await invoke(
        runtime=None,
        description="test",
        prompt="p",
        subagent_type="researcher",
        tool_call_id="tc-registry-offloop",
    )

    messages = command.update["messages"]
    assert len(messages) == 1
    assert isinstance(messages[0], ToolMessage)
    assert "Task Succeeded" in messages[0].content
    assert observed_threads, "the managed-definition signature sweep must be invoked"
    assert all(thread is not threading.main_thread() for thread in observed_threads)


async def test_batch_task_registry_reads_resolve_off_loop(monkeypatch, tmp_path):
    """batch_task resolves the subagent registry on a worker thread.

    The submitter is a failing stub: batch_task validates the registry (and
    the caller policy) BEFORE attempting submission, so the sweep must have
    run — off the loop — by the time the submission error is reported.
    """
    observed_threads: list = []
    _install_real_file_store(monkeypatch, tmp_path, observed_threads)

    class _FailingSubmitter:
        accepts_continuation_authority = False

        async def submit(self, _request):
            raise RuntimeError("no durable batch backend in this test")

        async def get_batch(self, **_kwargs):
            return None

    monkeypatch.setattr(batch_task_tool_module, "_batch_submitter", lambda: _FailingSubmitter())
    tool = batch_task_tool_module.batch_task
    invoke = getattr(tool, "coroutine", None) or getattr(tool, "func", None)
    assert invoke is not None
    result = await invoke(
        runtime=SimpleNamespace(
            state={},
            context={},
            config={"configurable": {"thread_id": "thread-1"}},
        ),
        title="batch",
        items=[BatchTaskItem(key="k1", prompt="p")],
        subagent_type="researcher",
        tool_call_id="tc-batch-registry-offloop",
    )

    messages = result.update["messages"]
    assert len(messages) == 1
    assert "Batch submission failed" in messages[0].content
    assert observed_threads, "the managed-definition signature sweep must be invoked"
    assert all(thread is not threading.main_thread() for thread in observed_threads)


async def test_registry_signature_sweep_trips_the_gate(monkeypatch, tmp_path):
    """Meta-check: the real file-store signature sweep called on the loop must
    raise BlockingError, so the anchors above cannot go vacuously green."""
    from blockbuster import BlockingError

    observed_threads: list = []
    store = _install_real_file_store(monkeypatch, tmp_path, observed_threads)

    with pytest.raises(BlockingError):
        store.signature()
    assert observed_threads == [threading.main_thread()]


async def test_task_tool_sandbox_policy_resolves_off_loop(monkeypatch, tmp_path):
    """The subagent_type="bash" sandbox-policy hop dispatches to a worker thread.

    ``is_host_bash_allowed(config=None)`` falls through to ``get_app_config()``,
    which stats and hashes the config files on every call — so flattening this
    one dispatch back to a synchronous call would silently return that read to
    the loop even though the registry anchors stay green (they never enter the
    bash branch). A real blocking file-read probe as ``is_host_bash_allowed``
    keeps it teeth-verified like every other offload in this file.
    """
    probe_file = tmp_path / "sandbox-policy-probe.txt"
    probe_file.write_text("probe body", encoding="utf-8")
    observed_threads: list = []

    def _blocking_probe_is_host_bash_allowed(_config=None):
        # Real filesystem IO: trips the strict gate when it runs on the loop.
        probe_file.read_text(encoding="utf-8")
        observed_threads.append(threading.current_thread())
        return True

    _install_real_file_store(monkeypatch, tmp_path, [])
    monkeypatch.setattr(task_tool_module, "SubagentStatus", _FakeSubagentStatus)
    monkeypatch.setattr(task_tool_module, "SubagentExecutor", _DummyExecutor)
    monkeypatch.setattr(task_tool_module, "is_host_bash_allowed", _blocking_probe_is_host_bash_allowed)
    monkeypatch.setattr(task_tool_module, "get_app_config", lambda: SimpleNamespace(models=[SimpleNamespace(name="default-model")]))
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **_kwargs: [])
    monkeypatch.setattr(task_tool_module, "get_background_task_result", lambda _task_id: _completed_result())
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: lambda _event: None)

    async def _no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(task_tool_module.asyncio, "sleep", _no_sleep)

    tool = task_tool_module.task_tool
    invoke = getattr(tool, "coroutine", None) or getattr(tool, "func", None)
    assert invoke is not None
    command = await invoke(
        runtime=None,
        description="test",
        prompt="p",
        subagent_type="bash",
        tool_call_id="tc-sandbox-policy-offloop",
    )

    messages = command.update["messages"]
    assert len(messages) == 1
    assert isinstance(messages[0], ToolMessage)
    assert "Task Succeeded" in messages[0].content
    assert observed_threads, "the sandbox-policy read must be invoked"
    assert all(thread is not threading.main_thread() for thread in observed_threads)
