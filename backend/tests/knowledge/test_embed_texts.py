"""Tests for the shared embedding-input helpers (spec 2026-09-24 §4.1).

The write paths and the rebuild pass must embed the *same* text, so the
f-strings move into ``deerflow_knowledge.embed_texts`` and both sides call in.
"""

from __future__ import annotations

from deerflow_knowledge.embed_texts import (
    EMBED_CONTENT_CHARS,
    entity_embed_text,
    manual_card_embed_text,
    wiki_entry_embed_text,
)


def test_entity_embed_text_normalizes_nullable_description():
    # Raw graph rows carry a nullable description (models.py:101).
    assert entity_embed_text("X", None) == "X\n"
    assert entity_embed_text("X", "d") == "X\nd"


def test_wiki_entry_embed_text_truncates_content_to_embed_chars():
    text = wiki_entry_embed_text("T", "长" * 600)
    title, content = text.split("\n", 1)
    assert title == "T"
    assert len(content) == EMBED_CONTENT_CHARS == 500


def test_manual_card_embed_text_shape():
    assert manual_card_embed_text("T", "C") == "T\nC"
