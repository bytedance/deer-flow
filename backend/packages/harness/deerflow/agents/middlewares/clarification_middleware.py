"""Middleware for intercepting clarification requests and presenting them to the user."""

import json
import logging
import re
from collections.abc import Callable
from hashlib import sha256
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.graph import END
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

logger = logging.getLogger(__name__)

# Whitelisted form field types; anything else degrades to "text" so a bad
# model-provided type can never produce an unrenderable card.
FORM_FIELD_TYPES = frozenset({"text", "textarea", "number", "select", "multi_select", "checkbox", "date"})
_OPTION_FIELD_TYPES = frozenset({"select", "multi_select"})

# Field names that collide with JavaScript Object.prototype properties. The
# frontend stores form values in a plain object keyed by field name, so these
# would read inherited prototype members instead of user input.
_RESERVED_FIELD_NAMES = frozenset(
    {
        "__proto__",
        "constructor",
        "prototype",
        "toString",
        "toLocaleString",
        "valueOf",
        "hasOwnProperty",
        "isPrototypeOf",
        "propertyIsEnumerable",
        "__defineGetter__",
        "__defineSetter__",
        "__lookupGetter__",
        "__lookupSetter__",
    }
)

# Hard caps so a runaway model cannot publish an unbounded form. Exceeding a
# cap is a structural error: the whole form degrades to the legacy modes
# instead of silently truncating business fields.
MAX_FORM_FIELDS = 16
MAX_FIELD_OPTIONS = 24
MAX_FIELD_TEXT_CHARS = 200
# Total budget over the serialized normalized fields, in UTF-8 bytes. The
# per-item caps alone still admit forms whose plain-text IM fallback exceeds
# channel delivery limits (Slack truncates at 40k chars per message; Feishu
# guides ~30KB per card), which would silently drop trailing fields — the very
# thing atomic validation exists to prevent. 16KB keeps the fallback text of
# any accepted form comfortably inside the strictest supported channel while
# leaving headroom for question/context.
MAX_FORM_SERIALIZED_BYTES = 16_384

_XML_TAG_RE = re.compile(r"</?[A-Za-z_][\w:.-]*(?:\s[^<>]*?)?\s*/?>")


class ClarificationMiddlewareState(AgentState):
    """Compatible with the `ThreadState` schema."""

    pass


class ClarificationMiddleware(AgentMiddleware[ClarificationMiddlewareState]):
    """Intercepts clarification tool calls and interrupts execution to present questions to the user.

    When the model calls the `ask_clarification` tool, this middleware:
    1. Intercepts the tool call before execution
    2. Extracts the clarification question and metadata
    3. Formats a user-friendly message
    4. Returns a Command that interrupts execution and presents the question
    5. Waits for user response before continuing

    This replaces the tool-based approach where clarification continued the conversation flow.
    """

    state_schema = ClarificationMiddlewareState

    def _stable_message_id(self, tool_call_id: str, formatted_message: str) -> str:
        """Build a deterministic message ID so retried clarification calls replace, not append."""
        if tool_call_id:
            return f"clarification:{tool_call_id}"
        digest = sha256(formatted_message.encode("utf-8")).hexdigest()[:16]
        return f"clarification:{digest}"

    def _normalize_options(self, raw_options: Any) -> list[str]:
        """Normalize tool-provided options into displayable string values."""
        options = raw_options

        # Some models (e.g. Qwen3-Max) serialize array parameters as JSON strings
        # instead of native arrays. Deserialize and normalize so `options`
        # is always a list for the rendering logic below.
        if isinstance(options, str):
            try:
                options = json.loads(options)
            except (json.JSONDecodeError, TypeError):
                options = [options]

        if options is None:
            return []
        if isinstance(options, dict):
            options = self._flatten_dict_option_values(options)
        elif not isinstance(options, list):
            options = [options]

        # Trim, drop blanks, and dedupe (order-preserving): the frontend parser
        # rejects the whole payload on blank option labels, so they must never
        # be emitted.
        normalized: list[str] = []
        seen: set[str] = set()
        for option in options:
            text = _XML_TAG_RE.sub("", str(option)).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            normalized.append(text)
        return normalized

    @staticmethod
    def _flatten_dict_option_values(value: dict[str, Any]) -> list[str | int | float]:
        """Flatten scalar leaves from XML-to-dict option payloads in source order."""
        flattened: list[str | int | float] = []

        def collect(nested: Any) -> None:
            if isinstance(nested, dict):
                for item in nested.values():
                    collect(item)
            elif isinstance(nested, list):
                for item in nested:
                    collect(item)
            elif isinstance(nested, str | int | float):
                flattened.append(nested)

        collect(value)
        return flattened

    @staticmethod
    def _normalize_bool(raw: Any) -> bool:
        """Coerce a model-provided boolean; some models serialize booleans as strings or 1/0."""
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, int | float):
            return bool(raw)
        if isinstance(raw, str):
            return raw.strip().lower() == "true"
        return False

    def _normalize_fields(self, raw_fields: Any) -> list[dict[str, Any]]:
        """Normalize tool-provided form fields into the validated v2 field schema.

        Validation is atomic: any structurally broken entry (non-dict, bad or
        reserved or duplicate name, over-cap counts/lengths) invalidates the
        whole form so the card can never render "complete" while silently
        missing a required business field. Benign issues keep their local
        degradation: unknown types and option-less selects become ``text``.
        """
        fields = raw_fields
        if isinstance(fields, str):
            try:
                fields = json.loads(fields)
            except (json.JSONDecodeError, TypeError):
                return []
        if not isinstance(fields, list):
            return []
        if len(fields) > MAX_FORM_FIELDS:
            return []

        normalized: list[dict[str, Any]] = []
        seen_names: set[str] = set()
        for entry in fields:
            if not isinstance(entry, dict):
                return []
            raw_name = entry.get("name")
            if not isinstance(raw_name, str) or not raw_name.strip():
                return []
            name = raw_name.strip()
            if name in _RESERVED_FIELD_NAMES or name in seen_names or len(name) > MAX_FIELD_TEXT_CHARS:
                return []
            seen_names.add(name)

            raw_label = entry.get("label")
            label = raw_label.strip() if isinstance(raw_label, str) and raw_label.strip() else name
            if len(label) > MAX_FIELD_TEXT_CHARS:
                return []

            field_type = entry.get("type")
            # isinstance guard first: `type: []` / `type: {}` are legal JSON
            # from a model, and an unhashable membership probe would raise
            # TypeError instead of degrading.
            if not isinstance(field_type, str) or field_type not in FORM_FIELD_TYPES:
                field_type = "text"

            options = self._normalize_options(entry.get("options")) if field_type in _OPTION_FIELD_TYPES else []
            if len(options) > MAX_FIELD_OPTIONS or any(len(option) > MAX_FIELD_TEXT_CHARS for option in options):
                return []
            if field_type in _OPTION_FIELD_TYPES and not options:
                field_type = "text"

            field: dict[str, Any] = {
                "name": name,
                "label": label,
                "type": field_type,
                "required": self._normalize_bool(entry.get("required")),
            }
            if field_type in _OPTION_FIELD_TYPES:
                field["options"] = [
                    {
                        "id": f"{name}-option-{index}",
                        "label": option,
                        "value": option,
                    }
                    for index, option in enumerate(options, 1)
                ]
            placeholder = entry.get("placeholder")
            if isinstance(placeholder, str) and placeholder.strip():
                if len(placeholder.strip()) > MAX_FIELD_TEXT_CHARS:
                    return []
                field["placeholder"] = placeholder.strip()
            normalized.append(field)

        if len(json.dumps(normalized, ensure_ascii=False).encode("utf-8")) > MAX_FORM_SERIALIZED_BYTES:
            return []

        return normalized

    def _build_human_input_payload(self, args: dict[str, Any], *, tool_call_id: str, request_id: str, fields: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Build the structured UI payload while keeping ToolMessage.content as fallback.

        Protocol versioning: legacy modes (``free_text`` / ``choice_with_other``)
        keep ``version: 1`` so their wire format is unchanged; the v2 ``form``
        mode carries ``version: 2`` so older frontends reject the payload and
        degrade to the plain-text ToolMessage content. Replies stay on the v1
        response protocol (``text`` / ``option``) — the form card submits a
        readable ``value`` summary, so no new response kind is introduced.

        ``fields`` accepts an already-normalized list so callers rendering both
        the payload and the text fallback normalize only once.
        """
        if fields is None:
            fields = self._normalize_fields(args.get("fields"))
        options = self._normalize_options(args.get("options", []))
        clarification_type = str(args.get("clarification_type", "missing_info"))

        if fields:
            version, input_mode = 2, "form"
        elif options:
            version, input_mode = 1, "choice_with_other"
        else:
            version, input_mode = 1, "free_text"

        payload: dict[str, Any] = {
            "version": version,
            "kind": "human_input_request",
            "source": "ask_clarification",
            "request_id": request_id,
            "clarification_type": clarification_type,
            "question": str(args.get("question") or ""),
            "input_mode": input_mode,
        }

        if tool_call_id:
            payload["tool_call_id"] = tool_call_id

        if "context" in args:
            context = args.get("context")
            payload["context"] = None if context is None else str(context)

        if input_mode == "form":
            payload["fields"] = fields
        elif options:
            payload["options"] = [
                {
                    "id": f"option-{index}",
                    "label": option,
                    "value": option,
                }
                for index, option in enumerate(options, 1)
            ]

        return payload

    def _is_chinese(self, text: str) -> bool:
        """Check if text contains Chinese characters.

        Args:
            text: Text to check

        Returns:
            True if text contains Chinese characters
        """
        return any("\u4e00" <= char <= "\u9fff" for char in text)

    def _format_clarification_message(self, args: dict, fields: list[dict[str, Any]] | None = None) -> str:
        """Format the clarification arguments into a user-friendly message.

        Args:
            args: The tool call arguments containing clarification details
            fields: Already-normalized form fields, so callers rendering both
                the payload and this fallback normalize only once

        Returns:
            Formatted message string
        """
        question = args.get("question", "")
        # str() coercion keeps the icon lookup hashable — `clarification_type:
        # []` is legal JSON from a model and would raise TypeError as a dict key.
        clarification_type = str(args.get("clarification_type", "missing_info"))
        context = args.get("context")
        if fields is None:
            fields = self._normalize_fields(args.get("fields"))
        options = self._normalize_options(args.get("options", []))

        # Type-specific icons
        type_icons = {
            "missing_info": "❓",
            "ambiguous_requirement": "🤔",
            "approach_choice": "🔀",
            "risk_confirmation": "⚠️",
            "suggestion": "💡",
        }

        icon = type_icons.get(clarification_type, "❓")

        # Build the message naturally
        message_parts = []

        # Add icon and question together for a more natural flow
        if context:
            # If there's context, present it first as background
            message_parts.append(f"{icon} {context}")
            message_parts.append(f"\n{question}")
        else:
            # Just the question with icon
            message_parts.append(f"{icon} {question}")

        # Form fields take precedence over options, mirroring the payload logic.
        if fields:
            message_parts.append("")  # blank line for spacing
            for i, field in enumerate(fields, 1):
                line = f"  {i}. {field['label']}"
                if field["required"]:
                    line += " (required)"
                field_options = field.get("options")
                if field_options:
                    line += " — options: " + " / ".join(option["label"] for option in field_options)
                    if field["type"] == "multi_select":
                        line += " (multiple allowed)"
                message_parts.append(line)
            message_parts.append("")
            message_parts.append("Please reply with a value for each field.")
        elif options and len(options) > 0:
            message_parts.append("")  # blank line for spacing
            for i, option in enumerate(options, 1):
                message_parts.append(f"  {i}. {option}")

        return "\n".join(message_parts)

    def _is_disabled(self, request: ToolCallRequest) -> bool:
        """Whether clarifications are suppressed for this run.

        Non-interactive channels (e.g. GitHub webhooks) set
        ``disable_clarification`` in the run context because a clarification
        would dead-end the run — the human only "replies" via a later
        webhook delivery, by which point the agent's turn is long over.
        When set, we don't interrupt; we return a ToolMessage nudging the
        agent to proceed with its best judgment instead.
        """
        runtime = getattr(request, "runtime", None)
        context = getattr(runtime, "context", None)
        if not context:
            return False
        return bool(context.get("disable_clarification"))

    def _handle_disabled_clarification(self, request: ToolCallRequest) -> ToolMessage:
        """Suppress a clarification and tell the agent to proceed.

        Returns a plain ToolMessage (not a ``Command(goto=END)``) so the
        agent loop continues instead of ending — the agent receives this
        as the tool result and generates again, ideally acting rather
        than re-asking.
        """
        tool_call_id = request.tool_call.get("id", "")
        logger.info("ask_clarification suppressed (disable_clarification set); instructing agent to proceed")
        return ToolMessage(
            id=self._stable_message_id(tool_call_id, "proceed-without-clarification"),
            content=(
                "Clarification is disabled in this context — the human is not present "
                "to answer synchronously. Do not ask for confirmation. Proceed with your "
                "best judgment, carry out the requested action, and state any assumptions "
                "you made in your final response."
            ),
            tool_call_id=tool_call_id,
            name="ask_clarification",
        )

    def _handle_clarification(self, request: ToolCallRequest) -> Command:
        """Handle clarification request and return command to interrupt execution.

        Args:
            request: Tool call request

        Returns:
            Command that interrupts execution with the formatted clarification message
        """
        # Extract clarification arguments
        args = request.tool_call.get("args", {})
        question = args.get("question", "")

        logger.info("Intercepted clarification request")
        logger.debug("Clarification question: %s", question)

        # Normalize form fields once; both the text fallback and the payload
        # consume the same result.
        fields = self._normalize_fields(args.get("fields"))

        # Format the clarification message
        formatted_message = self._format_clarification_message(args, fields=fields)

        # Get the tool call ID
        tool_call_id = request.tool_call.get("id", "")

        request_id = self._stable_message_id(tool_call_id, formatted_message)
        human_input_payload = self._build_human_input_payload(args, tool_call_id=tool_call_id, request_id=request_id, fields=fields)

        # Create a ToolMessage with the formatted question
        # This will be added to the message history
        tool_message = ToolMessage(
            id=request_id,
            content=formatted_message,
            tool_call_id=tool_call_id,
            name="ask_clarification",
            artifact={"human_input": human_input_payload},
        )

        # Return a Command that:
        # 1. Adds the formatted tool message
        # 2. Interrupts execution by going to __end__
        # Note: We don't add an extra AIMessage here - the frontend will detect
        # and display ask_clarification tool messages directly
        return Command(
            update={"messages": [tool_message]},
            goto=END,
        )

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """Intercept ask_clarification tool calls and interrupt execution (sync version).

        Args:
            request: Tool call request
            handler: Original tool execution handler

        Returns:
            Command that interrupts execution with the formatted clarification message
        """
        # Check if this is an ask_clarification tool call
        if request.tool_call.get("name") != "ask_clarification":
            # Not a clarification call, execute normally
            return handler(request)

        if self._is_disabled(request):
            return self._handle_disabled_clarification(request)

        return self._handle_clarification(request)

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """Intercept ask_clarification tool calls and interrupt execution (async version).

        Args:
            request: Tool call request
            handler: Original tool execution handler (async)

        Returns:
            Command that interrupts execution with the formatted clarification message
        """
        # Check if this is an ask_clarification tool call
        if request.tool_call.get("name") != "ask_clarification":
            # Not a clarification call, execute normally
            return await handler(request)

        if self._is_disabled(request):
            return self._handle_disabled_clarification(request)

        return self._handle_clarification(request)
