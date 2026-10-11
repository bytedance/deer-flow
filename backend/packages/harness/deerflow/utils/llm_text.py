"""Utilities for normalizing LLM response text before structured parsing."""

from __future__ import annotations

import re

# A word boundary also accepts punctuation in unrelated XML/HTML tag names.
# Keep the exact unfinished prefix for leading-summary cleanup.
# Accept the self-closing delimiter without treating <think/other> as reasoning.
_THINK_OPEN_PREFIX_RE = re.compile(r"<think(?=[\s>]|/>|$)", re.IGNORECASE)
_THINK_CLOSE_PREFIX_RE = re.compile(r"</think", re.IGNORECASE)


def _find_tag_end(text: str, start: int) -> int:
    """Find the closing delimiter outside single- or double-quoted attributes."""
    quote = ""
    for index in range(start, len(text)):
        char = text[index]
        if quote:
            if char == quote:
                quote = ""
        elif char in {"'", '"'}:
            quote = char
        elif char == ">":
            return index
    return -1


def _find_think_open(text: str, start: int) -> tuple[int, int] | None:
    """Find the next complete opening tag without retrying its suffix at each prefix."""
    match = _THINK_OPEN_PREFIX_RE.search(text, start)
    if match is None:
        return None
    end = _find_tag_end(text, match.end())
    if end < 0:
        return None
    return match.start(), end + 1


def _is_self_closing_think_tag(text: str, start: int, end: int) -> bool:
    """Recognize a terminal slash only when it is outside quoted attributes."""
    if text[end - 2] != "/":
        return False
    quote = ""
    for char in text[start : end - 1]:
        if quote:
            if char == quote:
                quote = ""
        elif char in {"'", '"'}:
            quote = char
    return not quote


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

    Complete ``<think>...</think>`` blocks are always removed. Self-closing
    ``<think/>`` tags are empty blocks and leave following text intact. A dangling,
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
        if _is_self_closing_think_tag(text, *opening):
            parts.append(text[start : opening[0]])
            start = opening[1]
            continue
        closing = _find_think_close(text, opening[1])
        if closing is None:
            if truncate_unclosed:
                return ("".join(parts) + text[start : opening[0]]).strip()
            break
        parts.append(text[start : opening[0]])
        start = closing[1]
    parts.append(text[start:])
    return "".join(parts).strip()


def strip_leading_think_blocks(text: str) -> str:
    """Remove leading reasoning for display summaries, leaving tags in the answer intact.

    Unlike structured-response parsing, a displayed answer may explain the
    tag in prose or code. Only a leading XML-style reasoning section is
    removed; an unfinished section has no answer to summarize. Leading
    self-closing tags are removed as empty reasoning sections.
    """
    start = 0
    while True:
        whitespace_start = start
        while start < len(text) and text[start].isspace():
            start += 1
        newline = text.rfind("\n", whitespace_start, start)
        indent = text[max(newline + 1, whitespace_start) : start]
        if (whitespace_start == 0 or newline >= 0) and ("\t" in indent or indent.startswith("    ")):
            break  # Root-level indented Markdown code is a literal example.
        opening = _THINK_OPEN_PREFIX_RE.match(text, start)
        if opening is None:
            break
        end = _find_tag_end(text, opening.end())
        if end >= 0 and _is_self_closing_think_tag(text, start, end + 1):
            start = end + 1
            continue
        closing = _find_think_close(text, end + 1) if end >= 0 else None
        if closing is None:
            return ""
        start = closing[1]
    return text[start:].strip()


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
            elif isinstance(block, dict) and block.get("type") in ("text", "output_text"):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    if content is None:
        return ""
    return str(content)
