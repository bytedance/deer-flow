"""Backend↔frontend contract for structured subagent result metadata.

``task`` tool result text is model-visible display content. Runtime
consumers read the structured facts carried inside
``ToolMessage.additional_kwargs``:

- ``subagent_status``: one of ``SUBAGENT_STATUS_VALUES``.
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
    "max_turns_reached",
]

#: Enumeration of every value ``subagent_status`` may take. Mirrors the
#: ``valid_status_values`` array in the shared fixture; the contract test
#: pins them against each other.
SUBAGENT_STATUS_VALUES: tuple[SubagentStatusValue, ...] = (
    "completed",
    "failed",
    "cancelled",
    "timed_out",
    "polling_timed_out",
    "max_turns_reached",
)

#: Statuses that carry a recoverable result in ``subagent_result_brief`` /
#: ``subagent_result_sha256``. ``completed`` is the obvious case;
#: ``max_turns_reached`` (#3875 Phase 2) is included because a turn-capped
#: subagent may have produced useful partial work before hitting the budget,
#: and that work should survive on the wire (and in the delegation ledger)
#: the same way a completed result does — not be discarded with the cap
#: notice alone. Other non-completed statuses carry only ``subagent_error``.
_RESULT_BEARING_STATUSES: frozenset[SubagentStatusValue] = frozenset({"completed", "max_turns_reached"})


class StructuredSubagentResult(TypedDict):
    status: SubagentStatusValue
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
) -> dict[str, str]:
    """Build the ``additional_kwargs`` payload the middleware stamps.

    Drops the error field when blank so the JSON wire format never carries
    a misleading empty ``subagent_error: ""``.

    Raises:
        ValueError: when ``status`` is not in :data:`SUBAGENT_STATUS_VALUES`.
            We do not accept arbitrary strings: a typo would silently leak
            through to consumers as missing metadata rather than failing
            loudly at the producer boundary.
    """
    if status not in SUBAGENT_STATUS_VALUES:
        raise ValueError(f"invalid subagent status {status!r}; expected one of {SUBAGENT_STATUS_VALUES}")
    payload: dict[str, str] = {SUBAGENT_STATUS_KEY: status}
    if status in _RESULT_BEARING_STATUSES and isinstance(result, str) and result.strip():
        payload[SUBAGENT_RESULT_BRIEF_KEY] = _bound_metadata_text(result)
        payload[SUBAGENT_RESULT_SHA256_KEY] = hashlib.sha256(result.encode("utf-8")).hexdigest()
    # ``max_turns_reached`` is result-bearing AND carries the cap notice as
    # ``subagent_error``; only ``completed`` (a clean success) suppresses it.
    if status != "completed" and isinstance(error, str) and error.strip():
        payload[SUBAGENT_ERROR_KEY] = _bound_metadata_text(error)
    return payload


def format_subagent_result_message(
    status: SubagentStatusValue,
    *,
    result: str | None = None,
    error: str | None = None,
) -> tuple[str, str | None]:
    """Return model-visible task content plus normalized metadata error."""
    result_text = "" if result is None else str(result)
    error_text = str(error).strip() if isinstance(error, str) else ""

    if status == "completed":
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

    if status == "max_turns_reached":
        # Turn-budget cap (#3875 Phase 2): the cap reason travels on
        # ``error`` (metadata), and the model-visible text leads with the
        # partial result the executor recovered so the lead can reuse the
        # work instead of seeing a bare failure.
        detail = error_text or "Turn budget reached."
        partial = result_text.strip() if result_text.strip() else "No partial result was produced before the turn budget was reached."
        return f"Task reached max turns. {detail} Partial result: {partial}", detail

    detail = error_text or "Task failed."
    if detail == "Task failed.":
        return detail, detail
    return f"Task failed. Error: {detail}", detail


def read_subagent_result_metadata(
    additional_kwargs: Mapping[str, object] | None,
) -> StructuredSubagentResult | None:
    if not additional_kwargs:
        return None
    raw_status = additional_kwargs.get(SUBAGENT_STATUS_KEY)
    if raw_status not in SUBAGENT_STATUS_VALUES:
        return None
    status = raw_status
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
    return payload
