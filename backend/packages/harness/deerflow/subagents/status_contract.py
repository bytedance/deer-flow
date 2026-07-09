"""Backend↔frontend contract for structured subagent result metadata.

``task`` tool result text is model-visible display content. Runtime
consumers read the structured facts carried inside
``ToolMessage.additional_kwargs``:

- ``subagent_status``: one of ``SUBAGENT_STATUS_VALUES``.
- ``subagent_stop_reason`` (optional): when a guardrail cap ended the run
  early, one of ``SUBAGENT_STOP_REASON_VALUES`` (``token_capped`` /
  ``turn_capped`` / ``loop_capped``). Additive (#3875 Phase 2): a capped run
  that still produced a final answer stays ``status=completed`` and carries
  the cap here; a capped run with no usable output is ``status=failed`` +
  ``stop_reason``. Old frontends ignore the unknown field.
- ``subagent_error`` (optional): the human-readable error blob the
  backend recorded.
- ``subagent_result_brief`` / ``subagent_result_sha256`` (optional):
  bounded completed-result metadata plus a digest of the full result.

The shared fixture at ``contracts/subagent_status_contract.json`` pins
the enum values across Python and TypeScript.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Literal, NotRequired, TypedDict

SUBAGENT_STATUS_KEY = "subagent_status"
SUBAGENT_STOP_REASON_KEY = "subagent_stop_reason"
SUBAGENT_ERROR_KEY = "subagent_error"
SUBAGENT_RESULT_BRIEF_KEY = "subagent_result_brief"
SUBAGENT_RESULT_SHA256_KEY = "subagent_result_sha256"
SUBAGENT_METADATA_TEXT_MAX_CHARS = 2000

#: The producer always emits ``hashlib.sha256(...).hexdigest()`` — 64
#: lowercase hex chars. Readers enforce the same shape so a corrupted
#: relay value cannot masquerade as a digest.
_SHA256_HEX_RE = re.compile(r"[0-9a-f]{64}")

SubagentStatusValue = Literal[
    "completed",
    "failed",
    "cancelled",
    "timed_out",
    "polling_timed_out",
]

#: Enumeration of every value ``subagent_status`` may take. Mirrors the
#: ``valid_status_values`` array in the shared fixture; the contract test
#: pins them against each other. Capped runs do NOT get their own status
#: value (#3875 Phase 2): a cap that still produced output is ``completed``
#: and a cap with no output is ``failed``, with the reason carried on the
#: additive ``subagent_stop_reason`` field so old consumers keep working.
SUBAGENT_STATUS_VALUES: tuple[SubagentStatusValue, ...] = (
    "completed",
    "failed",
    "cancelled",
    "timed_out",
    "polling_timed_out",
)

#: Why a guardrail cap ended a run early. Carried on the additive
#: ``subagent_stop_reason`` field, never as a status enum value.
SubagentStopReasonValue = Literal["token_capped", "turn_capped", "loop_capped"]

SUBAGENT_STOP_REASON_VALUES: tuple[SubagentStopReasonValue, ...] = (
    "token_capped",
    "turn_capped",
    "loop_capped",
)

#: Human-readable label folded into the model-visible result text when a cap
#: fired, e.g. ``Task Succeeded (capped: token budget). Result: ...``.
_STOP_REASON_LABELS: dict[SubagentStopReasonValue, str] = {
    "token_capped": "token budget",
    "turn_capped": "turn budget",
    "loop_capped": "repeated tool-call loop",
}

#: Statuses that carry a recoverable result in ``subagent_result_brief`` /
#: ``subagent_result_sha256``. Only ``completed`` — and a capped run that
#: produced usable partial work surfaces as ``completed`` (+ ``stop_reason``),
#: so its work survives on the wire the same way a clean success does. Other
#: non-completed statuses carry only ``subagent_error``.
_RESULT_BEARING_STATUSES: frozenset[SubagentStatusValue] = frozenset({"completed"})

#: Read-side normalization for status values that previously appeared in
#: checkpointed thread history but are no longer produced. ``max_turns_reached``
#: was emitted by Phase 1 (#3949) and lives in persisted
#: ``ToolMessage.additional_kwargs``; #3980 removed it from the producer and the
#: contract fixture, but the reader still maps it to its Phase 2 cap equivalent
#: so historical data resolves terminally (with the cap on ``stop_reason``)
#: instead of stranding as ``in_progress`` in the delegation ledger. The frontend
#: ``subtask-result.ts`` keeps a parallel deprecated alias for the same reason.
_LEGACY_STATUS_NORMALIZATION: dict[str, SubagentStopReasonValue] = {
    "max_turns_reached": "turn_capped",
}


class StructuredSubagentResult(TypedDict):
    status: SubagentStatusValue
    stop_reason: NotRequired[SubagentStopReasonValue]
    result_brief: NotRequired[str]
    result_sha256: NotRequired[str]
    error: NotRequired[str]


def _bound_metadata_text(text: str, cap: int = SUBAGENT_METADATA_TEXT_MAX_CHARS) -> str:
    cleaned = text.strip()
    if len(cleaned) <= cap:
        return cleaned
    marker = "\n...\n"
    if cap <= len(marker):
        return cleaned[:cap]
    head = cap * 2 // 3
    tail = cap - head - len(marker)
    if tail <= 0:
        return cleaned[:cap]
    return f"{cleaned[:head]}{marker}{cleaned[-tail:]}"


def make_subagent_additional_kwargs(
    status: SubagentStatusValue,
    *,
    result: str | None = None,
    error: str | None = None,
    stop_reason: SubagentStopReasonValue | None = None,
) -> dict[str, str]:
    """Build the ``additional_kwargs`` payload the middleware stamps.

    Drops the error field when blank so the JSON wire format never carries
    a misleading empty ``subagent_error: ""``. ``stop_reason`` is stamped
    only when a guardrail cap ended the run (see :data:`SUBAGENT_STOP_REASON_VALUES`).

    Raises:
        ValueError: when ``status`` is not in :data:`SUBAGENT_STATUS_VALUES`,
            or ``stop_reason`` is not in :data:`SUBAGENT_STOP_REASON_VALUES`.
            We do not accept arbitrary strings: a typo would silently leak
            through to consumers as missing metadata rather than failing
            loudly at the producer boundary.
    """
    if status not in SUBAGENT_STATUS_VALUES:
        raise ValueError(f"invalid subagent status {status!r}; expected one of {SUBAGENT_STATUS_VALUES}")
    if stop_reason is not None and stop_reason not in SUBAGENT_STOP_REASON_VALUES:
        raise ValueError(f"invalid subagent stop_reason {stop_reason!r}; expected one of {SUBAGENT_STOP_REASON_VALUES}")
    payload: dict[str, str] = {SUBAGENT_STATUS_KEY: status}
    if status in _RESULT_BEARING_STATUSES and isinstance(result, str) and result.strip():
        payload[SUBAGENT_RESULT_BRIEF_KEY] = _bound_metadata_text(result)
        payload[SUBAGENT_RESULT_SHA256_KEY] = hashlib.sha256(result.encode("utf-8")).hexdigest()
    # Only ``completed`` (a clean success, or a capped run whose partial work
    # survived) suppresses the error blob; every other status carries it.
    if status != "completed" and isinstance(error, str) and error.strip():
        payload[SUBAGENT_ERROR_KEY] = _bound_metadata_text(error)
    if stop_reason is not None:
        payload[SUBAGENT_STOP_REASON_KEY] = stop_reason
    return payload


def format_subagent_result_message(
    status: SubagentStatusValue,
    *,
    result: str | None = None,
    error: str | None = None,
    stop_reason: SubagentStopReasonValue | None = None,
) -> tuple[str, str | None]:
    """Return model-visible task content plus normalized metadata error.

    When ``stop_reason`` is set, a short ``(capped: ...)`` note is folded into
    the text so the lead agent sees — without parsing metadata — that the run
    was ended by a guardrail cap. A capped run that produced usable work is
    ``status=completed`` (+ the partial result); a capped run with no usable
    output is ``status=failed``.
    """
    result_text = "" if result is None else str(result)
    error_text = str(error).strip() if isinstance(error, str) else ""
    capped = _STOP_REASON_LABELS.get(stop_reason) if stop_reason is not None else None

    if status == "completed":
        if capped:
            return f"Task Succeeded (capped: {capped}). Result: {result_text}", None
        return f"Task Succeeded. Result: {result_text}", None

    if status == "cancelled":
        detail = error_text or "Task cancelled by user."
        if detail == "Task cancelled by user.":
            return detail, detail
        return f"Task cancelled by user. Error: {detail}", detail

    if status == "timed_out":
        detail = error_text or "Task timed out."
        if detail == "Task timed out.":
            return detail, detail
        return f"Task timed out. Error: {detail}", detail

    if status == "polling_timed_out":
        detail = error_text or "Task polling timed out."
        return detail, detail

    # ``failed`` — including a turn-capped run that produced no usable output
    # (``stop_reason=turn_capped``): the cap note is folded in so the lead can
    # tell a broken subagent from one that simply ran out of turn budget.
    detail = error_text or "Task failed."
    if capped:
        if detail == "Task failed.":
            return f"Task failed (capped: {capped}).", detail
        return f"Task failed (capped: {capped}). Error: {detail}", detail
    if detail == "Task failed.":
        return detail, detail
    return f"Task failed. Error: {detail}", detail


def read_subagent_result_metadata(
    additional_kwargs: Mapping[str, object] | None,
) -> StructuredSubagentResult | None:
    if not additional_kwargs:
        return None
    raw_status = additional_kwargs.get(SUBAGENT_STATUS_KEY)
    # Legacy checkpointed values (#3949) are no longer produced (#3980) but
    # survive in persisted history. Normalize them before the validity check so
    # they resolve terminally instead of returning ``None`` (which would strand
    # the delegation entry as ``in_progress``). A legacy ``max_turns_reached``
    # carried a recovered partial, so a payload that still has ``result_brief``
    # maps to the Phase 2 ``completed + turn_capped`` shape (partial survives on
    # the wire); one with no result maps to ``failed + turn_capped``.
    legacy_stop_reason = _LEGACY_STATUS_NORMALIZATION.get(raw_status) if isinstance(raw_status, str) else None
    if legacy_stop_reason is not None:
        raw_result_brief = additional_kwargs.get(SUBAGENT_RESULT_BRIEF_KEY)
        status = "completed" if (isinstance(raw_result_brief, str) and raw_result_brief.strip()) else "failed"
    elif raw_status in SUBAGENT_STATUS_VALUES:
        status = raw_status
    else:
        return None
    payload: StructuredSubagentResult = {"status": status}
    raw_result = additional_kwargs.get(SUBAGENT_RESULT_BRIEF_KEY)
    raw_hash = additional_kwargs.get(SUBAGENT_RESULT_SHA256_KEY)
    raw_error = additional_kwargs.get(SUBAGENT_ERROR_KEY)
    if status in _RESULT_BEARING_STATUSES and isinstance(raw_result, str) and raw_result.strip():
        payload["result_brief"] = _bound_metadata_text(raw_result)
        if isinstance(raw_hash, str) and _SHA256_HEX_RE.fullmatch(raw_hash):
            payload["result_sha256"] = raw_hash
    if status != "completed" and isinstance(raw_error, str) and raw_error.strip():
        payload["error"] = _bound_metadata_text(raw_error)
    # An explicit stop_reason on the wire wins; else the synthesized legacy reason.
    raw_stop_reason = additional_kwargs.get(SUBAGENT_STOP_REASON_KEY)
    if isinstance(raw_stop_reason, str) and raw_stop_reason in SUBAGENT_STOP_REASON_VALUES:
        payload["stop_reason"] = raw_stop_reason
    elif legacy_stop_reason is not None:
        payload["stop_reason"] = legacy_stop_reason
    return payload
