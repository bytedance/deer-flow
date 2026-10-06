"""Tests for WikiStore.upsert_entry with supplement_content parameter.

Phase-3 Batch-1 (P1): Verify that:
1. upsert_entry accepts supplement_content parameter (RED)
2. Re-generation preserves supplement layer unchanged (GREEN)
3. Legacy entries without supplement read NULL (backward compatible)
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
import sqlalchemy as sa

import deerflow.persistence.models  # noqa: F401 -- registers models
from deerflow.knowledge.wiki.store import WikiStore, wiki_entry_id


@pytest.mark.asyncio
async def test_upsert_entry_accepts_supplement_content(session_factory):
    """GREEN (was RED): verify upsert_entry accepts and saves supplement_content."""
    store = WikiStore(session_factory)

    result = await store.upsert_entry(
        kb_id="kb-test",
        title="TestEntry",
        content="Main content",
        source_chunk_ids=["chunk-1"],
        status="ready",
        supplement_content="User annotation",
    )

    # Should save successfully now
    assert result["content"] == "Main content"
    assert result.get("supplement_content") == "User annotation"


@pytest.mark.asyncio
async def test_upsert_entry_preserves_supplement_layer(session_factory):
    """GREEN: insert with supplement → re-generate without it → still exists.

    This is the core P1 contract: supplement layer survives dirty re-generation.
    """
    from deerflow.knowledge.wiki.store import WikiStore

    store = WikiStore(session_factory)

    # Step 1: Insert entry WITH supplement_content
    first_result = await store.upsert_entry(
        kb_id="kb-test",
        title="PolymorphismTest",
        content="Polymorphism is an OOP feature",
        source_chunk_ids=["chunk-1"],
        status="ready",
        supplement_content="User note: includes overloading and overriding",
    )

    assert first_result["content"] == "Polymorphism is an OOP feature"
    assert first_result.get("supplement_content") == "User note: includes overloading and overriding"

    # Step 2: Re-generate WITHOUT supplement_content (simulate dirty re-gen)
    second_result = await store.upsert_entry(
        kb_id="kb-test",
        title="PolymorphismTest",
        content="Polymorphism allows different responses to same message",
        source_chunk_ids=["chunk-2"],
        status="ready",
        # NO supplement_content provided - should preserve existing
    )

    # Main content changed
    assert second_result["content"] == "Polymorphism allows different responses to same message"
    # Status unchanged
    assert second_result["status"] == "ready"
    # Source chunks updated
    assert second_result["source_chunk_ids"] == ["chunk-2"]
    # SUPPLEMENT LAYER PRESERVED
    assert second_result.get("supplement_content") == "User note: includes overloading and overriding"

    # Step 3: Explicitly set to None (should clear)
    third_result = await store.upsert_entry(
        kb_id="kb-test",
        title="PolymorphismTest",
        content="Updated definition",
        source_chunk_ids=["chunk-3"],
        status="ready",
        supplement_content=None,  # Explicitly clear
    )

    assert third_result.get("supplement_content") is None


@pytest.mark.asyncio
async def test_legacy_entry_without_supplement_reads_null(session_factory):
    """Legacy entries created before P1 read NULL for supplement_content."""
    from deerflow.persistence.engine import close_engine, init_engine

    # Create a fresh DB and manually insert an entry WITHOUT supplement_content
    with TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "legacy.db"
        url = f"sqlite+aiosqlite:///{db_path.as_posix()}"

        await init_engine(backend="sqlite", url=url, sqlite_dir=str(tmp_dir))
        try:
            async with session_factory() as sess:
                # Manually insert row WITHOUT supplement_content column
                # (simulating pre-migration legacy data)
                entry_id = wiki_entry_id("kb-legacy", "LegacyEntry")
                await sess.execute(
                    sa.text("INSERT INTO wiki_entries (id, kb_id, title, content, status, source_chunk_ids, updated_at) VALUES (:id, :kb_id, :title, :content, :status, :source_chunk_ids, :updated_at)"),
                    {
                        "id": entry_id,
                        "kb_id": "kb-legacy",
                        "title": "LegacyEntry",
                        "content": "Old content",
                        "status": "ready",
                        "source_chunk_ids": "[]",
                        "updated_at": datetime.now(UTC).isoformat(),
                    },
                )
                await sess.commit()

            # Now read via upsert_entry (should not crash)
            store = WikiStore(session_factory)

            # Read existing entry (upsert will find it and update)
            result = await store.upsert_entry(
                kb_id="kb-legacy",
                title="LegacyEntry",
                content="Updated via upsert",
                source_chunk_ids=["c2"],
                status="ready",
            )

            # Should work fine, supplement_content defaults to NULL
            assert result["supplement_content"] is None

        finally:
            await close_engine()
