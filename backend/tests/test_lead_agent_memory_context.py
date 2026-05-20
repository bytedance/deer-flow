from unittest.mock import patch

from deerflow.agents.lead_agent.prompt import _get_memory_context
from deerflow.config.memory_config import MemoryConfig


def test_get_memory_context_uses_runtime_memory_context() -> None:
    with (
        patch("deerflow.agents.lead_agent.prompt.get_config", return_value={"configurable": {"memory_context": "DeerFlow retrieval"}}),
        patch("deerflow.config.memory_config.get_memory_config", return_value=MemoryConfig()),
        patch("deerflow.agents.memory.get_memory_data", return_value={"facts": []}),
        patch("deerflow.agents.memory.format_memory_for_injection", return_value="Facts:\n- [context | 0.90] DeerFlow retrieval works"),
    ):
        result = _get_memory_context(agent_name=None)

    assert "<memory>" in result
    assert "DeerFlow retrieval works" in result


def test_get_memory_context_forwards_explicit_context_hint() -> None:
    with (
        patch("deerflow.agents.lead_agent.prompt.get_config", return_value={}),
        patch("deerflow.config.memory_config.get_memory_config", return_value=MemoryConfig()),
        patch("deerflow.agents.memory.get_memory_data", return_value={"facts": []}),
        patch("deerflow.agents.memory.format_memory_for_injection", return_value="Facts:\n- [context | 0.90] explicit hint") as mock_format,
    ):
        _get_memory_context(agent_name=None, current_context="explicit hint")

    assert mock_format.call_args.kwargs["current_context"] == "explicit hint"
