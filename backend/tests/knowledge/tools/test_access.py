"""Tests for the Phase-1 access gate (owner-only) and the kb scope resolver."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from deerflow_knowledge.access import can_access, resolve_kb_scope
from deerflow_knowledge.store import KnowledgeStore


@pytest.mark.asyncio
async def test_owner_can_access(session_factory):
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-a", owner_id="user-1", name="私有库")

    assert await can_access(store, "user-1", "kb-a") is True


@pytest.mark.asyncio
async def test_non_owner_denied(session_factory):
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-a", owner_id="user-1", name="私有库")

    assert await can_access(store, "user-2", "kb-a") is False


@pytest.mark.asyncio
async def test_missing_kb_denied(session_factory):
    store = KnowledgeStore(session_factory)

    assert await can_access(store, "user-1", "kb-nope") is False


def test_resolve_kb_scope_reads_context():
    runtime = SimpleNamespace(context={"kb_id": "kb-1", "user_id": "user-9"})

    kb_id, user_id = resolve_kb_scope(runtime)

    assert kb_id == "kb-1"
    assert user_id == "user-9"


def test_resolve_kb_scope_missing_kb():
    runtime = SimpleNamespace(context={"user_id": "user-9"})

    kb_id, _ = resolve_kb_scope(runtime)

    assert kb_id is None
