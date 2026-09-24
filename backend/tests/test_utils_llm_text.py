"""Tests for ``deerflow.utils.llm_text``."""

from __future__ import annotations

from deerflow.utils.llm_text import (
    extract_response_text,
    strip_markdown_code_fence,
    strip_think_blocks,
)

# ---------------------------------------------------------------------------
# strip_think_blocks
# ---------------------------------------------------------------------------


def test_strip_think_blocks_removes_complete_block() -> None:
    assert strip_think_blocks("before<think>reasoning</think>after") == "beforeafter"


def test_strip_think_blocks_removes_multiline_block() -> None:
    # DOTALL: the block spans newlines and surrounding whitespace is stripped.
    text = "answer\n<think>\nmulti\nline\n</think>\n"
    assert strip_think_blocks(text) == "answer"


def test_strip_think_blocks_is_case_insensitive_and_tolerates_close_spacing() -> None:
    assert strip_think_blocks("<THINK>x</THINK >done") == "done"


def test_strip_think_blocks_handles_open_tag_attributes() -> None:
    assert strip_think_blocks('<think class="a">secret</think>visible') == "visible"


def test_strip_think_blocks_removes_multiple_blocks_non_greedy() -> None:
    # Non-greedy matching removes each block independently, not everything
    # between the first open and the last close.
    assert strip_think_blocks("a<think>1</think>b<think>2</think>c") == "abc"


def test_strip_think_blocks_response_that_is_only_reasoning_becomes_empty() -> None:
    assert strip_think_blocks("<think>only</think>") == ""


def test_strip_think_blocks_passes_plain_text_through() -> None:
    assert strip_think_blocks("just text") == "just text"


def test_strip_think_blocks_truncates_unclosed_by_default() -> None:
    # A dangling open tag means the model was truncated mid-thought; drop the
    # rest of the text so downstream JSON parsers do not choke on it.
    assert strip_think_blocks("visible answer <think>partial reasoning") == "visible answer"


def test_strip_think_blocks_keeps_unclosed_tag_when_truncation_disabled() -> None:
    text = "visible answer <think>partial reasoning"
    assert strip_think_blocks(text, truncate_unclosed=False) == text


def test_strip_think_blocks_removes_complete_then_truncates_dangling() -> None:
    assert strip_think_blocks("<think>done</think>keep<think>trunc") == "keep"


def test_strip_think_blocks_removes_complete_and_keeps_dangling_when_disabled() -> None:
    result = strip_think_blocks("<think>done</think>keep<think>trunc", truncate_unclosed=False)
    assert result == "keep<think>trunc"


# ---------------------------------------------------------------------------
# strip_markdown_code_fence
# ---------------------------------------------------------------------------


def test_strip_markdown_code_fence_unwraps_language_fence() -> None:
    assert strip_markdown_code_fence('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_strip_markdown_code_fence_unwraps_bare_fence() -> None:
    assert strip_markdown_code_fence("```\nhello\n```") == "hello"


def test_strip_markdown_code_fence_ignores_surrounding_whitespace() -> None:
    assert strip_markdown_code_fence("  ```json\n{}\n```  ") == "{}"


def test_strip_markdown_code_fence_preserves_multiline_body() -> None:
    fenced = "```python\ndef f():\n    return 1\n```"
    assert strip_markdown_code_fence(fenced) == "def f():\n    return 1"


def test_strip_markdown_code_fence_returns_plain_text_unchanged() -> None:
    assert strip_markdown_code_fence("plain text") == "plain text"


def test_strip_markdown_code_fence_ignores_inline_backticks() -> None:
    assert strip_markdown_code_fence("see `code` here") == "see `code` here"


def test_strip_markdown_code_fence_leaves_lone_fence_line_unchanged() -> None:
    # Fewer than three lines cannot be an opening + body + closing fence.
    assert strip_markdown_code_fence("```json") == "```json"


def test_strip_markdown_code_fence_leaves_unterminated_fence_unchanged() -> None:
    assert strip_markdown_code_fence("```\ncontent") == "```\ncontent"


# ---------------------------------------------------------------------------
# extract_response_text
# ---------------------------------------------------------------------------


def test_extract_response_text_passes_string_through_verbatim() -> None:
    # No stripping: the raw string content is returned unchanged.
    assert extract_response_text("  hi  ") == "  hi  "


def test_extract_response_text_joins_string_blocks() -> None:
    assert extract_response_text(["a", "b"]) == "a\nb"


def test_extract_response_text_reads_text_and_output_text_blocks() -> None:
    content = [
        {"type": "text", "text": "x"},
        {"type": "output_text", "text": "y"},
    ]
    assert extract_response_text(content) == "x\ny"


def test_extract_response_text_ignores_non_text_blocks() -> None:
    content = [
        {"type": "tool_use", "text": "ignored"},
        {"type": "text", "text": "kept"},
    ]
    assert extract_response_text(content) == "kept"


def test_extract_response_text_mixes_string_and_dict_blocks() -> None:
    content = ["intro", {"type": "text", "text": "body"}]
    assert extract_response_text(content) == "intro\nbody"


def test_extract_response_text_skips_blocks_with_non_string_text() -> None:
    content = [{"type": "text", "text": 123}, {"type": "text", "text": "ok"}]
    assert extract_response_text(content) == "ok"


def test_extract_response_text_returns_empty_for_empty_list() -> None:
    assert extract_response_text([]) == ""


def test_extract_response_text_returns_empty_for_none() -> None:
    assert extract_response_text(None) == ""


def test_extract_response_text_stringifies_other_types() -> None:
    assert extract_response_text(123) == "123"
    assert extract_response_text({"a": 1}) == str({"a": 1})
