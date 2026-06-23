"""Patched ChatOpenAI adapter for 360 OpenAI-compatible models.

360's ``/v1/chat/completions`` support is inconsistent in two unrelated ways
that break DeerFlow's agent runtime:

1. Some tool-enabled turns return pseudo tool calls as plain text wrapped in
   ``<tool_call>...</tool_call>`` instead of structured ``tool_calls``.
2. The model may emit a skill name (for example ``frontend-design``) as if it
   were a callable tool, even though DeerFlow expects skills to be loaded via
   ``read_file(<skill>/SKILL.md)``.
3. Thinking-enabled turns stream ``reasoning_content`` deltas instead of
   ``content`` deltas. Standard ``ChatOpenAI._convert_chunk_to_generation_chunk``
   only understands the OpenAI-shaped ``content`` / ``tool_calls`` /
   ``function_call`` / ``refusal`` fields, so 360's ``reasoning_content`` is
   silently dropped. The result is a stream of empty ``AIMessageChunk``s during
   the entire reasoning phase and a perceived "non-streaming" UX: nothing shows
   up in the browser until the model switches to the answer phase. Capturing
   ``reasoning_content`` into ``additional_kwargs.reasoning_content`` (matching
   the convention used by DeepSeek/StepFun/MiMo patches) makes the stream
   visible immediately.

This adapter repairs the first three issues at the model boundary so the rest
of the runtime can keep operating on standard LangChain ``tool_calls`` /
``additional_kwargs.reasoning_content``.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterator, Mapping
from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI

from deerflow.agents.lead_agent.prompt import get_enabled_skills_for_config
from deerflow.config import get_app_config
from deerflow.models.assistant_payload_replay import (
    restore_assistant_payloads,
    restore_reasoning_content,
)

_TOOL_CALL_BLOCK_PATTERN = re.compile(r"</?tool_call>")
_FENCED_JSON_PATTERN = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)
_OPEN_TOOL_CALL_TAG = "<tool_call>"
_CLOSE_TOOL_CALL_TAG = "</tool_call>"
_SIMULATED_STREAM_CHUNK_SIZE = 15
_MISSING = object()


def _extract_reasoning(value: Any) -> str | object:
    """Return ``reasoning_content`` from a delta/message dict if present.

    360 only emits ``reasoning_content`` (not the StepFun-style ``reasoning``).
    Returns ``_MISSING`` when no reasoning field is present, so callers can tell
    "absent" apart from an explicit empty-string value.
    """
    if isinstance(value, Mapping):
        if "reasoning_content" in value and value["reasoning_content"] is not None:
            return value["reasoning_content"]
        return _MISSING

    # Pydantic / SDK objects
    attr = getattr(value, "reasoning_content", _MISSING)
    if attr is not _MISSING and attr is not None:
        return attr

    model_extra = getattr(value, "model_extra", None)
    if isinstance(model_extra, Mapping) and model_extra.get("reasoning_content") is not None:
        return model_extra["reasoning_content"]

    return _MISSING


def _with_reasoning_content(
    message: AIMessage | AIMessageChunk,
    reasoning: str,
) -> AIMessage | AIMessageChunk:
    """Return a copy of *message* with ``reasoning_content`` in additional_kwargs.

    Mirrors patched_stepfun / patched_mimo so downstream middlewares (memory,
    title, suggestions) recognize the reasoning payload uniformly across
    providers.
    """
    additional_kwargs = dict(message.additional_kwargs)
    if additional_kwargs.get("reasoning_content") != reasoning:
        additional_kwargs["reasoning_content"] = reasoning
    return message.model_copy(update={"additional_kwargs": additional_kwargs})


def _get_typed_choice_message(response: Any, index: int) -> Any:
    """Extract the SDK-typed choice message at *index*, if available."""
    choices = getattr(response, "choices", None)
    if choices is None:
        return None
    try:
        return choices[index].message
    except (AttributeError, IndexError, TypeError):
        return None


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


def _parse_tool_call_args(args_text: str) -> dict[str, Any] | None:
    stripped = args_text.strip()
    if not stripped:
        return {}
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _recover_stream_tool_calls(content: str) -> tuple[str, list[dict[str, Any]]]:
    """Strip complete pseudo tool-call blocks from streamed text."""
    cleaned, tool_calls = _extract_tool_calls_from_content(content)
    return cleaned, tool_calls


def _find_pending_tool_markup_start(content: str) -> int | None:
    """Return the start of a trailing incomplete tool-call block, if any."""
    last_open = content.rfind(_OPEN_TOOL_CALL_TAG)
    last_close = content.rfind(_CLOSE_TOOL_CALL_TAG)
    if last_open > last_close:
        return last_open

    for token in (_OPEN_TOOL_CALL_TAG, _CLOSE_TOOL_CALL_TAG):
        max_prefix_len = min(len(token) - 1, len(content))
        for prefix_len in range(max_prefix_len, 0, -1):
            if content.endswith(token[:prefix_len]):
                return len(content) - prefix_len
    return None


def _iter_text_chunks(text: str, *, chunk_size: int = _SIMULATED_STREAM_CHUNK_SIZE) -> Iterator[str]:
    for start in range(0, len(text), chunk_size):
        yield text[start : start + chunk_size]


class _ToolStreamRepairState:
    """Incrementally repair 360 tool-stream chunks into DeerFlow-friendly chunks."""

    def __init__(self) -> None:
        self._pending_content = ""
        self._structured_calls: dict[str, dict[str, Any]] = {}
        self._seen_signatures: set[tuple[str, str]] = set()
        self._last_message_id: str | None = None

    def _dedupe_tool_calls(self, tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        for tool_call in tool_calls:
            signature = _tool_call_signature(tool_call)
            if signature in self._seen_signatures:
                continue
            self._seen_signatures.add(signature)
            deduped.append(tool_call)
        return deduped

    def _consume_text(self, content: str, *, final: bool) -> tuple[str, list[dict[str, Any]]]:
        if content:
            self._pending_content += content

        cleaned, extracted_tool_calls = _recover_stream_tool_calls(self._pending_content)
        pending_start = None if final else _find_pending_tool_markup_start(cleaned)
        if pending_start is None:
            visible_text = cleaned
            self._pending_content = ""
        else:
            visible_text = cleaned[:pending_start]
            self._pending_content = cleaned[pending_start:]

        return visible_text, self._dedupe_tool_calls(extracted_tool_calls)

    def _consume_structured_tool_call_chunks(
        self,
        tool_call_chunks: list[dict[str, Any]] | None,
        *,
        final: bool,
    ) -> list[dict[str, Any]]:
        for raw_chunk in tool_call_chunks or []:
            if not isinstance(raw_chunk, dict):
                continue

            key = raw_chunk.get("id") or f"index:{raw_chunk.get('index')}"
            state = self._structured_calls.setdefault(
                key,
                {
                    "name": "",
                    "args": "",
                    "id": raw_chunk.get("id"),
                    "index": raw_chunk.get("index"),
                },
            )
            if raw_chunk.get("name"):
                state["name"] += str(raw_chunk["name"])
            if raw_chunk.get("args"):
                state["args"] += str(raw_chunk["args"])
            if raw_chunk.get("id") and not state.get("id"):
                state["id"] = raw_chunk["id"]

        completed: list[dict[str, Any]] = []
        for key, state in list(self._structured_calls.items()):
            name = str(state.get("name") or "").strip()
            if not name:
                continue

            parsed_args = _parse_tool_call_args(str(state.get("args") or ""))
            if parsed_args is None and not final:
                continue
            if parsed_args is None:
                parsed_args = {}

            canonical_name, canonical_args = _canonicalize_tool_name_and_args(
                name,
                parsed_args,
            )
            completed.append(
                {
                    "name": canonical_name,
                    "args": canonical_args,
                    "id": state.get("id") or f"call_{uuid.uuid4().hex[:24]}",
                }
            )
            del self._structured_calls[key]

        return self._dedupe_tool_calls(completed)

    def _build_output_chunks(
        self,
        *,
        message_id: str | None,
        visible_text: str,
        tool_calls: list[dict[str, Any]],
        source_chunk: ChatGenerationChunk | None,
    ) -> list[ChatGenerationChunk]:
        outputs: list[ChatGenerationChunk] = []

        if visible_text:
            outputs.append(
                ChatGenerationChunk(
                    message=AIMessageChunk(content=visible_text, id=message_id),
                )
            )

        if tool_calls:
            outputs.append(
                ChatGenerationChunk(
                    message=AIMessageChunk(
                        content="",
                        id=message_id,
                        tool_calls=tool_calls,
                        invalid_tool_calls=(
                            list(getattr(source_chunk.message, "invalid_tool_calls", []))
                            if source_chunk is not None
                            else []
                        ),
                        additional_kwargs=(
                            dict(source_chunk.message.additional_kwargs)
                            if source_chunk is not None
                            else {}
                        ),
                    ),
                )
            )

        # A streaming tail chunk often carries only usage_metadata + finish
        # reason (no content, no tool_calls). Without this branch _build_output
        # would return [] for it, dropping usage_metadata — and the accumulated
        # AIMessage that TokenUsageMiddleware reads (messages[-1].usage_metadata)
        # would have no usage, so per-turn token counts silently disappear.
        if not outputs and source_chunk is not None:
            source_msg = source_chunk.message
            if (
                getattr(source_msg, "usage_metadata", None)
                or source_chunk.generation_info
                or getattr(source_msg, "response_metadata", None)
            ):
                outputs.append(
                    ChatGenerationChunk(
                        message=AIMessageChunk(content="", id=message_id),
                    )
                )

        if outputs and source_chunk is not None:
            metadata_target = outputs[-1]
            metadata_target.generation_info = source_chunk.generation_info
            metadata_target.message.response_metadata = dict(
                source_chunk.message.response_metadata,
            )
            metadata_target.message.usage_metadata = source_chunk.message.usage_metadata

        return outputs

    def consume_chunk(self, chunk: ChatGenerationChunk) -> list[ChatGenerationChunk]:
        if chunk.message.id is not None:
            self._last_message_id = chunk.message.id

        visible_text, recovered_tool_calls = self._consume_text(
            chunk.message.content if isinstance(chunk.message.content, str) else "",
            final=False,
        )
        structured_tool_calls = self._consume_structured_tool_call_chunks(
            getattr(chunk.message, "tool_call_chunks", []),
            final=False,
        )
        return self._build_output_chunks(
            message_id=chunk.message.id or self._last_message_id,
            visible_text=visible_text,
            tool_calls=[*recovered_tool_calls, *structured_tool_calls],
            source_chunk=chunk,
        )

    def flush(self, source_chunk: ChatGenerationChunk | None) -> list[ChatGenerationChunk]:
        visible_text, recovered_tool_calls = self._consume_text("", final=True)
        structured_tool_calls = self._consume_structured_tool_call_chunks(
            None,
            final=True,
        )
        return self._build_output_chunks(
            message_id=(
                source_chunk.message.id
                if source_chunk is not None and source_chunk.message.id is not None
                else self._last_message_id
            ),
            visible_text=visible_text,
            tool_calls=[*recovered_tool_calls, *structured_tool_calls],
            source_chunk=source_chunk,
        )


def _reasoning_passthrough_chunk(chunk: ChatGenerationChunk) -> ChatGenerationChunk | None:
    """Return a reasoning-only chunk if *chunk* carries a ``reasoning_content`` delta.

    The tool-call repair state machine rebuilds content/tool_call chunks from
    scratch and does not preserve ``additional_kwargs``, so reasoning deltas
    must be emitted separately to survive the with-tools streaming path. Returns
    ``None`` when the chunk has no reasoning content.
    """
    reasoning = chunk.message.additional_kwargs.get("reasoning_content")
    if not reasoning:
        return None
    return ChatGenerationChunk(
        message=AIMessageChunk(
            content="",
            id=chunk.message.id,
            additional_kwargs={"reasoning_content": reasoning},
        ),
        generation_info=chunk.generation_info,
    )


def _iter_simulated_stream_chunks(result: ChatResult) -> Iterator[ChatGenerationChunk]:
    for generation in result.generations:
        message = generation.message
        content = message.content
        tool_calls = _normalize_tool_calls(getattr(message, "tool_calls", []))
        if isinstance(content, str) and content:
            for index, text_chunk in enumerate(_iter_text_chunks(content)):
                yield ChatGenerationChunk(
                    message=AIMessageChunk(
                        content=text_chunk,
                        id=message.id,
                        response_metadata=message.response_metadata if index == 0 else {},
                        usage_metadata=message.usage_metadata if index == 0 else None,
                    ),
                    generation_info=generation.generation_info if index == 0 else None,
                )
        if tool_calls:
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    id=message.id,
                    tool_calls=tool_calls,
                    invalid_tool_calls=getattr(message, "invalid_tool_calls", []),
                    additional_kwargs=message.additional_kwargs,
                    response_metadata=message.response_metadata,
                    usage_metadata=message.usage_metadata,
                ),
                generation_info=generation.generation_info,
            )
        elif not isinstance(content, str):
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content=content,
                    id=message.id,
                    response_metadata=message.response_metadata,
                    usage_metadata=message.usage_metadata,
                ),
                generation_info=generation.generation_info,
            )


class PatchedChat360(ChatOpenAI):
    """ChatOpenAI with 360-specific pseudo tool-call recovery and reasoning capture."""

    @classmethod
    def is_lc_serializable(cls) -> bool:
        return True

    @property
    def lc_secrets(self) -> dict[str, str]:
        return {"api_key": "QIHOO_360_API_KEY", "openai_api_key": "QIHOO_360_API_KEY"}

    # --- Multi-turn replay: keep reasoning_content on historical assistant
    #     messages so the next API call does not lose it. Required by reasoning
    #     models when the agent makes follow-up tool-call turns. ----------------

    def _get_request_payload(
        self,
        input_: LanguageModelInput,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict:
        original_messages = self._convert_input(input_).to_messages()
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        restore_assistant_payloads(
            payload.get("messages", []),
            original_messages,
            restore_reasoning_content,
        )
        return payload

    # --- Streaming reasoning capture ----------------------------------------
    # Hooks into the per-chunk conversion so that ``reasoning_content`` deltas
    # land in ``additional_kwargs.reasoning_content`` instead of being dropped
    # by the standard OpenAI chunk converter. Without this hook, every chunk
    # of the reasoning phase yields an empty ``AIMessageChunk`` and the UI
    # appears to hang until the model switches to the answer phase.

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict,
        default_chunk_class: type,
        base_generation_info: dict | None,
    ) -> ChatGenerationChunk | None:
        generation_chunk = super()._convert_chunk_to_generation_chunk(
            chunk,
            default_chunk_class,
            base_generation_info,
        )
        if generation_chunk is None:
            return None

        choices = chunk.get("choices", [])
        if choices:
            delta = choices[0].get("delta") or {}
            reasoning = _extract_reasoning(delta)
            if reasoning is not _MISSING and isinstance(generation_chunk.message, AIMessageChunk):
                generation_chunk = ChatGenerationChunk(
                    message=_with_reasoning_content(generation_chunk.message, reasoning),
                    generation_info=generation_chunk.generation_info,
                )

        return generation_chunk

    # --- Non-streaming reasoning capture ------------------------------------

    def _create_chat_result(
        self,
        response: dict | Any,
        generation_info: dict | None = None,
    ) -> ChatResult:
        result = super()._create_chat_result(response, generation_info)
        response_dict = response if isinstance(response, dict) else response.model_dump()
        choices = response_dict.get("choices", [])

        patched_generations: list[ChatGeneration] | None = None
        for index, generation in enumerate(result.generations):
            choice = choices[index] if index < len(choices) else {}
            choice_message = choice.get("message", {}) if isinstance(choice, Mapping) else {}
            reasoning = _extract_reasoning(choice_message)
            if reasoning is _MISSING and not isinstance(response, dict):
                reasoning = _extract_reasoning(_get_typed_choice_message(response, index))

            message = generation.message
            if reasoning is not _MISSING and isinstance(message, AIMessage):
                if patched_generations is None:
                    patched_generations = list(result.generations)
                patched_generations[index] = ChatGeneration(
                    message=_with_reasoning_content(message, reasoning),
                    generation_info=generation.generation_info,
                )

        if patched_generations is not None:
            return ChatResult(
                generations=patched_generations,
                llm_output=result.llm_output,
            )
        return result

    # --- Tool-call repair ---------------------------------------------------

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

        repair = _ToolStreamRepairState()
        yielded_any = False
        last_chunk: ChatGenerationChunk | None = None
        try:
            for chunk in super()._stream(messages, stop=stop, run_manager=run_manager, **kwargs):
                last_chunk = chunk
                # Pass reasoning_content deltas through untouched. The repair
                # state machine rebuilds content/tool_call chunks without
                # preserving additional_kwargs, so without this passthrough the
                # entire reasoning phase would be dropped on the with-tools path.
                reasoning_chunk = _reasoning_passthrough_chunk(chunk)
                if reasoning_chunk is not None:
                    yielded_any = True
                    yield reasoning_chunk
                for repaired in repair.consume_chunk(chunk):
                    yielded_any = True
                    yield repaired
            for repaired in repair.flush(last_chunk):
                yielded_any = True
                yield repaired
            if yielded_any:
                return
        except Exception:
            if yielded_any:
                raise

        yield from _iter_simulated_stream_chunks(
            self._generate(messages, stop=stop, run_manager=run_manager, **kwargs),
        )

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        if not kwargs.get("tools"):
            async for chunk in super()._astream(messages, stop=stop, run_manager=run_manager, **kwargs):
                yield chunk
            return

        repair = _ToolStreamRepairState()
        yielded_any = False
        last_chunk: ChatGenerationChunk | None = None
        try:
            async for chunk in super()._astream(messages, stop=stop, run_manager=run_manager, **kwargs):
                last_chunk = chunk
                # See _stream: pass reasoning_content through untouched so the
                # thinking phase stays visible on the with-tools path.
                reasoning_chunk = _reasoning_passthrough_chunk(chunk)
                if reasoning_chunk is not None:
                    yielded_any = True
                    yield reasoning_chunk
                for repaired in repair.consume_chunk(chunk):
                    yielded_any = True
                    yield repaired
            for repaired in repair.flush(last_chunk):
                yielded_any = True
                yield repaired
            if yielded_any:
                return
        except Exception:
            if yielded_any:
                raise

        for chunk in _iter_simulated_stream_chunks(
            await self._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs),
        ):
            yield chunk
