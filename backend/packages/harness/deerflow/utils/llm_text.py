"""Utilities for normalizing LLM response text before structured parsing."""

from __future__ import annotations

import re

_THINK_OPEN_PREFIX_RE = re.compile(r"<think\b", re.IGNORECASE)
_THINK_CLOSE_PREFIX_RE = re.compile(r"</think", re.IGNORECASE)


def _find_think_open(text: str, start: int) -> tuple[int, int] | None:
    """Find the next complete opening tag without retrying its suffix at each prefix."""
    match = _THINK_OPEN_PREFIX_RE.search(text, start)
    if match is None:
        return None
    end = text.find(">", match.end())
    if end < 0:
        return None
    return match.start(), end + 1


def _find_think_close(text: str, start: int) -> tuple[int, int] | None:
    """Find the first closing tag, allowing whitespace before its final ``>``."""
    while match := _THINK_CLOSE_PREFIX_RE.search(text, start):
        end = match.end()
        while end < len(text) and text[end].isspace():
            end += 1
        if end < len(text) and text[end] == ">":
            return match.start(), end + 1
        start = match.end()
    return None


def strip_think_blocks(text: str, *, truncate_unclosed: bool = True) -> str:
    """Remove inline reasoning ``<think>`` blocks from a model response.

    Complete ``<think>...</think>`` blocks are always removed. A dangling,
    unclosed ``<think>`` open tag is treated as a model that was truncated
    mid-thought: when ``truncate_unclosed`` is True (the default, used by JSON
    parsers like suggestions/goal where trailing garbage must be dropped) the
    text is cut at that tag. Callers that may legitimately echo a literal
    ``<think>`` substring in their output (e.g. the input polisher rewriting a
    draft that mentions the tag) pass ``truncate_unclosed=False`` so the tag is
    preserved instead of silently discarding the rest of the text.
    """
    parts: list[str] = []
    start = 0
    while (opening := _find_think_open(text, start)) is not None:
        closing = _find_think_close(text, opening[1])
        if closing is None:
            if truncate_unclosed:
                return ("".join(parts) + text[start : opening[0]]).strip()
            break
        parts.append(text[start : opening[0]])
        start = closing[1]
    parts.append(text[start:])
    return "".join(parts).strip()


def strip_markdown_code_fence(text: str) -> str:
    """Remove a single wrapping markdown code fence when present."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].startswith("```"):
        return "\n".join(lines[1:-1]).strip()
    return stripped


def extract_response_text(content: object) -> str:
    """Extract textual content from common chat-model response content shapes."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") in {"text", "output_text"}:
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    if content is None:
        return ""
    return str(content)
