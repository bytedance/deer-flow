"""Host adapter for the public read-only run evidence contract."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
from typing import Any

from deerflow_extension_api import (
    InvalidRunEvidenceCursor,
    RunEventPage,
    RunEventView,
    RunPage,
    RunStatusView,
)

from deerflow.runtime.secret_context import redact_metadata_secrets

_CURSOR_VERSION = 1


def _scope_fingerprint(user_id: str | None) -> str:
    scope = user_id if user_id is not None else "*"
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()[:16]


def _encode_cursor(change_seq: int, run_id: str, user_id: str | None) -> str:
    payload = json.dumps(
        {"q": change_seq, "r": run_id, "s": _scope_fingerprint(user_id), "v": _CURSOR_VERSION},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str | None, user_id: str | None) -> tuple[int, str]:
    if cursor is None:
        return -1, ""
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise InvalidRunEvidenceCursor("invalid run evidence cursor") from exc
    if not isinstance(payload, dict) or payload.get("v") != _CURSOR_VERSION:
        raise InvalidRunEvidenceCursor("unsupported run evidence cursor")
    if payload.get("s") != _scope_fingerprint(user_id):
        raise InvalidRunEvidenceCursor("run evidence cursor scope does not match this reader")
    change_seq, run_id = payload.get("q"), payload.get("r")
    if not isinstance(change_seq, int) or isinstance(change_seq, bool) or not isinstance(run_id, str):
        raise InvalidRunEvidenceCursor("invalid run evidence cursor")
    return change_seq, run_id


def _status_view(record: dict[str, Any]) -> RunStatusView:
    return RunStatusView(
        thread_id=str(record.get("thread_id") or ""),
        run_id=str(record.get("run_id") or ""),
        status=str(record.get("status") or ""),
        created_at=str(record.get("created_at") or ""),
        updated_at=str(record.get("updated_at") or ""),
        error=record.get("error") if isinstance(record.get("error"), str) else None,
        stop_reason=record.get("stop_reason") if isinstance(record.get("stop_reason"), str) else None,
    )


def _event_view(event: dict[str, Any]) -> RunEventView:
    content = copy.deepcopy(event.get("content"))
    metadata = copy.deepcopy(redact_metadata_secrets(event.get("metadata")))
    return RunEventView(
        thread_id=str(event.get("thread_id") or ""),
        run_id=str(event.get("run_id") or ""),
        seq=int(event.get("seq") or 0),
        event_type=str(event.get("event_type") or ""),
        category=str(event.get("category") or ""),
        content=content,
        metadata=metadata if isinstance(metadata, dict) else {},
        created_at=str(event.get("created_at") or ""),
    )


class StoreRunEvidenceReader:
    """Read configured stores through one immutable owner scope."""

    def __init__(self, run_store: Any, event_store: Any, *, user_id: str | None = None) -> None:
        self._run_store = run_store
        self._event_store = event_store
        self._user_id = user_id

    @staticmethod
    def _validate_limit(limit: int) -> None:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 2000:
            raise ValueError("limit must be an integer between 1 and 2000")

    async def list_changed_runs(self, *, cursor: str | None, limit: int) -> RunPage:
        self._validate_limit(limit)
        after_seq, after_run_id = _decode_cursor(cursor, self._user_id)
        records = await self._run_store.list_changed(
            after_change_seq=after_seq,
            after_run_id=after_run_id,
            user_id=self._user_id,
            limit=limit + 1,
        )
        page_records = records[:limit]
        next_cursor = cursor
        if page_records:
            last = page_records[-1]
            next_cursor = _encode_cursor(
                int(last.get("change_seq") or 0),
                str(last.get("run_id") or ""),
                self._user_id,
            )
        return RunPage(
            items=tuple(_status_view(record) for record in page_records),
            next_cursor=next_cursor,
            has_more=len(records) > limit,
        )

    async def get_run_status(self, *, thread_id: str, run_id: str) -> RunStatusView | None:
        record = await self._run_store.get(run_id, user_id=self._user_id)
        if record is None or record.get("thread_id") != thread_id or record.get("operation_kind", "run") != "run":
            return None
        return _status_view(record)

    async def list_run_events(
        self,
        *,
        thread_id: str,
        run_id: str,
        after_seq: int | None,
        limit: int,
    ) -> RunEventPage:
        self._validate_limit(limit)
        if after_seq is not None and (not isinstance(after_seq, int) or isinstance(after_seq, bool) or after_seq < 0):
            raise ValueError("after_seq must be a non-negative integer or None")
        if await self.get_run_status(thread_id=thread_id, run_id=run_id) is None:
            return RunEventPage(next_after_seq=after_seq)
        events = await self._event_store.list_events(
            thread_id,
            run_id,
            limit=limit + 1,
            after_seq=after_seq,
            user_id=self._user_id,
        )
        page_events = events[:limit]
        next_after_seq = after_seq
        if page_events:
            next_after_seq = int(page_events[-1]["seq"])
        return RunEventPage(
            items=tuple(_event_view(event) for event in page_events),
            next_after_seq=next_after_seq,
            has_more=len(events) > limit,
        )
