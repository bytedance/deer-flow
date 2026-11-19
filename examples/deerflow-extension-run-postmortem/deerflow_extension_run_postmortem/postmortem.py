"""Turn sealed-run evidence into a bounded, human-readable postmortem.

The host hands plugins immutable snapshots and bounded event pages; this module
owns only the interpretation. Everything here is pure so the service and the
HTTP surface stay thin and the derivation stays unit-testable without a host.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from deerflow_extension_api import CompletedRunEvent, CompletedRunSnapshot

_SUMMARY_CAP = 240
_MESSAGE_EVENT_TYPES = {"llm.human.input", "llm.ai.response", "llm.tool.result"}
_GUARDRAIL_EVENT_TYPES = {
    "middleware:guardrail": "guardrail",
    "middleware:loop_detection": "loop_detection",
    "middleware:safety_termination": "safety termination",
}
_TOOL_FAILURE_STATUSES = {"error", "failed", "failure"}


@dataclass(frozen=True)
class TimelineEntry:
    """One bounded, printable line derived from a persisted run event."""

    seq: int
    event_type: str
    category: str
    summary: str
    truncated: bool = False


@dataclass(frozen=True)
class Anomaly:
    """A finding worth checking, with the evidence that produced it."""

    code: str
    detail: str


@dataclass(frozen=True)
class DeliverySummary:
    satisfied: bool | None = None
    presented: int | None = None
    produced: int | None = None


@dataclass(frozen=True)
class Postmortem:
    thread_id: str
    run_id: str
    owner_id: str
    agent_id: str | None
    origin: str
    status: str
    stop_reason: str | None
    seal_state: str
    seal_error: str | None
    events_read: int
    events_total: int
    counts_by_category: dict[str, int] = field(default_factory=dict)
    counts_by_type: dict[str, int] = field(default_factory=dict)
    message_counts: dict[str, int] = field(default_factory=dict)
    tool_failures: int = 0
    delivery: DeliverySummary = field(default_factory=DeliverySummary)
    subagents_started: int = 0
    subagents_ended: int = 0
    timeline: tuple[TimelineEntry, ...] = ()
    anomalies: tuple[Anomaly, ...] = ()
    caveats: tuple[str, ...] = ()
    snapshot_ref: str = ""
    evidence_revision: str = ""

    @property
    def verdict(self) -> str:
        if self.status == "success":
            return "Run completed successfully." if not self.anomalies else "Run completed; review the anomalies below."
        if self.status == "waiting_for_input":
            return "Run paused for human input."
        if not self.status:
            return "Run status is not recorded in this evidence."
        return f"Run ended with status {self.status}."


def _loads(raw: str, fallback: Any) -> Any:
    try:
        return json.loads(raw) if raw else fallback
    except (TypeError, ValueError):
        return fallback


def _text(value: Any, cap: int = _SUMMARY_CAP) -> str:
    """Collapse a value to one bounded line of printable text."""
    if isinstance(value, str):
        text = value
    elif isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    elif value is None:
        text = ""
    else:
        text = str(value)
    text = " ".join(text.split())
    return text if len(text) <= cap else text[: cap - 1] + "…"


def _content_text(content: Any) -> str:
    """Flatten a message-like payload (string, block list or dump) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
                elif block.get("type") not in (None, "text"):
                    parts.append(f"[{block.get('type')}]")
        return " ".join(parts)
    if isinstance(content, dict):
        return _content_text(content.get("content"))
    return ""


def _message_summary(event_type: str, content: Any) -> str:
    if not isinstance(content, (dict, str, list)):
        return _text(content)
    if event_type == "llm.ai.response" and isinstance(content, dict):
        tool_calls = content.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            names = []
            for call in tool_calls:
                if isinstance(call, dict):
                    name = call.get("name") or call.get("function", {}).get("name")
                    names.append(str(name or "?"))
            return _text("assistant → " + ", ".join(names))
        return _text("assistant: " + (_content_text(content) or "(empty)"))
    if event_type == "llm.tool.result" and isinstance(content, dict):
        name = content.get("name") or content.get("tool")
        body = _content_text(content)
        return _text(f"tool {name or '?'}: {body or '(empty)'}")
    return _text("user: " + _content_text(content))


def _tool_failed(content: Any) -> bool:
    """A tool result reports failure only through explicit markers."""
    if not isinstance(content, dict):
        return False
    status = content.get("status")
    if isinstance(status, str) and status.lower() in _TOOL_FAILURE_STATUSES:
        return True
    if content.get("is_error") is True or content.get("error") is True:
        return True
    text = _content_text(content).lstrip()
    # A bare "Error " prefix is prose ("Error handling in this tool ..."),
    # not a marker; only the structured fields above and "Error:" signal it.
    return text.startswith("Error:")


def _delivery_summary(content: Any) -> DeliverySummary:
    if not isinstance(content, dict):
        return DeliverySummary()
    satisfied = content.get("satisfied")
    presented = content.get("presented")
    produced = content.get("produced_paths")
    return DeliverySummary(
        satisfied=satisfied if isinstance(satisfied, bool) else None,
        presented=presented if type(presented) is int else None,
        produced=len(produced) if isinstance(produced, list) else None,
    )


def _subagent_summary(event_type: str, content: Any) -> str:
    name = None
    if isinstance(content, dict):
        name = content.get("name") or content.get("subagent") or content.get("agent")
    action = event_type.rsplit(".", 1)[-1]
    return _text(f"subagent {action}: {name or '?'}")


def _summary(event: CompletedRunEvent, content: Any) -> str:
    event_type = event.event_type
    if event_type in _MESSAGE_EVENT_TYPES:
        return _message_summary(event_type, content)
    if event_type == "run.delivery":
        delivery = _delivery_summary(content)
        if delivery.satisfied is None:
            return _text("delivery receipt recorded")
        return _text(f"delivery: satisfied={delivery.satisfied} presented={delivery.presented} produced={delivery.produced}")
    if event_type.startswith("subagent."):
        return _subagent_summary(event_type, content)
    if event_type.startswith("middleware:"):
        tag = event_type.split(":", 1)[1]
        detail = _content_text(content) or _text(content)
        return _text(f"{tag}: {detail}")
    if event_type == "workspace_changes" and isinstance(content, dict):
        files = content.get("files") or content.get("changes")
        if isinstance(files, list):
            return _text(f"workspace: {len(files)} file(s) changed")
        return _text("workspace changes recorded")
    if event_type == "context:memory":
        return _text(f"memory context: {_text(content)}")
    if event_type in {"run.error", "llm.error"}:
        return _text(f"{event_type}: {_content_text(content) or _text(content)}")
    if event_type in {"run.start", "run.end", "run.terminal"}:
        status = None
        if isinstance(content, dict):
            status = content.get("status") or content.get("stop_reason")
        return _text(f"{event_type}: {status}" if status else event_type)
    return _text(_content_text(content) or event.content_json)


def build_postmortem(snapshot: CompletedRunSnapshot, events: list[CompletedRunEvent] | tuple[CompletedRunEvent, ...], *, max_events: int | None = None) -> Postmortem:
    """Derive the bounded report from a snapshot and the events read for it.

    ``max_events`` is the caller's read bound (``None`` when unbounded), so a
    short read caused by that bound is reported as ``evidence_bounded`` rather
    than as retention or sealing damage.
    """
    counts_by_category: dict[str, int] = {}
    counts_by_type: dict[str, int] = {}
    message_counts = {"user": 0, "assistant": 0, "tool_results": 0}
    tool_failures = 0
    delivery = DeliverySummary()
    subagents_started = 0
    subagents_ended = 0
    timeline: list[TimelineEntry] = []
    error_details: list[str] = []
    guardrail_hits: list[str] = []

    for event in events:
        content = _loads(event.content_json, event.content_json)
        counts_by_category[event.category] = counts_by_category.get(event.category, 0) + 1
        counts_by_type[event.event_type] = counts_by_type.get(event.event_type, 0) + 1
        if event.event_type == "llm.human.input":
            message_counts["user"] += 1
        elif event.event_type == "llm.ai.response":
            message_counts["assistant"] += 1
        elif event.event_type == "llm.tool.result":
            message_counts["tool_results"] += 1
            if _tool_failed(content):
                tool_failures += 1
        elif event.event_type == "run.delivery":
            delivery = _delivery_summary(content)
        elif event.event_type == "subagent.start":
            subagents_started += 1
        elif event.event_type == "subagent.end":
            subagents_ended += 1
        if event.event_type in {"run.error", "llm.error"}:
            error_details.append(_text(_content_text(content) or _text(content), 160))
        if event.event_type in _GUARDRAIL_EVENT_TYPES:
            guardrail_hits.append(f"{_GUARDRAIL_EVENT_TYPES[event.event_type]}: {_text(_content_text(content) or _text(content), 160)}")
        timeline.append(
            TimelineEntry(
                seq=event.seq,
                event_type=event.event_type,
                category=event.category,
                summary=_summary(event, content),
                truncated=event.truncated,
            )
        )

    anomalies: list[Anomaly] = []
    if snapshot.seal_state != "sealed":
        detail = f"seal state is {snapshot.seal_state or 'unknown'}"
        if snapshot.seal_error:
            detail += f": {_text(snapshot.seal_error, 160)}"
        anomalies.append(Anomaly("evidence_partial", detail))
    if snapshot.status == "error":
        anomalies.append(Anomaly("run_failed", f"run status is error ({error_details[0] if error_details else 'no error event retained'})"))
    if error_details:
        anomalies.append(Anomaly("run_or_model_errors", f"{len(error_details)} error event(s); first: {error_details[0]}"))
    if guardrail_hits:
        anomalies.append(Anomaly("guardrail_triggered", f"{len(guardrail_hits)} guardrail event(s); first: {guardrail_hits[0]}"))
    if delivery.satisfied is False:
        anomalies.append(Anomaly("delivery_incomplete", f"delivery unsatisfied (presented={delivery.presented}, produced={delivery.produced})"))
    if tool_failures:
        anomalies.append(Anomaly("tool_failures", f"{tool_failures} tool result(s) report a failure"))
    if snapshot.stop_reason:
        anomalies.append(Anomaly("stopped_early", f"stop_reason={snapshot.stop_reason}"))
    if subagents_started > subagents_ended:
        anomalies.append(Anomaly("subagent_unfinished", f"{subagents_started} started, {subagents_ended} ended; background completion may be outside this evidence"))
    if any(entry.truncated for entry in timeline):
        anomalies.append(Anomaly("evidence_truncated", "some event payloads were truncated by the evidence reader"))
    if len(events) < snapshot.event_count:
        if max_events is not None and len(events) >= max_events:
            anomalies.append(Anomaly("evidence_bounded", f"read {len(events)} of {snapshot.event_count} retained event(s); bounded by max_events={max_events}"))
        else:
            anomalies.append(Anomaly("evidence_incomplete", f"read {len(events)} of {snapshot.event_count} retained event(s); the remainder is not available in this snapshot"))

    caveats = list(snapshot.coverage_limits)
    if snapshot.expires_at:
        caveats.append(f"Evidence expires at {snapshot.expires_at}.")
    if not events:
        caveats.append("No run events were retained for this snapshot.")
    if max_events is not None and len(events) >= max_events and len(events) < snapshot.event_count:
        caveats.append(f"Report bounded by max_events={max_events}; raise the bound for a longer timeline.")

    return Postmortem(
        thread_id=snapshot.thread_id,
        run_id=snapshot.run_id,
        owner_id=snapshot.owner_id,
        agent_id=snapshot.agent_id,
        origin=snapshot.origin,
        status=snapshot.status,
        stop_reason=snapshot.stop_reason,
        seal_state=snapshot.seal_state,
        seal_error=snapshot.seal_error,
        events_read=len(events),
        events_total=snapshot.event_count,
        counts_by_category=counts_by_category,
        counts_by_type=counts_by_type,
        message_counts=message_counts,
        tool_failures=tool_failures,
        delivery=delivery,
        subagents_started=subagents_started,
        subagents_ended=subagents_ended,
        timeline=tuple(timeline),
        anomalies=tuple(anomalies),
        caveats=tuple(caveats),
        snapshot_ref=snapshot.snapshot_ref,
        evidence_revision=snapshot.evidence_revision,
    )


def to_dict(postmortem: Postmortem) -> dict[str, Any]:
    """JSON-safe projection for the HTTP surface."""
    return {
        "thread_id": postmortem.thread_id,
        "run_id": postmortem.run_id,
        "agent_id": postmortem.agent_id,
        "origin": postmortem.origin,
        "status": postmortem.status,
        "stop_reason": postmortem.stop_reason,
        "seal_state": postmortem.seal_state,
        "seal_error": postmortem.seal_error,
        "verdict": postmortem.verdict,
        "events_read": postmortem.events_read,
        "events_total": postmortem.events_total,
        "counts_by_category": dict(postmortem.counts_by_category),
        "counts_by_type": dict(postmortem.counts_by_type),
        "message_counts": dict(postmortem.message_counts),
        "tool_failures": postmortem.tool_failures,
        "delivery": {
            "satisfied": postmortem.delivery.satisfied,
            "presented": postmortem.delivery.presented,
            "produced": postmortem.delivery.produced,
        },
        "subagents": {"started": postmortem.subagents_started, "ended": postmortem.subagents_ended},
        "anomalies": [{"code": anomaly.code, "detail": anomaly.detail} for anomaly in postmortem.anomalies],
        "caveats": list(postmortem.caveats),
        "timeline": [{"seq": entry.seq, "event_type": entry.event_type, "category": entry.category, "summary": entry.summary, "truncated": entry.truncated} for entry in postmortem.timeline],
        "snapshot_ref": postmortem.snapshot_ref,
        "evidence_revision": postmortem.evidence_revision,
    }


def render_markdown(postmortem: Postmortem) -> str:
    """Render the report as a shareable Markdown document."""
    lines = [
        f"# Run postmortem — `{postmortem.run_id}`",
        "",
        postmortem.verdict,
        "",
        "## Overview",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Thread | `{postmortem.thread_id}` |",
        f"| Agent | `{postmortem.agent_id or '-'}` |",
        f"| Origin | {postmortem.origin or '-'} |",
        f"| Status | {postmortem.status or '-'} |",
        f"| Stop reason | {postmortem.stop_reason or '-'} |",
        f"| Evidence | {postmortem.seal_state or '-'} ({postmortem.events_read}/{postmortem.events_total} events) |",
        "",
        "## Anomalies",
        "",
    ]
    if postmortem.anomalies:
        lines.extend(f"- **{anomaly.code}** — {anomaly.detail}" for anomaly in postmortem.anomalies)
    else:
        lines.append("None detected in the retained evidence.")
    lines.extend(
        [
            "",
            "## Activity",
            "",
            f"- Messages: {postmortem.message_counts.get('user', 0)} user, {postmortem.message_counts.get('assistant', 0)} assistant, {postmortem.message_counts.get('tool_results', 0)} tool results",
            f"- Tool failures: {postmortem.tool_failures}",
            f"- Subagents: {postmortem.subagents_started} started, {postmortem.subagents_ended} ended",
        ]
    )
    delivery = postmortem.delivery
    if delivery.satisfied is not None:
        lines.append(f"- Delivery: satisfied={delivery.satisfied}, presented={delivery.presented}, produced={delivery.produced}")
    lines.extend(["", "## Timeline", "", "| # | Event | Summary |", "| --- | --- | --- |"])
    if postmortem.timeline:
        for entry in postmortem.timeline:
            summary = entry.summary.replace("|", "\\|")
            suffix = " _(truncated)_" if entry.truncated else ""
            lines.append(f"| {entry.seq} | `{entry.event_type}` | {summary}{suffix} |")
    else:
        lines.append("| - | - | No retained events |")
    lines.extend(["", "## Evidence caveats", ""])
    lines.extend(f"- {caveat}" for caveat in postmortem.caveats)
    lines.extend(["", f"_snapshot `{postmortem.snapshot_ref}` · revision `{postmortem.evidence_revision}`_", ""])
    return "\n".join(lines)
