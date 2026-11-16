"""Incognito runs skip every durable write the agent normally performs.

The marker is pinned at admission and hoisted into the runtime context (see
``test_incognito_run_context.py``); these tests drive each write surface with
that context and assert the memory backend and the shared blob store stay
untouched. Thread-scoped files (workspace, uploads, outputs) still work and
are purged with the thread by the lifecycle sweep.
"""

from __future__ import annotations

import asyncio
import base64
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.runtime import Runtime

from deerflow.agents.memory import summarization_hook
from deerflow.agents.memory.tools import memory_add_tool, memory_delete_tool, memory_update_tool
from deerflow.agents.middlewares import memory_middleware as memory_middleware_module
from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware
from deerflow.agents.middlewares.summarization_middleware import SummarizationEvent
from deerflow.config.memory_config import MemoryConfig
from deerflow.runtime.context_keys import INCOGNITO_CONTEXT_KEY, is_incognito_runtime

# Minimal 1x1 PNG, the same fixture the view_image tests use.
PNG_BYTES = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


def _runtime(**context) -> Runtime:
    return Runtime(context={"thread_id": "secret", "user_id": "alice", **context})


def _incognito_runtime() -> Runtime:
    return _runtime(**{INCOGNITO_CONTEXT_KEY: True})


def test_only_the_server_boolean_marks_a_run_incognito():
    assert is_incognito_runtime(_incognito_runtime())
    assert not is_incognito_runtime(_runtime())
    # A persisted string or another truthy value is not the marker.
    assert not is_incognito_runtime(_runtime(**{INCOGNITO_CONTEXT_KEY: "true"}))
    assert not is_incognito_runtime(_runtime(**{INCOGNITO_CONTEXT_KEY: 1}))
    assert not is_incognito_runtime(SimpleNamespace(context=None))
    assert not is_incognito_runtime(None)


def test_memory_middleware_skips_incognito_capture(monkeypatch):
    manager = MagicMock()
    monkeypatch.setattr(memory_middleware_module, "get_memory_manager", lambda: manager)
    middleware = MemoryMiddleware(memory_config=MemoryConfig(enabled=True))
    state = {"messages": [HumanMessage("secret"), AIMessage("ok")]}

    assert middleware.after_agent(state, _incognito_runtime()) is None
    assert asyncio.run(middleware.aafter_agent(state, _incognito_runtime())) is None

    manager.add.assert_not_called()
    manager.aadd.assert_not_called()


def test_compaction_flush_skips_incognito(monkeypatch):
    manager = MagicMock()
    monkeypatch.setattr(summarization_hook, "get_memory_manager", lambda: manager)
    monkeypatch.setattr(summarization_hook, "get_memory_config", lambda: SimpleNamespace(enabled=True))
    event = SummarizationEvent(
        messages_to_summarize=(HumanMessage("secret"),),
        preserved_messages=(),
        thread_id="secret",
        agent_name=None,
        runtime=_incognito_runtime(),
    )

    summarization_hook.memory_flush_hook(event)

    manager.add_nowait.assert_not_called()


def test_memory_write_tools_refuse_incognito(monkeypatch):
    manager = MagicMock()
    monkeypatch.setattr("deerflow.agents.memory.tools.get_memory_manager", lambda: manager)
    runtime = _incognito_runtime()

    results = [
        memory_add_tool.func(runtime, "secret preference"),
        memory_update_tool.func(runtime, "fact-1", content="secret"),
        memory_delete_tool.func(runtime, "fact-1"),
    ]

    for result in results:
        assert "incognito" in json.loads(result)["error"].lower()
    assert manager.mock_calls == []


def test_tool_output_blobs_are_skipped_for_incognito(tmp_path: Path, monkeypatch):
    from deerflow.agents.middlewares import tool_output_budget_middleware as budget

    store = MagicMock()
    monkeypatch.setattr(budget, "get_blob_store_if_enabled", lambda: store)
    config = budget.ToolOutputConfig(externalize_min_chars=100, fallback_max_chars=50)
    message = ToolMessage(content="x" * 500, name="web_fetch", tool_call_id="tc-1")

    patched = budget._patch_tool_message(message, config, str(tmp_path), persist_blobs=False)

    assert patched is not message
    store.put_bytes.assert_not_called()
    # The full output still externalizes into the thread's own outputs tree.
    assert any(path.is_file() for path in tmp_path.rglob("*"))

    budget._patch_tool_message(message, config, str(tmp_path))
    store.put_bytes.assert_called_once()


def test_tool_output_wrapper_reads_the_incognito_marker(tmp_path: Path, monkeypatch):
    from langchain.agents.middleware import ToolCallRequest

    from deerflow.agents.middlewares.tool_output_budget_middleware import ToolOutputBudgetMiddleware, ToolOutputConfig

    store = MagicMock()
    monkeypatch.setattr("deerflow.agents.middlewares.tool_output_budget_middleware.get_blob_store_if_enabled", lambda: store)
    middleware = ToolOutputBudgetMiddleware(ToolOutputConfig(externalize_min_chars=100, fallback_max_chars=50))
    message = ToolMessage(content="x" * 500, name="web_fetch", tool_call_id="tc-1")

    def call(marker: dict) -> ToolMessage:
        request = ToolCallRequest(
            tool_call={"name": "web_fetch", "args": {}, "id": "tc-1", "type": "tool_call"},
            tool=None,
            state={},
            runtime=SimpleNamespace(
                context={"thread_id": "secret", **marker},
                state={"thread_data": {"outputs_path": str(tmp_path)}},
                config={},
            ),
        )
        return middleware.wrap_tool_call(request, lambda _request: message)

    patched = call({INCOGNITO_CONTEXT_KEY: True})
    assert patched is not message
    store.put_bytes.assert_not_called()

    call({})
    store.put_bytes.assert_called_once()


def _thread_data(tmp_path: Path) -> dict[str, str]:
    user_data = tmp_path / "threads" / "thread-1" / "user-data"
    paths = {
        "workspace_path": user_data / "workspace",
        "uploads_path": user_data / "uploads",
        "outputs_path": user_data / "outputs",
    }
    for path in paths.values():
        path.mkdir(parents=True)
    return {name: str(path) for name, path in paths.items()}


def _view_runtime(thread_data: dict[str, str], **context) -> SimpleNamespace:
    return SimpleNamespace(state={"thread_data": thread_data}, context={"thread_id": "thread-1", **context}, config={})


@pytest.mark.parametrize("incognito", [True, False])
def test_view_image_writes_a_blob_only_for_ordinary_runs(tmp_path: Path, monkeypatch, incognito: bool) -> None:
    module = importlib.import_module("deerflow.tools.builtins.view_image_tool")

    thread_data = _thread_data(tmp_path)
    image_path = Path(thread_data["uploads_path"]) / "sample.png"
    image_path.write_bytes(PNG_BYTES)
    store = MagicMock()
    monkeypatch.setattr("deerflow.storage.get_blob_store_if_enabled", lambda: store)
    context = {INCOGNITO_CONTEXT_KEY: True} if incognito else {}

    result = module.view_image_tool.func(
        runtime=_view_runtime(thread_data, **context),
        image_path="/mnt/user-data/uploads/sample.png",
        tool_call_id="tc-view",
    )

    assert result.update["messages"][0].content == "Successfully read image"
    viewed = result.update["viewed_images"]["/mnt/user-data/uploads/sample.png"]
    if incognito:
        assert "blob_ref" not in viewed
        store.put_bytes.assert_not_called()
    else:
        assert "blob_ref" in viewed
        store.put_bytes.assert_called_once()
