from __future__ import annotations

from uuid import uuid4

import pytest
from langchain_core.messages import HumanMessage

from deerflow.tracing.knowledge_scope import (
    KnowledgeScopeRedactingCallback,
    redact_knowledge_scope,
)


def _message() -> HumanMessage:
    return HumanMessage(
        content="Search",
        additional_kwargs={
            "knowledge_scope": {
                "version": 1,
                "mode": "selected",
                "dataset_ids": ["secret-dataset"],
                "display": {"datasets": [{"id": "secret-dataset", "name": "Private knowledge"}]},
            },
            "safe": "kept",
        },
    )


def test_redact_knowledge_scope_copies_nested_callback_payloads() -> None:
    original = {
        "messages": [_message()],
        "context": {"__knowledge_scope_execution": {"dataset_ids": ["secret"]}},
    }

    redacted = redact_knowledge_scope(original)

    assert redacted["messages"][0].additional_kwargs == {"safe": "kept"}
    assert redacted["context"] == {}
    assert "knowledge_scope" in original["messages"][0].additional_kwargs


def test_callback_proxy_redacts_sync_chain_inputs() -> None:
    captured = {}

    class Callback:
        def on_chain_start(self, serialized, inputs, **kwargs):
            captured["inputs"] = inputs

    proxy = KnowledgeScopeRedactingCallback(Callback())
    proxy.on_chain_start({}, {"messages": [_message()]}, run_id=uuid4())

    assert captured["inputs"]["messages"][0].additional_kwargs == {"safe": "kept"}


@pytest.mark.asyncio
async def test_callback_proxy_redacts_async_chain_outputs() -> None:
    captured = {}

    class Callback:
        async def on_chain_end(self, outputs, **kwargs):
            captured["outputs"] = outputs

    proxy = KnowledgeScopeRedactingCallback(Callback())
    await proxy.on_chain_end({"messages": [_message()]}, run_id=uuid4())

    assert captured["outputs"]["messages"][0].additional_kwargs == {"safe": "kept"}
