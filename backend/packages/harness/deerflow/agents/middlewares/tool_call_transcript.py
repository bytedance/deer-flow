"""Standalone validator and normalizer for tool-call transcript validity.

Ensures that before a model invocation, the provider-visible transcript satisfies
the tool-call protocol:

  - Every AIMessage with ``tool_calls`` must be immediately followed by
    ToolMessages for each tool_call ID.
  - No non-tool messages between an AIMessage(tool_calls) and its ToolMessages.
  - Every ToolMessage must have a matching preceding AIMessage(tool_call with
    same ID).
  - Multiple tool calls from one AIMessage → multiple ToolMessages in the same
    block.

These are pure functions — no state, no side effects — making them straightforward
to test and safe to call from any middleware.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

ViolationKind = Literal[
    "missing_tool_result",
    "non_adjacent_tool_result",
    "orphan_tool_message",
    "non_tool_between_ai_and_tool",
]


@dataclass(frozen=True)
class Violation:
    """A single tool-call transcript rule violation."""

    kind: ViolationKind
    index: int  # position in the original message list
    detail: str = ""

    def __str__(self) -> str:
        return f"Violation(kind={self.kind!r}, index={self.index}, detail={self.detail!r})"


@dataclass
class ValidationResult:
    """Result of validating a message list against the tool-call protocol."""

    is_valid: bool
    violations: list[Violation] = field(default_factory=list)


def _collect_ai_tool_call_ids(msg: BaseMessage) -> set[str]:
    """Return all tool_call IDs declared on an AIMessage (including invalid)."""
    if getattr(msg, "type", None) != "ai":
        return set()
    ids: set[str] = set()
    for tc in getattr(msg, "tool_calls", None) or []:
        tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
        if tc_id:
            ids.add(tc_id)
    for raw_tc in (getattr(msg, "additional_kwargs", None) or {}).get("tool_calls") or []:
        if isinstance(raw_tc, dict):
            tc_id = raw_tc.get("id")
            if tc_id:
                ids.add(tc_id)
    for itc in getattr(msg, "invalid_tool_calls", None) or []:
        if isinstance(itc, dict):
            tc_id = itc.get("id")
            if tc_id:
                ids.add(tc_id)
    return ids


def validate_tool_call_transcript(messages: list[BaseMessage]) -> ValidationResult:
    """Validate *messages* against the tool-call protocol.

    Returns a :class:`ValidationResult` with ``is_valid=True`` when the
    transcript satisfies all rules, and a list of :class:`Violation` objects
    otherwise.
    """
    violations: list[Violation] = []

    # Build a map of tool_call_id → index of the AIMessage that declared it.
    tool_call_to_ai_idx: dict[str, int] = {}
    for i, msg in enumerate(messages):
        for tc_id in _collect_ai_tool_call_ids(msg):
            tool_call_to_ai_idx[tc_id] = i

    # Track which tool_call_ids have been satisfied (ToolMessage seen after AI).
    satisfied: set[str] = set()
    # For each AI message with tool_calls, track if we've started seeing
    # ToolMessages for it — if so, any non-ToolMessage before all are
    # satisfied is a non_tool_between violation.
    ai_started_tool_block: set[int] = set()

    seen_tool_msg_ids: set[str] = set()

    for i, msg in enumerate(messages):
        if isinstance(msg, ToolMessage):
            tc_id = msg.tool_call_id
            seen_tool_msg_ids.add(tc_id)

            if tc_id not in tool_call_to_ai_idx:
                violations.append(Violation(
                    kind="orphan_tool_message",
                    index=i,
                    detail=f"ToolMessage with tool_call_id={tc_id!r} has no matching AIMessage",
                ))
                continue

            ai_idx = tool_call_to_ai_idx[tc_id]
            # Check adjacency: the ToolMessage must follow the AIMessage with no
            # non-tool messages in between.
            if ai_idx not in ai_started_tool_block:
                # First tool result for this AI — check nothing non-tool between
                # ai_idx and here.
                for j in range(ai_idx + 1, i):
                    if not isinstance(messages[j], ToolMessage):
                        violations.append(Violation(
                            kind="non_adjacent_tool_result",
                            index=i,
                            detail=f"ToolMessage for tool_call_id={tc_id!r} is non-adjacent to AIMessage at index {ai_idx}",
                        ))
                        break
                ai_started_tool_block.add(ai_idx)

            satisfied.add(tc_id)

        elif getattr(msg, "type", None) == "ai":
            tc_ids = _collect_ai_tool_call_ids(msg)
            if tc_ids:
                # Check if this AI turn's previous tool block is incomplete.
                pass  # handled below after full scan

    # Check for missing tool results.
    for tc_id, ai_idx in tool_call_to_ai_idx.items():
        if tc_id not in satisfied:
            violations.append(Violation(
                kind="missing_tool_result",
                index=ai_idx,
                detail=f"AIMessage at index {ai_idx} has tool_call_id={tc_id!r} with no ToolMessage",
            ))

    # Check for non-tool messages between AI(tool_calls) and its ToolMessages.
    for i, msg in enumerate(messages):
        if getattr(msg, "type", None) != "ai":
            continue
        tc_ids = _collect_ai_tool_call_ids(msg)
        if not tc_ids:
            continue
        # Scan forward: once we see the AI msg, all following msgs must be
        # ToolMessages until all its tool_call_ids are satisfied.
        pending = set(tc_ids)
        j = i + 1
        while j < len(messages) and pending:
            m = messages[j]
            if isinstance(m, ToolMessage):
                pending.discard(m.tool_call_id)
            else:
                # Non-tool message while we still have pending tool results.
                if pending:
                    violations.append(Violation(
                        kind="non_tool_between_ai_and_tool",
                        index=j,
                        detail=f"Non-tool message at index {j} interrupts tool results for AIMessage at index {i}",
                    ))
                    break
            j += 1

    is_valid = len(violations) == 0
    return ValidationResult(is_valid=is_valid, violations=violations)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def normalize_tool_call_transcript(
    messages: list[BaseMessage],
    *,
    synthetic_content: str = "[Tool call was interrupted and did not return a result.]",
) -> list[BaseMessage]:
    """Normalize *messages* to satisfy the tool-call protocol.

    Repair logic:

    - **Missing tool result** → insert a synthetic error ToolMessage.
    - **Non-adjacent tool result** → move to correct position (immediately
      after the owning AIMessage).
    - **Orphan ToolMessage** (no matching AIMessage tool_call) → preserved
      in its original relative position among non-tool messages.
    - **Non-tool messages between AIMessage(tool_calls) and ToolMessages** →
      moved after the ToolMessage block.
    - **Multiple AI tool-call turns** → each result stays grouped with its
      own AI turn, preserving order between turns.

    Returns a new list.  The input is not mutated.
    """
    # Collect all tool_call_ids declared by AI messages.
    tool_call_ids: set[str] = set()
    for msg in messages:
        for tc_id in _collect_ai_tool_call_ids(msg):
            tool_call_ids.add(tc_id)

    # Index existing ToolMessages by their tool_call_id (first occurrence wins).
    tool_messages_by_id: dict[str, ToolMessage] = {}
    for msg in messages:
        if isinstance(msg, ToolMessage) and msg.tool_call_id not in tool_messages_by_id:
            tool_messages_by_id[msg.tool_call_id] = msg

    # Walk through messages, grouping ToolMessages right after their AI turn.
    result: list[BaseMessage] = []
    consumed_tool_msg_ids: set[str] = set()
    synthetic_count = 0

    for msg in messages:
        # Skip ToolMessages here — they'll be placed right after their AI msg.
        if isinstance(msg, ToolMessage) and msg.tool_call_id in tool_call_ids:
            continue

        result.append(msg)

        if getattr(msg, "type", None) != "ai":
            continue

        tc_ids = _collect_ai_tool_call_ids(msg)
        if not tc_ids:
            continue

        # Place ToolMessages for this AI turn right here.
        for tc_id in tc_ids:
            if not tc_id:
                continue
            if tc_id in consumed_tool_msg_ids:
                continue

            existing = tool_messages_by_id.get(tc_id)
            if existing is not None:
                result.append(existing)
                consumed_tool_msg_ids.add(tc_id)
            else:
                # Insert synthetic error ToolMessage.
                result.append(ToolMessage(
                    content=synthetic_content,
                    tool_call_id=tc_id,
                    name="unknown",
                    status="error",
                ))
                consumed_tool_msg_ids.add(tc_id)
                synthetic_count += 1

    if synthetic_count:
        logger.warning(
            "normalize_tool_call_transcript: injected %d synthetic ToolMessage(s)",
            synthetic_count,
        )

    # If nothing changed, return the original list object to signal no-op.
    if len(result) == len(messages) and all(a is b for a, b in zip(result, messages)):
        return messages

    return result
