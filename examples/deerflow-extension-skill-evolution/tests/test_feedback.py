"""Tests for the read-only ``skill_feedback`` model tool (Plan B)."""

import asyncio
import sys
import types
from contextlib import closing
from types import SimpleNamespace

import pytest
from langchain_core.tools import BaseTool

from deerflow_extension_skill_evolution.evolved import EvolvedSkillStore
from deerflow_extension_skill_evolution.feedback import TOOL_NAME, build_skill_feedback_tool


def _stub_host_seams(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the lazily imported host seams; the tool reads the user from
    runtime.context, mirroring the host's resolution order."""
    user_context = types.ModuleType("deerflow.runtime.user_context")

    def _resolve(runtime):
        context = getattr(runtime, "context", None)
        if isinstance(context, dict) and context.get("user_id"):
            return str(context["user_id"])
        return "anonymous"

    user_context.resolve_runtime_user_id = _resolve
    monkeypatch.setitem(sys.modules, "deerflow.runtime.user_context", user_context)
    tools_types = types.ModuleType("deerflow.tools.types")
    from langchain.tools import ToolRuntime

    tools_types.Runtime = ToolRuntime[dict, object]
    monkeypatch.setitem(sys.modules, "deerflow.tools.types", tools_types)


def _runtime(user_id: str) -> SimpleNamespace:
    return SimpleNamespace(context={"user_id": user_id})


def _tool(monkeypatch, tmp_path) -> BaseTool:
    _stub_host_seams(monkeypatch)
    return build_skill_feedback_tool(EvolvedSkillStore(tmp_path / "store.sqlite"))


def _call(tool: BaseTool, user_id: str, skill_name: str) -> str:
    return asyncio.run(tool.coroutine(runtime=_runtime(user_id), skill_name=skill_name))  # type: ignore[attr-defined]


def test_tool_is_a_named_readonly_tool(monkeypatch, tmp_path) -> None:
    tool = _tool(monkeypatch, tmp_path)
    assert isinstance(tool, BaseTool)
    assert tool.name == TOOL_NAME
    # The injected runtime parameter stays out of the model-visible schema.
    assert "runtime" not in (tool.args or {})
    assert "skill_name" in (tool.args or {})


def test_tool_lists_the_callers_annotations_newest_first(monkeypatch, tmp_path) -> None:
    tool = _tool(monkeypatch, tmp_path)
    store = EvolvedSkillStore(tmp_path / "store.sqlite")
    store.save_annotation(owner="user-1", skill_name="demo-evolution", run_id="run-0001", event_id="evt-01", note="first note")
    store.save_annotation(owner="user-1", skill_name="demo-evolution", run_id="run-0002", event_id="evt-02", note="second note")
    with closing(store.connect()) as db, db:
        db.execute("UPDATE skill_annotations SET updated_at = ? WHERE run_id = 'run-0001'", ("2026-01-01 00:00:01",))
        db.execute("UPDATE skill_annotations SET updated_at = ? WHERE run_id = 'run-0002'", ("2026-01-01 00:00:02",))

    text = _call(tool, "user-1", "demo-evolution")

    assert "2 feedback note(s) for skill 'demo-evolution'" in text
    assert text.index("second note") < text.index("first note")
    assert "[run run-0002" in text


def test_tool_scopes_annotations_to_the_runtime_user(monkeypatch, tmp_path) -> None:
    tool = _tool(monkeypatch, tmp_path)
    store = EvolvedSkillStore(tmp_path / "store.sqlite")
    store.save_annotation(owner="user-2", skill_name="demo-evolution", run_id="run-0001", event_id="evt-01", note="someone else")

    text = _call(tool, "user-1", "demo-evolution")

    assert "No feedback notes" in text
    assert "someone else" not in text


def test_tool_reports_empty_and_never_raises(monkeypatch, tmp_path) -> None:
    tool = _tool(monkeypatch, tmp_path)
    assert "No feedback notes" in _call(tool, "user-1", "demo-evolution")
    # Invalid names degrade to guidance instead of an exception.
    assert "Invalid skill name" in _call(tool, "user-1", "Not A Name")


def test_tool_caps_its_output(monkeypatch, tmp_path) -> None:
    tool = _tool(monkeypatch, tmp_path)
    store = EvolvedSkillStore(tmp_path / "store.sqlite")
    for index in range(25):
        store.save_annotation(owner="user-1", skill_name="demo-evolution", run_id=f"run-{index:04d}", event_id=f"evt-{index:02d}", note=f"note {index}")
    text = _call(tool, "user-1", "demo-evolution")
    assert "25 feedback note(s)" in text
    assert "5 older note(s) omitted" in text


def test_build_fails_closed_without_the_host_seams(monkeypatch, tmp_path) -> None:
    monkeypatch.setitem(sys.modules, "deerflow.tools.types", None)
    with pytest.raises(RuntimeError, match="skill-evolution requires the host tool seams"):
        build_skill_feedback_tool(EvolvedSkillStore(tmp_path / "store.sqlite"))
