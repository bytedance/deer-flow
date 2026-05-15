"""Tests for GenUI interaction callback isolation."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import types


langchain_core = types.ModuleType("langchain_core")
langchain_core_messages = types.ModuleType("langchain_core.messages")


class HumanMessage:
    def __init__(self, content: str, id: str | None = None):
        self.content = content
        self.id = id


langchain_core_messages.HumanMessage = HumanMessage
langchain_core.messages = langchain_core_messages
sys.modules.setdefault("langchain_core", langchain_core)
sys.modules.setdefault("langchain_core.messages", langchain_core_messages)


def _load_module(module_name: str, relative_path: str):
    path = Path(__file__).resolve().parents[1] / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


genui_middleware = _load_module(
    "test_genui_middleware_module",
    "packages/harness/deerflow/agents/middlewares/genui_middleware.py",
)
InteractionStore = genui_middleware.InteractionStore
process_interaction = genui_middleware.process_interaction


def test_interaction_store_scopes_same_callback_id_by_thread() -> None:
    store = InteractionStore()

    store.register("daily-report-scope", "thread-a", "checkpoint-a")
    store.register("daily-report-scope", "thread-b", "checkpoint-b")

    record_a = store.get("thread-a", "daily-report-scope")
    record_b = store.get("thread-b", "daily-report-scope")

    assert record_a is not None
    assert record_b is not None
    assert record_a.checkpoint_id == "checkpoint-a"
    assert record_b.checkpoint_id == "checkpoint-b"


def test_process_interaction_uses_thread_scoped_callback_lookup(monkeypatch) -> None:
    store = InteractionStore()
    store.register("daily-report-scope", "thread-a", "checkpoint-a")
    store.register("daily-report-scope", "thread-b", "checkpoint-b")
    monkeypatch.setattr(genui_middleware, "_interaction_store", store)

    message = process_interaction(
        "thread-b",
        "daily-report-scope",
        {"report_date": "2026-05-15"},
    )

    assert message is not None
    parsed = json.loads(message.content)
    assert parsed["callback_id"] == "daily-report-scope"
    assert parsed["payload"]["report_date"] == "2026-05-15"

    record_a = store.get("thread-a", "daily-report-scope")
    record_b = store.get("thread-b", "daily-report-scope")
    assert record_a is not None and record_a.submitted is False
    assert record_b is not None and record_b.submitted is True
