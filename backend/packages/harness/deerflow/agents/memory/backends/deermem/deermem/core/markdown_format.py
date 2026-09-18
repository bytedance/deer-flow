"""Markdown (de)serialization for DeerMem user-memory summaries.

This module is intentionally dependency-free so it can be unit-tested and
imported without the rest of the DeerMem stack.

Design
------
A Markdown summary carries its *lossless* state inside a fenced
````` ```memory-json ```` ``` block. Everything above the fence is a
human-readable rendering (debugging / hand-editing convenience). When
loading, the fenced JSON block is the source of truth; if it is missing or
malformed we fall back to a best-effort structured parse of the Markdown
sections. This makes the on-disk format tolerant: a partially written or
hand-edited file still recovers instead of crashing the agent.
"""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE_RE = re.compile(r"```memory-json\s*\n(.*?)```", re.DOTALL)
_META_BULLET_RE = re.compile(r"^-\s+([A-Za-z_][\w]*)\s*:\s*(.+)$", re.MULTILINE)
_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$\n(.*?)(?=^##\s|\Z)", re.MULTILINE | re.DOTALL)


def _looks_like_markdown(raw: str) -> bool:
    """Heuristic: True when *raw* is more likely Markdown than JSON."""
    stripped = raw.lstrip()
    if stripped.startswith("#"):
        return True
    if "memory-json" in raw:
        return True
    # A JSON document starts with '{' or '[` after optional whitespace.
    return bool(stripped) and stripped[0] not in "{["


def _extract_fenced_json(raw: str) -> str | None:
    match = _FENCE_RE.search(raw)
    return match.group(1).strip() if match else None


def _parse_markdown_sections(raw: str) -> dict[str, Any] | None:
    """Best-effort parse of the readable Markdown sections into a dict."""
    data: dict[str, Any] = {}
    for m in _META_BULLET_RE.finditer(raw):
        key, val = m.group(1), m.group(2).strip()
        if key in ("version", "revision"):
            try:
                data[key] = int(val)
            except ValueError:
                data[key] = val
        else:
            data[key] = val
    for m in _SECTION_RE.finditer(raw):
        heading = m.group(1).strip().lower()
        body = m.group(2).strip()
        items = re.findall(r"^-\s+(.+)$", body, re.MULTILINE)
        data[heading] = items if items else body
    return data or None


def _parse_markdown_memory(raw: str) -> dict[str, Any] | None:
    """Parse a Markdown summary into a dict, or None when nothing usable."""
    fenced = _extract_fenced_json(raw)
    if fenced is not None:
        try:
            value = json.loads(fenced)
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(value, dict):
                return value
    structured = _parse_markdown_sections(raw)
    if structured:
        return structured
    return None


def _render_memory_markdown(data: dict[str, Any]) -> str:
    """Render a summary dict as a readable Markdown document.

    The fenced ``memory-json`` block at the end is the lossless source of
    truth; the sections above are for humans.
    """
    lines: list[str] = ["# DeerFlow Memory", ""]
    for key in ("version", "revision", "lastUpdated"):
        if key in data and data[key] is not None:
            lines.append(f"- {key}: {data[key]}")
    lines.append("")
    for key in ("user", "history"):
        section = data.get(key)
        if isinstance(section, dict) and section:
            lines.append(f"## {key.capitalize()}")
            lines.append("")
            for k, v in section.items():
                lines.append(f"- {k}: {v}")
            lines.append("")
    lines.append("```memory-json")
    lines.append(json.dumps(data, ensure_ascii=False, indent=2))
    lines.append("```")
    return "\n".join(lines) + "\n"
