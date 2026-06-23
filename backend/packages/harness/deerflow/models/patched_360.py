"""Patched ChatOpenAI adapter for 360 OpenAI-compatible models.

360's ``/v1/chat/completions`` tool-calling support is inconsistent in two ways
that break DeerFlow's agent runtime:

1. Some tool-enabled turns return pseudo tool calls as plain text wrapped in
   ``<tool_call>...</tool_call>`` instead of structured ``tool_calls``.
2. The model may emit a skill name (for example ``frontend-design``) as if it
   were a callable tool, even though DeerFlow expects skills to be loaded via
   ``read_file(<skill>/SKILL.md)``.

This adapter repairs those responses at the model boundary so the rest of the
runtime can keep operating on standard LangChain ``tool_calls``.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterator
from typing import Any

from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI

from deerflow.agents.lead_agent.prompt import get_enabled_skills_for_config
from deerflow.config import get_app_config

_TOOL_CALL_BLOCK_PATTERN = re.compile(r"</?tool_call>")
_FENCED_JSON_PATTERN = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _iter_tool_call_blocks(content: str) -> Iterator[tuple[int, int, str]]:
    """Iterate ``<tool_call>...</tool_call>`` blocks while tolerating nesting."""
    depth = 0
    block_start = -1

    for match in _TOOL_CALL_BLOCK_PATTERN.finditer(content):
        token = match.group(0)
        if token == "<tool_call>":
            if depth == 0:
                block_start = match.start()
            depth += 1
            continue

        if depth == 0:
            continue

        depth -= 1
        if depth == 0 and block_start != -1:
            block_end = match.end()
            inner_start = block_start + len("<tool_call>")
            inner_end = match.start()
            yield block_start, block_end, content[inner_start:inner_end]
            block_start = -1


def _unwrap_fenced_json(text: str) -> str:
    stripped = text.strip()
    match = _FENCED_JSON_PATTERN.match(stripped)
    if match:
        return match.group(1).strip()
    return stripped


def _normalize_skill_alias(name: str) -> str:
    normalized = name.strip().lower().lstrip("_")
    normalized = normalized.replace("_", "-")
    if normalized.endswith("-skill"):
        normalized = normalized[: -len("-skill")]
    return normalized


def _skill_alias_map() -> dict[str, tuple[str, str]]:
    app_config = get_app_config()
    container_base_path = app_config.skills.container_path
    aliases: dict[str, tuple[str, str]] = {}
    for skill in get_enabled_skills_for_config(app_config):
        skill_path = skill.get_container_file_path(container_base_path)
        aliases[_normalize_skill_alias(skill.name)] = (skill.name, skill_path)
    return aliases


def _canonicalize_tool_name_and_args(name: str, args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Map pseudo skill calls to DeerFlow's real ``read_file`` tool."""
    aliases = _skill_alias_map()
    alias = _normalize_skill_alias(name)
    skill = aliases.get(alias)
    if skill is None:
        return name, args

    skill_name, skill_path = skill
    description = args.get("description")
    if not isinstance(description, str) or not description.strip():
        description = f"Load {skill_name} skill"
    return "read_file", {"description": description, "path": skill_path}


def _tool_call_signature(tool_call: dict[str, Any]) -> tuple[str, str]:
    """Return a stable signature for de-duplicating recovered tool calls."""
    name = str(tool_call.get("name") or "")
    args = tool_call.get("args") or {}
    try:
        args_key = json.dumps(args, ensure_ascii=False, sort_keys=True)
    except TypeError:
        args_key = str(args)
    return name, args_key


def _normalize_tool_calls(tool_calls: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Canonicalize tool names/args while preserving ids and extra fields."""
    normalized: list[dict[str, Any]] = []
    for tool_call in tool_calls or []:
        if not isinstance(tool_call, dict):
            normalized.append(tool_call)
            continue

        raw_name = tool_call.get("name")
        raw_args = tool_call.get("args")
        if not isinstance(raw_name, str):
            normalized.append(tool_call)
            continue

        args = raw_args if isinstance(raw_args, dict) else {}
        canonical_name, canonical_args = _canonicalize_tool_name_and_args(raw_name, args)
        normalized.append(
            {
                **tool_call,
                "name": canonical_name,
                "args": canonical_args,
            }
        )
    return normalized


def _extract_tool_calls_from_content(content: str) -> tuple[str, list[dict[str, Any]]]:
    """Parse JSON pseudo tool calls embedded in plain-text model output."""
    if not isinstance(content, str) or "<tool_call>" not in content:
        return content, []

    tool_calls: list[dict[str, Any]] = []
    clean_parts: list[str] = []
    cursor = 0

    for start, end, inner in _iter_tool_call_blocks(content):
        clean_parts.append(content[cursor:start])
        cursor = end

        payload_text = _unwrap_fenced_json(inner)
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            continue

        if not isinstance(payload, dict):
            continue

        name = payload.get("name")
        raw_args = payload.get("arguments")
        if raw_args is None:
            raw_args = payload.get("args")
        if raw_args is None:
            raw_args = payload.get("parameters")

        if not isinstance(name, str):
            continue

        args = raw_args if isinstance(raw_args, dict) else {}
        normalized_name, normalized_args = _canonicalize_tool_name_and_args(name, args)
        tool_calls.append(
            {
                "name": normalized_name,
                "args": normalized_args,
                "id": f"call_{uuid.uuid4().hex[:24]}",
            }
        )

    clean_parts.append(content[cursor:])
    cleaned = "".join(clean_parts).strip()
    return cleaned, tool_calls


class PatchedChat360(ChatOpenAI):
    """ChatOpenAI with 360-specific pseudo tool-call recovery."""

    def __init__(self, **kwargs: Any):
        kwargs.setdefault("disable_streaming", "tool_calling")
        super().__init__(**kwargs)

    def _patch_result_with_tools(self, result: ChatResult) -> ChatResult:
        for generation in result.generations:
            message = generation.message
            existing_tool_calls = _normalize_tool_calls(getattr(message, "tool_calls", []))
            if getattr(message, "tool_calls", None) is not None:
                message.tool_calls = existing_tool_calls
            if not isinstance(message.content, str):
                continue
            cleaned, extracted_tool_calls = _extract_tool_calls_from_content(message.content)
            if not extracted_tool_calls:
                continue
            message.content = cleaned
            if getattr(message, "tool_calls", None) is None:
                message.tool_calls = []
            seen = {_tool_call_signature(tc) for tc in message.tool_calls}
            for tool_call in extracted_tool_calls:
                signature = _tool_call_signature(tool_call)
                if signature in seen:
                    continue
                message.tool_calls.append(tool_call)
                seen.add(signature)
        return result

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        result = super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        return self._patch_result_with_tools(result)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        result = await super()._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)
        return self._patch_result_with_tools(result)

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        if not kwargs.get("tools"):
            yield from super()._stream(messages, stop=stop, run_manager=run_manager, **kwargs)
            return

        result = self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        for generation in result.generations:
            message = generation.message
            content = message.content
            tool_calls = getattr(message, "tool_calls", [])
            if isinstance(content, str) and content:
                yield ChatGenerationChunk(message=AIMessageChunk(content=content, id=message.id), generation_info=generation.generation_info)
            if tool_calls:
                yield ChatGenerationChunk(
                    message=AIMessageChunk(
                        content="",
                        id=message.id,
                        tool_calls=tool_calls,
                        invalid_tool_calls=getattr(message, "invalid_tool_calls", []),
                        additional_kwargs=message.additional_kwargs,
                    )
                )

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        if not kwargs.get("tools"):
            async for chunk in super()._astream(messages, stop=stop, run_manager=run_manager, **kwargs):
                yield chunk
            return

        result = await self._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)
        for generation in result.generations:
            message = generation.message
            content = message.content
            tool_calls = getattr(message, "tool_calls", [])
            if isinstance(content, str) and content:
                yield ChatGenerationChunk(message=AIMessageChunk(content=content, id=message.id), generation_info=generation.generation_info)
            if tool_calls:
                yield ChatGenerationChunk(
                    message=AIMessageChunk(
                        content="",
                        id=message.id,
                        tool_calls=tool_calls,
                        invalid_tool_calls=getattr(message, "invalid_tool_calls", []),
                        additional_kwargs=message.additional_kwargs,
                    )
                )
