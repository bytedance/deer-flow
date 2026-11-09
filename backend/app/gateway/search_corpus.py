"""Permission-scoped transcript projection shared by search and message navigation."""

from __future__ import annotations

import hashlib
import json
import re

from deerflow_extension_api.search import SearchMessage, SearchMessagePage, SearchThread

from app.gateway.conversation_access import _visible_text
from app.gateway.conversation_reader import default_history_hidden_run_ids, read_visible_message_page
from deerflow.runtime.events.message_identity import message_identity
from deerflow.utils.time import coerce_iso


def visible_search_text(row: dict, *, thread_id: str):
    """Use the transcript reader and the chat UI's display-only exclusions."""
    content = row.get("content")
    if isinstance(content, dict) and content.get("name") in {"summary", "loop_warning", "todo_reminder", "todo_completion_reminder"}:
        return None
    visible = _visible_text(row, thread_id=thread_id)
    if visible and visible[0] == "user":
        text = re.sub(r"<(current_uploads|uploaded_files|slash_skill_activation)>[\s\S]*?</\1>", "", visible[1]).strip()
        return ("user", text) if text else None
    return visible


class GatewaySearchCorpus:
    def __init__(self, thread_store, event_store, run_manager, user_id: str, *, request=None):
        self.thread_store = thread_store
        self.event_store = event_store
        self.run_manager = run_manager
        self.user_id = user_id
        self.request = request

    async def threads(self) -> tuple[SearchThread, ...]:
        result = []
        offset = 0
        while True:
            rows = await self.thread_store.search(user_id=self.user_id, limit=200, offset=offset)
            for row in rows:
                metadata = row.get("metadata") or {}
                if metadata.get("deerflow_sidecar") is True:
                    continue
                result.append(self.project_thread(row))
            offset += len(rows)
            if len(rows) < 200:
                return tuple(result)

    @staticmethod
    def project_thread(row) -> SearchThread:
        from app.gateway.services import custom_agent_name

        try:
            agent_name = custom_agent_name(row.get("assistant_id"))
        except (TypeError, ValueError):
            agent_name = None
        metadata = row.get("metadata") or {}
        return SearchThread(
            thread_id=row["thread_id"],
            incarnation=str(row.get("incarnation") or row.get("created_at") or ""),
            title=row.get("display_name") or "",
            updated_at=coerce_iso(row.get("updated_at", "")),
            agent_name=agent_name,
            project_id=metadata.get("deerflow_project_id"),
            archived=metadata.get("deerflow_archived") is True,
        )

    async def thread(self, thread_id: str) -> SearchThread | None:
        row = await self.thread_store.get(thread_id, user_id=self.user_id)
        if row is None or (row.get("metadata") or {}).get("deerflow_sidecar") is True:
            return None
        return self.project_thread(row)

    async def seed_legacy_history(self, thread: SearchThread) -> None:
        if self.request is None or await self.event_store.list_messages(thread.thread_id, limit=1, user_id=None):
            return
        row = await self.thread_store.get(thread.thread_id, user_id=self.user_id)
        if row is None or self.project_thread(row).incarnation != thread.incarnation:
            return
        from app.gateway.services import ensure_checkpoint_history_seeded

        await ensure_checkpoint_history_seeded(self.request, thread_id=thread.thread_id, assistant_id=row.get("assistant_id"))

    async def owns(self, thread: SearchThread) -> bool:
        row = await self.thread_store.get(thread.thread_id, user_id=self.user_id)
        return bool(row and str(row.get("incarnation") or row.get("created_at") or "") == thread.incarnation and (row.get("metadata") or {}).get("deerflow_sidecar") is not True)

    async def revision(self, thread: SearchThread) -> str | None:
        if not await self.owns(thread):
            return None
        await self.seed_legacy_history(thread)
        latest = await self.event_store.list_messages(thread.thread_id, limit=1, user_id=self.user_id)
        hidden = await default_history_hidden_run_ids(self.run_manager, thread.thread_id, user_id=self.user_id)
        revision = [thread.incarnation, thread.updated_at, latest[-1]["seq"] if latest else 0, sorted(hidden)]
        return hashlib.sha256(json.dumps(revision).encode()).hexdigest()

    @staticmethod
    def project(thread: SearchThread, row: dict) -> SearchMessage | None:
        visible = visible_search_text(row, thread_id=thread.thread_id)
        content = row.get("content")
        identity = message_identity(content) if isinstance(content, dict) else None
        if not visible or not identity:
            return None
        return SearchMessage(thread.thread_id, thread.incarnation, identity.removeprefix("message:"), row["run_id"], row["seq"], visible[0], visible[1], coerce_iso(row.get("created_at", "")))

    async def messages(self, thread: SearchThread, *, before_seq: int | None) -> SearchMessagePage:
        if not await self.owns(thread):
            return SearchMessagePage()
        rows, more = await self._page(thread.thread_id, limit=200, before_seq=before_seq)
        items = tuple(message for row in rows if (message := self.project(thread, row)) is not None)
        return SearchMessagePage(items, rows[0]["seq"] if more else None)

    async def _page(self, thread_id: str, *, limit: int, before_seq=None, after_seq=None):
        return await read_visible_message_page(
            event_store=self.event_store,
            run_manager=self.run_manager,
            thread_id=thread_id,
            user_id=self.user_id,
            limit=limit,
            before_seq=before_seq,
            after_seq=after_seq,
            message_filter=lambda row: visible_search_text(row, thread_id=thread_id) is not None and message_identity(row.get("content", {})) is not None,
        )

    async def around(self, thread_id: str, message_id: str, *, limit: int = 20, seq: int | None = None) -> dict | None:
        row = await self.thread_store.get(thread_id, user_id=self.user_id)
        if row is None or (row.get("metadata") or {}).get("deerflow_sidecar") is True:
            return None
        await self.seed_legacy_history(self.project_thread(row))
        # Walk backward from the head so later versions win even when they
        # live on another storage page. Sequence hints never select old text.
        rows = await self.latest_rows(thread_id)
        index = next((i for i, item in enumerate(rows) if message_identity(item["content"]) == f"message:{message_id}"), None)
        if index is None or (seq is not None and rows[index]["seq"] != seq):
            return None
        target = rows[index]
        seq = target["seq"]
        left, right = max(0, index - limit), min(len(rows), index + limit + 1)
        older, newer = rows[left:index], rows[index + 1 : right]
        has_before, has_after = left > 0, right < len(rows)
        # Recheck ownership/incarnation after the asynchronous history reads.
        current = await self.thread_store.get(thread_id, user_id=self.user_id)
        if current is None or current.get("incarnation") != row.get("incarnation"):
            return None
        return {"data": older + [target] + newer, "target_seq": seq, "has_before": has_before, "has_after": has_after}

    async def latest_rows(self, thread_id: str) -> list[dict]:
        latest = {}
        before = None
        while True:
            rows, more = await self._page(thread_id, limit=200, before_seq=before)
            for row in reversed(rows):
                latest.setdefault(message_identity(row["content"]), row)
            if not more:
                break
            before = rows[0]["seq"]
        return sorted(latest.values(), key=lambda row: row["seq"])

    async def latest_message(self, thread: SearchThread, message_id: str) -> SearchMessage | None:
        if not await self.owns(thread):
            return None
        before = None
        while True:
            rows, more = await self._page(thread.thread_id, limit=200, before_seq=before)
            for row in reversed(rows):
                if message_identity(row["content"]) == f"message:{message_id}":
                    return self.project(thread, row)
            if not more:
                return None
            before = rows[0]["seq"]
