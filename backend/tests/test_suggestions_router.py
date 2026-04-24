import asyncio
from unittest.mock import AsyncMock, MagicMock

from app.gateway.routers import suggestions


def test_strip_markdown_code_fence_removes_wrapping():
    text = '```json\n["a"]\n```'
    assert suggestions._strip_markdown_code_fence(text) == '["a"]'


def test_strip_markdown_code_fence_no_fence_keeps_content():
    text = '  ["a"]  '
    assert suggestions._strip_markdown_code_fence(text) == '["a"]'


def test_parse_json_string_list_filters_invalid_items():
    text = '```json\n["a", " ", 1, "b"]\n```'
    assert suggestions._parse_json_string_list(text) == ["a", "b"]


def test_parse_json_string_list_rejects_non_list():
    text = '{"a": 1}'
    assert suggestions._parse_json_string_list(text) is None


def test_format_conversation_formats_roles():
    messages = [
        suggestions.SuggestionMessage(role="User", content="Hi"),
        suggestions.SuggestionMessage(role="assistant", content="Hello"),
        suggestions.SuggestionMessage(role="system", content="note"),
    ]
    assert suggestions._format_conversation(messages) == "User: Hi\nAssistant: Hello\nsystem: note"


def test_generate_suggestions_parses_and_limits(monkeypatch):
    req = suggestions.SuggestionsRequest(
        messages=[
            suggestions.SuggestionMessage(role="user", content="Hi"),
            suggestions.SuggestionMessage(role="assistant", content="Hello"),
        ],
        n=3,
        model_name=None,
    )
    fake_model = MagicMock()
    fake_model.ainvoke = AsyncMock(return_value=MagicMock(content='```json\n["Q1", "Q2", "Q3", "Q4"]\n```'))
    monkeypatch.setattr(suggestions, "get_system_model_name", lambda task_override=None: "sys-default")
    monkeypatch.setattr(suggestions, "create_chat_model", lambda **kwargs: fake_model)

    result = asyncio.run(suggestions.generate_suggestions("t1", req))

    assert result.suggestions == ["Q1", "Q2", "Q3"]


def test_generate_suggestions_parses_list_block_content(monkeypatch):
    req = suggestions.SuggestionsRequest(
        messages=[
            suggestions.SuggestionMessage(role="user", content="Hi"),
            suggestions.SuggestionMessage(role="assistant", content="Hello"),
        ],
        n=2,
        model_name=None,
    )
    fake_model = MagicMock()
    fake_model.ainvoke = AsyncMock(return_value=MagicMock(content=[{"type": "text", "text": '```json\n["Q1", "Q2"]\n```'}]))
    monkeypatch.setattr(suggestions, "get_system_model_name", lambda task_override=None: None)
    monkeypatch.setattr(suggestions, "create_chat_model", lambda **kwargs: fake_model)

    result = asyncio.run(suggestions.generate_suggestions("t1", req))

    assert result.suggestions == ["Q1", "Q2"]


def test_generate_suggestions_parses_output_text_block_content(monkeypatch):
    req = suggestions.SuggestionsRequest(
        messages=[
            suggestions.SuggestionMessage(role="user", content="Hi"),
            suggestions.SuggestionMessage(role="assistant", content="Hello"),
        ],
        n=2,
        model_name=None,
    )
    fake_model = MagicMock()
    fake_model.ainvoke = AsyncMock(return_value=MagicMock(content=[{"type": "output_text", "text": '```json\n["Q1", "Q2"]\n```'}]))
    monkeypatch.setattr(suggestions, "get_system_model_name", lambda task_override=None: None)
    monkeypatch.setattr(suggestions, "create_chat_model", lambda **kwargs: fake_model)

    result = asyncio.run(suggestions.generate_suggestions("t1", req))

    assert result.suggestions == ["Q1", "Q2"]


def test_generate_suggestions_returns_empty_on_model_error(monkeypatch):
    req = suggestions.SuggestionsRequest(
        messages=[suggestions.SuggestionMessage(role="user", content="Hi")],
        n=2,
        model_name=None,
    )
    fake_model = MagicMock()
    fake_model.ainvoke = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(suggestions, "get_system_model_name", lambda task_override=None: None)
    monkeypatch.setattr(suggestions, "create_chat_model", lambda **kwargs: fake_model)

    result = asyncio.run(suggestions.generate_suggestions("t1", req))

    assert result.suggestions == []


def test_generate_suggestions_uses_system_model_name(monkeypatch):
    """Verify that generate_suggestions passes the resolved system model name to create_chat_model."""
    req = suggestions.SuggestionsRequest(
        messages=[
            suggestions.SuggestionMessage(role="user", content="Hi"),
            suggestions.SuggestionMessage(role="assistant", content="Hello"),
        ],
        n=2,
        model_name=None,
    )
    fake_model = MagicMock()
    fake_model.ainvoke = AsyncMock(return_value=MagicMock(content='```json\n["Q1", "Q2"]\n```'))

    captured_name = {}

    def _fake_get_system_model_name(task_override=None):
        return "gpt-4o-mini"

    def _fake_create_chat_model(**kwargs):
        captured_name["name"] = kwargs.get("name")
        return fake_model

    monkeypatch.setattr(suggestions, "get_system_model_name", _fake_get_system_model_name)
    monkeypatch.setattr(suggestions, "create_chat_model", _fake_create_chat_model)

    result = asyncio.run(suggestions.generate_suggestions("t1", req))

    assert result.suggestions == ["Q1", "Q2"]
    assert captured_name["name"] == "gpt-4o-mini"
