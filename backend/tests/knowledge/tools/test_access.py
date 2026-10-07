"""Tests for the Phase-1 access gate (owner-only) and the scope→kb resolver."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from deerflow_knowledge.access import (
    SCOPE_DISABLED_MESSAGE,
    SCOPE_DOCUMENT_FILTERS_MESSAGE,
    SCOPE_FOREIGN_DATASET_MESSAGE,
    SCOPE_INVALID_MESSAGE,
    SCOPE_MULTI_DATASET_MESSAGE,
    can_access,
    resolve_kb_scope,
)
from deerflow_knowledge.store import KnowledgeStore

from deerflow.knowledge_scope import KNOWLEDGE_SCOPE_RUNTIME_KEY, local_dataset_id


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


def _runtime(scope: dict | None = None, *, user_id: str = "user-9") -> SimpleNamespace:
    context: dict = {"user_id": user_id}
    if scope is not None:
        context[KNOWLEDGE_SCOPE_RUNTIME_KEY] = scope
    return SimpleNamespace(context=context)


def _selected(dataset_ids: list[str], **extra) -> dict:
    return {"version": 1, "mode": "selected", "dataset_ids": dataset_ids, **extra}


def test_resolve_kb_scope_reads_selected_local_dataset():
    kb_id, user_id, refusal = resolve_kb_scope(_runtime(_selected([local_dataset_id("kb-1")])))

    assert kb_id == "kb-1"
    assert user_id == "user-9"
    assert refusal is None


def test_resolve_kb_scope_without_scope_needs_no_refusal():
    kb_id, _, refusal = resolve_kb_scope(_runtime())

    assert kb_id is None
    assert refusal is None


def test_resolve_kb_scope_all_mode_keeps_the_no_binding_guidance():
    kb_id, _, refusal = resolve_kb_scope(_runtime({"version": 1, "mode": "all"}))

    assert kb_id is None
    assert refusal is None


def test_resolve_kb_scope_disabled_mode_refuses():
    kb_id, _, refusal = resolve_kb_scope(_runtime({"version": 1, "mode": "disabled"}))

    assert kb_id is None
    assert refusal == SCOPE_DISABLED_MESSAGE


def test_resolve_kb_scope_invalid_scope_refuses():
    kb_id, _, refusal = resolve_kb_scope(_runtime(_selected([])))

    assert kb_id is None
    assert refusal == SCOPE_INVALID_MESSAGE


def test_resolve_kb_scope_multiple_datasets_refuse():
    kb_id, _, refusal = resolve_kb_scope(_runtime(_selected([local_dataset_id("kb-1"), local_dataset_id("kb-2")])))

    assert kb_id is None
    assert refusal == SCOPE_MULTI_DATASET_MESSAGE


def test_resolve_kb_scope_foreign_provider_refuses():
    kb_id, _, refusal = resolve_kb_scope(_runtime(_selected(["0123456789abcdef0123456789abcdef"])))

    assert kb_id is None
    assert refusal == SCOPE_FOREIGN_DATASET_MESSAGE


def test_resolve_kb_scope_document_filters_refuse():
    kb_id, _, refusal = resolve_kb_scope(
        _runtime(
            _selected(
                [local_dataset_id("kb-1")],
                document_filters=[{"dataset_id": local_dataset_id("kb-1"), "document_ids": ["doc-1"]}],
            )
        )
    )

    assert kb_id is None
    assert refusal == SCOPE_DOCUMENT_FILTERS_MESSAGE
