"""PII redaction middleware for model-bound context (issue #3190).

Detects personally identifiable information in the two untrusted-content entry
points — genuine user messages and remote-content tool results — and rewrites
it to keyed, value-derived placeholders (128-bit HMAC digests over base-26
letters, keyed by the deployment-scoped ``token_secret``) before it reaches
the model.
Complements the structural guardrails: ``InputSanitizationMiddleware``
neutralizes injection tags in user input and ``ToolResultSanitizationMiddleware``
does the same for remote tool results; neither inspects *content* for PII.

v1 is deterministic-only: fixed regex detectors with checksum validation where
the identifier format defines one (Luhn for card numbers, mod-11 for CN resident
IDs and CPF), no model calls, no new dependencies. Placeholders are HMAC-keyed
with the deployment-scoped ``token_secret`` (required whenever redaction is
enabled) and no mapping table is stored, so tokens cannot be re-derived
offline — neither from the repository nor from an observed token.

Scope model (mirrors the structural guardrails):

* the user-message rewrite is request-scoped — thread state keeps the raw text,
  so the UI still shows the original message and the whole conversation is
  re-redacted on every model call. Placeholders are value-derived
  (a 128-bit HMAC of the value under the deployment secret): the same raw
  value always renders the same token, so identities stay stable across
  turns, compaction, enqueues, and downstream content-signature
  deduplication — without any stored mapping;
* tool-result redaction runs at the tool boundary (``wrap_tool_call``) with the
  same allowlist as ``ToolResultSanitizationMiddleware`` (first-party web tools
  by name, MCP tools via their ``deerflow_mcp`` tag), so redacted text is what
  enters model context in the first place;
* subagents are covered because ``build_subagent_runtime_middlewares`` reuses
  this base;
* The memory-enqueue path is covered by the follow-up slice (#5577):
  ``redact_queued_messages`` (memory middleware) applies the same configured
  policy to the extraction payloads queued for the memory backend.
* The compaction and durable-context seams run outside ``wrap_model_call``;
  :func:`redact_text` is the shared entry point they call, wired from
  SummarizationMiddleware (compaction input) and DurableContextMiddleware
  (reinjected ``summary_text``); TitleMiddleware redacts its complete user and
  assistant fields before truncation and direct model invocation.

Detector order is fixed and pinned by a regression test; email → api_key →
national_id → credit_card → phone. Checksum-gated national IDs run *before*
the credit-card detector so an 18-digit resident ID whose digit run also
passes Luhn is never consumed as a card; unambiguous prefix/format patterns
(email, API keys) rewrite first, and phones last see only digits the stronger
gates did not claim.
"""

from __future__ import annotations

import hashlib
import hmac
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

# Digit-anchored patterns use digit-aware lookarounds instead of Unicode \b:
# CJK characters are word characters, so \b fails between a Chinese label and
# the identifier and the match is lost entirely ("身份证110105…").
_CREDIT_CARD_PATTERN = re.compile(r"(?<!\d)(?:\d{4}[ -]){3}\d{1,7}(?!\d)|(?<!\d)\d{13,19}(?!\d)")

_PHONE_PATTERN = re.compile(
    r"(?<!\d)\+\d{1,3}(?:[ \-]?\d{1,4}){3,6}(?!\d)"  # international +CC form; single-char separators so a candidate cannot run across a newline
    r"|(?<!\d)1[3-9]\d{9}(?!\d)"  # CN mobile
    r"|\(\d{3}\) ?\d{3}[-.]?\d{4}(?!\d)"  # US formatted
)

_NATIONAL_ID_PATTERN = re.compile(
    r"(?<![\dXx])\d{17}[\dXx](?![\dXx])"  # CN resident ID (checksum-validated)
    r"|(?<!\d)\d{3}\.\d{3}\.\d{3}-\d{2}(?!\d)"  # CPF (checksum-validated)
    r"|(?<!\d)\d{2}-\d{8}-\d(?!\d)"  # CUIT, 2+8+1 digits (format-only)
    r"|(?<![A-Z0-9Ñ&])[A-ZÑ&]{4}\d{6}[0-9A-Z]{3}(?![A-Z0-9Ñ&])"  # RFC with homoclave (format-only)
)

_DETECTORS: tuple[_Detector, ...] = (
    _Detector("email", _EMAIL_PATTERN),
    _Detector("api_key", _API_KEY_PATTERN),
    _Detector("national_id", _NATIONAL_ID_PATTERN, _national_id_valid),
    _Detector("credit_card", _CREDIT_CARD_PATTERN, _luhn_valid),
    _Detector("phone", _PHONE_PATTERN, lambda value: 8 <= len(re.sub(r"\D", "", value)) <= 15),
)


def active_pii_detectors(config: PiiRedactionConfig | None) -> tuple[_Detector, ...]:
    """Detectors active under *config*; empty when the feature is off."""
    if config is None or not config.enabled:
        return ()
    return tuple(d for d in _DETECTORS if getattr(config, f"redact_{d.name}"))


def redact_text(text: str | None, config: PiiRedactionConfig | None) -> str | None:
    """Redact PII from *text* under *config*; ``None``/disabled leaves it unchanged.

    Shared entry point for the seams that sit *outside* this middleware's
    ``wrap_model_call`` wrapper — SummarizationMiddleware invokes its summary
    model directly from ``before_model``, and DurableContextMiddleware injects
    its durable-context block inner of it — so compaction input and reinjected
    summaries get the same treatment as model-bound messages.
    """
    if config is None or not config.enabled or not isinstance(text, str) or not text:
        return text
    return _make_redactor(config).redact(text)


def redact_texts(texts: Sequence[str], config: PiiRedactionConfig | None) -> list[str]:
    """Redact related text fields, before truncation."""
    redactor = _make_redactor(config)
    return [redactor.redact(text) for text in texts]


def _make_redactor(config: PiiRedactionConfig | None) -> _Redactor:
    """Build the scan redactor: active detectors + the configured token key."""
    if config is None:
        return _Redactor((), None)
    return _Redactor(active_pii_detectors(config), config.token_secret)


def _placeholder_token(category: str, value: str, token_key: str) -> str:
    """Value-derived, deterministic placeholder (128-bit HMAC digest, base-26 letters).

    Three properties the token format must uphold:

    * **Value-derived** — sequential allocation is order-dependent: the same
      unchanged message re-redacted in a later batch can get a different
      token, which breaks downstream content-signature deduplication (e.g.
      OpenViking capture) and cross-turn identity. A pure function of the
      matched value keeps the token stable across batches, seams, and
      enqueues, with no shared state and no stored mapping;
    * **Letters-only** — the digest is encoded over ``a-z`` instead of hex, so
      a minted token contains no digit runs and can never satisfy the
      digit-anchored detectors that run later in the pinned order (no nested
      ``[EMAIL_…[PHONE_…]…`` corruption);
    * **Deployment-scoped linkability** — the digest is an HMAC over the
      deployment-scoped ``token_secret``: tokens are linkable only within one
      deployment and cannot be re-derived offline without the secret. The
      config model rejects enabling redaction without a non-empty secret, and
      the empty-key guard below is the backstop that keeps every code path on
      keyed digests (an unkeyed digest would be a publicly computable
      fingerprint, linkable across deployments and confirmable by guessing
      for low-entropy values). 128 bits keep distinct identities
      collision-free at any realistic volume.
    """
    if not token_key:
        raise ValueError("placeholder tokens require the configured non-empty token_secret")
    key_bytes = token_key.encode("utf-8")
    digest = hmac.new(key_bytes, f"{category}\x00{value}".encode(), hashlib.sha256).digest()
    alphabet = "abcdefghijklmnopqrstuvwxyz"
    number = int.from_bytes(digest[:16], "big")
    letters = []
    for _ in range(27):
        number, rem = divmod(number, 26)
        letters.append(alphabet[rem])
    return f"[{category.upper()}_{''.join(letters)}]"  # noqa: FS003


class _Redactor:
    """Applies the active detectors, in pinned order, to one piece of text.

    Stateless by design: the placeholder is a pure function of the matched
    value (see :func:`_placeholder_token`), so identical values render the
    same token within a scan, across scans, across enqueues, and across every
    seam that shares this module.
    """

    def __init__(self, detectors: Sequence[_Detector], token_key: str | None = None) -> None:
        self._detectors = detectors
        self._token_key = token_key

    def redact(self, text: str) -> str:
        for detector in self._detectors:
            text = detector.pattern.sub(self._replacer(detector), text)
        return text

    def _replacer(self, detector: _Detector) -> Callable[[re.Match[str]], str]:
        def replace(match: re.Match[str]) -> str:
            value = match.group(0)
            if detector.validator is not None and not detector.validator(value):
                return value
            return _placeholder_token(detector.name, value, self._token_key)

        return replace


def _redact_content(content: object, redactor: _Redactor) -> tuple[object, bool]:
    """Redact *content*, preserving its shape. Returns ``(content, changed)``.

    Handles the two shapes message content takes — plain ``str`` and a list of
    content blocks. Blocks pass through untouched except for any string-valued
    ``text`` field they carry: lenient downstream consumers (e.g. DeerMem's
    ``format_conversation_for_update``) read ``p.get("text")`` regardless of
    the block type, so a non-text block must not smuggle raw PII past the
    helper. The input is never mutated.
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
        elif isinstance(block, dict) and isinstance(block.get("text"), str):
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
        self._detectors = active_pii_detectors(config)
        self._token_key = config.token_secret if config else None

    def release_policy_parameters(self) -> dict[str, object]:
        """Declare the behaviour-affecting settings (middleware module guide)."""
        return {
            "enabled": True,
            "detectors": sorted(detector.name for detector in self._detectors),
        }

    # -- model-call boundary: genuine user messages ---------------------------

    def _process_request(self, request: ModelRequest) -> ModelRequest:
        redactor = _Redactor(self._detectors, self._token_key)
        messages = list(request.messages)
        state = getattr(request, "state", None) or {}
        summary = state.get("summary_text")
        redacted_summary = redactor.redact(summary) if isinstance(summary, str) else summary
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
        updates = {}
        if changed:
            updates["messages"] = messages
        if redacted_summary != summary:
            # Request-local copy only: the inner durable-context wrapper must
            # use the same allocation as the retained user messages.
            updates["state"] = {**state, "summary_text": redacted_summary}
        return request.override(**updates) if updates else request

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
        redactor = _Redactor(self._detectors, self._token_key)
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
