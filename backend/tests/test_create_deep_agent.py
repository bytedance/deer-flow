"""Tests for create_deep_agent SDK entry point."""

from unittest.mock import MagicMock, patch

import pytest

from deerflow.agents.factory import create_deep_agent
from deerflow.agents.features import AgentFeatures, MemoryOptions, SubagentOptions, SummarizationOptions


def _make_mock_model():
    return MagicMock(name="mock_model")


def _make_mock_tool(name: str = "my_tool"):
    tool = MagicMock(name=name)
    tool.name = name
    return tool


# ---------------------------------------------------------------------------
# 1. Minimal creation — only model
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_minimal_creation(mock_create_agent):
    mock_create_agent.return_value = MagicMock(name="compiled_graph")
    model = _make_mock_model()

    result = create_deep_agent(model)

    mock_create_agent.assert_called_once()
    assert result is mock_create_agent.return_value
    call_kwargs = mock_create_agent.call_args[1]
    assert call_kwargs["model"] is model
    assert call_kwargs["system_prompt"] is None


# ---------------------------------------------------------------------------
# 2. With tools
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_with_tools(mock_create_agent):
    mock_create_agent.return_value = MagicMock()
    model = _make_mock_model()
    tool = _make_mock_tool("search")

    create_deep_agent(model, tools=[tool])

    call_kwargs = mock_create_agent.call_args[1]
    tool_names = [t.name for t in call_kwargs["tools"]]
    assert "search" in tool_names


# ---------------------------------------------------------------------------
# 3. With system_prompt
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_with_system_prompt(mock_create_agent):
    mock_create_agent.return_value = MagicMock()
    prompt = "You are a helpful assistant."

    create_deep_agent(_make_mock_model(), system_prompt=prompt)

    call_kwargs = mock_create_agent.call_args[1]
    assert call_kwargs["system_prompt"] == prompt


# ---------------------------------------------------------------------------
# 4. Features mode — auto-assemble middleware chain
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_features_mode(mock_create_agent):
    mock_create_agent.return_value = MagicMock()
    feat = AgentFeatures(sandbox=True, loop_detection=True, auto_title=True)

    create_deep_agent(_make_mock_model(), features=feat)

    call_kwargs = mock_create_agent.call_args[1]
    middleware = call_kwargs["middleware"]
    assert len(middleware) > 0
    # Verify middleware types are present
    mw_types = [type(m).__name__ for m in middleware]
    assert "ThreadDataMiddleware" in mw_types
    assert "SandboxMiddleware" in mw_types
    assert "LoopDetectionMiddleware" in mw_types
    assert "TitleMiddleware" in mw_types
    assert "ClarificationMiddleware" in mw_types


# ---------------------------------------------------------------------------
# 5. Middleware full takeover
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_middleware_takeover(mock_create_agent):
    mock_create_agent.return_value = MagicMock()
    custom_mw = MagicMock(name="custom_middleware")
    custom_mw.name = "custom"

    create_deep_agent(_make_mock_model(), middleware=[custom_mw])

    call_kwargs = mock_create_agent.call_args[1]
    assert call_kwargs["middleware"] == [custom_mw]


# ---------------------------------------------------------------------------
# 6. Conflict — middleware + features raises ValueError
# ---------------------------------------------------------------------------
def test_middleware_and_features_conflict():
    with pytest.raises(ValueError, match="Cannot specify both"):
        create_deep_agent(
            _make_mock_model(),
            middleware=[MagicMock()],
            features=AgentFeatures(),
        )


# ---------------------------------------------------------------------------
# 7. Vision feature auto-injects view_image_tool
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_vision_injects_view_image_tool(mock_create_agent):
    mock_create_agent.return_value = MagicMock()
    feat = AgentFeatures(vision=True, sandbox=False, auto_title=False, loop_detection=False)

    create_deep_agent(_make_mock_model(), features=feat)

    call_kwargs = mock_create_agent.call_args[1]
    tool_names = [t.name for t in call_kwargs["tools"]]
    assert "view_image" in tool_names


# ---------------------------------------------------------------------------
# 8. Subagent feature auto-injects task_tool
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_subagent_injects_task_tool(mock_create_agent):
    mock_create_agent.return_value = MagicMock()
    feat = AgentFeatures(subagent=True, sandbox=False, auto_title=False, loop_detection=False)

    create_deep_agent(_make_mock_model(), features=feat)

    call_kwargs = mock_create_agent.call_args[1]
    tool_names = [t.name for t in call_kwargs["tools"]]
    assert "task" in tool_names


# ---------------------------------------------------------------------------
# 9. Middleware ordering — ClarificationMiddleware always last
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_clarification_always_last(mock_create_agent):
    mock_create_agent.return_value = MagicMock()
    feat = AgentFeatures(sandbox=True, memory=True, vision=True, loop_detection=True)

    create_deep_agent(_make_mock_model(), features=feat)

    call_kwargs = mock_create_agent.call_args[1]
    middleware = call_kwargs["middleware"]
    last_mw = middleware[-1]
    assert type(last_mw).__name__ == "ClarificationMiddleware"


# ---------------------------------------------------------------------------
# 10. AgentFeatures default values
# ---------------------------------------------------------------------------
def test_agent_features_defaults():
    f = AgentFeatures()
    assert f.sandbox is True
    assert f.memory is False
    assert f.summarization is False
    assert f.plan_mode is False
    assert f.subagent is False
    assert f.vision is False
    assert f.auto_title is True
    assert f.loop_detection is True
    assert f.extra_middleware == []


# ---------------------------------------------------------------------------
# 11. Tool deduplication — user-provided tools take priority
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_tool_deduplication(mock_create_agent):
    """If user provides a tool with the same name as an auto-injected one, no duplicate."""
    mock_create_agent.return_value = MagicMock()
    user_clarification = _make_mock_tool("ask_clarification")

    create_deep_agent(_make_mock_model(), tools=[user_clarification], features=AgentFeatures(sandbox=False, auto_title=False, loop_detection=False))

    call_kwargs = mock_create_agent.call_args[1]
    names = [t.name for t in call_kwargs["tools"]]
    assert names.count("ask_clarification") == 1
    # The first one should be the user-provided tool
    assert call_kwargs["tools"][0] is user_clarification


# ---------------------------------------------------------------------------
# 12. Sandbox disabled — no ThreadData/Uploads/Sandbox middleware
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_sandbox_disabled(mock_create_agent):
    mock_create_agent.return_value = MagicMock()
    feat = AgentFeatures(sandbox=False, auto_title=False, loop_detection=False)

    create_deep_agent(_make_mock_model(), features=feat)

    call_kwargs = mock_create_agent.call_args[1]
    mw_types = [type(m).__name__ for m in call_kwargs["middleware"]]
    assert "ThreadDataMiddleware" not in mw_types
    assert "UploadsMiddleware" not in mw_types
    assert "SandboxMiddleware" not in mw_types


# ---------------------------------------------------------------------------
# 13. Checkpointer passed through
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_checkpointer_passthrough(mock_create_agent):
    mock_create_agent.return_value = MagicMock()
    cp = MagicMock(name="checkpointer")

    create_deep_agent(_make_mock_model(), checkpointer=cp)

    call_kwargs = mock_create_agent.call_args[1]
    assert call_kwargs["checkpointer"] is cp


# ---------------------------------------------------------------------------
# 14. SubagentOptions max_concurrent
# ---------------------------------------------------------------------------
@patch("deerflow.agents.factory.create_agent")
def test_subagent_options_max_concurrent(mock_create_agent):
    mock_create_agent.return_value = MagicMock()
    feat = AgentFeatures(subagent=SubagentOptions(max_concurrent=2), sandbox=False, auto_title=False, loop_detection=False)

    create_deep_agent(_make_mock_model(), features=feat)

    call_kwargs = mock_create_agent.call_args[1]
    mw_types = {type(m).__name__: m for m in call_kwargs["middleware"]}
    assert "SubagentLimitMiddleware" in mw_types
    assert mw_types["SubagentLimitMiddleware"].max_concurrent == 2


# ---------------------------------------------------------------------------
# 15. Options dataclass defaults
# ---------------------------------------------------------------------------
def test_memory_options_defaults():
    opts = MemoryOptions()
    assert opts is not None  # Phase 1: empty enabler class


def test_summarization_options_defaults():
    opts = SummarizationOptions()
    assert opts.model is None
    assert opts.trigger is None
    assert opts.keep is None


def test_subagent_options_defaults():
    opts = SubagentOptions()
    assert opts.max_concurrent == 3
