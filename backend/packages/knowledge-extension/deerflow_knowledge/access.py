"""Knowledge-base access gate + runtime scope resolution (spec §4.5, §7).

Phase-1 permission model is owner-only: a KB is reachable exactly when the
caller is its owner (``visibility``/invite-based sharing arrives in Phase 2 —
the check funnels through this one function so the upgrade touches one place).
The scope resolver pulls the bound ``kb_id`` and the effective ``user_id``
from the tool runtime context, per the single-KB binding chain: frontend →
run ``context.kb_id`` → mandatory Qdrant filter.
"""

from __future__ import annotations

from typing import Any

from deerflow_knowledge.store import KnowledgeStore

#: Guidance returned by the retrieval tools when the run carries no kb_id.
NO_KB_GUIDANCE = "当前对话未绑定知识库。请先在窗口中选择要检索的知识库后再试。"
#: Message returned when the caller fails the access gate.
ACCESS_DENIED_MESSAGE = "你没有访问该知识库的权限（一期知识库仅所有者可访问）。"


async def can_access(store: KnowledgeStore, user_id: str, kb_id: str) -> bool:
    """Phase-1 access rule: the KB must exist and the caller must be its owner."""
    kb = await store.get_kb(kb_id)
    return kb is not None and kb.get("owner_id") == user_id


def resolve_kb_scope(runtime: Any) -> tuple[str | None, str]:
    """Pull ``(kb_id, user_id)`` from the tool runtime context."""
    kb_id = None
    context = getattr(runtime, "context", None) if runtime is not None else None
    if isinstance(context, dict):
        raw = context.get("kb_id")
        kb_id = str(raw) if raw else None
    from deerflow.runtime.user_context import resolve_runtime_user_id

    return kb_id, resolve_runtime_user_id(runtime)
