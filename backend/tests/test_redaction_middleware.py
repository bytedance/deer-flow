import pytest
from langchain.agents.middleware.types import ModelRequest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from deerflow.agents.middlewares.redaction_middleware import RedactionMiddleware
from deerflow.config.redaction_config import load_redaction_config_from_dict


@pytest.fixture
def middleware():
    config_dict = {"enabled": True, "redact_string": "[REDACTED]", "patterns": [r"(?i)api_key\s*=\s*['\"][A-Za-z0-9_-]+['\"]", r"password123"]}
    load_redaction_config_from_dict(config_dict)
    try:
        yield RedactionMiddleware()
    finally:
        load_redaction_config_from_dict(None)


def test_redact_text(middleware):
    text = "Here is my api_key='secret123' and password123"
    redacted = middleware._redact_text(text)
    assert "[REDACTED]" in redacted
    assert "secret123" not in redacted
    assert "password123" not in redacted


def test_wrap_model_call(middleware):
    request = ModelRequest(messages=[HumanMessage(content="Use api_key='secret123'")], model=None)

    def mock_handler(req: ModelRequest) -> tuple[AIMessage, bool]:
        assert "secret123" not in req.messages[0].content
        assert "[REDACTED]" in req.messages[0].content
        return AIMessage(content="i generated an api_key='my_secret_key'")

    response = middleware.wrap_model_call(request, mock_handler)

    assert "[REDACTED]" in response.content
    assert "secret123" not in response.content


def test_wrap_tool_call(middleware):
    request = ToolCallRequest(tool_call={"name": "test_tool", "id": "1", "args": {}}, tool=None, state={}, runtime=None)

    def mock_handler(req: ToolCallRequest) -> ToolMessage:
        return ToolMessage(content="Found api_key='sk_secret_123' in the file.", tool_call_id="1", name="test_tool")

    response = middleware.wrap_tool_call(request, mock_handler)

    assert "[REDACTED]" in response.content
    assert "sk_secret_123" not in response.content


def test_wrap_tool_call_command(middleware):
    """Verify that ToolMessage wrapped inside a Command are also redacted."""
    from langgraph.types import Command

    request = ToolCallRequest(tool_call={"name": "test_tool", "id": "2", "args": {}}, tool=None, state={}, runtime=None)

    def mock_handler(req: ToolCallRequest):
        return Command(update={"messages": [ToolMessage(content="Found api_key='sk_secret_123' in the file.", tool_call_id="2", name="test_tool")]})

    response = middleware.wrap_tool_call(request, mock_handler)

    assert isinstance(response, Command)
    assert "sk_secret_123" not in response.update["messages"][0].content
    assert "[REDACTED]" in response.update["messages"][0].content
