import json
from collections import namedtuple
from unittest.mock import MagicMock, patch

import pytest

from src.graph.nodes import (
    _execute_agent_step,
    _setup_and_execute_agent_step,
    coordinator_node,
    human_feedback_node,
    planner_node,
    reporter_node,
    researcher_node,
    extract_plan_content,
)


class TestExtractPlanContent:
    """Test cases for the extract_plan_content function."""

    def test_extract_plan_content_with_string(self):
        """Test that extract_plan_content returns the input string as-is."""
        plan_json_str = '{"locale": "en-US", "has_enough_context": false, "title": "Test Plan"}'
        result = extract_plan_content(plan_json_str)
        assert result == plan_json_str

    def test_extract_plan_content_with_ai_message(self):
        """Test that extract_plan_content extracts content from an AIMessage-like object."""
        # Create a mock AIMessage object
        class MockAIMessage:
            def __init__(self, content):
                self.content = content
        
        plan_content = '{"locale": "zh-CN", "has_enough_context": false, "title": "测试计划"}'
        plan_message = MockAIMessage(plan_content)
        
        result = extract_plan_content(plan_message)
        assert result == plan_content

    def test_extract_plan_content_with_dict(self):
        """Test that extract_plan_content converts a dictionary to JSON string."""
        plan_dict = {
            "locale": "fr-FR",
            "has_enough_context": True,
            "title": "Plan de test",
            "steps": []
        }
        expected_json = json.dumps(plan_dict)
        
        result = extract_plan_content(plan_dict)
        assert result == expected_json

    def test_extract_plan_content_with_other_type(self):
        """Test that extract_plan_content converts other types to string."""
        plan_value = 12345
        expected_string = "12345"
        
        result = extract_plan_content(plan_value)
        assert result == expected_string

    def test_extract_plan_content_with_complex_dict(self):
        """Test that extract_plan_content handles complex nested dictionaries."""
        plan_dict = {
            "locale": "zh-CN",
            "has_enough_context": False,
            "title": "埃菲尔铁塔与世界最高建筑高度比较研究计划",
            "thought": "要回答埃菲尔铁塔比世界最高建筑高多少倍的问题，我们需要知道埃菲尔铁塔的高度以及当前世界最高建筑的高度。",
            "steps": [
                {
                    "need_search": True,
                    "title": "收集埃菲尔铁塔和世界最高建筑的高度数据",
                    "description": "从可靠来源检索埃菲尔铁塔的确切高度以及目前被公认为世界最高建筑的建筑物及其高度数据。",
                    "step_type": "research"
                },
                {
                    "need_search": True,
                    "title": "查找其他超高建筑作为对比基准",
                    "description": "获取其他具有代表性的超高建筑的高度数据，以提供更全面的比较背景。",
                    "step_type": "research"
                }
            ]
        }
        
        result = extract_plan_content(plan_dict)
        # Verify the result can be parsed back to a dictionary
        parsed_result = json.loads(result)
        assert parsed_result == plan_dict

    def test_extract_plan_content_with_non_string_content(self):
        """Test that extract_plan_content handles AIMessage with non-string content."""
        class MockAIMessageWithNonStringContent:
            def __init__(self, content):
                self.content = content
        
        # Test with non-string content (should not be extracted)
        plan_content = 12345
        plan_message = MockAIMessageWithNonStringContent(plan_content)
        
        result = extract_plan_content(plan_message)
        # Should convert the entire object to string since content is not a string
        assert isinstance(result, str)
        assert "MockAIMessageWithNonStringContent" in result

    def test_extract_plan_content_with_empty_string(self):
        """Test that extract_plan_content handles empty strings."""
        empty_string = ""
        result = extract_plan_content(empty_string)
        assert result == ""

    def test_extract_plan_content_with_empty_dict(self):
        """Test that extract_plan_content handles empty dictionaries."""
        empty_dict = {}
        expected_json = "{}"
        
        result = extract_plan_content(empty_dict)
        assert result == expected_json

    def test_extract_plan_content_with_content_dict(self):
        """Test that extract_plan_content handles dictionaries with content."""
        content_dict = {"content": {
                "locale": "zh-CN",
                "has_enough_context": False,
                "title": "埃菲尔铁塔与世界最高建筑高度比较研究计划",
                "thought": "要回答埃菲尔铁塔比世界最高建筑高多少倍的问题，我们需要知道埃菲尔铁塔的高度以及当前世界最高建筑的高度。",
                "steps": [
                    {
                        "need_search": True,
                        "title": "收集埃菲尔铁塔和世界最高建筑的高度数据",
                        "description": "从可靠来源检索埃菲尔铁塔的确切高度以及目前被公认为世界最高建筑的建筑物及其高度数据。",
                        "step_type": "research"
                    }
                ]
            }
        }
        
        result = extract_plan_content(content_dict)
        # Verify the result can be parsed back to a dictionary
        parsed_result = json.loads(result)
        assert parsed_result == content_dict["content"]

    def test_extract_plan_content_with_content_string(self):
        content_dict = {"content": '{"locale": "en-US", "title": "Test"}'}
        result = extract_plan_content(content_dict)
        assert result == '{"locale": "en-US", "title": "Test"}'

    def test_extract_plan_content_issue_703_case(self):
        """Test that extract_plan_content handles the specific case from issue #703."""
        # This is the exact structure that was causing the error in issue #703
        class MockAIMessageFromIssue703:
            def __init__(self, content):
                self.content = content
                self.additional_kwargs = {}
                self.response_metadata = {'finish_reason': 'stop', 'model_name': 'qwen-max-latest'}
                self.type = 'ai'
                self.id = 'run--ebc626af-3845-472b-aeee-acddebf5a4ea'
                self.example = False
                self.tool_calls = []
                self.invalid_tool_calls = []
        
        plan_content = '''{
            "locale": "zh-CN",
            "has_enough_context": false,
            "thought": "要回答埃菲尔铁塔比世界最高建筑高多少倍的问题，我们需要知道埃菲尔铁塔的高度以及当前世界最高建筑的高度。",
            "title": "埃菲尔铁塔与世界最高建筑高度比较研究计划",
            "steps": [
                {
                    "need_search": true,
                    "title": "收集埃菲尔铁塔和世界最高建筑的高度数据",
                    "description": "从可靠来源检索埃菲尔铁塔的确切高度以及目前被公认为世界最高建筑的建筑物及其高度数据。",
                    "step_type": "research"
                }
            ]
        }'''
        
        plan_message = MockAIMessageFromIssue703(plan_content)
        
        # Extract the content
        result = extract_plan_content(plan_message)
        
        # Verify the extracted content is the same as the original
        assert result == plan_content
        
        # Verify the extracted content can be parsed as JSON
        parsed_result = json.loads(result)
        assert parsed_result["locale"] == "zh-CN"
        assert parsed_result["title"] == "埃菲尔铁塔与世界最高建筑高度比较研究计划"
        assert len(parsed_result["steps"]) == 1
        assert parsed_result["steps"][0]["title"] == "收集埃菲尔铁塔和世界最高建筑的高度数据"

    def test_extract_plan_content_with_multimodal_list_issue_845(self):
        """Test that extract_plan_content handles multimodal message format (list type) from issue #845."""
        # This is the structure that causes ValidationError in issue #845
        # When content is a list like ['', ['XXXXXXXX']] from multimodal LLM models
        plan_json = '{"locale": "en-US", "has_enough_context": false, "title": "Test Plan", "steps": []}'
        content_dict_simple_list = {"content": [plan_json]}
        
        result = extract_plan_content(content_dict_simple_list)
        # Should extract the text content from the list
        assert result == plan_json
        # Verify it can be parsed as JSON
        parsed_result = json.loads(result)
        assert parsed_result["locale"] == "en-US"

    def test_extract_plan_content_with_multimodal_list_mixed_content(self):
        """Test multimodal list with mixed content (text and references)."""
        plan_json = '{"locale": "zh-CN", "title": "测试计划", "steps": []}'
        # Simulate multimodal format: ['text_content', ['reference1', 'reference2']]
        content_dict_mixed = {"content": [plan_json, ["ref1", "ref2"]]}
        
        result = extract_plan_content(content_dict_mixed)
        # Should extract only the text content, ignoring nested lists
        assert result == plan_json
        parsed_result = json.loads(result)
        assert parsed_result["title"] == "测试计划"

    def test_extract_plan_content_with_multimodal_content_blocks(self):
        """Test multimodal list with content block format."""
        plan_json = '{"locale": "en-US", "title": "Block Test", "steps": []}'
        # Simulate content block format: [{"type": "text", "text": "..."}]
        content_dict_blocks = {"content": [{"type": "text", "text": plan_json}]}
        
        result = extract_plan_content(content_dict_blocks)
        assert result == plan_json
        parsed_result = json.loads(result)
        assert parsed_result["title"] == "Block Test"

    def test_extract_plan_content_with_empty_multimodal_list(self):
        """Test multimodal list with empty or whitespace-only content."""
        # Simulate the case from issue #845: ['', ['XXXXXXXX']]
        content_dict_empty = {"content": ["", ["XXXXXXXX"]]}
        
        result = extract_plan_content(content_dict_empty)
        # Should fallback to JSON dump since no valid text content found
        assert isinstance(result, str)


# 在这里 mock 掉 get_llm_by_type，避免 ValueError
with patch("src.llms.llm.get_llm_by_type", return_value=MagicMock()):
    from langchain_core.messages import HumanMessage
    from langgraph.types import Command

    from src.config import SearchEngine
    from src.graph.nodes import background_investigation_node


# Mock data
MOCK_SEARCH_RESULTS = [
    {"title": "Test Title 1", "content": "Test Content 1"},
    {"title": "Test Title 2", "content": "Test Content 2"},
]


@pytest.fixture
def mock_state():
    return {
        "messages": [HumanMessage(content="test query")],
        "research_topic": "test query",
        "background_investigation_results": None,
    }


@pytest.fixture
def mock_configurable():
    mock = MagicMock()
    mock.max_search_results = 7
    return mock


@pytest.fixture
def mock_config():
    # 你可以根据实际需要返回一个 MagicMock 或 dict
    return MagicMock()


@pytest.fixture
def patch_config_from_runnable_config(mock_configurable):
    with patch(
        "src.graph.nodes.Configuration.from_runnable_config",
        return_value=mock_configurable,
    ):
        yield


@pytest.fixture
def mock_tavily_search():
    with patch("src.graph.nodes.LoggedTavilySearch") as mock:
        instance = mock.return_value
        instance.invoke.return_value = [
            {"title": "Test Title 1", "content": "Test Content 1"},
            {"title": "Test Title 2", "content": "Test Content 2"},
        ]
        yield mock


@pytest.fixture
def mock_web_search_tool():
    with patch("src.graph.nodes.get_web_search_tool") as mock:
        instance = mock.return_value
        instance.invoke.return_value = [
            {"title": "Test Title 1", "content": "Test Content 1"},
            {"title": "Test Title 2", "content": "Test Content 2"},
        ]
        yield mock


@pytest.mark.parametrize("search_engine", [SearchEngine.TAVILY.value, "other"])
def test_background_investigation_node_tavily(
    mock_state,
    mock_tavily_search,
    mock_web_search_tool,
    search_engine,
    patch_config_from_runnable_config,
    mock_config,
):
    """Test background_investigation_node with Tavily search engine"""
    with patch("src.graph.nodes.SELECTED_SEARCH_ENGINE", search_engine):
        result = background_investigation_node(mock_state, mock_config)

        # Verify the result structure
        assert isinstance(result, dict)

        # Verify the update contains background_investigation_results
        assert "background_investigation_results" in result

        # Parse and verify the JSON content
        results = result["background_investigation_results"]

        if search_engine == SearchEngine.TAVILY.value:
            mock_tavily_search.return_value.invoke.assert_called_once_with("test query")
            assert (
                results
                == "## Test Title 1\n\nTest Content 1\n\n## Test Title 2\n\nTest Content 2"
            )
        else:
            mock_web_search_tool.return_value.invoke.assert_called_once_with(
                "test query"
            )
            assert len(json.loads(results)) == 2


def test_background_investigation_node_malformed_response(
    mock_state, mock_tavily_search, patch_config_from_runnable_config, mock_config
):
    """Test background_investigation_node with malformed Tavily response"""
    with patch("src.graph.nodes.SELECTED_SEARCH_ENGINE", SearchEngine.TAVILY.value):
        # Mock a malformed response
        mock_tavily_search.return_value.invoke.return_value = "invalid response"

        result = background_investigation_node(mock_state, mock_config)

        # Verify the result structure
        assert isinstance(result, dict)

        # Verify the update contains background_investigation_results
        assert "background_investigation_results" in result

        # Parse and verify the JSON content
        results = result["background_investigation_results"]
        assert json.loads(results) == []


@pytest.fixture
def mock_plan():
    return {
        "has_enough_context": True,
        "title": "Test Plan",
        "thought": "Test Thought",
        "steps": [],
        "locale": "en-US",
    }


@pytest.fixture
def mock_state_planner():
    return {
        "messages": [HumanMessage(content="plan this")],
        "plan_iterations": 0,
        "enable_background_investigation": True,
        "background_investigation_results": "Background info",
    }


@pytest.fixture
def mock_configurable_planner():
    mock = MagicMock()
    mock.max_plan_iterations = 3
    mock.enable_deep_thinking = False
    return mock


@pytest.fixture
def patch_config_from_runnable_config_planner(mock_configurable_planner):
    with patch(
        "src.graph.nodes.Configuration.from_runnable_config",
        return_value=mock_configurable_planner,
    ):
        yield


@pytest.fixture
def patch_apply_prompt_template():
    with patch(
        "src.graph.nodes.apply_prompt_template",
        return_value=[{"role": "user", "content": "plan this"}],
    ) as mock:
        yield mock


@pytest.fixture
def patch_repair_json_output():
    with patch("src.graph.nodes.repair_json_output", side_effect=lambda x: x) as mock:
        yield mock


@pytest.fixture
def patch_plan_model_validate():
    with patch("src.graph.nodes.Plan.model_validate", side_effect=lambda x: x) as mock:
        yield mock


@pytest.fixture
def patch_ai_message():
    AIMessage = namedtuple("AIMessage", ["content", "name"])
    with patch(
        "src.graph.nodes.AIMessage",
        side_effect=lambda content, name: AIMessage(content, name),
    ) as mock:
        yield mock


def test_planner_node_basic_has_enough_context(
    mock_state_planner,
    patch_config_from_runnable_config_planner,
    patch_apply_prompt_template,
    patch_repair_json_output,
    patch_plan_model_validate,
    patch_ai_message,
    mock_plan,
):
    # AGENT_LLM_MAP["planner"] == "basic" and not thinking mode
    with (
        patch("src.graph.nodes.AGENT_LLM_MAP", {"planner": "basic"}),
        patch("src.graph.nodes.get_llm_by_type") as mock_get_llm,
    ):
        mock_llm = MagicMock()
        mock_llm.with_structured_output.return_value = mock_llm
        mock_response = MagicMock()
        mock_response.model_dump_json.return_value = json.dumps(mock_plan)
        mock_llm.invoke.return_value = mock_response
        mock_get_llm.return_value = mock_llm

        result = planner_node(mock_state_planner, MagicMock())
        assert isinstance(result, Command)
        assert result.goto == "reporter"
        assert "current_plan" in result.update
        assert result.update["current_plan"]["has_enough_context"] is True
        assert result.update["messages"][0].name == "planner"


def test_planner_node_basic_not_enough_context(
    mock_state_planner,
    patch_config_from_runnable_config_planner,
    patch_apply_prompt_template,
    patch_repair_json_output,
    patch_plan_model_validate,
    patch_ai_message,
):
    # AGENT_LLM_MAP["planner"] == "basic" and not thinking mode
    plan = {
        "has_enough_context": False,
        "title": "Test Plan",
        "thought": "Test Thought",
        "steps": [],
        "locale": "en-US",
    }
    with (
        patch("src.graph.nodes.AGENT_LLM_MAP", {"planner": "basic"}),
        patch("src.graph.nodes.get_llm_by_type") as mock_get_llm,
    ):
        mock_llm = MagicMock()
        mock_llm.with_structured_output.return_value = mock_llm
        mock_response = MagicMock()
        mock_response.model_dump_json.return_value = json.dumps(plan)
        mock_llm.invoke.return_value = mock_response
        mock_get_llm.return_value = mock_llm

        result = planner_node(mock_state_planner, MagicMock())
        assert isinstance(result, Command)
        assert result.goto == "human_feedback"
        assert "current_plan" in result.update
        assert isinstance(result.update["current_plan"], str)
        assert result.update["messages"][0].name == "planner"


def test_planner_node_stream_mode_has_enough_context(
    mock_state_planner,
    patch_config_from_runnable_config_planner,
    patch_apply_prompt_template,
    patch_repair_json_output,
    patch_plan_model_validate,
    patch_ai_message,
    mock_plan,
):
    # AGENT_LLM_MAP["planner"] != "basic"
    with (
        patch("src.graph.nodes.AGENT_LLM_MAP", {"planner": "other"}),
        patch("src.graph.nodes.get_llm_by_type") as mock_get_llm,
    ):
        mock_llm = MagicMock()
        # Simulate streaming chunks
        chunk = MagicMock()
        chunk.content = json.dumps(mock_plan)
        mock_llm.stream.return_value = [chunk]
        mock_get_llm.return_value = mock_llm

        result = planner_node(mock_state_planner, MagicMock())
        assert isinstance(result, Command)
        assert result.goto == "reporter"
        assert "current_plan" in result.update
        assert result.update["current_plan"]["has_enough_context"] is True


def test_planner_node_stream_mode_not_enough_context(
    mock_state_planner,
    patch_config_from_runnable_config_planner,
    patch_apply_prompt_template,
    patch_repair_json_output,
    patch_plan_model_validate,
    patch_ai_message,
):
    # AGENT_LLM_MAP["planner"] != "basic"
    plan = {
        "has_enough_context": False,
        "title": "Test Plan",
        "thought": "Test Thought",
        "steps": [],
        "locale": "en-US",
    }
    with (
        patch("src.graph.nodes.AGENT_LLM_MAP", {"planner": "other"}),
        patch("src.graph.nodes.get_llm_by_type") as mock_get_llm,
    ):
        mock_llm = MagicMock()
        chunk = MagicMock()
        chunk.content = json.dumps(plan)
        mock_llm.stream.return_value = [chunk]
        mock_get_llm.return_value = mock_llm

        result = planner_node(mock_state_planner, MagicMock())
        assert isinstance(result, Command)
        assert result.goto == "human_feedback"
        assert "current_plan" in result.update
        assert isinstance(result.update["current_plan"], str)


def test_planner_node_plan_iterations_exceeded(mock_state_planner):
    # plan_iterations >= max_plan_iterations
    state = dict(mock_state_planner)
    state["plan_iterations"] = 5
    with (
        patch("src.graph.nodes.AGENT_LLM_MAP", {"planner": "basic"}),
        patch("src.graph.nodes.get_llm_by_type", return_value=MagicMock()),
    ):
        result = planner_node(state, MagicMock())
        assert isinstance(result, Command)
        assert result.goto == "reporter"


def test_planner_node_json_decode_error_first_iteration(mock_state_planner):
    # Simulate JSONDecodeError on first iteration
    with (
        patch("src.graph.nodes.AGENT_LLM_MAP", {"planner": "basic"}),
        patch("src.graph.nodes.get_llm_by_type") as mock_get_llm,
        patch(
            "src.graph.nodes.json.loads",
            side_effect=json.JSONDecodeError("err", "doc", 0),
        ),
    ):
        mock_llm = MagicMock()
        mock_llm.with_structured_output.return_value = mock_llm
        mock_response = MagicMock()
        mock_response.model_dump_json.return_value = '{"bad": "json"'
        mock_llm.invoke.return_value = mock_response
        mock_get_llm.return_value = mock_llm

        result = planner_node(mock_state_planner, MagicMock())
        assert isinstance(result, Command)
        assert result.goto == "__end__"


def test_planner_node_json_decode_error_second_iteration(mock_state_planner):
    # Simulate JSONDecodeError on second iteration
    state = dict(mock_state_planner)
    state["plan_iterations"] = 1
    with (
        patch("src.graph.nodes.AGENT_LLM_MAP", {"planner": "basic"}),
        patch("src.graph.nodes.get_llm_by_type") as mock_get_llm,
        patch(
            "src.graph.nodes.json.loads",
            side_effect=json.JSONDecodeError("err", "doc", 0),
        ),
    ):
        mock_llm = MagicMock()
        mock_llm.with_structured_output.return_value = mock_llm
        mock_response = MagicMock()
        mock_response.model_dump_json.return_value = '{"bad": "json"'
        mock_llm.invoke.return_value = mock_response
        mock_get_llm.return_value = mock_llm

        result = planner_node(state, MagicMock())
        assert isinstance(result, Command)
        assert result.goto == "reporter"


# Patch Plan.model_validate and repair_json_output globally for these tests
@pytest.fixture(autouse=True)
def patch_plan_and_repair(monkeypatch):
    monkeypatch.setattr("src.graph.nodes.Plan.model_validate", lambda x: x)
    monkeypatch.setattr("src.graph.nodes.repair_json_output", lambda x: x)
    yield


@pytest.fixture
def mock_state_base():
    return {
        "current_plan": json.dumps(
            {
                "has_enough_context": False,
                "title": "Test Plan",
                "thought": "Test Thought",
                "steps": [],
                "locale": "en-US",
            }
        ),
        "plan_iterations": 0,
    }


def test_human_feedback_node_auto_accepted(monkeypatch, mock_state_base, mock_config):
    # auto_accepted_plan True, should skip interrupt and parse plan
    state = dict(mock_state_base)
    state["auto_accepted_plan"] = True
    result = human_feedback_node(state, mock_config)
    assert isinstance(result, Command)
    assert result.goto == "research_team"
    assert result.update["plan_iterations"] == 1
    assert result.update["current_plan"]["has_enough_context"] is False


def test_human_feedback_node_edit_plan(monkeypatch, mock_state_base, mock_config):
    # interrupt returns [EDIT_PLAN]..., should return Command to planner
    state = dict(mock_state_base)
    state["auto_accepted_plan"] = False
    with patch("src.graph.nodes.interrupt", return_value="[EDIT_PLAN] Please revise"):
        result = human_feedback_node(state, mock_config)
        assert isinstance(result, Command)
        assert result.goto == "planner"
        assert result.update["messages"][0].name == "feedback"
        assert "[EDIT_PLAN]" in result.update["messages"][0].content


def test_human_feedback_node_accepted(monkeypatch, mock_state_base, mock_config):
    # interrupt returns [ACCEPTED]..., should proceed to parse plan
    state = dict(mock_state_base)
    state["auto_accepted_plan"] = False
    with patch("src.graph.nodes.interrupt", return_value="[ACCEPTED] Looks good!"):
        result = human_feedback_node(state, mock_config)
        assert isinstance(result, Command)
        assert result.goto == "research_team"
        assert result.update["plan_iterations"] == 1
        assert result.update["current_plan"]["has_enough_context"] is False


def test_human_feedback_node_invalid_interrupt(
    monkeypatch, mock_state_base, mock_config
):
    # interrupt returns something else, should gracefully return to planner (not raise TypeError)
    state = dict(mock_state_base)
    state["auto_accepted_plan"] = False
    with patch("src.graph.nodes.interrupt", return_value="RANDOM_FEEDBACK"):
        result = human_feedback_node(state, mock_config)
        assert isinstance(result, Command)
        assert result.goto == "planner"


def test_human_feedback_node_none_feedback(
    monkeypatch, mock_state_base, mock_config
):
    # interrupt returns None, should gracefully return to planner
    state = dict(mock_state_base)
    state["auto_accepted_plan"] = False
    with patch("src.graph.nodes.interrupt", return_value=None):
        result = human_feedback_node(state, mock_config)
        assert isinstance(result, Command)
        assert result.goto == "planner"


def test_human_feedback_node_empty_feedback(
    monkeypatch, mock_state_base, mock_config
):
    # interrupt returns empty string, should gracefully return to planner
    state = dict(mock_state_base)
    state["auto_accepted_plan"] = False
    with patch("src.graph.nodes.interrupt", return_value=""):
        result = human_feedback_node(state, mock_config)
        assert isinstance(result, Command)
        assert result.goto == "planner"


def test_human_feedback_node_json_decode_error_first_iteration(
    monkeypatch, mock_state_base, mock_config
):
    # repair_json_output returns bad json, json.loads raises JSONDecodeError, plan_iterations=0
    state = dict(mock_state_base)
    state["auto_accepted_plan"] = True
    state["plan_iterations"] = 0
    with patch(
        "src.graph.nodes.json.loads", side_effect=json.JSONDecodeError("err", "doc", 0)
    ):
        result = human_feedback_node(state, mock_config)
        assert isinstance(result, Command)
        assert result.goto == "__end__"


def test_human_feedback_node_json_decode_error_second_iteration(
    monkeypatch, mock_state_base, mock_config
):
    # repair_json_output returns bad json, json.loads raises JSONDecodeError, plan_iterations>0
    state = dict(mock_state_base)
    state["auto_accepted_plan"] = True
    state["plan_iterations"] = 2
    with patch(
        "src.graph.nodes.json.loads", side_effect=json.JSONDecodeError("err", "doc", 0)
    ):
        result = human_feedback_node(state, mock_config)
        assert isinstance(result, Command)
        assert result.goto == "reporter"


def test_human_feedback_node_not_enough_context(
    monkeypatch, mock_state_base, mock_config
):
    # Plan does not have enough context, should goto research_team
    plan = {
        "has_enough_context": False,
        "title": "Test Plan",
        "thought": "Test Thought",
        "steps": [],
        "locale": "en-US",
    }
    state = dict(mock_state_base)
    state["current_plan"] = json.dumps(plan)
    state["auto_accepted_plan"] = True
    result = human_feedback_node(state, mock_config)
    assert isinstance(result, Command)
    assert result.goto == "research_team"
    assert result.update["plan_iterations"] == 1
    assert result.update["current_plan"]["has_enough_context"] is False


@pytest.fixture
def mock_state_coordinator():
    return {
        "messages": [{"role": "user", "content": "test"}],
        "locale": "en-US",
        "enable_clarification": False,
    }


@pytest.fixture
def mock_configurable_coordinator():
    mock = MagicMock()
    mock.resources = ["resource1", "resource2"]
    return mock


@pytest.fixture
def patch_config_from_runnable_config_coordinator(mock_configurable_coordinator):
    with patch(
        "src.graph.nodes.Configuration.from_runnable_config",
        return_value=mock_configurable_coordinator,
    ):
        yield


@pytest.fixture
def patch_apply_prompt_template_coordinator():
    with patch(
        "src.graph.nodes.apply_prompt_template",
        return_value=[{"role": "user", "content": "test"}],
    ) as mock:
        yield mock


@pytest.fixture
def patch_handoff_to_planner():
    with patch("src.graph.nodes.handoff_to_planner", MagicMock()):
        yield


@pytest.fixture
def patch_logger():
    with patch("src.graph.nodes.logger") as mock_logger:
        yield mock_logger


def make_mock_llm_response(tool_calls=None):
    resp = MagicMock()
    resp.tool_calls = tool_calls or []
    return resp


def test_coordinator_node_no_tool_calls(
    mock_state_coordinator,
    patch_config_from_runnable_config_coordinator,
    patch_apply_prompt_template_coordinator,
    patch_handoff_to_planner,
    patch_logger,
):
    # No tool calls when clarification disabled - should end workflow (fix for issue #733)
    # When LLM doesn't call any tools in BRANCH 1, workflow ends gracefully
    with (
        patch("src.graph.nodes.AGENT_LLM_MAP", {"coordinator": "basic"}),
        patch("src.graph.nodes.get_llm_by_type") as mock_get_llm,
    ):
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.invoke.return_value = make_mock_llm_response([])
        mock_get_llm.return_value = mock_llm

        result = coordinator_node(mock_state_coordinator, MagicMock())
        # With direct_response tool available, no tool calls means end workflow
        assert result.goto == "__end__"
        assert result.update["locale"] == "en-US"
        assert result.update["resources"] == ["resource1", "resource2"]


def test_coordinator_node_with_tool_calls_planner(
    mock_state_coordinator,
    patch_config_from_runnable_config_coordinator,
    patch_apply_prompt_template_coordinator,
    patch_handoff_to_planner,
    patch_logger,
):
    # tool_calls present, should goto planner
    tool_calls = [{"name": "handoff_to_planner", "args": {}}]
    with (
        patch("src.graph.nodes.AGENT_LLM_MAP", {"coordinator": "basic"}),
        patch("src.graph.nodes.get_llm_by_type") as mock_get_llm,
    ):
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.invoke.return_value = make_mock_llm_response(tool_calls)
        mock_get_llm.return_value = mock_llm

        result = coordinator_node(mock_state_coordinator, MagicMock())
        assert result.goto == "planner"
        assert result.update["locale"] == "en-US"
        assert result.update["resources"] == ["resource1", "resource2"]


def test_coordinator_node_with_tool_calls_background_investigator(
    mock_state_coordinator,
    patch_config_from_runnable_config_coordinator,
    patch_apply_prompt_template_coordinator,
    patch_handoff_to_planner,
    patch_logger,
):
    # enable_background_investigation True, should goto background_investigator
    state = dict(mock_state_coordinator)
    state["enable_background_investigation"] = True
    tool_calls = [{"name": "handoff_to_planner", "args": {}}]
    with (
        patch("src.graph.nodes.AGENT_LLM_MAP", {"coordinator": "basic"}),
        patch("src.graph.nodes.get_llm_by_type") as mock_get_llm,
    ):
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.invoke.return_value = make_mock_llm_response(tool_calls)
        mock_get_llm.return_value = mock_llm

        result = coordinator_node(state, MagicMock())
        assert result.goto == "background_investigator"
        assert result.update["locale"] == "en-US"
        assert result.update["resources"] == ["resource1", "resource2"]


def test_coordinator_node_with_tool_calls_locale_override(
    mock_state_coordinator,
    patch_config_from_runnable_config_coordinator,
    patch_apply_prompt_template_coordinator,
    patch_handoff_to_planner,
    patch_logger,
):
    # tool_calls with locale in args should override locale
    tool_calls = [
        {
            "name": "handoff_to_planner",
            "args": {"locale": "auto", "research_topic": "test topic"},
        }
    ]
    with (
        patch("src.graph.nodes.AGENT_LLM_MAP", {"coordinator": "basic"}),
        patch("src.graph.nodes.get_llm_by_type") as mock_get_llm,
    ):
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.invoke.return_value = make_mock_llm_response(tool_calls)
        mock_get_llm.return_value = mock_llm

        result = coordinator_node(mock_state_coordinator, MagicMock())
        assert result.goto == "planner"
        assert result.update["locale"] == "en-US"
        assert result.update["research_topic"] == "test topic"
        assert result.update["resources"] == ["resource1", "resource2"]
        assert result.update["resources"] == ["resource1", "resource2"]


def test_coordinator_node_tool_calls_exception_handling(
    mock_state_coordinator,
    patch_config_from_runnable_config_coordinator,
    patch_apply_prompt_template_coordinator,
    patch_handoff_to_planner,
    patch_logger,
):
    with (
        patch("src.graph.nodes.AGENT_LLM_MAP", {"coordinator": "basic"}),
        patch("src.graph.nodes.get_llm_by_type") as mock_get_llm,
    ):
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm

        # Simulate tool_call.get("args", {}) raising AttributeError
        class BadToolCall(dict):
            def get(self, key, default=None):
                if key == "args":
                    raise Exception("bad args")
                return super().get(key, default)

        mock_llm.invoke.return_value = make_mock_llm_response(
            [BadToolCall({"name": "handoff_to_planner"})]
        )
        mock_get_llm.return_value = mock_llm

        # Should not raise, just log error and continue
        result = coordinator_node(mock_state_coordinator, MagicMock())
        assert result.goto == "planner"
        assert result.update["locale"] == "en-US"
        assert result.update["resources"] == ["resource1", "resource2"]


@pytest.fixture
def mock_state_reporter():
    # Simulate a plan object with title and thought attributes
    Plan = namedtuple("Plan", ["title", "thought"])
    return {
        "current_plan": Plan(title="Test Title", thought="Test Thought"),
        "locale": "en-US",
        "observations": [],
    }


@pytest.fixture
def mock_state_reporter_with_observations():
    Plan = namedtuple("Plan", ["title", "thought"])
    return {
        "current_plan": Plan(title="Test Title", thought="Test Thought"),
        "locale": "en-US",
        "observations": ["Observation 1", "Observation 2"],
    }


@pytest.fixture
def mock_configurable_reporter():
    mock = MagicMock()
    return mock


@pytest.fixture
def patch_config_from_runnable_config_reporter(mock_configurable_reporter):
    with patch(
        "src.graph.nodes.Configuration.from_runnable_config",
        return_value=mock_configurable_reporter,
    ):
        yield


@pytest.fixture
def patch_apply_prompt_template_reporter():
    with patch(
        "src.graph.nodes.apply_prompt_template",
        side_effect=lambda *args, **kwargs: [MagicMock()],
    ) as mock:
        yield mock


@pytest.fixture
def patch_human_message():
    HumanMessage = MagicMock()
    with patch("src.graph.nodes.HumanMessage", HumanMessage):
        yield HumanMessage


@pytest.fixture
def patch_logger_reporter():
    with patch("src.graph.nodes.logger") as mock_logger:
        yield mock_logger


def make_mock_llm_response_reporter(content):
    resp = MagicMock()
    resp.content = content
    return resp


def test_reporter_node_basic(
    mock_state_reporter,
    patch_config_from_runnable_config_reporter,
    patch_apply_prompt_template_reporter,
    patch_human_message,
    patch_logger_reporter,
):
    # Patch get_llm_by_type and AGENT_LLM_MAP
    with (
        patch("src.graph.nodes.AGENT_LLM_MAP", {"reporter": "basic"}),
        patch("src.graph.nodes.get_llm_by_type") as mock_get_llm,
    ):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = make_mock_llm_response_reporter(
            "Final Report Content"
        )
        mock_get_llm.return_value = mock_llm

        result = reporter_node(mock_state_reporter, MagicMock())
        assert isinstance(result, dict)
        assert "final_report" in result
        assert result["final_report"] == "Final Report Content"
        # Should call apply_prompt_template with correct arguments
        patch_apply_prompt_template_reporter.assert_called()
        # Should call invoke on the LLM
        mock_llm.invoke.assert_called()


def test_reporter_node_with_observations(
    mock_state_reporter_with_observations,
    patch_config_from_runnable_config_reporter,
    patch_apply_prompt_template_reporter,
    patch_human_message,
    patch_logger_reporter,
):
    with (
        patch("src.graph.nodes.AGENT_LLM_MAP", {"reporter": "basic"}),
        patch("src.graph.nodes.get_llm_by_type") as mock_get_llm,
    ):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = make_mock_llm_response_reporter(
            "Report with Observations"
        )
        mock_get_llm.return_value = mock_llm

        result = reporter_node(mock_state_reporter_with_observations, MagicMock())
        assert isinstance(result, dict)
        assert "final_report" in result
        assert result["final_report"] == "Report with Observations"
        # Should call apply_prompt_template with correct arguments
        patch_apply_prompt_template_reporter.assert_called()
        # Should call invoke on the LLM
        mock_llm.invoke.assert_called()


def test_reporter_node_locale_default(
    patch_config_from_runnable_config_reporter,
    patch_apply_prompt_template_reporter,
    patch_human_message,
    patch_logger_reporter,
):
    # If locale is missing, should default to "en-US"
    Plan = namedtuple("Plan", ["title", "thought"])
    state = {
        "current_plan": Plan(title="Test Title", thought="Test Thought"),
        # "locale" omitted
        "observations": [],
    }
    with (
        patch("src.graph.nodes.AGENT_LLM_MAP", {"reporter": "basic"}),
        patch("src.graph.nodes.get_llm_by_type") as mock_get_llm,
    ):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = make_mock_llm_response_reporter(
            "Default Locale Report"
        )
        mock_get_llm.return_value = mock_llm

        result = reporter_node(state, MagicMock())
        assert isinstance(result, dict)
        assert "final_report" in result
        assert result["final_report"] == "Default Locale Report"


# Create the real Step class for the tests
class Step:
    def __init__(self, title, description, execution_res=None):
        self.title = title
        self.description = description
        self.execution_res = execution_res


@pytest.fixture
def mock_step():
    return Step(title="Step 1", description="Desc 1", execution_res=None)


@pytest.fixture
def mock_completed_step():
    return Step(title="Step 0", description="Desc 0", execution_res="Done")


@pytest.fixture
def mock_state_with_steps(mock_step, mock_completed_step):
    # Simulate a plan with one completed and one unexecuted step
    Plan = MagicMock()
    Plan.steps = [mock_completed_step, mock_step]
    return {
        "current_plan": Plan,
        "observations": ["obs1"],
        "locale": "en-US",
        "resources": [],
    }


@pytest.fixture
def mock_state_no_unexecuted():
    Step = namedtuple("Step", ["title", "description", "execution_res"])
    Plan = MagicMock()
    Plan.steps = [
        Step(title="Step 1", description="Desc 1", execution_res="done"),
        Step(title="Step 2", description="Desc 2", execution_res="done"),
    ]
    return {
        "current_plan": Plan,
        "observations": [],
        "locale": "en-US",
        "resources": [],
    }


@pytest.fixture
def mock_agent():
    agent = MagicMock()

    async def ainvoke(input, config):
        # Simulate agent returning a message list
        return {"messages": [MagicMock(content="result content")]}

    async def astream(input, config, stream_mode):
        # Simulate agent.astream() yielding messages (async generator)
        yield {"messages": [MagicMock(content="result content")]}

    agent.ainvoke = ainvoke
    agent.astream = astream
    return agent


@pytest.mark.asyncio
async def test_execute_agent_step_basic(mock_state_with_steps, mock_agent):
    # Should execute the first unexecuted step and update execution_res
    with patch(
        "src.graph.nodes.HumanMessage",
        side_effect=lambda content, name=None: MagicMock(content=content, name=name),
    ):
        result = await _execute_agent_step(
            mock_state_with_steps, mock_agent, "researcher"
        )
        assert isinstance(result, Command)
        assert result.goto == "research_team"
        assert "messages" in result.update
        assert "observations" in result.update
        # The new observation should be appended
        assert result.update["observations"][-1] == "result content" + "\n\n[WARNING] This research was completed without using the web_search tool. " + "Please verify that the information provided is accurate and up-to-date." + "\n\n[VALIDATION WARNING] Researcher did not use the web_search tool as recommended."
        # The step's execution_res should be updated
        assert (
            mock_state_with_steps["current_plan"].steps[1].execution_res
            == "result content"
        )


@pytest.mark.asyncio
async def test_execute_agent_step_no_unexecuted_step(
    mock_state_no_unexecuted, mock_agent
):
    # Should return Command with goto="research_team" and not fail
    with patch("src.graph.nodes.logger") as mock_logger:
        result = await _execute_agent_step(
            mock_state_no_unexecuted, mock_agent, "researcher"
        )
        assert isinstance(result, Command)
        assert result.goto == "research_team"
        # Updated assertion to match new debug logging format
        mock_logger.warning.assert_called_once()
        assert "No unexecuted step found" in mock_logger.warning.call_args[0][0]


@pytest.mark.asyncio
async def test_execute_agent_step_with_resources_and_researcher(mock_step):
    # Should add resource info and citation reminder for researcher
    Resource = namedtuple("Resource", ["title", "description"])
    resources = [Resource(title="file1.txt", description="desc1")]
    Plan = MagicMock()
    Plan.steps = [mock_step]
    state = {
        "current_plan": Plan,
        "observations": [],
        "locale": "en-US",
        "resources": resources,
    }
    agent = MagicMock()

    async def ainvoke(input, config):
        # Check that resource info and citation reminder are present
        messages = input["messages"]
        assert any("local_search_tool" in m.content for m in messages)
        assert any("DO NOT include inline citations" in m.content for m in messages)
        return {"messages": [MagicMock(content="resource result")]}

    async def astream(input, config, stream_mode):
        # Simulate agent.astream() yielding messages (async generator)
        yield {"messages": [MagicMock(content="resource result")]}

    agent.ainvoke = ainvoke
    agent.astream = astream
    with patch(
        "src.graph.nodes.HumanMessage",
        side_effect=lambda content, name=None: MagicMock(content=content, name=name),
    ):
        result = await _execute_agent_step(state, agent, "researcher")
        assert isinstance(result, Command)
        assert result.goto == "research_team"
        assert result.update["observations"][-1] == "resource result" + "\n\n[WARNING] This research was completed without using the web_search tool. " + "Please verify that the information provided is accurate and up-to-date." + "\n\n[VALIDATION WARNING] Researcher did not use the web_search tool as recommended."


@pytest.mark.asyncio
async def test_execute_agent_step_recursion_limit_env(
    monkeypatch, mock_state_with_steps, mock_agent
):
    # Should respect AGENT_RECURSION_LIMIT env variable if set and valid
    monkeypatch.setenv("AGENT_RECURSION_LIMIT", "42")
    with (
        patch("src.graph.nodes.logger") as mock_logger,
        patch(
            "src.graph.nodes.HumanMessage",
            side_effect=lambda content, name=None: MagicMock(
                content=content, name=name
            ),
        ),
    ):
        result = await _execute_agent_step(mock_state_with_steps, mock_agent, "coder")
        assert isinstance(result, Command)
        mock_logger.info.assert_any_call("Recursion limit set to: 42")


@pytest.mark.asyncio
async def test_execute_agent_step_recursion_limit_env_invalid(
    monkeypatch, mock_state_with_steps, mock_agent
):
    # Should fallback to default if env variable is invalid
    monkeypatch.setenv("AGENT_RECURSION_LIMIT", "notanint")
    with (
        patch("src.graph.nodes.logger") as mock_logger,
        patch(
            "src.graph.nodes.HumanMessage",
            side_effect=lambda content, name=None: MagicMock(
                content=content, name=name
            ),
        ),
    ):
        result = await _execute_agent_step(mock_state_with_steps, mock_agent, "coder")
        assert isinstance(result, Command)
        mock_logger.warning.assert_any_call(
            "Invalid AGENT_RECURSION_LIMIT value: 'notanint'. Using default value 25."
        )


@pytest.mark.asyncio
async def test_execute_agent_step_recursion_limit_env_negative(
    monkeypatch, mock_state_with_steps, mock_agent
):
    # Should fallback to default if env variable is negative or zero
    monkeypatch.setenv("AGENT_RECURSION_LIMIT", "-5")
    with (
        patch("src.graph.nodes.logger") as mock_logger,
        patch(
            "src.graph.nodes.HumanMessage",
            side_effect=lambda content, name=None: MagicMock(
                content=content, name=name
            ),
        ),
    ):
        result = await _execute_agent_step(mock_state_with_steps, mock_agent, "coder")
        assert isinstance(result, Command)
        mock_logger.warning.assert_any_call(
            "AGENT_RECURSION_LIMIT value '-5' (parsed as -5) is not positive. Using default value 25."
        )


@pytest.fixture
def mock_configurable_with_mcp():
    mock = MagicMock()
    mock.mcp_settings = {
        "servers": {
            "server1": {
                "enabled_tools": ["toolA", "toolB"],
                "add_to_agents": ["researcher"],
                "transport": "http",
                "command": "run",
                "args": {},
                "url": "http://localhost",
                "env": {},
                "other": "ignore",
            }
        }
    }
    return mock


@pytest.fixture
def mock_configurable_without_mcp():
    mock = MagicMock()
    mock.mcp_settings = None
    return mock


@pytest.fixture
def patch_config_from_runnable_config_with_mcp(mock_configurable_with_mcp):
    with patch(
        "src.graph.nodes.Configuration.from_runnable_config",
        return_value=mock_configurable_with_mcp,
    ):
        yield


@pytest.fixture
def patch_config_from_runnable_config_without_mcp(mock_configurable_without_mcp):
    with patch(
        "src.graph.nodes.Configuration.from_runnable_config",
        return_value=mock_configurable_without_mcp,
    ):
        yield


@pytest.fixture
def patch_create_agent():
    with patch("src.graph.nodes.create_agent") as mock:
        yield mock


@pytest.fixture
def patch_execute_agent_step():
    async def fake_execute_agent_step(state, agent, agent_type, config=None):
        return "EXECUTED"

    with patch(
        "src.graph.nodes._execute_agent_step", side_effect=fake_execute_agent_step
    ) as mock:
        yield mock


@pytest.fixture
def patch_multiserver_mcp_client():
    # Patch MultiServerMCPClient as async context manager
    class FakeTool:
        def __init__(self, name, description="desc"):
            self.name = name
            self.description = description

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        async def get_tools(self):
            return [
                FakeTool("toolA", "descA"),
                FakeTool("toolB", "descB"),
                FakeTool("toolC", "descC"),
            ]

    with patch(
        "src.graph.nodes.MultiServerMCPClient", return_value=FakeClient()
    ) as mock:
        yield mock


@pytest.mark.asyncio
async def test_setup_and_execute_agent_step_with_mcp(
    mock_state_with_steps,
    mock_config,
    patch_config_from_runnable_config_with_mcp,
    patch_create_agent,
    patch_execute_agent_step,
    patch_multiserver_mcp_client,
):
    # Should use MCP client, load tools, and call create_agent with correct tools
    default_tools = [MagicMock(name="default_tool")]
    agent_type = "researcher"

    result = await _setup_and_execute_agent_step(
        mock_state_with_steps,
        mock_config,
        agent_type,
        default_tools,
    )
    # Should call create_agent with loaded_tools including toolA and toolB
    args, kwargs = patch_create_agent.call_args
    loaded_tools = args[2]
    tool_names = [t.name for t in loaded_tools if hasattr(t, "name")]
    assert "toolA" in tool_names
    assert "toolB" in tool_names
    # Should call _execute_agent_step
    patch_execute_agent_step.assert_called_once()
    assert result == "EXECUTED"


@pytest.mark.asyncio
async def test_setup_and_execute_agent_step_without_mcp(
    mock_state_with_steps,
    mock_config,
    patch_config_from_runnable_config_without_mcp,
    patch_create_agent,
    patch_execute_agent_step,
):
    # Should use default tools and not use MCP client
    default_tools = [MagicMock(name="default_tool")]
    agent_type = "coder"

    result = await _setup_and_execute_agent_step(
        mock_state_with_steps,
        mock_config,
        agent_type,
        default_tools,
    )
    # Should call create_agent with default_tools
    args, kwargs = patch_create_agent.call_args
    assert args[2] == default_tools
    patch_execute_agent_step.assert_called_once()
    assert result == "EXECUTED"


@pytest.mark.asyncio
async def test_setup_and_execute_agent_step_with_mcp_no_enabled_tools(
    mock_state_with_steps,
    mock_config,
    patch_create_agent,
    patch_execute_agent_step,
):
    # If mcp_settings present but no enabled_tools for agent_type, should fallback to default_tools
    mcp_settings = {
        "servers": {
            "server1": {
                "enabled_tools": ["toolA"],
                "add_to_agents": ["other_agent"],
                "transport": "http",
                "command": "run",
                "args": {},
                "url": "http://localhost",
                "env": {},
            }
        }
    }
    configurable = MagicMock()
    configurable.mcp_settings = mcp_settings
    with patch(
        "src.graph.nodes.Configuration.from_runnable_config",
        return_value=configurable,
    ):
        default_tools = [MagicMock(name="default_tool")]
        agent_type = "researcher"
        result = await _setup_and_execute_agent_step(
            mock_state_with_steps,
            mock_config,
            agent_type,
            default_tools,
        )
        args, kwargs = patch_create_agent.call_args
        assert args[2] == default_tools
        patch_execute_agent_step.assert_called_once()
        assert result == "EXECUTED"


@pytest.mark.asyncio
async def test_setup_and_execute_agent_step_with_mcp_tools_description_update(
    mock_state_with_steps,
    mock_config,
    patch_config_from_runnable_config_with_mcp,
    patch_create_agent,
    patch_execute_agent_step,
):
    # Should update tool.description with Powered by info
    default_tools = [MagicMock(name="default_tool")]
    agent_type = "researcher"

    # Patch MultiServerMCPClient to check description update
    class FakeTool:
        def __init__(self, name, description="desc"):
            self.name = name
            self.description = description

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        async def get_tools(self):
            return [FakeTool("toolA", "descA")]

    with patch("src.graph.nodes.MultiServerMCPClient", return_value=FakeClient()):
        await _setup_and_execute_agent_step(
            mock_state_with_steps,
            mock_config,
            agent_type,
            default_tools,
        )
        # The tool description should be updated
        args, kwargs = patch_create_agent.call_args
        loaded_tools = args[2]
        found = False
        for t in loaded_tools:
            if hasattr(t, "name") and t.name == "toolA":
                assert t.description.startswith("Powered by 'server1'.\n")
                found = True
        assert found


@pytest.fixture
def mock_state_with_resources():
    return {"resources": ["resource1", "resource2"], "other": "value"}


@pytest.fixture
def mock_state_without_resources():
    return {"other": "value"}


@pytest.fixture
def patch_get_web_search_tool():
    with patch("src.graph.nodes.get_web_search_tool") as mock:
        mock_tool = MagicMock(name="web_search_tool")
        mock.return_value = mock_tool
        yield mock


@pytest.fixture
def patch_crawl_tool():
    with patch("src.graph.nodes.crawl_tool", MagicMock(name="crawl_tool")):
        yield


@pytest.fixture
def patch_get_retriever_tool():
    with patch("src.graph.nodes.get_retriever_tool") as mock:
        yield mock


@pytest.fixture
def patch_setup_and_execute_agent_step():
    async def fake_setup_and_execute_agent_step(state, config, agent_type, tools):
        return "RESEARCHER_RESULT"

    with patch(
        "src.graph.nodes._setup_and_execute_agent_step",
        side_effect=fake_setup_and_execute_agent_step,
    ) as mock:
        yield mock


@pytest.mark.asyncio
async def test_researcher_node_with_retriever_tool(
    mock_state_with_resources,
    mock_config,
    patch_config_from_runnable_config,
    patch_get_web_search_tool,
    patch_crawl_tool,
    patch_get_retriever_tool,
    patch_setup_and_execute_agent_step,
):
    # Simulate retriever_tool is returned
    retriever_tool = MagicMock(name="retriever_tool")
    patch_get_retriever_tool.return_value = retriever_tool

    result = await researcher_node(mock_state_with_resources, mock_config)

    # Should call get_web_search_tool with correct max_search_results
    patch_get_web_search_tool.assert_called_once_with(7)
    # Should call get_retriever_tool with resources
    patch_get_retriever_tool.assert_called_once_with(["resource1", "resource2"])
    # Should call _setup_and_execute_agent_step with retriever_tool first
    args, kwargs = patch_setup_and_execute_agent_step.call_args
    tools = args[3]
    assert tools[0] == retriever_tool
    assert patch_get_web_search_tool.return_value in tools
    assert result == "RESEARCHER_RESULT"


@pytest.mark.asyncio
async def test_researcher_node_without_retriever_tool(
    mock_state_with_resources,
    mock_config,
    patch_config_from_runnable_config,
    patch_get_web_search_tool,
    patch_crawl_tool,
    patch_get_retriever_tool,
    patch_setup_and_execute_agent_step,
):
    # Simulate retriever_tool is None
    patch_get_retriever_tool.return_value = None

    result = await researcher_node(mock_state_with_resources, mock_config)

    patch_get_web_search_tool.assert_called_once_with(7)
    patch_get_retriever_tool.assert_called_once_with(["resource1", "resource2"])
    args, kwargs = patch_setup_and_execute_agent_step.call_args
    tools = args[3]
    # Should not include retriever_tool
    assert all(getattr(t, "name", None) != "retriever_tool" for t in tools)
    assert patch_get_web_search_tool.return_value in tools
    assert result == "RESEARCHER_RESULT"


@pytest.mark.asyncio
async def test_researcher_node_without_resources(
    mock_state_without_resources,
    mock_config,
    patch_config_from_runnable_config,
    patch_get_web_search_tool,
    patch_crawl_tool,
    patch_get_retriever_tool,
    patch_setup_and_execute_agent_step,
):
    patch_get_retriever_tool.return_value = None

    result = await researcher_node(mock_state_without_resources, mock_config)

    patch_get_web_search_tool.assert_called_once_with(7)
    patch_get_retriever_tool.assert_called_once_with([])
    args, kwargs = patch_setup_and_execute_agent_step.call_args
    tools = args[3]
    assert patch_get_web_search_tool.return_value in tools
    assert result == "RESEARCHER_RESULT"


# ============================================================================
# Clarification Feature Tests
# ============================================================================


@pytest.mark.asyncio
async def test_clarification_workflow_integration():
    """Test the complete clarification workflow integration."""
    import inspect

    from src.workflow import run_agent_workflow_async

    # Verify that the function accepts clarification parameters
    sig = inspect.signature(run_agent_workflow_async)
    assert "max_clarification_rounds" in sig.parameters
    assert "enable_clarification" in sig.parameters
    assert "initial_state" in sig.parameters


def test_clarification_parameters_combinations():
    """Test various combinations of clarification parameters."""
    from src.graph.nodes import needs_clarification

    test_cases = [
        # (enable_clarification, clarification_rounds, max_rounds, is_complete, expected)
        (True, 0, 3, False, False),  # No rounds started
        (True, 1, 3, False, True),  # In progress
        (True, 2, 3, False, True),  # In progress
        (True, 3, 3, False, True),  # At max - still waiting for last answer
        (True, 4, 3, False, False),  # Exceeded max
        (True, 1, 3, True, False),  # Completed
        (False, 1, 3, False, False),  # Disabled
    ]

    for enable, rounds, max_rounds, complete, expected in test_cases:
        state = {
            "enable_clarification": enable,
            "clarification_rounds": rounds,
            "max_clarification_rounds": max_rounds,
            "is_clarification_complete": complete,
        }

        result = needs_clarification(state)
        assert result == expected, f"Failed for case: {state}"


def test_handoff_tools():
    """Test that handoff tools are properly defined."""
    from src.graph.nodes import handoff_after_clarification, handoff_to_planner

    # Test handoff_to_planner tool - use invoke() method
    result = handoff_to_planner.invoke(
        {"research_topic": "renewable energy", "locale": "en-US"}
    )
    assert result is None  # Tool should return None (no-op)

    # Test handoff_after_clarification tool - use invoke() method
    result = handoff_after_clarification.invoke(
        {"locale": "en-US", "research_topic": "renewable energy research"}
    )
    assert result is None  # Tool should return None (no-op)


@patch("src.graph.nodes.get_llm_by_type")
def test_coordinator_tools_with_clarification_enabled(mock_get_llm):
    """Test that coordinator binds correct tools when clarification is enabled."""
    # Mock LLM response
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "Let me clarify..."
    mock_response.tool_calls = []
    mock_llm.bind_tools.return_value.invoke.return_value = mock_response
    mock_get_llm.return_value = mock_llm

    # State with clarification enabled (in progress)
    state = {
        "messages": [{"role": "user", "content": "Tell me about something"}],
        "enable_clarification": True,
        "clarification_rounds": 2,
        "max_clarification_rounds": 3,
        "is_clarification_complete": False,
        "clarification_history": [
            "Tell me about something",
            "response 1",
            "response 2",
        ],
        "locale": "en-US",
        "research_topic": "Tell me about something",
    }

    # Mock config
    config = {"configurable": {"resources": []}}

    # Call coordinator_node
    coordinator_node(state, config)

    # Verify that LLM was called with bind_tools
    assert mock_llm.bind_tools.called
    bound_tools = mock_llm.bind_tools.call_args[0][0]

    # Should bind 2 tools when clarification is enabled
    assert len(bound_tools) == 2
    tool_names = [tool.name for tool in bound_tools]
    assert "handoff_to_planner" in tool_names
    assert "handoff_after_clarification" in tool_names


@patch("src.graph.nodes.get_llm_by_type")
def test_coordinator_tools_with_clarification_disabled(mock_get_llm):
    """Test that coordinator binds two tools when clarification is disabled (fix for issue #733)."""
    # Mock LLM response with tool call
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = ""
    mock_response.tool_calls = [
        {
            "name": "handoff_to_planner",
            "args": {"research_topic": "test", "locale": "en-US"},
        }
    ]
    mock_llm.bind_tools.return_value.invoke.return_value = mock_response
    mock_get_llm.return_value = mock_llm

    # State with clarification disabled
    state = {
        "messages": [{"role": "user", "content": "Tell me about something"}],
        "enable_clarification": False,
        "locale": "en-US",
        "research_topic": "",
    }

    # Mock config
    config = {"configurable": {"resources": []}}

    # Call coordinator_node
    coordinator_node(state, config)

    # Verify that LLM was called with bind_tools
    assert mock_llm.bind_tools.called
    bound_tools = mock_llm.bind_tools.call_args[0][0]

    # Should bind 2 tools when clarification is disabled: handoff_to_planner and direct_response
    assert len(bound_tools) == 2
    tool_names = {tool.name for tool in bound_tools}
    assert "handoff_to_planner" in tool_names
    assert "direct_response" in tool_names


@patch("src.graph.nodes.get_llm_by_type")
def test_coordinator_empty_llm_response_corner_case(mock_get_llm):
    """
    Corner case test: LLM returns empty response when clarification is enabled.

    This tests error handling when LLM fails to return any content or tool calls
    in the initial state (clarification_rounds=0). The system should gracefully
    handle this by going to planner instead of crashing (fix for issue #535).

    Note: This is NOT a typical clarification workflow test, but rather tests
    fault tolerance when LLM misbehaves.
    """
    # Mock LLM response - empty response (failure scenario)
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = ""
    mock_response.tool_calls = []
    mock_llm.bind_tools.return_value.invoke.return_value = mock_response
    mock_get_llm.return_value = mock_llm

    # State with clarification enabled but initial round
    state = {
        "messages": [{"role": "user", "content": "test"}],
        "enable_clarification": True,
        # clarification_rounds: 0 (default, not started)
        "locale": "en-US",
        "research_topic": "",
    }

    # Mock config
    config = {"configurable": {"resources": []}}

    # Call coordinator_node - should not crash
    result = coordinator_node(state, config)

    # Should gracefully handle empty response by going to planner to ensure workflow continues
    assert result.goto == "planner"
    assert result.update["locale"] == "en-US"


# ============================================================================
# Clarification flow tests
# ============================================================================


def test_clarification_handoff_combines_history():
    """Coordinator should merge original topic with all clarification answers before handoff."""
    from langchain_core.messages import AIMessage
    from langchain_core.runnables import RunnableConfig

    test_state = {
        "messages": [
            {"role": "user", "content": "Research artificial intelligence"},
            {"role": "assistant", "content": "Which area of AI should we focus on?"},
            {"role": "user", "content": "Machine learning applications"},
            {"role": "assistant", "content": "What dimension of that should we cover?"},
            {"role": "user", "content": "Technical implementation details"},
        ],
        "enable_clarification": True,
        "clarification_rounds": 2,
        "clarification_history": [
            "Research artificial intelligence",
            "Machine learning applications",
            "Technical implementation details",
        ],
        "max_clarification_rounds": 3,
        "research_topic": "Research artificial intelligence",
        "clarified_research_topic": "Research artificial intelligence - Machine learning applications, Technical implementation details",
        "locale": "en-US",
    }

    config = RunnableConfig(configurable={"thread_id": "clarification-test"})

    mock_response = AIMessage(
        content="Understood, handing off now.",
        tool_calls=[
            {
                "name": "handoff_after_clarification",
                "args": {"locale": "en-US", "research_topic": "placeholder"},
                "id": "tool-call-handoff",
                "type": "tool_call",
            }
        ],
    )

    with patch("src.graph.nodes.get_llm_by_type") as mock_get_llm:
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value.invoke.return_value = mock_response
        mock_get_llm.return_value = mock_llm

        result = coordinator_node(test_state, config)

    assert hasattr(result, "update")
    update = result.update
    assert update["clarification_history"] == [
        "Research artificial intelligence",
        "Machine learning applications",
        "Technical implementation details",
    ]
    expected_topic = (
        "Research artificial intelligence - "
        "Machine learning applications, Technical implementation details"
    )
    assert update["research_topic"] == "Research artificial intelligence"
    assert update["clarified_research_topic"] == expected_topic


def test_clarification_history_reconstructed_from_messages():
    """Coordinator should rebuild clarification history from full message log when state is incomplete."""
    from langchain_core.messages import AIMessage
    from langchain_core.runnables import RunnableConfig

    incomplete_state = {
        "messages": [
            {"role": "user", "content": "Research on renewable energy"},
            {
                "role": "assistant",
                "content": "Which type of renewable energy interests you?",
            },
            {"role": "user", "content": "Solar and wind energy"},
            {"role": "assistant", "content": "Which aspect should we focus on?"},
            {"role": "user", "content": "Technical implementation"},
        ],
        "enable_clarification": True,
        "clarification_rounds": 2,
        "clarification_history": ["Technical implementation"],
        "max_clarification_rounds": 3,
        "research_topic": "Research on renewable energy",
        "clarified_research_topic": "Research on renewable energy",
        "locale": "en-US",
    }

    config = RunnableConfig(configurable={"thread_id": "clarification-history-rebuild"})

    mock_response = AIMessage(
        content="Understood, handing over now.",
        tool_calls=[
            {
                "name": "handoff_after_clarification",
                "args": {"locale": "en-US", "research_topic": "placeholder"},
                "id": "tool-call-handoff",
                "type": "tool_call",
            }
        ],
    )

    with patch("src.graph.nodes.get_llm_by_type") as mock_get_llm:
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value.invoke.return_value = mock_response
        mock_get_llm.return_value = mock_llm

        result = coordinator_node(incomplete_state, config)

    update = result.update
    assert update["clarification_history"] == [
        "Research on renewable energy",
        "Solar and wind energy",
        "Technical implementation",
    ]
    assert update["research_topic"] == "Research on renewable energy"
    assert (
        update["clarified_research_topic"]
        == "Research on renewable energy - Solar and wind energy, Technical implementation"
    )


def test_clarification_max_rounds_without_tool_call():
    """Coordinator should stop asking questions after max rounds and hand off with compiled topic."""
    from langchain_core.messages import AIMessage
    from langchain_core.runnables import RunnableConfig

    test_state = {
        "messages": [
            {"role": "user", "content": "Research artificial intelligence"},
            {"role": "assistant", "content": "Which area should we focus on?"},
            {"role": "user", "content": "Natural language processing"},
            {"role": "assistant", "content": "Which domain matters most?"},
            {"role": "user", "content": "Healthcare"},
            {"role": "assistant", "content": "Any specific scenario to study?"},
            {"role": "user", "content": "Clinical documentation"},
        ],
        "enable_clarification": True,
        "clarification_rounds": 3,
        "clarification_history": [
            "Research artificial intelligence",
            "Natural language processing",
            "Healthcare",
            "Clinical documentation",
        ],
        "max_clarification_rounds": 3,
        "research_topic": "Research artificial intelligence",
        "clarified_research_topic": "Research artificial intelligence - Natural language processing, Healthcare, Clinical documentation",
        "locale": "en-US",
    }

    config = RunnableConfig(configurable={"thread_id": "clarification-max"})

    mock_response = AIMessage(
        content="Got it, sending this to the planner.",
        tool_calls=[],
    )

    with patch("src.graph.nodes.get_llm_by_type") as mock_get_llm:
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value.invoke.return_value = mock_response
        mock_get_llm.return_value = mock_llm

        result = coordinator_node(test_state, config)

    assert hasattr(result, "update")
    update = result.update
    expected_topic = (
        "Research artificial intelligence - "
        "Natural language processing, Healthcare, Clinical documentation"
    )
    assert update["research_topic"] == "Research artificial intelligence"
    assert update["clarified_research_topic"] == expected_topic
    assert result.goto == "planner"


def test_clarification_human_message_support():
    """Coordinator should treat HumanMessage instances from the user as user authored."""
    from langchain_core.messages import AIMessage, HumanMessage
    from langchain_core.runnables import RunnableConfig

    test_state = {
        "messages": [
            HumanMessage(content="Research artificial intelligence"),
            HumanMessage(content="Which area should we focus on?", name="coordinator"),
            HumanMessage(content="Machine learning"),
            HumanMessage(
                content="Which dimension should we explore?", name="coordinator"
            ),
            HumanMessage(content="Technical feasibility"),
        ],
        "enable_clarification": True,
        "clarification_rounds": 2,
        "clarification_history": [
            "Research artificial intelligence",
            "Machine learning",
            "Technical feasibility",
        ],
        "max_clarification_rounds": 3,
        "research_topic": "Research artificial intelligence",
        "clarified_research_topic": "Research artificial intelligence - Machine learning, Technical feasibility",
        "locale": "en-US",
    }

    config = RunnableConfig(configurable={"thread_id": "clarification-human"})

    mock_response = AIMessage(
        content="Moving to planner.",
        tool_calls=[
            {
                "name": "handoff_after_clarification",
                "args": {"locale": "en-US", "research_topic": "placeholder"},
                "id": "human-message-handoff",
                "type": "tool_call",
            }
        ],
    )

    with patch("src.graph.nodes.get_llm_by_type") as mock_get_llm:
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value.invoke.return_value = mock_response
        mock_get_llm.return_value = mock_llm

        result = coordinator_node(test_state, config)

    assert hasattr(result, "update")
    update = result.update
    expected_topic = (
        "Research artificial intelligence - Machine learning, Technical feasibility"
    )
    assert update["clarification_history"] == [
        "Research artificial intelligence",
        "Machine learning",
        "Technical feasibility",
    ]
    assert update["research_topic"] == "Research artificial intelligence"
    assert update["clarified_research_topic"] == expected_topic


def test_clarification_no_history_defaults_to_topic():
    """If clarification never started, coordinator should forward the original topic."""
    from langchain_core.messages import AIMessage
    from langchain_core.runnables import RunnableConfig

    test_state = {
        "messages": [{"role": "user", "content": "What is quantum computing?"}],
        "enable_clarification": True,
        "clarification_rounds": 0,
        "clarification_history": ["What is quantum computing?"],
        "max_clarification_rounds": 3,
        "research_topic": "What is quantum computing?",
        "clarified_research_topic": "What is quantum computing?",
        "locale": "en-US",
    }

    config = RunnableConfig(configurable={"thread_id": "clarification-none"})

    mock_response = AIMessage(
        content="Understood.",
        tool_calls=[
            {
                "name": "handoff_to_planner",
                "args": {"locale": "en-US", "research_topic": "placeholder"},
                "id": "clarification-none",
                "type": "tool_call",
            }
        ],
    )

    with patch("src.graph.nodes.get_llm_by_type") as mock_get_llm:
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value.invoke.return_value = mock_response
        mock_get_llm.return_value = mock_llm

        result = coordinator_node(test_state, config)

    assert hasattr(result, "update")
    assert result.update["research_topic"] == "What is quantum computing?"
    assert result.update["clarified_research_topic"] == "What is quantum computing?"


# ============================================================================
# Issue #650: Pydantic validation errors (missing step_type field)
# ============================================================================


def test_planner_node_issue_650_missing_step_type_basic():
    """Test planner_node with missing step_type fields (Issue #650)."""
    from src.graph.nodes import validate_and_fix_plan

    # Simulate LLM response with missing step_type (Issue #650 scenario)
    llm_response = {
        "locale": "en-US",
        "has_enough_context": False,
        "thought": "Need to gather data",
        "title": "Test Plan",
        "steps": [
            {
                "need_search": True,
                "title": "Research Step",
                "description": "Gather info",
                # step_type MISSING - this is the issue
            },
            {
                "need_search": False,
                "title": "Processing Step",
                "description": "Analyze",
                # step_type MISSING
            },
        ],
    }

    # Apply the fix
    fixed_plan = validate_and_fix_plan(llm_response)

    # Verify all steps have step_type after fix
    assert isinstance(fixed_plan, dict)
    assert fixed_plan["steps"][0]["step_type"] == "research"
    # Issue #677: non-search steps now default to "analysis" instead of "processing"
    assert fixed_plan["steps"][1]["step_type"] == "analysis"
    assert all("step_type" in step for step in fixed_plan["steps"])


def test_planner_node_issue_650_water_footprint_scenario():
    """Test the exact water footprint query scenario from Issue #650."""
    from src.graph.nodes import validate_and_fix_plan

    # Approximate the exact plan structure that caused Issue #650
    # "How many liters of water are required to produce 1 kg of beef?"
    llm_response = {
        "locale": "en-US",
        "has_enough_context": False,
        "thought": "You asked about water footprint of beef - need comprehensive data gathering",
        "title": "Research Plan — Water Footprint of 1 kg of Beef",
        "steps": [
            {
                "need_search": True,
                "title": "Authoritative global estimates",
                "description": "Collect peer-reviewed estimates",
                # MISSING step_type
            },
            {
                "need_search": True,
                "title": "System-specific data",
                "description": "Gather system-level variation data",
                # MISSING step_type
            },
            {
                "need_search": False,
                "title": "Synthesize estimates",
                "description": "Calculate scenario-based estimates",
                # MISSING step_type
            },
        ],
    }

    # Apply the fix
    fixed_plan = validate_and_fix_plan(llm_response)

    # Verify structure - all steps should have step_type filled in
    assert len(fixed_plan["steps"]) == 3
    assert fixed_plan["steps"][0]["step_type"] == "research"
    assert fixed_plan["steps"][1]["step_type"] == "research"
    # Issue #677: non-search steps now default to "analysis" instead of "processing"
    assert fixed_plan["steps"][2]["step_type"] == "analysis"
    assert all("step_type" in step for step in fixed_plan["steps"])


def test_planner_node_issue_650_validation_error_fixed():
    """Test that the validation error from Issue #650 is now prevented."""
    from src.graph.nodes import validate_and_fix_plan

    # This is the exact type of response that caused the error in Issue #650
    malformed_response = {
        "locale": "en-US",
        "has_enough_context": False,
        "title": "Test",
        "thought": "Test",
        "steps": [
            {
                "need_search": True,
                "title": "Step 1",
                "description": "Test description",
                # Missing step_type - caused "Field required" error
            },
        ],
    }

    # Before fix would raise:
    # ValidationError: 1 validation error for Plan
    # steps.0.step_type Field required [type=missing, ...]

    # After fix should succeed without raising exception
    fixed = validate_and_fix_plan(malformed_response)

    # Verify the fix was applied
    assert fixed["steps"][0]["step_type"] in ["research", "processing"]
    assert "step_type" in fixed["steps"][0]


def test_human_feedback_node_issue_650_plan_parsing():
    """Test human_feedback_node with Issue #650 plan that has missing step_type."""
    from src.graph.nodes import human_feedback_node

    # Plan with missing step_type fields
    state = {
        "current_plan": json.dumps(
            {
                "locale": "en-US",
                "has_enough_context": False,
                "title": "Test Plan",
                "thought": "Test",
                "steps": [
                    {
                        "need_search": True,
                        "title": "Step 1",
                        "description": "Gather",
                        # MISSING step_type
                    },
                ],
            }
        ),
        "plan_iterations": 0,
        "auto_accepted_plan": True,
    }

    config = MagicMock()
    with patch(
        "src.graph.nodes.Configuration.from_runnable_config",
        return_value=MagicMock(enforce_web_search=False),
    ):
        with patch("src.graph.nodes.Plan.model_validate", side_effect=lambda x: x):
            with patch("src.graph.nodes.repair_json_output", side_effect=lambda x: x):
                result = human_feedback_node(state, config)

                # Should succeed without validation error
                assert isinstance(result, Command)
                assert result.goto == "research_team"


def test_plan_validation_with_all_issue_650_error_scenarios():
    """Test all variations of Issue #650 error scenarios."""
    from src.graph.nodes import validate_and_fix_plan

    test_scenarios = [
        # Missing step_type with need_search=true
        {
            "steps": [
                {"need_search": True, "title": "R", "description": "D"},
            ]
        },
        # Missing step_type with need_search=false
        {
            "steps": [
                {"need_search": False, "title": "P", "description": "D"},
            ]
        },
        # Multiple missing step_types
        {
            "steps": [
                {"need_search": True, "title": "R1", "description": "D"},
                {"need_search": True, "title": "R2", "description": "D"},
                {"need_search": False, "title": "P", "description": "D"},
            ]
        },
        # Mix of missing and present step_type
        {
            "steps": [
                {"need_search": True, "title": "R", "description": "D", "step_type": "research"},
                {"need_search": False, "title": "P", "description": "D"},
            ]
        },
    ]

    for scenario in test_scenarios:
        plan = {
            "locale": "en-US",
            "has_enough_context": False,
            "title": "Test",
            "thought": "Test",
            **scenario,
        }

        # Should not raise exception
        fixed = validate_and_fix_plan(plan)

        # All steps should have step_type after fix
        for step in fixed["steps"]:
            assert "step_type" in step
            # Issue #677: 'analysis' is now a valid step_type
            assert step["step_type"] in ["research", "analysis", "processing"]

def test_clarification_skips_specific_topics():
    """Coordinator should skip clarification for already specific topics."""
    from langchain_core.messages import AIMessage
    from langchain_core.runnables import RunnableConfig

    test_state = {
        "messages": [
            {
                "role": "user",
                "content": "Research Plan for Improving Efficiency of AI e-commerce Video Synthesis Technology Based on Transformer Model",
            }
        ],
        "enable_clarification": True,
        "clarification_rounds": 0,
        "clarification_history": [],
        "max_clarification_rounds": 3,
        "research_topic": "Research Plan for Improving Efficiency of AI e-commerce Video Synthesis Technology Based on Transformer Model",
        "locale": "en-US",
    }

    config = RunnableConfig(configurable={"thread_id": "specific-topic-test"})

    mock_response = AIMessage(
        content="I understand you want to research AI e-commerce video synthesis technology. Let me hand this off to the planner.",
        tool_calls=[
            {
                "name": "handoff_to_planner",
                "args": {
                    "locale": "en-US",
                    "research_topic": "Research Plan for Improving Efficiency of AI e-commerce Video Synthesis Technology Based on Transformer Model",
                },
                "id": "tool-call-handoff",
                "type": "tool_call",
            }
        ],
    )

    with patch("src.graph.nodes.get_llm_by_type") as mock_get_llm:
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value.invoke.return_value = mock_response
        mock_get_llm.return_value = mock_llm

        result = coordinator_node(test_state, config)

    assert hasattr(result, "update")
    assert result.goto == "planner"
    assert (
        result.update["research_topic"]
        == "Research Plan for Improving Efficiency of AI e-commerce Video Synthesis Technology Based on Transformer Model"
    )


# ============================================================================
# Issue #693 Tests: Multiple web_search ToolMessages Preservation
# ============================================================================


@pytest.mark.asyncio
async def test_execute_agent_step_preserves_multiple_tool_messages():
    """
    Test for Issue #693: Verify that all ToolMessages from multiple tool calls
    (e.g., multiple web_search calls) are preserved and not just the final result.
    
    This test ensures that when an agent makes multiple web_search calls, each
    ToolMessage is preserved in the Command update, allowing the frontend to
    receive and display all search results.
    """
    from langchain_core.messages import AIMessage, ToolMessage
    
    # Create test state with a plan and an unexecuted step
    class TestStep:
        def __init__(self, title, description, execution_res=None):
            self.title = title
            self.description = description
            self.execution_res = execution_res
    
    Plan = MagicMock()
    Plan.title = "Test Research Plan"
    Plan.steps = [
        TestStep(title="Test Step", description="Test Description", execution_res=None)
    ]
    
    state = {
        "current_plan": Plan,
        "observations": [],
        "locale": "en-US",
        "resources": [],
    }
    
    # Create a mock agent that simulates multiple web_search tool calls
    # This mimics what a ReAct agent does internally
    agent = MagicMock()
    
    async def mock_ainvoke(input, config):
        # Simulate the agent making 2 web_search calls with this message sequence:
        # 1. AIMessage with first tool call
        # 2. ToolMessage with first tool result
        # 3. AIMessage with second tool call
        # 4. ToolMessage with second tool result
        # 5. Final AIMessage with the complete response
        
        messages = [
            AIMessage(
                content="I'll search for information about this topic.",
                tool_calls=[{
                    "id": "call_1",
                    "name": "web_search",
                    "args": {"query": "first search query"}
                }]
            ),
            ToolMessage(
                content="First search result content here",
                tool_call_id="call_1",
                name="web_search",
            ),
            AIMessage(
                content="Let me search for more specific information.",
                tool_calls=[{
                    "id": "call_2",
                    "name": "web_search",
                    "args": {"query": "second search query"}
                }]
            ),
            ToolMessage(
                content="Second search result content here",
                tool_call_id="call_2",
                name="web_search",
            ),
            AIMessage(
                content="Based on my research, here is the comprehensive answer..."
            ),
        ]
        return {"messages": messages}
    
    async def astream(input, config, stream_mode):
        # Simulate agent.astream() yielding the final messages (async generator)
        messages = [
            AIMessage(
                content="I'll search for information about this topic.",
                tool_calls=[{
                    "id": "call_1",
                    "name": "web_search",
                    "args": {"query": "first search query"}
                }]
            ),
            ToolMessage(
                content="First search result content here",
                tool_call_id="call_1",
                name="web_search",
            ),
            AIMessage(
                content="Let me search for more specific information.",
                tool_calls=[{
                    "id": "call_2",
                    "name": "web_search",
                    "args": {"query": "second search query"}
                }]
            ),
            ToolMessage(
                content="Second search result content here",
                tool_call_id="call_2",
                name="web_search",
            ),
            AIMessage(
                content="Based on my research, here is the comprehensive answer..."
            ),
        ]
        yield {"messages": messages}
    
    agent.ainvoke = mock_ainvoke
    agent.astream = astream
    
    # Execute the agent step
    with patch(
        "src.graph.nodes.HumanMessage",
        side_effect=lambda content, name=None: MagicMock(content=content, name=name),
    ):
        result = await _execute_agent_step(state, agent, "researcher")
    
    # Verify the result is a Command with correct goto
    assert isinstance(result, Command)
    assert result.goto == "research_team"
    
    # Verify that ALL messages are preserved in the Command update
    # (not just the final message content)
    messages_in_update = result.update.get("messages", [])
    
    # Should have 5 messages: 2 AIMessages + 2 ToolMessages + 1 final AIMessage
    assert len(messages_in_update) == 5, (
        f"Expected 5 messages to be preserved, but got {len(messages_in_update)}. "
        f"This indicates that intermediate ToolMessages are being dropped, "
        f"which is the bug from Issue #693."
    )
    
    # Verify message types
    message_types = [type(msg).__name__ for msg in messages_in_update]
    assert message_types.count("AIMessage") == 3, "Should have 3 AIMessages"
    assert message_types.count("ToolMessage") == 2, "Should have 2 ToolMessages"
    
    # Verify that we have both ToolMessages with their content
    tool_messages = [msg for msg in messages_in_update if isinstance(msg, ToolMessage)]
    assert len(tool_messages) == 2, "Should preserve both tool calls"
    assert "First search result content here" in tool_messages[0].content
    assert "Second search result content here" in tool_messages[1].content
    
    # Verify that observations still contain the final response
    assert "observations" in result.update
    observations = result.update["observations"]
    assert len(observations) > 0
    assert "Based on my research" in observations[-1]
    
    # Verify step execution result is set to final message
    assert state["current_plan"].steps[0].execution_res == "Based on my research, here is the comprehensive answer..."


@pytest.mark.asyncio
async def test_execute_agent_step_single_tool_call_still_works():
    """
    Test that the fix for Issue #693 doesn't break the case where
    an agent makes only a single tool call.
    """
    from langchain_core.messages import AIMessage, ToolMessage
    
    class TestStep:
        def __init__(self, title, description, execution_res=None):
            self.title = title
            self.description = description
            self.execution_res = execution_res
    
    Plan = MagicMock()
    Plan.title = "Test Research Plan"
    Plan.steps = [
        TestStep(title="Test Step", description="Test Description", execution_res=None)
    ]
    
    state = {
        "current_plan": Plan,
        "observations": [],
        "locale": "en-US",
        "resources": [],
    }
    
    agent = MagicMock()
    
    async def mock_ainvoke(input, config):
        # Simulate a single web_search call
        messages = [
            AIMessage(
                content="I'll search for information.",
                tool_calls=[{
                    "id": "call_1",
                    "name": "web_search",
                    "args": {"query": "search query"}
                }]
            ),
            ToolMessage(
                content="Search result content",
                tool_call_id="call_1",
                name="web_search",
            ),
            AIMessage(
                content="Here is the answer based on the search result."
            ),
        ]
        return {"messages": messages}
    
    async def astream(input, config, stream_mode):
        # Simulate agent.astream() yielding the messages (async generator)
        messages = [
            AIMessage(
                content="I'll search for information.",
                tool_calls=[{
                    "id": "call_1",
                    "name": "web_search",
                    "args": {"query": "search query"}
                }]
            ),
            ToolMessage(
                content="Search result content",
                tool_call_id="call_1",
                name="web_search",
            ),
            AIMessage(
                content="Here is the answer based on the search result."
            ),
        ]
        yield {"messages": messages}
    
    agent.ainvoke = mock_ainvoke
    agent.astream = astream
    
    with patch(
        "src.graph.nodes.HumanMessage",
        side_effect=lambda content, name=None: MagicMock(content=content, name=name),
    ):
        result = await _execute_agent_step(state, agent, "researcher")
    
    # Verify result structure
    assert isinstance(result, Command)
    assert result.goto == "research_team"
    
    # Verify all 3 messages are preserved
    messages_in_update = result.update.get("messages", [])
    assert len(messages_in_update) == 3
    
    # Verify the single tool message is present
    tool_messages = [msg for msg in messages_in_update if isinstance(msg, ToolMessage)]
    assert len(tool_messages) == 1
    assert "Search result content" in tool_messages[0].content


@pytest.mark.asyncio
async def test_execute_agent_step_no_tool_calls_still_works():
    """
    Test that the fix for Issue #693 doesn't break the case where
    an agent completes without making any tool calls.
    """
    from langchain_core.messages import AIMessage
    
    class TestStep:
        def __init__(self, title, description, execution_res=None):
            self.title = title
            self.description = description
            self.execution_res = execution_res
    
    Plan = MagicMock()
    Plan.title = "Test Research Plan"
    Plan.steps = [
        TestStep(title="Test Step", description="Test Description", execution_res=None)
    ]
    
    state = {
        "current_plan": Plan,
        "observations": [],
        "locale": "en-US",
        "resources": [],
    }
    
    agent = MagicMock()
    
    async def mock_ainvoke(input, config):
        # Agent responds without making any tool calls
        messages = [
            AIMessage(
                content="Based on my knowledge, here is the answer without needing to search."
            ),
        ]
        return {"messages": messages}
    
    async def astream(input, config, stream_mode):
        # Simulate agent.astream() yielding messages without tool calls (async generator)
        messages = [
            AIMessage(
                content="Based on my knowledge, here is the answer without needing to search."
            ),
        ]
        yield {"messages": messages}
    
    agent.ainvoke = mock_ainvoke
    agent.astream = astream
    
    with patch(
        "src.graph.nodes.HumanMessage",
        side_effect=lambda content, name=None: MagicMock(content=content, name=name),
    ):
        result = await _execute_agent_step(state, agent, "researcher")
    
    # Verify result structure
    assert isinstance(result, Command)
    assert result.goto == "research_team"
    
    # Verify the single message is preserved
    messages_in_update = result.update.get("messages", [])
    assert len(messages_in_update) == 1
    
    # Verify step execution result is set
    assert state["current_plan"].steps[0].execution_res == "Based on my knowledge, here is the answer without needing to search."
