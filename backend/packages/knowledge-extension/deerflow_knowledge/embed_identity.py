"""The embedding identity: which coordinate space a library's vectors live in (spec 2026-10-04 D2).

The identity covers exactly the three fields that decide the space — provider, model and
base_url. The API key is deliberately absent: rotating a credential changes no vector.
The width is absent too: it is its own axis and has its own channel (``rag_migration``).

The value is a compact JSON object rather than a bare hash so the mismatch warning (D4)
can name *which* field moved; a hash could only ever answer "different".

Written at exactly two points, both of which know the vectors are uniform:
``reindex_kb`` after a fully successful rebuild, and the indexing worker when a
library's first document completes. An incomplete rebuild or a later incremental
document never writes — a library whose space is unknown or mixed keeps ``NULL``
rather than a false claim (``NULL`` = unstamped, not "current").
"""

from __future__ import annotations

import json
from typing import Any

from deerflow_knowledge.models import KnowledgeBaseRow


def embedding_identity(provider: str | None, model: str | None, base_url: str | None) -> str:
    """One stable string per coordinate space (blank == absent, so '' and None agree)."""
    return json.dumps({"provider": _norm(provider), "model": _norm(model), "base_url": _norm(base_url)}, sort_keys=True, separators=(",", ":"))


def identity_from_rag(rag: Any) -> str:
    """The identity of the configuration an embedder is built from."""
    return embedding_identity(rag.embedding_provider, rag.embedding_model, rag.embedding_base_url)


def identity_diff_fields(stored: str | None, current: str) -> tuple[str, ...] | None:
    """Which space fields moved since the library was stamped (D4's read-side verdict).

    ``None`` = no claim: an unstamped (or unparsable) library is *unknown*, so the
    caller must neither warn about a mismatch nor assert the two agree. Otherwise the
    tuple names the differing fields — empty when the library is in the current space.
    """
    text = (stored or "").strip()
    if not text:
        return None
    try:
        stored_fields = json.loads(text)
    except ValueError:
        return None
    if not isinstance(stored_fields, dict):
        return None
    current_fields = json.loads(current)
    return tuple(key for key in ("provider", "model", "base_url") if _norm(stored_fields.get(key)) != _norm(current_fields.get(key)))


def _norm(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


async def write_kb_identity(session_factory: Any, kb_id: str, identity: str) -> None:
    """Record a library's space identity; a missing row is a no-op."""
    async with session_factory() as session:
        row = await session.get(KnowledgeBaseRow, kb_id)
        if row is None:
            return
        row.embedding_identity = identity
        await session.commit()
