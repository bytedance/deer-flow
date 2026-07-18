"""Middleware to fix dangling tool calls and orphan tool results in message history.

A dangling tool call occurs when an AIMessage contains tool_calls but there are
no corresponding ToolMessages in the history (e.g., due to user interruption or
request cancellation). An orphan ToolMessage occurs when a tool result exists
without a matching AIMessage tool_call (e.g., after summarization/branching
dropped the upstream AIMessage). Both cause strict-provider rejections.

This middleware intercepts the model call to:
- Sanitize malformed tool-call names and arguments before provider serialization
- Insert synthetic ToolMessages with an error indicator for each dangling AIMessage
  tool_call, ensuring correct message ordering
- Drop orphan ToolMessages whose originating tool_call is no longer present in the
  request, preventing strict OpenAI-compatible backends from returning HTTP 400

Note: Uses wrap_model_call instead of before_model to ensure patches are inserted
at the correct positions (immediately after each dangling AIMessage), not appended
to the end of the message list as before_model + add_messages reducer would do.
"""

import json
import logging
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import ToolMessage

logger = logging.getLogger(__name__)

# Workaround for issue #2894: malformed write_file calls can carry huge Markdown
# payloads in invalid tool-call args. Keep recovery error details short so the
# synthetic ToolMessage does not echo large or malformed content back to the model.
_MAX_RECOVERY_ERROR_DETAIL_LEN = 500
_UNKNOWN_TOOL_NAME = "unknown_tool"
_EMPTY_TOOL_NAME_ERROR = "Tool call could not be executed because its name was missing or empty."
_SYNTHETIC_TOOL_CALL_ID_PREFIX = "deerflow_synthetic_tool_call_"


def _valid_tool_name(name: object) -> bool:
    return isinstance(name, str) and bool(name.strip())


def _valid_tool_call_id(tool_call_id: object) -> bool:
    return isinstance(tool_call_id, str) and bool(tool_call_id.strip())


def _tool_call_name(tool_call: dict) -> object:
    """Return a call's declared name, mirroring _message_tool_calls' raw-payload fallback."""
    name = tool_call.get("name")
    if _valid_tool_name(name):
        return name
    function = tool_call.get("function")
    return function.get("name") if isinstance(function, dict) else name


def _names_can_pair(call_name: object, result_name: object) -> bool:
    """Whether a result's name contradicts a call's name.

    Either side may legitimately be missing (the empty-name sibling recovery exists
    for exactly that), and a missing name cannot contradict anything — only two
    usable names that differ rule the pairing out.
    """
    if not _valid_tool_name(call_name) or not _valid_tool_name(result_name):
        return True
    return call_name.strip() == result_name.strip()


def _relabel_tool_call_ids(tool_calls: list, msg_index: int, source: str) -> tuple[list, list[dict], bool]:
    """Replace malformed ids in one tool-call list with stable synthetic ids.

    The id is derived from the call's position so both the pairing pass and the
    model-bound message agree on it without threading state between them.

    Returns the rewritten list, one ``{original, synthetic, name}`` claim entry per
    relabelled call, and whether anything changed.
    """
    relabeled: list = []
    assigned: list[dict] = []
    changed = False
    for position, tool_call in enumerate(tool_calls):
        if not isinstance(tool_call, dict) or _valid_tool_call_id(tool_call.get("id")):
            relabeled.append(tool_call)
            continue
        synthetic = f"{_SYNTHETIC_TOOL_CALL_ID_PREFIX}{msg_index}_{source}_{position}"
        relabeled.append({**tool_call, "id": synthetic})
        changed = True
        assigned.append({"original": tool_call.get("id"), "synthetic": synthetic, "name": _tool_call_name(tool_call)})
    return relabeled, assigned, changed


def _turn_malformed_result_count(messages: list, start: int) -> int:
    """Count the malformed results issued by the turn opened at ``start``."""
    count = 0
    for msg in messages[start + 1 :]:
        if getattr(msg, "type", None) == "ai":
            break
        if isinstance(msg, ToolMessage) and not _valid_tool_call_id(msg.tool_call_id):
            count += 1
    return count


def _claim_synthetic_id(open_calls: list[dict], result: ToolMessage, positional: bool) -> str | None:
    """Consume the open malformed call that ``result`` answers, returning its new id.

    Malformed originals are all equally empty, so they cannot identify their own
    result; ``open_calls`` is already scoped to the issuing turn. Within that turn the
    result's name narrows the candidates, and only a *forced* choice is taken:

    * one compatible call — its name, or being the turn's only call, identifies it;
    * several compatible calls — position identifies them, but only while ``positional``
      holds, i.e. every open call in the turn has a result. Identical parallel calls
      (two ``bash``) are distinguishable by nothing else, and order here is a
      construction guarantee rather than an assumption about the provider: LangGraph's
      ``ToolNode`` builds the results with ``asyncio.gather`` / ``executor.map`` over
      ``tool_calls``, both of which yield in input order however the tools interleave.
      A *missing* result means a call was interrupted — this middleware's own trigger —
      so the surviving results can no longer be trusted to line up with the calls.

    Returning ``None`` leaves the result malformed for the orphan pass to drop, which is
    what an unattributable result gets today — better than inventing a pairing.
    """
    candidates = [position for position, entry in enumerate(open_calls) if entry["original"] == result.tool_call_id and _names_can_pair(entry["name"], result.name)]
    if not candidates or (len(candidates) > 1 and not positional):
        return None
    return open_calls.pop(candidates[0])["synthetic"]


def _normalize_tool_name(name: object) -> str:
    return name.strip() if _valid_tool_name(name) else _UNKNOWN_TOOL_NAME


def _has_invalid_tool_name(name: object) -> bool:
    return not _valid_tool_name(name)


def _parse_json_object(value: object) -> dict | None:
    """Parse a JSON-object string, returning None for other inputs."""
    if not isinstance(value, str):
        return None
    try:
        parsed = json.loads(value)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _normalize_tool_arguments(arguments: object) -> str:
    """Return a JSON-object string safe for OpenAI-compatible replay."""
    if isinstance(arguments, dict):
        try:
            return json.dumps(arguments, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError):
            return "{}"
    return arguments if _parse_json_object(arguments) is not None else "{}"


class DanglingToolCallMiddleware(AgentMiddleware[AgentState]):
    """Inserts placeholder ToolMessages for dangling tool calls and drops orphan
    ToolMessages (tool results whose originating AIMessage tool_call is gone).

    Scans the message history for:
    - AIMessages whose tool_calls lack corresponding ToolMessages, and injects
      synthetic error responses immediately after the offending AIMessage
    - ToolMessages with no matching AIMessage tool_call (orphans), and drops
      them so strict OpenAI-compatible backends do not reject the request
    """

    @staticmethod
    def _message_tool_calls(msg) -> list[dict]:
        """Return normalized tool calls from structured fields or raw provider payloads.

        LangChain stores malformed provider function calls in ``invalid_tool_calls``.
        They do not execute, but provider adapters may still serialize enough of
        the call id/name back into the next request that strict OpenAI-compatible
        validators expect a matching ToolMessage. Treat them as dangling calls so
        the next model request stays well-formed and the model sees a recoverable
        tool error instead of another provider 400.
        """
        normalized: list[dict] = []

        tool_calls = getattr(msg, "tool_calls", None) or []
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                logger.debug("Skipping malformed non-dict tool_call in AIMessage: %r", tool_call)
                continue
            original_name = tool_call.get("name")
            normalized_call = dict(tool_call)
            normalized_call["name"] = _normalize_tool_name(original_name)
            if _has_invalid_tool_name(original_name):
                normalized_call["invalid_tool_name"] = True
            normalized.append(normalized_call)

        raw_tool_calls = (getattr(msg, "additional_kwargs", None) or {}).get("tool_calls") or []
        if not tool_calls:
            for raw_tc in raw_tool_calls:
                if not isinstance(raw_tc, dict):
                    continue

                function = raw_tc.get("function")
                name = raw_tc.get("name")
                if not name and isinstance(function, dict):
                    name = function.get("name")

                args = raw_tc.get("args", {})
                if not args and isinstance(function, dict):
                    parsed_args = _parse_json_object(function.get("arguments"))
                    args = parsed_args if parsed_args is not None else {}

                normalized_call = {
                    "id": raw_tc.get("id"),
                    "name": _normalize_tool_name(name),
                    "args": args if isinstance(args, dict) else {},
                }
                if _has_invalid_tool_name(name):
                    normalized_call["invalid_tool_name"] = True
                normalized.append(normalized_call)

        for invalid_tc in getattr(msg, "invalid_tool_calls", None) or []:
            if not isinstance(invalid_tc, dict):
                continue
            original_name = invalid_tc.get("name")
            normalized_call = {
                "id": invalid_tc.get("id"),
                "name": _normalize_tool_name(original_name),
                "args": {},
                "invalid": True,
                "error": invalid_tc.get("error"),
            }
            if _has_invalid_tool_name(original_name):
                normalized_call["invalid_tool_name"] = True
            normalized.append(normalized_call)

        return normalized

    @staticmethod
    def _synthetic_tool_message_content(tool_call: dict) -> str:
        if tool_call.get("invalid_tool_name"):
            return f"[{_EMPTY_TOOL_NAME_ERROR} Use one of the available tool names when retrying.]"
        if tool_call.get("invalid"):
            name = tool_call.get("name")
            error = tool_call.get("error")
            error_text = error[:_MAX_RECOVERY_ERROR_DETAIL_LEN] if isinstance(error, str) and error else ""
            # Workaround for issue #2894: malformed write_file calls can carry huge Markdown
            # payloads in invalid tool-call args. Keep recovery guidance actionable without
            # echoing large or malformed content back to the model.
            if name == "write_file":
                details = f" Parser error: {error_text}" if error_text else ""
                return (
                    "[write_file failed before execution: the tool-call arguments were not valid JSON, "
                    "so no file was written. This often happens when the model tries to write a very "
                    "large Markdown file in a single tool call, especially when `content` contains "
                    "unescaped quotes, inline JSON, backslashes, or code fences. Do not retry the same "
                    "large `write_file` payload for this artifact; provide the report/content directly "
                    "as normal assistant text in your next response. If a file write is still needed "
                    f"later, split the file into smaller sections instead of one large payload.{details}]"
                )
            if error_text:
                return f"[Tool call could not be executed because its arguments were invalid: {error_text}]"
            return "[Tool call could not be executed because its arguments were invalid.]"
        return "[Tool call was interrupted and did not return a result.]"

    @staticmethod
    def _sanitize_ai_message_tool_calls(msg):
        """Return an AIMessage with model-bound tool calls safe to serialize."""
        if getattr(msg, "type", None) != "ai":
            return msg

        changed = False
        update: dict = {}

        tool_calls = getattr(msg, "tool_calls", None)
        if tool_calls:
            structured_changed = False
            sanitized_tool_calls = []
            for tool_call in tool_calls:
                if not isinstance(tool_call, dict):
                    sanitized_tool_calls.append(tool_call)
                    continue
                name = tool_call.get("name")
                sanitized = dict(tool_call)
                normalized_name = _normalize_tool_name(name)
                if sanitized.get("name") != normalized_name:
                    sanitized["name"] = normalized_name
                    structured_changed = True
                sanitized_tool_calls.append(sanitized)
            if structured_changed:
                update["tool_calls"] = sanitized_tool_calls
                changed = True

        invalid_tool_calls = getattr(msg, "invalid_tool_calls", None)
        if invalid_tool_calls:
            invalid_changed = False
            sanitized_invalid_tool_calls = []
            for invalid_tool_call in invalid_tool_calls:
                if not isinstance(invalid_tool_call, dict):
                    sanitized_invalid_tool_calls.append(invalid_tool_call)
                    continue
                sanitized = dict(invalid_tool_call)
                normalized_name = _normalize_tool_name(sanitized.get("name"))
                normalized_arguments = _normalize_tool_arguments(sanitized.get("args"))
                if sanitized.get("name") != normalized_name:
                    sanitized["name"] = normalized_name
                    invalid_changed = True
                if sanitized.get("args") != normalized_arguments:
                    sanitized["args"] = normalized_arguments
                    invalid_changed = True
                sanitized_invalid_tool_calls.append(sanitized)
            if invalid_changed:
                update["invalid_tool_calls"] = sanitized_invalid_tool_calls
                changed = True

        additional_kwargs = dict(getattr(msg, "additional_kwargs", {}) or {})
        raw_tool_calls = additional_kwargs.get("tool_calls")
        if isinstance(raw_tool_calls, list):
            raw_changed = False
            sanitized_raw_tool_calls = []
            for raw_tool_call in raw_tool_calls:
                if not isinstance(raw_tool_call, dict):
                    sanitized_raw_tool_calls.append(raw_tool_call)
                    continue

                sanitized_raw = dict(raw_tool_call)
                function = sanitized_raw.get("function")
                if isinstance(function, dict):
                    sanitized_function = dict(function)
                    normalized_name = _normalize_tool_name(sanitized_function.get("name"))
                    normalized_arguments = _normalize_tool_arguments(sanitized_function.get("arguments"))
                    if sanitized_function.get("name") != normalized_name:
                        sanitized_function["name"] = normalized_name
                        raw_changed = True
                    if sanitized_function.get("arguments") != normalized_arguments:
                        sanitized_function["arguments"] = normalized_arguments
                        raw_changed = True
                    if sanitized_function != function:
                        sanitized_raw["function"] = sanitized_function
                else:
                    normalized_name = _normalize_tool_name(sanitized_raw.get("name"))
                    if sanitized_raw.get("name") != normalized_name:
                        sanitized_raw["name"] = normalized_name
                        raw_changed = True
                sanitized_raw_tool_calls.append(sanitized_raw)

            if raw_changed:
                additional_kwargs["tool_calls"] = sanitized_raw_tool_calls
                update["additional_kwargs"] = additional_kwargs
                changed = True

        if not changed:
            return msg
        return msg.model_copy(update=update)

    @staticmethod
    def _normalize_tool_call_ids(messages: list) -> list:
        """Return messages with malformed tool-call ids replaced by synthetic ids.

        A provider that omits a tool-call id parses into a well-formed ``tool_calls``
        entry with an empty/``None`` id. Such an id can never enter the pairing set
        below, so the call's own result is dropped as an orphan and no placeholder
        replaces it — the request then reaches the provider with an empty id and the
        tool result gone. Normalizing ids up front lets the pairing and placeholder
        logic treat the call like any other, mirroring the empty-name recovery.
        """
        rewritten: dict[int, object] = {}
        # Malformed calls from the most recent AIMessage that are still unanswered.
        # Walking in document order and resetting here is what scopes a result to the
        # turn that issued it: a result never answers a call from an earlier turn, so
        # an earlier dangling call must not consume a later turn's result.
        open_calls: list[dict] = []
        # Whether this turn's results line up 1:1 with its malformed calls, which is what
        # lets position break a tie between otherwise indistinguishable siblings.
        positional = False

        for index, msg in enumerate(messages):
            if getattr(msg, "type", None) == "ai":
                update: dict = {}
                assigned: list[dict] = []
                structured = getattr(msg, "tool_calls", None) or []
                additional_kwargs = getattr(msg, "additional_kwargs", None) or {}
                raw_tool_calls = additional_kwargs.get("tool_calls")

                invalid = getattr(msg, "invalid_tool_calls", None) or []
                sources: list[tuple[str, list, str]] = [
                    ("call", structured, "tool_calls"),
                    ("invalid", invalid, "invalid_tool_calls"),
                ]
                # The raw payload is a fallback view of the same calls, so relabel it only when
                # it is the view actually serialized: the OpenAI serializer reaches for it only
                # once *both* structured views are empty. Minting an id for a shadowed raw view
                # would owe a placeholder to a call the provider never sees, putting an orphan
                # tool result on the wire.
                if not structured and not invalid and isinstance(raw_tool_calls, list):
                    sources.append(("raw", raw_tool_calls, "additional_kwargs"))

                for source, tool_calls, field in sources:
                    relabeled, source_assigned, changed = _relabel_tool_call_ids(tool_calls, index, source)
                    assigned.extend(source_assigned)
                    if not changed:
                        continue
                    update[field] = {**additional_kwargs, "tool_calls": relabeled} if field == "additional_kwargs" else relabeled

                open_calls = assigned
                positional = _turn_malformed_result_count(messages, index) == len(assigned)
                if update:
                    rewritten[index] = msg.model_copy(update=update)
                continue

            # Re-point an already-paired result at its call's new id so the pairing
            # below keeps it instead of dropping it as an orphan.
            if not isinstance(msg, ToolMessage) or _valid_tool_call_id(msg.tool_call_id):
                continue
            synthetic = _claim_synthetic_id(open_calls, msg, positional)
            if synthetic is not None:
                rewritten[index] = msg.model_copy(update={"tool_call_id": synthetic})

        if not rewritten:
            return messages
        return [rewritten.get(index, msg) for index, msg in enumerate(messages)]

    def _build_patched_messages(self, messages: list) -> list | None:
        """Return messages with tool results grouped after their tool-call AIMessage.

        This normalizes model-bound causal order before provider serialization while
        preserving already-valid transcripts unchanged.
        """
        normalized = self._normalize_tool_call_ids(messages)

        tool_messages_by_id: dict[str, deque[ToolMessage]] = defaultdict(deque)
        for msg in normalized:
            if isinstance(msg, ToolMessage):
                tool_messages_by_id[msg.tool_call_id].append(msg)

        tool_call_ids: set[str] = set()
        for msg in normalized:
            if getattr(msg, "type", None) != "ai":
                continue
            for tc in self._message_tool_calls(msg):
                tc_id = tc.get("id")
                if tc_id:
                    tool_call_ids.add(tc_id)

        patched: list = []
        patch_count = 0
        drop_count = 0
        for msg in normalized:
            if isinstance(msg, ToolMessage):
                if msg.tool_call_id in tool_call_ids:
                    continue  # Will be re-emitted after its AIMessage
                # Orphan: ToolMessage whose originating AIMessage tool_call is
                # no longer in the request (e.g. removed by summarization).
                # Drop it silently from the model request so strict providers
                # do not reject it with HTTP 400. Persisted state is untouched;
                # this only affects the single model call.
                drop_count += 1
                continue

            sanitized_msg = self._sanitize_ai_message_tool_calls(msg)
            patched.append(sanitized_msg)
            if getattr(msg, "type", None) != "ai":
                continue

            # Intentionally inspect the original message so empty names can be
            # classified before the sanitized message replaces them.
            for tc in self._message_tool_calls(msg):
                tc_id = tc.get("id")
                if not tc_id:
                    continue

                tool_msg_queue = tool_messages_by_id.get(tc_id)
                existing_tool_msg = tool_msg_queue.popleft() if tool_msg_queue else None
                if existing_tool_msg is not None:
                    if tc.get("invalid_tool_name") and _has_invalid_tool_name(existing_tool_msg.name):
                        existing_tool_msg = existing_tool_msg.model_copy(update={"name": tc["name"]})
                    patched.append(existing_tool_msg)
                else:
                    patched.append(
                        ToolMessage(
                            content=self._synthetic_tool_message_content(tc),
                            tool_call_id=tc_id,
                            name=tc.get("name", "unknown"),
                            status="error",
                        )
                    )
                    patch_count += 1

        if patched == messages and not drop_count:
            return None
        if drop_count or patch_count:
            logger.warning(
                "DanglingToolCallMiddleware: %d orphan(s) dropped, %d placeholder(s) injected",
                drop_count,
                patch_count,
            )
        return patched

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        patched = self._build_patched_messages(request.messages)
        if patched is not None:
            request = request.override(messages=patched)
        return handler(request)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        patched = self._build_patched_messages(request.messages)
        if patched is not None:
            request = request.override(messages=patched)
        return await handler(request)
