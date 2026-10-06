"""Embedding-input texts shared by the write paths and the rebuild pass.

The rebuild re-embeds rows that writers already embedded; feeding the embedder
the *same* string is what makes the result trustworthy, so both sides call in
here instead of inlining the f-string (spec 2026-09-24 §4.1).
"""

from __future__ import annotations

#: Characters of entry content folded into the embedding text.
EMBED_CONTENT_CHARS = 500


def entity_embed_text(name: str, description: str | None) -> str:
    """Entity vectors embed ``name\\ndescription`` (raw rows carry a nullable description)."""
    return f"{name}\n{description or ''}"


def wiki_entry_embed_text(title: str, content: str) -> str:
    """Entry vectors embed ``title\\n`` plus the leading slice of the entry text."""
    return f"{title}\n{content[:EMBED_CONTENT_CHARS]}"


def manual_card_embed_text(title: str, content: str) -> str:
    """Card vectors share the entity shape (Phase-3 Batch-1 P6, spec §8)."""
    return f"{title}\n{content}"
