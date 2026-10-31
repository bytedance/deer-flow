"""Per-skill usage trajectories and event annotations.

The evidence contract exposes each sealed completed run as a snapshot plus its
persisted event journal. The host's ``SkillActivationMiddleware`` records every
skill activation (slash command and ``skill:activate`` tool alike) as a
``middleware:skill_activation`` run event carrying the skill name, container
path and content hash — that is the "invocation point" signal this module
builds on. Snapshot-level ``skill_observations`` exists in the contract but has
no host-side writer yet, so matching is done by scanning the event stream.

``list`` walks the newest sealed, caller-owned runs (bounded lookback), keeps
the most recent ones whose journal contains at least one activation of the
requested skill, and returns a readable timeline per run: system noise
(``run.*``, ``context:*``) is dropped and every meaningful event carries a
*kind* (human / model / tool / activation) plus a bounded text preview — the
user's message text, the model's reply text, or the tool name with its result
excerpt — so a human can see what actually happened around each activation
and annotate the events that mattered. Previews are excerpts of the caller's
own sealed run content, capped well below the page budget, and never include
other users' data.

Annotations are the caller's own notes attached to one event of one run,
stored in the plugin-owned ``skill_annotations`` table. The acting owner is
always the principal's user id, never a payload field, mirroring
``mutations.py``'s identity boundary.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from collections.abc import Mapping
from typing import Any

from deerflow_extension_api import ActionContext, HostCapabilityError

from .evolved import EvolvedSkillStore
from .mutations import _check_id, _check_skill_name, _error, _usable_source
from .recent_runs import changed_runs, recent_changed_runs

logger = logging.getLogger(__name__)

_ACTIVATION_EVENT_TYPE = "middleware:skill_activation"
# Bounded scan: newest runs first, stop after this many matching trajectories.
_TRAJECTORY_LIMIT = 3
_RUN_LOOKBACK = 25
_RUN_PAGE_SIZE = 50
_MAX_EVENT_SCAN_PAGES = 200
_TIMELINE_LIMIT = 200
_CONTEXT_BEFORE = 100
_PAGE_LIMITS_MAX_EVENTS = 100
_PAGE_LIMITS_MAX_BYTES = 131072
# Timeline readability: only events a human can act on. run.* / context:*
# noise is dropped; model turns without text (pure tool calls) carry nothing
# to annotate.
_KIND_BY_TYPE = {
    "llm.human.input": "human",
    "llm.ai.response": "ai",
    "llm.tool.result": "tool",
    _ACTIVATION_EVENT_TYPE: "activation",
}
# Preview excerpt of the caller's own sealed content per event.
_PREVIEW_CHARS = 200


def _page_limits() -> Any:
    from deerflow_extension_api import EvidenceLimits

    return EvidenceLimits(max_events=_PAGE_LIMITS_MAX_EVENTS, max_bytes=_PAGE_LIMITS_MAX_BYTES)


def _parse_content(event: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(event.content_json) if event.content_json else None
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _invocation_skill(event: Any, parsed: dict[str, Any]) -> str | None:
    if event.event_type != _ACTIVATION_EVENT_TYPE:
        return None
    changes = parsed.get("changes")
    if isinstance(changes, dict):
        name = changes.get("skill_name")
        if isinstance(name, str) and name:
            return name
    return None


def _text_preview(value: Any) -> str | None:
    """Collapse and bound one excerpt of the caller's own sealed content."""
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    if len(text) > _PREVIEW_CHARS:
        text = text[:_PREVIEW_CHARS].rstrip() + "…"
    return text or None


def _human_blocks_text(parsed: dict[str, Any]) -> str | None:
    blocks = parsed.get("content")
    if not isinstance(blocks, list):
        return None
    texts = [block.get("text") for block in blocks if isinstance(block, dict)]
    joined = " ".join(text for text in texts if isinstance(text, str))
    return joined or None


def _event_view(event: Any, skill_name: str) -> dict[str, Any] | None:
    kind = _KIND_BY_TYPE.get(event.event_type)
    if kind is None:
        return None
    parsed = _parse_content(event)
    label: str | None = None
    preview: str | None = None
    if kind == "human":
        preview = _text_preview(_human_blocks_text(parsed))
    elif kind == "ai":
        preview = _text_preview(parsed.get("content"))
        if preview is None:
            # A model turn without text (pure tool calls) says nothing to a
            # human annotator; the tool results carry that story.
            return None
    elif kind == "tool":
        name = parsed.get("name")
        if isinstance(name, str) and name:
            label = name
        preview = _text_preview(parsed.get("content"))
    matched = _invocation_skill(event, parsed) == skill_name
    detail = None
    if matched:
        changes = parsed.get("changes")
        detail = {
            "skill_name": changes.get("skill_name") if isinstance(changes, dict) else None,
            "category": changes.get("category") if isinstance(changes, dict) else None,
            "path": changes.get("path") if isinstance(changes, dict) else None,
            "content_hash": changes.get("content_hash") if isinstance(changes, dict) else None,
            "action": parsed.get("action"),
            "hook": parsed.get("hook"),
        }
    return {
        "event_id": event.event_id,
        "seq": event.seq,
        "event_type": event.event_type,
        "kind": kind,
        "label": label,
        "preview": preview,
        "invocation": matched,
        "detail": detail,
    }


async def _run_events(reader: Any, snapshot_ref: str):
    """Scan a sealed journal independently of the bounded timeline payload."""
    cursor: str | None = None
    seen: set[str] = set()
    for _ in range(_MAX_EVENT_SCAN_PAGES):
        page = await reader.read_events(snapshot_ref=snapshot_ref, cursor=cursor, limits=_page_limits())
        for event in page.items:
            yield event
        if not page.has_more:
            return
        next_cursor = page.next_cursor
        if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen:
            raise HostCapabilityError("UNAVAILABLE")
        seen.add(next_cursor)
        cursor = next_cursor
    # Never report an incomplete discovery as "this run did not use the skill".
    raise HostCapabilityError("QUOTA_EXCEEDED")


class SkillTrajectories:
    """Backend actions: per-skill recent trajectories plus event annotations."""

    def __init__(self, evidence: Any, store: EvolvedSkillStore | None) -> None:
        self._evidence = evidence
        self._store = store

    async def _reader(self) -> Any:
        reader = self._evidence.get()
        if reader is None:
            raise HostCapabilityError("UNAVAILABLE")
        return reader

    async def list(self, payload: Any, ctx: ActionContext) -> dict[str, Any]:
        principal = getattr(ctx, "principal", None)
        user_id = getattr(principal, "user_id", None)
        if not isinstance(user_id, str) or not user_id:
            return {"ok": False, "error": {"code": "UNAUTHENTICATED"}}
        if not isinstance(payload, Mapping) or set(payload) != {"skill_name"}:
            return {"ok": False, "error": {"code": "INVALID_REQUEST"}}
        try:
            name = _check_skill_name(payload.get("skill_name"))
            reader = await self._reader()
        except Exception as exc:
            return _error(exc)
        annotations: dict[tuple[str, str], dict[str, Any]] = {}
        if self._store is not None:
            try:
                for row in self._store.list_annotations(owner=user_id, skill_name=name):
                    annotations[(row["run_id"], row["event_id"])] = row
            except Exception:
                logger.warning("skill-evolution: failed to load annotations for %s", name, exc_info=True)
        trajectories: list[dict[str, Any]] = []
        try:
            changed = await recent_changed_runs(reader, limit=_RUN_LOOKBACK, page_size=_RUN_PAGE_SIZE)
            for status in reversed(changed):
                if len(trajectories) >= _TRAJECTORY_LIMIT:
                    break
                try:
                    snapshot = await reader.get_snapshot(thread_id=status.thread_id, run_id=status.run_id)
                except Exception:
                    continue
                if not _usable_source(snapshot, user_id):
                    # Owner mismatches and unsealed runs are skipped silently:
                    # the reader is globally visible, so never echo foreign runs.
                    continue
                events: list[dict[str, Any]] = []
                preceding: deque[dict[str, Any]] = deque(maxlen=_CONTEXT_BEFORE)
                matched = False
                truncated = False
                async for event in _run_events(reader, snapshot.snapshot_ref):
                    view = _event_view(event, name)
                    if view is None:
                        continue
                    if not matched:
                        if not view["invocation"]:
                            if len(preceding) == _CONTEXT_BEFORE:
                                truncated = True
                            preceding.append(view)
                            continue
                        matched = True
                        events.extend(preceding)
                    events.append(view)
                    if len(events) >= _TIMELINE_LIMIT:
                        truncated = True
                        break
                if not matched:
                    continue
                event_ids = {str(event["event_id"]) for event in events}
                trajectories.append(
                    {
                        "thread_id": snapshot.thread_id,
                        "run_id": snapshot.run_id,
                        "status": snapshot.status,
                        "stop_reason": status.stop_reason,
                        "origin": snapshot.origin,
                        "created_at": status.created_at,
                        "event_count": snapshot.event_count,
                        "events": events,
                        "timeline_truncated": truncated,
                        "annotations": [dict(a) for (run_id, event_id), a in annotations.items() if run_id == snapshot.run_id and event_id in event_ids],
                    }
                )
        except Exception as exc:
            return _error(exc)
        return {"ok": True, "skill_name": name, "trajectories": trajectories}

    async def _validate_annotation_source(self, user_id: str, name: str, run_id: str, event_id: str) -> None:
        reader = await self._reader()
        async for status in changed_runs(reader, page_size=_RUN_PAGE_SIZE):
            if status.run_id != run_id:
                continue
            snapshot = await reader.get_snapshot(thread_id=status.thread_id, run_id=run_id)
            if not _usable_source(snapshot, user_id) or snapshot.run_id != run_id or snapshot.thread_id != status.thread_id:
                raise HostCapabilityError("NOT_FOUND_OR_FORBIDDEN")
            matched = False
            found = False
            async for event in _run_events(reader, snapshot.snapshot_ref):
                view = _event_view(event, name)
                if view is None:
                    continue
                matched = matched or view["invocation"]
                if event.event_id == event_id:
                    # Ordinary visible events in a skill-using run are valid
                    # context. Another skill's activation is not this skill's.
                    found = view["kind"] != "activation" or view["invocation"]
                if matched and found:
                    return
            break
        raise HostCapabilityError("NOT_FOUND_OR_FORBIDDEN")

    async def annotate(self, payload: Any, ctx: ActionContext) -> dict[str, Any]:
        principal = getattr(ctx, "principal", None)
        user_id = getattr(principal, "user_id", None)
        if not isinstance(user_id, str) or not user_id:
            return {"ok": False, "error": {"code": "UNAUTHENTICATED"}}
        if not isinstance(payload, Mapping) or set(payload) != {"skill_name", "run_id", "event_id", "note"}:
            return {"ok": False, "error": {"code": "INVALID_REQUEST"}}
        try:
            name = _check_skill_name(payload.get("skill_name"))
            run_id = _check_id(payload.get("run_id"), label="run_id")
            event_id = _check_id(payload.get("event_id"), label="event_id")
            note = payload.get("note")
            if not isinstance(note, str) or not note or len(note.encode("utf-8")) > 2000:
                raise HostCapabilityError("INVALID_REQUEST")
            if self._store is None:
                raise HostCapabilityError("UNAVAILABLE")
            await self._validate_annotation_source(user_id, name, run_id, event_id)
            self._store.save_annotation(owner=user_id, skill_name=name, run_id=run_id, event_id=event_id, note=note)
            # A saved annotation supersedes a consumed draft: auto-clear the
            # published job so the panel returns to the evolve trigger
            # without a manual "Clear record". Pending drafts and failures
            # are deliberately kept.
            self._store.delete_published_job(owner=user_id, skill_name=name)
        except Exception as exc:
            return _error(exc)
        return {"ok": True}

    async def unannotate(self, payload: Any, ctx: ActionContext) -> dict[str, Any]:
        principal = getattr(ctx, "principal", None)
        user_id = getattr(principal, "user_id", None)
        if not isinstance(user_id, str) or not user_id:
            return {"ok": False, "error": {"code": "UNAUTHENTICATED"}}
        if not isinstance(payload, Mapping) or set(payload) != {"skill_name", "run_id", "event_id"}:
            return {"ok": False, "error": {"code": "INVALID_REQUEST"}}
        try:
            name = _check_skill_name(payload.get("skill_name"))
            run_id = _check_id(payload.get("run_id"), label="run_id")
            event_id = _check_id(payload.get("event_id"), label="event_id")
            if self._store is None:
                raise HostCapabilityError("UNAVAILABLE")
            self._store.delete_annotation(owner=user_id, skill_name=name, run_id=run_id, event_id=event_id)
        except Exception as exc:
            return _error(exc)
        return {"ok": True}
