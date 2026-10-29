"""Shared model-response classification helpers."""

from langchain_core.messages import AIMessage

from deerflow.agents.middlewares.model_response import has_visible_content


def test_has_visible_content_reads_plain_string_content() -> None:
    assert has_visible_content(AIMessage(content="visible answer")) is True
    assert has_visible_content(AIMessage(content="   \n ")) is False
    assert has_visible_content(AIMessage(content=[])) is False


def test_has_visible_content_reads_text_and_output_text_blocks() -> None:
    message = AIMessage(content=[{"type": "text", "text": "visible answer"}])
    assert has_visible_content(message) is True
    message = AIMessage(content=[{"type": "output_text", "text": "visible answer"}])
    assert has_visible_content(message) is True


def test_has_visible_content_ignores_whitespace_only_and_textless_blocks() -> None:
    assert has_visible_content(AIMessage(content=[{"type": "text", "text": "  "}])) is False
    assert has_visible_content(AIMessage(content=[{"type": "text"}])) is False
    assert has_visible_content(AIMessage(content=[{"type": "text", "text": 42}])) is False
    assert has_visible_content(AIMessage(content=[{"type": "reasoning", "reasoning": "thinking"}])) is False


def test_has_visible_content_keeps_visible_text_around_an_unhashable_block_type() -> None:
    # `type: []` / `type: {}` are legal JSON from a provider; probing the type
    # by equality skips the block instead of raising TypeError out of the
    # middleware chain (llm error handling, terminal response, model length).
    message = AIMessage(content=[{"type": [], "text": "ignored"}, {"type": "text", "text": "visible answer"}])
    assert has_visible_content(message) is True


def test_has_visible_content_skips_unhashable_block_types_without_other_text() -> None:
    message = AIMessage(content=[{"type": {}, "text": "ignored"}])
    assert has_visible_content(message) is False
