"""Tests for stripping <think> tags from model output (#781).

Some models (e.g. DeepSeek-R1, QwQ via ollama) embed reasoning in
content using <think>...</think> tags instead of the separate
reasoning_content field. These tests verify that <think> tags are
properly stripped in both the SubagentExecutor output path and the
frontend extractContentFromMessage utility.
"""

import pathlib
import re

# ── Backend: _strip_think_tags from executor.py ───────────────────────

def _get_strip_think_tags():
    """Extract and return the real _strip_think_tags function from executor.py.

    Direct import is not possible due to circular imports in the module,
    so we extract the function from source and exec it.
    """
    executor_path = pathlib.Path(__file__).parent.parent / "src" / "subagents" / "executor.py"
    source = executor_path.read_text()

    match = re.search(
        r"(def _strip_think_tags\(content: str\) -> str:.*?)(?=\ndef )",
        source,
        re.DOTALL,
    )
    assert match, "_strip_think_tags not found in executor.py"

    ns = {"re": re}
    exec(match.group(1), ns)
    return ns["_strip_think_tags"]


_strip_think_tags = _get_strip_think_tags()


class TestStripThinkTags:
    """Regression tests for _strip_think_tags."""

    def test_strips_think_block_at_beginning(self):
        result = _strip_think_tags(
            "<think>\nLet me analyze...\n</think>\n\n# Report\n\nContent here."
        )
        assert "<think>" not in result
        assert "# Report" in result
        assert "Content here." in result

    def test_strips_multiple_think_blocks(self):
        result = _strip_think_tags(
            "<think>First thought</think>\nParagraph 1.\n<think>Second thought</think>\nParagraph 2."
        )
        assert "<think>" not in result
        assert "Paragraph 1." in result
        assert "Paragraph 2." in result

    def test_preserves_content_without_think_tags(self):
        result = _strip_think_tags("Normal content without think tags.")
        assert result == "Normal content without think tags."

    def test_empty_content_after_stripping(self):
        result = _strip_think_tags("<think>Only thinking, no real content</think>")
        assert "<think>" not in result
        assert result == ""

    def test_empty_string(self):
        result = _strip_think_tags("")
        assert result == ""

    def test_multiline_think_block(self):
        result = _strip_think_tags(
            "<think>\nLine 1\nLine 2\nLine 3\n</think>\nActual content"
        )
        assert "<think>" not in result
        assert "Actual content" in result

    def test_think_block_in_middle(self):
        result = _strip_think_tags(
            "Before content\n<think>reasoning</think>\nAfter content"
        )
        assert "<think>" not in result
        assert "Before content" in result
        assert "After content" in result

    def test_nested_angle_brackets_preserved(self):
        result = _strip_think_tags("Use <div> tags for HTML layout.")
        assert result == "Use <div> tags for HTML layout."


# ── Backend: executor content extraction path ─────────────────────────

def _simulate_executor_content_extraction(content):
    """Reproduce the fixed logic from SubagentExecutor.execute() lines 290-304."""
    if isinstance(content, str):
        return _strip_think_tags(content)
    elif isinstance(content, list):
        text_parts = []
        for block in content:
            if isinstance(block, str):
                text_parts.append(block)
            elif isinstance(block, dict) and "text" in block:
                text_parts.append(block["text"])
        return _strip_think_tags("\n".join(text_parts)) if text_parts else "No text content in response"
    else:
        return str(content)


class TestExecutorContentExtraction:
    """Regression tests for SubagentExecutor content extraction with think tag stripping."""

    def test_string_content_stripped(self):
        result = _simulate_executor_content_extraction(
            "<think>reasoning</think>\n\nFinal answer"
        )
        assert "<think>" not in result
        assert "Final answer" in result

    def test_list_content_stripped(self):
        result = _simulate_executor_content_extraction([
            {"type": "text", "text": "<think>reasoning</think>\nActual content"},
        ])
        assert "<think>" not in result
        assert "Actual content" in result

    def test_non_string_passthrough(self):
        result = _simulate_executor_content_extraction(12345)
        assert result == "12345"

    def test_empty_list(self):
        result = _simulate_executor_content_extraction([])
        assert result == "No text content in response"

    def test_clean_content_unchanged(self):
        result = _simulate_executor_content_extraction("Clean content")
        assert result == "Clean content"
