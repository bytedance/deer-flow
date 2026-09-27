"""Display labels survive bootstrap and accept only safe Unicode text."""

from types import SimpleNamespace

import pytest
import yaml
from pydantic import ValidationError
from sqlalchemy import create_engine

from app.gateway.routers.agents import AgentCreateRequest, AgentUpdateRequest
from deerflow.config.agents_config import AgentConfig
from deerflow.persistence.agents.base import parse_agent_config
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
@pytest.mark.parametrize("codepoint", [*range(0x20), *range(0x7F, 0xA0), 0xAD, 0x61C, 0x200B, 0x200E, 0x200F, *range(0x2028, 0x202F), *range(0x2060, 0x206A), 0xFEFF])
def test_display_name_rejects_controls(model, codepoint):
    for value in [f"a{chr(codepoint)}b", f"{chr(codepoint)}name", f"name{chr(codepoint)}"]:
        with pytest.raises(ValidationError):
            model(name="reviewer", display_name=value)


@pytest.mark.parametrize("model", [AgentConfig, AgentCreateRequest, AgentUpdateRequest])
@pytest.mark.parametrize("value", ["🦌" * 100, "代码审查助手", "مراجع الكود", "می\u200cروم", "👩‍💻", "e\u0301"])
def test_display_name_accepts_multilingual_text(model, value):
    assert model(name="reviewer", display_name=f"  {value}  ").display_name == value
    with pytest.raises(ValidationError):
        model(name="reviewer", display_name="🦌" * 101)


@pytest.mark.parametrize("value", ["\u200b" * 3, "\u200c\u200d", "\ufe0f", "\u0301"])
def test_invisible_only_labels_are_rejected(value):
    with pytest.raises(ValidationError):
        AgentCreateRequest(name="reviewer", display_name=value)


@pytest.mark.parametrize("backend", ["file", "sql"])
@pytest.mark.parametrize("value", ["x" * 150, 123, "\u200b", "a\u200fb", ["invalid"]])
def test_invalid_stored_label_does_not_hide_or_break_agent(tmp_path, monkeypatch, backend, value):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    owner = "test-user-autouse"
    raw = {"display_name": value, "description": "healthy", "model": "gpt-x"}
    if backend == "file":
        store = FileAgentStore()
        config_file = tmp_path / "users" / owner / "agents" / "reviewer" / "config.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(yaml.safe_dump(raw), encoding="utf-8")
    else:
        url = f"sqlite:///{tmp_path}/agents.db"
        engine = create_engine(url)
        Base.metadata.create_all(engine, tables=[AgentRow.__table__])
        engine.dispose()
        store = SqlAgentStore(url)
        store.create("reviewer", raw, "old soul", user_id=owner)
    config = store.get("reviewer", user_id=owner)
    assert config.display_name is None
    assert config.description == "healthy"
    assert config.model == "gpt-x"
    assert store.list(user_id=owner)[0].name == "reviewer"
    assert store.list(user_id=owner)[0].display_name is None
    # Reads must not rewrite user-authored storage.
    if backend == "file":
        assert yaml.safe_load(config_file.read_text(encoding="utf-8")) == raw
    else:
        with store._Session() as session:
            assert session.query(AgentRow).one().config == raw
    monkeypatch.setattr("deerflow.tools.builtins.setup_agent_tool.get_agent_store", lambda: store)
    result = setup_agent.func(soul="new soul", description="rebootstrapped", runtime=SimpleNamespace(context={"agent_name": "reviewer"}, tool_call_id="test"))
    assert result.update["created_agent_name"] == "reviewer"
    assert store.get_soul("reviewer", user_id=owner) == "new soul"


def test_stored_label_tolerance_does_not_mask_other_errors():
    with pytest.raises(ValidationError):
        parse_agent_config({"display_name": 123, "description": []}, "reviewer")
