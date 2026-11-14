"""Workspace search and direct navigation to an owner-visible message."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.gateway.authz import require_permission
from app.gateway.deps import get_run_event_store, get_run_manager, get_thread_store
from app.gateway.search_corpus import GatewaySearchCorpus
from deerflow.utils.thread_id import ThreadId

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["search"])


class WorkspaceSearchRequest(BaseModel):
    query: str = Field(default="", max_length=256)
    types: list[Literal["thread", "message"]] = Field(default_factory=lambda: ["thread", "message"], min_length=1, max_length=2)
    archived: bool | None = Field(default=None, strict=True)
    project_id: str | None = Field(default=None, max_length=64)
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=4096)


def snippet(text: str, query: str) -> list[dict]:
    """Plain text only. Map case-fold expansions back to source characters."""
    normalized = text.casefold()
    position = normalized.find(query.casefold()) if query else -1
    if position < 0:
        return [{"text": text[:200] + ("…" if len(text) > 200 else "")}]
    offsets = []
    for index, character in enumerate(text):
        offsets.extend([index] * len(character.casefold()))
        if len(offsets) >= position + len(query.casefold()):
            break
    start, end = offsets[position], offsets[position + len(query.casefold()) - 1] + 1
    left, right = max(0, start - 65), min(len(text), end + 110)
    return [{"text": ("…" if left else "") + text[left:start]}, {"text": text[start:end], "matched": True}, {"text": text[end:right] + ("…" if right < len(text) else "")}]


def _corpus(request: Request) -> GatewaySearchCorpus:
    return GatewaySearchCorpus(get_thread_store(request), get_run_event_store(request), get_run_manager(request), str(request.state.auth.require_user().id), request=request)


def _encode_cursor(scope: str, phase: str, position) -> str:
    return base64.urlsafe_b64encode(json.dumps([scope, phase, position]).encode()).decode()


@router.post("/search")
@require_permission("threads", "read")
async def search_workspace(body: WorkspaceSearchRequest, request: Request):
    corpus = _corpus(request)
    query = body.query.strip()
    scope = hashlib.sha256(json.dumps([corpus.user_id, query, sorted(set(body.types)), body.archived, body.project_id, "project_id" in body.model_fields_set]).encode()).hexdigest()
    phase, position = "thread", None
    if body.cursor:
        try:
            saved_scope, phase, position = json.loads(base64.urlsafe_b64decode(body.cursor))
            if saved_scope != scope or phase not in {"thread", "message"}:
                raise ValueError
            if phase == "thread" and (not isinstance(position, list) or len(position) != 3 or not isinstance(position[0], int) or not all(isinstance(v, str) for v in position[1:])):
                raise ValueError
            if phase == "message" and position is not None and not isinstance(position, str):
                raise ValueError
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, "Invalid search cursor") from exc
    all_threads = await corpus.threads()
    threads = tuple(t for t in all_threads if (body.archived is None or t.archived == body.archived) and ("project_id" not in body.model_fields_set or t.project_id == body.project_id))
    lookup = {t.thread_id: t for t in threads}
    providers = getattr(getattr(request.app.state, "extensions", None), "workspace_search_providers", ())
    messages_available = bool(providers) and request.state.auth.has_permission("runs", "read")
    response = {"items": [], "cursor": None, "indexing": False, "messages_available": messages_available}

    def thread_hit(thread):
        return {
            "type": "thread",
            "thread_id": thread.thread_id,
            "title": thread.title,
            "agent_name": thread.agent_name,
            "archived": thread.archived,
            "project_id": thread.project_id,
            "updated_at": thread.updated_at,
            "snippet": snippet(thread.title, query),
        }

    if phase == "thread" and "thread" in body.types:

        def key(thread):
            title = thread.title.casefold()
            return (2 if query and title == query.casefold() else 1, thread.updated_at, thread.thread_id)

        matches = sorted((t for t in threads if not query or query.casefold() in t.title.casefold()), key=key, reverse=True)
        if position is not None:
            matches = [t for t in matches if key(t) < tuple(position)]
        selected = matches[: body.limit]
        response["items"].extend(thread_hit(t) for t in selected)
        if len(matches) > body.limit:
            response["cursor"] = _encode_cursor(scope, "thread", key(selected[-1]))
            return response
    if not query or "message" not in body.types or not messages_available:
        return response
    if len(response["items"]) == body.limit:
        response["cursor"] = _encode_cursor(scope, "message", None)
        return response
    provider = providers[0][1]
    provider_cursor = position if phase == "message" else None
    # Invalidated candidates must not consume a visible result slot. Keep a
    # bounded amount of work per HTTP page and expose continuation when needed.
    for _ in range(5):
        try:
            page = await provider.search(corpus, query=query, threads=threads, limit=body.limit - len(response["items"]), cursor=provider_cursor)
        except ValueError as exc:
            raise HTTPException(400, "Invalid search cursor") from exc
        except Exception:
            logger.exception("Workspace search provider failed")
            raise HTTPException(503, "Message search is temporarily unavailable") from None
        response["indexing"] = page.indexing
        for candidate in page.items:
            thread = lookup.get(candidate.thread_id)
            if thread is None or candidate.incarnation != thread.incarnation or not await corpus.owns(thread):
                continue
            # Re-read authoritative visible text before returning ANY snippet.
            current = await corpus.latest_message(thread, candidate.message_id)
            if current is None or current.seq != candidate.seq or query.casefold() not in current.text.casefold():
                continue
            hit = thread_hit(thread)
            hit.update(type="message", message_id=current.message_id, seq=current.seq, role=current.role, updated_at=current.created_at, snippet=snippet(current.text, query))
            response["items"].append(hit)
        if page.indexing:
            break
        if page.cursor == provider_cursor and page.cursor is not None:
            raise HTTPException(503, "Search pagination did not advance")
        provider_cursor = page.cursor
        if provider_cursor is None or len(response["items"]) >= body.limit:
            break
    if provider_cursor:
        response["cursor"] = _encode_cursor(scope, "message", provider_cursor)
    return response


@router.get("/threads/{thread_id}/messages/around")
@require_permission("runs", "read", owner_check=True, require_existing=True)
async def message_context(thread_id: ThreadId, request: Request, message_id: str = Query(min_length=1, max_length=512), seq: int | None = Query(default=None, ge=1), limit: int = Query(default=20, ge=1, le=50)):
    corpus = _corpus(request)
    window = await corpus.around(thread_id, message_id, seq=seq, limit=limit)
    if window is None:
        raise HTTPException(404, "Message is unavailable")
    thread = await corpus.thread(thread_id)
    if thread is None:
        raise HTTPException(404, "Message is unavailable")
    messages = [asdict(message) for row in window.pop("data") if (message := corpus.project(thread, row)) is not None]
    return {**window, "messages": messages}
