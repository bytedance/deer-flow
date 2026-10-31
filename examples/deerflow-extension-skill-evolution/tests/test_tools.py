import importlib
import sys
import types

import pytest
from langchain_core.tools import StructuredTool

from deerflow_extension_skill_evolution.tools import resolve_skill_manage_tool


def _fake_skill_manage_tool() -> StructuredTool:
    def _run(action: str, name: str = "", content: str = "") -> str:
        return "ok"

    return StructuredTool.from_function(func=_run, name="skill_manage", description="fake host tool")


def _stub_host_tool_module(monkeypatch: pytest.MonkeyPatch, tool_object) -> None:
    leaf = types.ModuleType("deerflow.tools.skill_manage_tool")
    leaf.skill_manage_tool = tool_object
    monkeypatch.setitem(sys.modules, "deerflow.tools.skill_manage_tool", leaf)


def test_resolve_returns_host_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = _fake_skill_manage_tool()
    _stub_host_tool_module(monkeypatch, tool)
    assert resolve_skill_manage_tool() is tool


def test_resolve_fails_loudly_when_host_lacks_the_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = importlib.import_module

    def fake_import(name, *args, **kwargs):
        if name == "deerflow.tools.skill_manage_tool":
            raise ImportError("No module named 'deerflow' (simulated)")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", fake_import)
    with pytest.raises(RuntimeError, match="skill_manage") as exc_info:
        resolve_skill_manage_tool()
    assert "disable this extension" in str(exc_info.value)


def test_resolve_rejects_a_missing_attribute(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "deerflow.tools.skill_manage_tool", types.ModuleType("deerflow.tools.skill_manage_tool"))
    with pytest.raises(RuntimeError, match="no longer exports"):
        resolve_skill_manage_tool()


def test_resolve_rejects_a_wrong_shaped_object(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_host_tool_module(monkeypatch, object())
    with pytest.raises(RuntimeError, match="BaseTool"):
        resolve_skill_manage_tool()


def test_resolve_rejects_a_misnamed_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    def _run(action: str) -> str:
        return "ok"

    _stub_host_tool_module(monkeypatch, StructuredTool.from_function(func=_run, name="other_tool", description="wrong"))
    with pytest.raises(RuntimeError, match="skill_manage"):
        resolve_skill_manage_tool()
