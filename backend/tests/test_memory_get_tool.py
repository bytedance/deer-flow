"""Exact fact recall through the tool-mode memory boundary."""

import json
from types import SimpleNamespace

import pytest

from deerflow.agents.memory import tools
from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem
from deerflow.agents.memory.backends.noop.noop_manager import NoopMemoryManager
from deerflow.agents.memory.manager import MemoryManager


def _get(runtime, fact_id):
    return json.loads(tools.memory_get_tool.func(runtime, fact_id))


def test_get_is_registered_with_runtime_hidden():
    registered = {tool.name: tool for tool in tools.get_memory_tools()}
    assert "memory_get" in registered
    assert set(registered["memory_get"].tool_call_schema.model_fields) == {"fact_id"}


@pytest.mark.parametrize("agent_name", [None, "research"])
def test_get_reads_only_the_runtime_user_and_agent(tmp_path, monkeypatch, agent_name):
    monkeypatch.setenv("DEERMEM_DATA_DIR", str(tmp_path))
    manager = DeerMem(backend_config={"retrieval_adapter": ""})
    monkeypatch.setattr(tools, "get_memory_manager", lambda: manager)
    document, fact_id = manager.create_fact("Prefers Python", user_id="alice", agent_name=agent_name)
    fact = next(fact for fact in document["facts"] if fact["id"] == fact_id)
    runtime = SimpleNamespace(server_info=SimpleNamespace(user=SimpleNamespace(identity="alice")), context={"user_id": "bob", "agent_name": agent_name})
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}

    assert _get(runtime, fact_id) == {"fact": fact}
    assert _get(runtime, "missing") == {"error": "Fact not found: missing"}
    for context in (
        {"user_id": "bob", "agent_name": agent_name},
        {"user_id": "alice", "agent_name": "other-agent"},
    ):
        assert _get(SimpleNamespace(context=context), fact_id) == {"error": f"Fact not found: {fact_id}"}
    assert all(path.read_bytes() == content for path, content in before.items())


def test_get_matches_id_exactly_and_preserves_unicode(monkeypatch):
    fact = {"id": "fact_1", "content": "喜欢 Python", "category": "preference", "confidence": 0.9}
    manager = SimpleNamespace(get_memory=lambda **kwargs: {"facts": [{"id": "fact_10", "content": "other"}, fact]})
    monkeypatch.setattr(tools, "get_memory_manager", lambda: manager)
    assert _get(SimpleNamespace(context={}), "fact_1") == {"fact": fact}
    assert _get(SimpleNamespace(context={}), "fact_") == {"error": "Fact not found: fact_"}


def test_get_unsupported_backend_returns_error(monkeypatch):
    class UnsupportedReadBackend(NoopMemoryManager):
        get_memory = MemoryManager.get_memory

    monkeypatch.setattr(tools, "get_memory_manager", lambda: UnsupportedReadBackend())
    assert _get(SimpleNamespace(context={}), "fact_1") == {"error": "memory backend UnsupportedReadBackend does not support get_memory"}


def test_get_rejects_unsupported_agent_scope_before_reading(monkeypatch):
    def unexpected_read(**kwargs):
        pytest.fail("An unscoped backend must not read a named agent's facts")

    monkeypatch.setattr(tools, "get_memory_manager", lambda: SimpleNamespace(get_memory=unexpected_read))
    result = _get(SimpleNamespace(context={"agent_name": "research"}), "fact_1")
    assert "does not support agent-scoped memory reads" in result["error"]


def test_get_backend_failure_returns_error(monkeypatch):
    def failed_read(**kwargs):
        raise RuntimeError("read failed")

    monkeypatch.setattr(tools, "get_memory_manager", lambda: SimpleNamespace(get_memory=failed_read))
    assert _get(SimpleNamespace(context={}), "fact_1") == {"error": "read failed"}
