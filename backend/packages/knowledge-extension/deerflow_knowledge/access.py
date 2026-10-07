"""Knowledge-base access gate + runtime scope resolution (spec §4.5, §7; RFC §4.1).

Phase-1 permission model is owner-only: a KB is reachable exactly when the
caller is its owner (``visibility``/invite-based sharing arrives in Phase 2 —
the check funnels through this one function so the upgrade touches one place).

The scope resolver projects the per-message knowledge scope (upstream #5238
contract) onto the single bound built-in KB: the frontend sends one
provider-qualified dataset id per turn (``local:<kb_id>``), and this module is
the one place that turns it back into the ``kb_id`` the retrieval path filters
on. The runtime-context carrier is the only source read here — message
snapshots and free-form run context are never trusted.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from deerflow.knowledge_scope import (
    KNOWLEDGE_SCOPE_RUNTIME_KEY,
    canonicalize_knowledge_scope,
    execution_scope,
    parse_local_dataset_id,
)
from deerflow_knowledge.store import KnowledgeStore

#: Guidance returned by the retrieval tools when the run carries no scope.
NO_KB_GUIDANCE = "当前对话未绑定知识库。请先在窗口中选择要检索的知识库后再试。"
#: Message returned when the caller fails the access gate.
ACCESS_DENIED_MESSAGE = "你没有访问该知识库的权限（一期知识库仅所有者可访问）。"
#: Message returned when the scoped knowledge base no longer exists.
KB_MISSING_MESSAGE = "该知识库不存在或已被删除。"
#: Scope-shaped refusals, mirroring the RAGFlow canonical tool answers.
SCOPE_INVALID_MESSAGE = "Error: Invalid knowledge scope for this turn."
SCOPE_DISABLED_MESSAGE = "Error: Knowledge search is disabled for this turn."
SCOPE_MULTI_DATASET_MESSAGE = "Error: The knowledge scope must select exactly one built-in knowledge base for this turn."
SCOPE_FOREIGN_DATASET_MESSAGE = "Error: The knowledge scope selects a dataset this knowledge provider cannot serve."
SCOPE_DOCUMENT_FILTERS_MESSAGE = "Error: Document-level scope is not supported by this knowledge provider yet."


async def can_access(store: KnowledgeStore, user_id: str, kb_id: str) -> bool:
    """Phase-1 access rule: the KB must exist and the caller must be its owner."""
    kb = await store.get_kb(kb_id)
    return kb is not None and kb.get("owner_id") == user_id


def resolve_kb_scope(runtime: Any) -> tuple[str | None, str, str | None]:
    """Project the admitted execution scope onto ``(kb_id, user_id, refusal)``.

    ``kb_id`` is None when the turn has no usable binding; ``refusal`` then
    carries the reason — a scope-shaped refusal message, or None for the plain
    "no knowledge base bound" guidance the caller answers with NO_KB_GUIDANCE.
    """
    from deerflow.runtime.user_context import resolve_runtime_user_id

    user_id = resolve_runtime_user_id(runtime)
    context = getattr(runtime, "context", None) if runtime is not None else None
    if not isinstance(context, dict) or KNOWLEDGE_SCOPE_RUNTIME_KEY not in context:
        return None, user_id, None
    try:
        scope = execution_scope(canonicalize_knowledge_scope(context[KNOWLEDGE_SCOPE_RUNTIME_KEY]))
    except ValidationError:
        return None, user_id, SCOPE_INVALID_MESSAGE
    if scope["mode"] == "disabled":
        return None, user_id, SCOPE_DISABLED_MESSAGE
    if scope["mode"] != "selected":
        # ``all`` means "every accessible dataset" upstream; a built-in
        # conversation is always bound to one KB, so an unqualified turn
        # keeps the no-binding guidance instead of widening retrieval.
        return None, user_id, None
    dataset_ids = scope.get("dataset_ids") or []
    if len(dataset_ids) > 1:
        return None, user_id, SCOPE_MULTI_DATASET_MESSAGE
    kb_id = parse_local_dataset_id(dataset_ids[0])
    if kb_id is None:
        return None, user_id, SCOPE_FOREIGN_DATASET_MESSAGE
    if scope.get("document_filters"):
        # Narrowing within the KB needs document-level retrieval filters that
        # this phase does not implement; accepting the scope would silently
        # widen it, so the refusal is explicit.
        return None, user_id, SCOPE_DOCUMENT_FILTERS_MESSAGE
    return kb_id, user_id, None
