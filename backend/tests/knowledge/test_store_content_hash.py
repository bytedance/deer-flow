"""Test store's content_hash support.

Task 11: persist SHA-256 hash in documents table.
"""

from __future__ import annotations

import hashlib

import pytest

from deerflow.knowledge.store import KnowledgeStore

pytestmark = pytest.mark.asyncio


async def test_create_document_with_hash(session_factory):
    """RED/GREEN: store accepts and returns content_hash."""
    store = KnowledgeStore(session_factory)

    kb = await store.create_kb(kb_id="kb-1", owner_id="user-1", name="Test KB")

    test_content = b"test content for duplicate detection"
    expected_hash = hashlib.sha256(test_content).hexdigest()

    doc = await store.create_document(
        doc_id="doc-1",
        kb_id=kb["id"],
        uploader_id="user-1",
        name="test.txt",
        size_bytes=len(test_content),
        storage_path="/fake/path/test.txt",
        content_hash=expected_hash,
    )

    assert doc["content_hash"] == expected_hash
    assert doc["name"] == "test.txt"


async def test_create_document_without_hash_legacy(session_factory):
    """Store allows NULL hash for legacy documents."""
    store = KnowledgeStore(session_factory)

    kb = await store.create_kb(kb_id="kb-1", owner_id="user-1", name="Test KB")

    doc = await store.create_document(
        doc_id="doc-legacy",
        kb_id=kb["id"],
        uploader_id="user-1",
        name="legacy.txt",
        size_bytes=100,
        storage_path="/fake/path/legacy.txt",
    )

    assert doc["content_hash"] is None


async def test_list_documents_returns_hash(session_factory):
    """list_documents API carries content_hash field."""
    store = KnowledgeStore(session_factory)

    kb = await store.create_kb(kb_id="kb-1", owner_id="user-1", name="Test KB")

    test_content = b"test content"
    expected_hash = hashlib.sha256(test_content).hexdigest()

    await store.create_document(
        doc_id="doc-1",
        kb_id=kb["id"],
        uploader_id="user-1",
        name="test.txt",
        size_bytes=len(test_content),
        storage_path="/fake/path/test.txt",
        content_hash=expected_hash,
    )

    documents = await store.list_documents(kb["id"])
    assert len(documents) == 1
    assert documents[0]["content_hash"] == expected_hash
