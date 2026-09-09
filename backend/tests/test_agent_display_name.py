"""Display labels survive bootstrap and accept only safe Unicode text."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine

from app.gateway.routers.agents import AgentCreateRequest, AgentUpdateRequest
from deerflow.config.agents_config import AgentConfig
from deerflow.persistence.agents.file import FileAgentStore
from deerflow.persistence.agents.model import AgentRow
from deerflow.persistence.agents.sql import SqlAgentStore
from deerflow.persistence.base import Base
from deerflow.tools.builtins.setup_agent_tool import setup_agent


@pytest.mark.parametrize("backend", ["file", "sql"])
@pytest.mark.parametrize("display_name", ["代码审查助手", None])
def test_bootstrap_preserves_owner_display_name(tmp_path, monkeypatch, backend, display_name):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    if backend == "file":
        store = FileAgentStore()
    else:
        url = f"sqlite:///{tmp_path}/agents.db"
        engine = create_engine(url)
        Base.metadata.create_all(engine, tables=[AgentRow.__table__])
        engine.dispose()
        store = SqlAgentStore(url)
    monkeypatch.setattr("deerflow.tools.builtins.setup_agent_tool.get_agent_store", lambda: store)
    owner = "test-user-autouse"
    store.create("reviewer", {"display_name": display_name}, "old soul", user_id=owner)
    store.create("reviewer", {"display_name": "Other owner"}, "other soul", user_id="other")
    result = setup_agent.func(
        soul="new soul",
        description="rebootstrapped",
        skills=["test-skill"],
        runtime=SimpleNamespace(context={"agent_name": "reviewer"}, tool_call_id="test"),
    )
    assert result.update["created_agent_name"] == "reviewer"
    config = store.get("reviewer", user_id=owner)
    assert config.display_name == display_name
    assert config.description == "rebootstrapped"
    assert config.skills == ["test-skill"]
    assert store.get_soul("reviewer", user_id=owner) == "new soul"
    assert store.get("reviewer", user_id="other").display_name == "Other owner"


@pytest.mark.parametrize("model", [AgentConfig, AgentCreateRequest, AgentUpdateRequest])
@pytest.mark.parametrize("codepoint", [*range(0x20), *range(0x7F, 0xA0), *range(0x202A, 0x202F), *range(0x2066, 0x206A)])
def test_display_name_rejects_controls(model, codepoint):
    for value in [f"a{chr(codepoint)}b", f"{chr(codepoint)}name", f"name{chr(codepoint)}"]:
        with pytest.raises(ValidationError):
            model(name="reviewer", display_name=value)


@pytest.mark.parametrize("model", [AgentConfig, AgentCreateRequest, AgentUpdateRequest])
@pytest.mark.parametrize("value", ["🦌" * 100, "代码审查助手", "مراجع الكود", "👩‍💻", "e\u0301"])
def test_display_name_accepts_multilingual_text(model, value):
    assert model(name="reviewer", display_name=f"  {value}  ").display_name == value
    with pytest.raises(ValidationError):
        model(name="reviewer", display_name="🦌" * 101)
