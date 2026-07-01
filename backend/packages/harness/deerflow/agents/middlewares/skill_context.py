"""Deterministic capture and rendering for loaded skill files."""

from __future__ import annotations

import posixpath
import re
from collections.abc import Collection
from html import escape
from typing import Any

import yaml
from langchain_core.messages import AIMessage, AnyMessage, ToolMessage

from deerflow.agents.thread_state import _SKILL_DESCRIPTION_MAX_CHARS, SkillEntry

_SKILL_FILE_NAME = "SKILL.md"
_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _tool_call_name(tool_call: dict[str, Any]) -> str:
    name = tool_call.get("name")
    if isinstance(name, str):
        return name
    function = tool_call.get("function")
    if isinstance(function, dict) and isinstance(function.get("name"), str):
        return function["name"]
    return ""


def _tool_call_id(tool_call: dict[str, Any]) -> str | None:
    tool_call_id = tool_call.get("id")
    return str(tool_call_id) if tool_call_id else None


def _tool_call_path(tool_call: dict[str, Any]) -> str | None:
    args = tool_call.get("args")
    if not isinstance(args, dict):
        return None
    for key in ("path", "file_path", "filepath"):
        value = args.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _normalize_under_root(path: str, normalized_root: str) -> str | None:
    normalized = posixpath.normpath(path)
    if normalized == normalized_root or normalized.startswith(normalized_root + "/"):
        return normalized
    return None


def _is_skill_file(path: str) -> bool:
    return posixpath.basename(path) == _SKILL_FILE_NAME


def _skill_name_from_path(skill_md_path: str) -> str:
    """Derive the skill name from the directory containing SKILL.md."""
    return posixpath.basename(posixpath.dirname(skill_md_path))


def _parse_description(content: str) -> str:
    """Extract frontmatter description from already-read SKILL.md content."""
    match = _FRONT_MATTER_RE.match(content)
    if not match:
        return ""
    try:
        metadata = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return ""
    if not isinstance(metadata, dict):
        return ""
    description = metadata.get("description")
    if not isinstance(description, str):
        return ""
    return " ".join(description.split())[:_SKILL_DESCRIPTION_MAX_CHARS]


def _is_tool_error_text(content: str) -> bool:
    return content.lstrip().startswith("Error:")


def _escape_context_text(value: object) -> str:
    return escape(str(value), quote=False)


def extract_skills(
    messages: list[AnyMessage],
    *,
    skills_root: str,
    read_tool_names: Collection[str],
) -> list[SkillEntry]:
    """Enumerate skill-file reads (AI read_file call + paired ToolMessage result)."""
    normalized_root = posixpath.normpath(skills_root.rstrip("/") or "/")
    read_names = frozenset(read_tool_names)

    skill_paths_by_id: dict[str, str] = {}
    for message in messages:
        if not isinstance(message, AIMessage):
            continue
        for tool_call in message.tool_calls or []:
            if _tool_call_name(tool_call) not in read_names:
                continue
            tool_call_id = _tool_call_id(tool_call)
            raw_path = _tool_call_path(tool_call)
            path = _normalize_under_root(raw_path, normalized_root) if raw_path else None
            if tool_call_id and path and _is_skill_file(path):
                skill_paths_by_id[tool_call_id] = path

    entries: list[SkillEntry] = []
    for index, message in enumerate(messages):
        if not isinstance(message, ToolMessage):
            continue
        if getattr(message, "status", "success") == "error":
            continue
        tool_call_id = str(message.tool_call_id) if message.tool_call_id else ""
        path = skill_paths_by_id.get(tool_call_id)
        if path is None:
            continue
        content = message.content if isinstance(message.content, str) else str(message.content)
        if _is_tool_error_text(content):
            continue
        entries.append(
            {
                "name": _skill_name_from_path(path),
                "path": path,
                "description": _parse_description(content),
                "loaded_at": index,
            }
        )
    return entries


def render_skill_context(entries: list[SkillEntry]) -> str:
    """Render active-skill references as a compact reminder, not the body."""
    if not entries:
        return ""

    lines = ["## Active skills (loaded earlier - re-read the file before applying its instructions)"]
    for entry in entries:
        name = _escape_context_text(entry["name"])
        path = _escape_context_text(entry["path"])
        raw_description = entry.get("description") or ""
        if isinstance(raw_description, str):
            raw_description = " ".join(raw_description.split())[:_SKILL_DESCRIPTION_MAX_CHARS]
        description = _escape_context_text(raw_description)
        suffix = f": {description}" if description else ""
        lines.append(f"- {name}{suffix} -> {path}")
    return "\n".join(lines)
