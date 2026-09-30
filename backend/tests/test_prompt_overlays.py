"""Operator overlays preserve stock prompts and never format user-like braces."""

from unittest.mock import MagicMock

import pytest
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from deerflow.config.prompt_overlay import PromptOverlay


def test_default_overlay_is_byte_identical():
    assert PromptOverlay().apply(" \nstock\n ") == " \nstock\n "


def test_overlay_is_literal_and_keeps_core():
    assert PromptOverlay(prepend="before {unknown}", append="after {conversation}").apply("core") == "before {unknown}\n\ncore\n\nafter {conversation}"


def test_invalid_overlay_rejected():
    with pytest.raises(ValidationError):
        PromptOverlay(prepend={"not": "text"})


def test_lead_overlay_uses_explicit_snapshot_and_does_not_accumulate(monkeypatch):
    from deerflow.agents.lead_agent import prompt as module
    from deerflow.config.app_config import AppConfig
    from deerflow.config.sandbox_config import SandboxConfig

    config = AppConfig(sandbox=SandboxConfig(use="test"))
    for helper in ("get_agent_soul", "get_skills_prompt_section", "get_deferred_tools_prompt_section", "_build_acp_section", "_build_custom_mounts_section", "_build_memory_tool_section"):
        monkeypatch.setattr(module, helper, lambda *args, **kwargs: "")
    stock = module.apply_prompt_template(app_config=config)
    configured = config.model_copy(update={"lead_prompt_overlay": PromptOverlay(prepend="规则 {unbound}", append="tail")})
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)
    expected = "规则 {unbound}\n\n" + stock + "\n\ntail"
    assert module.apply_prompt_template(app_config=configured) == expected
    assert module.apply_prompt_template(app_config=configured) == expected
    assert module.apply_prompt_template(app_config=config) == stock
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: configured)
    assert module.apply_prompt_template() == expected


@pytest.mark.parametrize("name", ["general-purpose", "bash"])
def test_builtin_overlay_does_not_mutate_registry(name):
    from deerflow.config.subagents_config import SubagentsAppConfig
    from deerflow.subagents.builtins import BUILTIN_SUBAGENTS
    from deerflow.subagents.registry import get_subagent_config

    original = BUILTIN_SUBAGENTS[name].system_prompt
    config = SubagentsAppConfig(agents={name: {"prompt_overlay": {"prepend": "First rule", "append": "Operator rule"}}})
    first = get_subagent_config(name, app_config=config)
    second = get_subagent_config(name, app_config=config)
    assert first.system_prompt == second.system_prompt == original
    assert first.prompt_overlay.apply("assembled") == "First rule\n\nassembled\n\nOperator rule"
    assert second.prompt_overlay == first.prompt_overlay
    assert BUILTIN_SUBAGENTS[name].system_prompt == original
    assert get_subagent_config(name, app_config=SubagentsAppConfig()).system_prompt == original


def test_memory_overlay_only_modifies_system_authority():
    from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
    from deerflow.agents.memory.backends.deermem.deermem.core.updater import MemoryUpdater

    storage = MagicMock()
    base = MemoryUpdater(DeerMemConfig(), storage)
    configured = MemoryUpdater(DeerMemConfig(prompt_prepend="before {conversation}", prompt_append="after {unknown}"), storage)
    for updater in (base, configured):
        updater.get_memory_data = lambda *args, **kwargs: {"facts": []}
    messages = [HumanMessage(content="Remember my preference for green.")]
    _, stock = base._prepare_update_prompt(messages, None, frozenset())
    _, rendered = configured._prepare_update_prompt(messages, None, frozenset())
    assert isinstance(rendered[0], SystemMessage)
    assert rendered[0].content == "before {conversation}\n\n" + stock[0].content + "\n\nafter {unknown}"
    assert rendered[1:] == stock[1:]
    _, again = configured._prepare_update_prompt(messages, None, frozenset())
    assert again == rendered
    _, still_stock = base._prepare_update_prompt(messages, None, frozenset())
    assert still_stock == stock


def test_memory_overlay_requires_system_message(monkeypatch):
    from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
    from deerflow.agents.memory.backends.deermem.deermem.core import updater as module

    monkeypatch.setattr(module, "load_prompt_messages", lambda *args, **kwargs: [HumanMessage(content="data")])
    updater = module.MemoryUpdater(DeerMemConfig(prompt_append="trusted rule"), MagicMock())
    updater.get_memory_data = lambda *args, **kwargs: {"facts": []}
    with pytest.raises(ValueError, match="require a system message"):
        updater._prepare_update_prompt([HumanMessage(content="conversation")], None, frozenset())
