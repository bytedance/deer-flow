"""Reasoning cleanup must not consume unrelated tag names."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.gateway.routers import input_polish, suggestions
from deerflow.utils.llm_text import strip_leading_think_blocks, strip_think_blocks


@pytest.mark.parametrize("name", ["think-tank", "think:note", "think.note", "think/other", "think=note", "THINK-card"])
@pytest.mark.parametrize("truncate_unclosed", [True, False])
def test_unrelated_tag_names_survive_between_real_reasoning_blocks(name: str, truncate_unclosed: bool) -> None:
    literal = f"<{name}>public content</{name}>"
    text = f"<think>first reasoning</think>before{literal}<think>second reasoning</think>after"
    assert strip_think_blocks(text, truncate_unclosed=truncate_unclosed) == f"before{literal}after"


@pytest.mark.parametrize("name", ["think-tank", "think:note", "think.note", "THINK-card"])
def test_unrelated_unclosed_tag_does_not_truncate_response(name: str) -> None:
    text = f"Explain <{name}> without dropping this answer."
    assert strip_think_blocks(text) == text


@pytest.mark.parametrize("text", ["<think", "<THINK", "<think>", "<think class='reasoning'>"])
def test_leading_unfinished_reasoning_still_has_no_visible_answer(text: str) -> None:
    assert strip_leading_think_blocks(text) == ""


def test_suggestions_parser_preserves_unrelated_tag_inside_json() -> None:
    text = '<think>choose questions</think>\n["How does <think-tank> work?", "What next?"]'
    assert suggestions._parse_json_string_list(text) == ["How does <think-tank> work?", "What next?"]


def test_generate_suggestions_keeps_questions_with_unrelated_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(suggestions, "get_current_user_from_request", AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(suggestions, "authorize_model_use", lambda *_args, **_kwargs: None)
    invoke = AsyncMock(return_value='<think>choose questions</think>\n["How does <think-tank> work?", "What next?"]')
    monkeypatch.setattr(suggestions, "run_oneshot_llm", invoke)
    result = asyncio.run(
        suggestions.generate_suggestions.__wrapped__(
            "thread-tags",
            suggestions.SuggestionsRequest(messages=[suggestions.SuggestionMessage(role="user", content="Explain custom HTML tags")], n=2),
            request=None,
            config=SimpleNamespace(suggestions=SimpleNamespace(enabled=True, max_suggestions=2)),
        )
    )
    assert result.suggestions == ["How does <think-tank> work?", "What next?"]
    invoke.assert_awaited_once()


def test_input_polish_keeps_unrelated_tag_before_real_reasoning() -> None:
    text = "Use <think-tank>public content</think-tank>.<think>private reasoning</think>"
    assert input_polish._clean_rewritten_text(text) == "Use <think-tank>public content</think-tank>."
