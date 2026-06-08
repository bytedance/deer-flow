import asyncio
from types import SimpleNamespace
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


def test_strip_think_blocks_removes_complete_block():
    text = "<think>\nreasoning here\n</think>\nanswer"
    assert suggestions._strip_think_blocks(text) == "answer"


def test_strip_think_blocks_is_case_insensitive():
    text = "<Think>reasoning</THINK>\nanswer"
    assert suggestions._strip_think_blocks(text) == "answer"


def test_strip_think_blocks_drops_unclosed_block():
    # Reasoning models truncated at max_tokens emit an unclosed <think>.
    text = "<think>\nreasoning that never finished because tokens ran out"
    assert suggestions._strip_think_blocks(text) == ""


def test_strip_think_blocks_keeps_text_without_think():
    text = '["a", "b"]'
    assert suggestions._strip_think_blocks(text) == '["a", "b"]'


def test_parse_json_string_list_ignores_brackets_inside_think_block():
    # MiniMax-M3 inlines its chain-of-thought as <think>...</think> in content
    # (reasoning_split=false). When that reasoning contains '[' / ']', the old
    # find('[')/rfind(']') logic grabbed the wrong span and parsing failed.
    text = '<think>\nMaybe a list like ["x", "y"] could work. Let me craft 3.\n</think>\n["Q1", "Q2", "Q3"]'
    assert suggestions._parse_json_string_list(text) == ["Q1", "Q2", "Q3"]


def test_parse_json_string_list_strips_think_then_code_fence():
    text = '<think>reasoning</think>\n```json\n["Q1", "Q2"]\n```'
    assert suggestions._parse_json_string_list(text) == ["Q1", "Q2"]


def test_generate_suggestions_strips_inline_think_block(monkeypatch):
    # End-to-end: model returns thinking inline followed by the JSON array.
    req = suggestions.SuggestionsRequest(
        messages=[
            suggestions.SuggestionMessage(role="user", content="介绍深度学习"),
            suggestions.SuggestionMessage(role="assistant", content="深度学习是机器学习的分支。"),
        ],
        n=3,
        model_name=None,
    )
    content = '<think>\nThe user asked about deep learning. Options: maybe [1] frameworks, [2] math basics.\n</think>\n["深度学习和机器学习的区别？", "常用框架有哪些？", "需要什么数学基础？"]'
    fake_model = MagicMock()
    fake_model.ainvoke = AsyncMock(return_value=MagicMock(content=content))
    monkeypatch.setattr(suggestions, "create_chat_model", lambda **kwargs: fake_model)

    result = asyncio.run(suggestions.generate_suggestions.__wrapped__("t1", req, request=None, config=SimpleNamespace()))

    assert result.suggestions == ["深度学习和机器学习的区别？", "常用框架有哪些？", "需要什么数学基础？"]


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
    monkeypatch.setattr(suggestions, "create_chat_model", lambda **kwargs: fake_model)

    # Bypass the require_permission decorator (which needs request +
    # thread_store) — these tests cover the parsing logic.
    result = asyncio.run(suggestions.generate_suggestions.__wrapped__("t1", req, request=None, config=SimpleNamespace()))

    assert result.suggestions == ["Q1", "Q2", "Q3"]
    fake_model.ainvoke.assert_awaited_once()
    assert fake_model.ainvoke.await_args.kwargs["config"] == {"run_name": "suggest_agent"}


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
    monkeypatch.setattr(suggestions, "create_chat_model", lambda **kwargs: fake_model)

    # Bypass the require_permission decorator (which needs request +
    # thread_store) — these tests cover the parsing logic.
    result = asyncio.run(suggestions.generate_suggestions.__wrapped__("t1", req, request=None, config=SimpleNamespace()))

    assert result.suggestions == ["Q1", "Q2"]
    fake_model.ainvoke.assert_awaited_once()
    assert fake_model.ainvoke.await_args.kwargs["config"] == {"run_name": "suggest_agent"}


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
    monkeypatch.setattr(suggestions, "create_chat_model", lambda **kwargs: fake_model)

    # Bypass the require_permission decorator (which needs request +
    # thread_store) — these tests cover the parsing logic.
    result = asyncio.run(suggestions.generate_suggestions.__wrapped__("t1", req, request=None, config=SimpleNamespace()))

    assert result.suggestions == ["Q1", "Q2"]
    fake_model.ainvoke.assert_awaited_once()
    assert fake_model.ainvoke.await_args.kwargs["config"] == {"run_name": "suggest_agent"}


def test_generate_suggestions_returns_empty_on_model_error(monkeypatch):
    req = suggestions.SuggestionsRequest(
        messages=[suggestions.SuggestionMessage(role="user", content="Hi")],
        n=2,
        model_name=None,
    )
    fake_model = MagicMock()
    fake_model.ainvoke = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(suggestions, "create_chat_model", lambda **kwargs: fake_model)

    # Bypass the require_permission decorator (which needs request +
    # thread_store) — these tests cover the parsing logic.
    result = asyncio.run(suggestions.generate_suggestions.__wrapped__("t1", req, request=None, config=SimpleNamespace()))

    assert result.suggestions == []
