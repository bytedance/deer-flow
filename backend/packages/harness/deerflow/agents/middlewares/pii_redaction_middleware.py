"""PII redaction middleware for model-bound context (issue #3190).

Detects personally identifiable information in the two untrusted-content entry
points — genuine user messages and remote-content tool results — and rewrites
it to irreversible placeholders (``[EMAIL_1]`` …) before it reaches the model.
Complements the structural guardrails: ``InputSanitizationMiddleware``
neutralizes injection tags in user input and ``ToolResultSanitizationMiddleware``
does the same for remote tool results; neither inspects *content* for PII.

v1 is deterministic-only: fixed regex detectors with checksum validation where
the identifier format defines one (Luhn for card numbers, mod-11 for CN resident
IDs and CPF), no model calls, no new dependencies. Redaction is irreversible —
no mapping table is stored, so there is nothing to protect and no
re-identification path.

Scope model (mirrors the structural guardrails):

* the user-message rewrite is request-scoped — thread state keeps the raw text,
  so the UI still shows the original message and the whole conversation is
  re-redacted on every model call, keeping placeholder numbering stable across
  turns (the Nth distinct email in a thread always renders ``[EMAIL_N]``);
* tool-result redaction runs at the tool boundary (``wrap_tool_call``) with the
  same allowlist as ``ToolResultSanitizationMiddleware`` (first-party web tools
  by name, MCP tools via their ``deerflow_mcp`` tag), so redacted text is what
  enters model context in the first place; placeholders restart per result;
* subagents are covered because ``build_subagent_runtime_middlewares`` reuses
  this base;
* NOT covered in v1: the memory-extraction path (follow-up slice per the issue
  discussion) and tool outputs externalized to disk by
  ``ToolOutputBudgetMiddleware`` (they are not model-bound).

Detector order is fixed and pinned by a regression test; email → api_key →
national_id → credit_card → phone. Checksum-gated national IDs run *before*
the credit-card detector so an 18-digit resident ID whose digit run also
passes Luhn is never consumed as a card; unambiguous prefix/format patterns
(email, API keys) rewrite first, and phones last see only digits the stronger
gates did not claim.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from dataclasses import replace as dc_replace
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import (
    ModelCallResult,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.errors import GraphBubbleUp
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from deerflow.agents.middlewares.message_utils import requires_input_sanitization
from deerflow.agents.middlewares.tool_result_sanitization_middleware import _REMOTE_CONTENT_TOOL_NAMES
from deerflow.agents.middlewares.tool_transform_meta import append_tool_transform
from deerflow.config.pii_redaction_config import PiiRedactionConfig
from deerflow.tools.mcp_metadata import is_mcp_tool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Checksum validators — the deterministic gate for numeric identifiers.
# ---------------------------------------------------------------------------


def _luhn_valid(value: str) -> bool:
    """Luhn checksum over the digits of *value* (separators ignored)."""
    digits = [int(ch) for ch in value if ch.isdigit()]
    if len(digits) < 13 or len(digits) > 19:
        return False
    checksum = 0
    for offset, digit in enumerate(reversed(digits)):
        if offset % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


_CN_ID_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
_CN_ID_CHECK_DIGITS = "10X98765432"


def _cn_resident_id_valid(value: str) -> bool:
    """GB 11643 checksum for the 18-digit resident ID number."""
    body = value[:17]
    if not body.isdigit():
        return False
    year, month, day = int(body[6:10]), int(body[10:12]), int(body[12:14])
    if not (1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31):
        return False
    total = sum(int(digit) * weight for digit, weight in zip(body, _CN_ID_WEIGHTS))
    return _CN_ID_CHECK_DIGITS[total % 11] == value[17].upper()


def _cpf_valid(value: str) -> bool:
    """Brazilian CPF mod-11 verification digits."""
    digits = [int(ch) for ch in value if ch.isdigit()]
    if len(digits) != 11 or len(set(digits)) == 1:
        return False
    for boundary in (9, 10):
        weight = 2
        total = 0
        for digit in reversed(digits[:boundary]):
            total += digit * weight
            weight += 1
        rest = (total * 10) % 11 % 10
        if rest != digits[boundary]:
            return False
    return True


def _national_id_valid(value: str) -> bool:
    """Dispatch by shape: CN resident ID, CPF; CUIT/RFC are format-only."""
    if "." in value or (len(value) == 18 and value[:17].isdigit()):
        return _cpf_valid(value) if "." in value else _cn_resident_id_valid(value)
    return True


# ---------------------------------------------------------------------------
# Detectors. Order is load-bearing: see module docstring.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Detector:
    name: str
    pattern: re.Pattern[str]
    validator: Callable[[str], bool] | None = None


_EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")

_API_KEY_PATTERN = re.compile(
    r"\b(?:"
    r"sk-[A-Za-z0-9_-]{20,}"  # OpenAI-style
    r"|AKIA[0-9A-Z]{16}"  # AWS access key id
    r"|gh[pousr]_[A-Za-z0-9]{30,}"  # GitHub token
    r"|github_pat_[A-Za-z0-9_]{20,}"  # GitHub fine-grained token
    r"|xox[baprs]-[A-Za-z0-9-]{10,}"  # Slack token
    r"|AIza[0-9A-Za-z_-]{35}"  # Google API key
    r")\b"
)

_CREDIT_CARD_PATTERN = re.compile(r"\b(?:\d{4}[ -]){3}\d{1,7}\b|\b\d{13,19}\b")

_PHONE_PATTERN = re.compile(
    r"\+\d{1,3}[\s-]?(?:\d{2,4}[\s-]?){2,4}\d{2,4}"  # international +CC form
    r"|\b1[3-9]\d{9}\b"  # CN mobile
    r"|\(\d{3}\)\s?\d{3}[-.]?\d{4}\b"  # US formatted
)

_NATIONAL_ID_PATTERN = re.compile(
    r"\b\d{17}[\dXx]\b"  # CN resident ID (checksum-validated)
    r"|\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"  # CPF (checksum-validated)
    r"|\b\d{2}-\d{10}-\d\b"  # CUIT (format-only)
    r"|\b[A-ZÑ&]{4}\d{6}[0-9A-Z]{3}\b"  # RFC with homoclave (format-only)
)

_DETECTORS: tuple[_Detector, ...] = (
    _Detector("email", _EMAIL_PATTERN),
    _Detector("api_key", _API_KEY_PATTERN),
    _Detector("national_id", _NATIONAL_ID_PATTERN, _national_id_valid),
    _Detector("credit_card", _CREDIT_CARD_PATTERN, _luhn_valid),
    _Detector("phone", _PHONE_PATTERN, lambda value: 8 <= len(re.sub(r"\D", "", value)) <= 15),
)


class _Redactor:
    """Per-scan redaction state: one stable placeholder per distinct value.

    A single instance covers one scan (one model request, or one tool result),
    so identical values render the same placeholder and cross-turn references
    stay coherent. Placeholders are irreversible — the mapping lives only as
    long as this instance.
    """

    def __init__(self, detectors: Sequence[_Detector]) -> None:
        self._detectors = detectors
        self._tokens: dict[tuple[str, str], str] = {}
        self._counts: dict[str, int] = {}

    def redact(self, text: str) -> str:
        for detector in self._detectors:
            text = detector.pattern.sub(self._replacer(detector), text)
        return text

    def _replacer(self, detector: _Detector) -> Callable[[re.Match[str]], str]:
        def replace(match: re.Match[str]) -> str:
            value = match.group(0)
            if detector.validator is not None and not detector.validator(value):
                return value
            key = (detector.name, value)
            token = self._tokens.get(key)
            if token is None:
                self._counts[detector.name] = self._counts.get(detector.name, 0) + 1
                token = f"[{detector.name.upper()}_{self._counts[detector.name]}]"
                self._tokens[key] = token
            return token

        return replace


def _redact_content(content: object, redactor: _Redactor) -> tuple[object, bool]:
    """Redact *content*, preserving its shape. Returns ``(content, changed)``.

    Handles the two shapes message content takes — plain ``str`` and a list of
    content blocks. Non-text blocks (images, etc.) pass through untouched.
    The input is never mutated.
    """
    if isinstance(content, str):
        redacted = redactor.redact(content)
        return redacted, redacted != content
    if not isinstance(content, list):
        return content, False
    new_content: list = []
    changed = False
    for block in content:
        if isinstance(block, str):
            redacted = redactor.redact(block)
            changed = changed or redacted != block
            new_content.append(redacted)
        elif isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
            redacted = redactor.redact(block["text"])
            if redacted != block["text"]:
                new_content.append({**block, "text": redacted})
                changed = True
            else:
                new_content.append(block)
        else:
            new_content.append(block)
    return new_content, changed


class PiiRedactionMiddleware(AgentMiddleware[AgentState]):
    """Rewrite PII in user messages and remote tool results to placeholders.

    Assembled only when ``pii_redaction.enabled`` is true, so every instance
    has at least one active detector. Unexpected errors fail open (the original
    content reaches the model) — consistent with the other guardrails, where
    one unprocessable row must not break the run; the trade-off is logged.
    """

    def __init__(self, config: PiiRedactionConfig) -> None:
        self._detectors = tuple(d for d in _DETECTORS if getattr(config, f"redact_{d.name}"))

    def release_policy_parameters(self) -> dict[str, object]:
        """Declare the behaviour-affecting settings (middleware module guide)."""
        return {
            "enabled": True,
            "detectors": sorted(detector.name for detector in self._detectors),
        }

    # -- model-call boundary: genuine user messages ---------------------------

    def _process_request(self, request: ModelRequest) -> ModelRequest:
        redactor = _Redactor(self._detectors)
        messages = list(request.messages)
        changed = False
        for index, msg in enumerate(messages):
            if not isinstance(msg, HumanMessage) or not requires_input_sanitization(msg):
                continue
            try:
                content, changed_msg = _redact_content(msg.content, redactor)
            except GraphBubbleUp:
                raise
            except Exception:
                logger.warning(
                    "PII redaction failed on user message at pos=%d; leaving it unchanged",
                    index,
                    exc_info=True,
                )
                continue
            if not changed_msg:
                continue
            messages[index] = HumanMessage(
                content=content,
                id=msg.id,
                name=msg.name,
                additional_kwargs=dict(msg.additional_kwargs or {}),
            )
            changed = True
        if not changed:
            return request
        return request.override(messages=messages)

    def _try_process(self, request: ModelRequest) -> ModelRequest:
        try:
            return self._process_request(request)
        except GraphBubbleUp:
            raise
        except Exception:
            logger.warning("PII redaction processing failed; passing original request to model", exc_info=True)
            return request

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        return handler(self._try_process(request))

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        return await handler(self._try_process(request))

    # -- tool boundary: remote-content tool results ---------------------------

    def _should_redact(self, request: ToolCallRequest) -> bool:
        if request.tool_call.get("name") in _REMOTE_CONTENT_TOOL_NAMES:
            return True
        return is_mcp_tool(getattr(request, "tool", None))

    def _redact_result(self, result: ToolMessage | Command) -> ToolMessage | Command:
        """Redact a tool-call result, mirroring ``_sanitize_result``'s shapes.

        Direct ``ToolMessage`` results are redacted; ``Command`` results carry
        their ToolMessages inside ``update.messages`` and are rebuilt with
        ``dc_replace`` only when one of them actually changed. One redactor
        spans the whole result, so placeholder numbering stays continuous
        across every ToolMessage the result carries.
        """
        redactor = _Redactor(self._detectors)
        if isinstance(result, ToolMessage):
            return self._redact_tool_message(result, redactor)
        update = getattr(result, "update", None)
        if isinstance(update, dict):
            messages = update.get("messages")
            if isinstance(messages, list) and any(isinstance(m, ToolMessage) for m in messages):
                new_messages = [self._redact_tool_message(m, redactor) if isinstance(m, ToolMessage) else m for m in messages]
                if new_messages != messages:
                    return dc_replace(result, update={**update, "messages": new_messages})
        return result

    def _redact_tool_message(self, message: ToolMessage, redactor: _Redactor) -> ToolMessage:
        content, changed = _redact_content(message.content, redactor)
        if not changed:
            return message
        additional_kwargs = dict(message.additional_kwargs or {})
        append_tool_transform(additional_kwargs, "pii_redaction", by="PiiRedactionMiddleware")
        # model_copy preserves artifact / response_metadata that a hand-built
        # constructor call would silently drop.
        return message.model_copy(update={"content": content, "additional_kwargs": additional_kwargs})

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        result = handler(request)
        if not self._should_redact(request):
            return result
        try:
            return self._redact_result(result)
        except Exception:
            logger.warning("PII redaction failed on tool result; leaving it unchanged", exc_info=True)
            return result

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        result = await handler(request)
        if not self._should_redact(request):
            return result
        try:
            return self._redact_result(result)
        except Exception:
            logger.warning("PII redaction failed on tool result; leaving it unchanged", exc_info=True)
            return result
