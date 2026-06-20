from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.runtime import RunStatus
from deerflow.utils.messages import ORIGINAL_USER_CONTENT_KEY


def _checkpoint(checkpoint_id: str, messages: list[object]):
    return SimpleNamespace(
        config={
            "configurable": {
                "thread_id": "thread-1",
                "checkpoint_ns": "",
                "checkpoint_id": checkpoint_id,
                "checkpoint_map": None,
            }
        },
        checkpoint={"channel_values": {"messages": messages}},
    )


class FakeCheckpointer:
    def __init__(self, history, *, latest=None):
        self.history = history
        self.latest = latest
        self.alist_limits = []

    async def aget_tuple(self, config):
        checkpoint_id = config.get("configurable", {}).get("checkpoint_id")
        if checkpoint_id:
            return next((item for item in self.history if item.config["configurable"]["checkpoint_id"] == checkpoint_id), None)
        return self.latest or (self.history[0] if self.history else None)

    async def alist(self, config, limit=200):
        self.alist_limits.append(limit)
        for item in self.history[:limit]:
            yield item


class FakeEventStore:
    def __init__(self, rows):
        self.rows = rows

    async def list_messages(self, thread_id, *, limit=50, before_seq=None, after_seq=None):
        return self.rows[-limit:]


class FakeRunManager:
    def __init__(self, records):
        self.records = records

    async def list_by_thread(self, thread_id, *, user_id=None, limit=100):
        return self.records[:limit]


def _request(checkpointer, event_store, *, run_manager=None, user_id="user-1"):
    from app.gateway.auth_disabled import AUTH_SOURCE_SESSION

    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                checkpointer=checkpointer,
                run_event_store=event_store,
                run_manager=run_manager or FakeRunManager([]),
            )
        ),
        state=SimpleNamespace(user=SimpleNamespace(id=user_id), auth_source=AUTH_SOURCE_SESSION),
    )


def test_prepare_regenerate_payload_returns_clean_input_and_base_checkpoint():
    from app.gateway.routers.thread_runs import _prepare_regenerate_payload

    human = HumanMessage(
        id="human-1",
        content="<uploaded_files>injected</uploaded_files>\n\n/data-analysis analyze data.csv",
        additional_kwargs={
            ORIGINAL_USER_CONTENT_KEY: "/data-analysis analyze data.csv",
            "files": [{"filename": "data.csv", "path": "/mnt/user-data/uploads/data.csv"}],
        },
    )
    ai = AIMessage(id="ai-1", content="answer v1")
    base = _checkpoint("ckpt-base", [])
    after_human = _checkpoint("ckpt-human", [human])
    latest = _checkpoint("ckpt-ai", [human, ai])
    checkpointer = FakeCheckpointer([latest, after_human, base])
    event_store = FakeEventStore(
        [
            {
                "run_id": "run-old",
                "event_type": "llm.ai.response",
                "category": "message",
                "content": {"id": "ai-1", "type": "ai", "content": "answer v1"},
                "metadata": {"caller": "lead_agent"},
            }
        ]
    )

    response = asyncio.run(_prepare_regenerate_payload("thread-1", "ai-1", _request(checkpointer, event_store)))

    assert response.checkpoint == {
        "checkpoint_ns": "",
        "checkpoint_id": "ckpt-base",
        "checkpoint_map": None,
    }
    assert response.target_run_id == "run-old"
    assert response.metadata == {
        "regenerate_from_message_id": "ai-1",
        "regenerate_from_run_id": "run-old",
        "regenerate_checkpoint_id": "ckpt-base",
    }
    regenerated_human = response.input["messages"][0]
    assert regenerated_human["id"] == "human-1"
    assert regenerated_human["content"] == [{"type": "text", "text": "/data-analysis analyze data.csv"}]
    assert regenerated_human["additional_kwargs"] == {"files": [{"filename": "data.csv", "path": "/mnt/user-data/uploads/data.csv"}]}


def test_prepare_regenerate_payload_rejects_non_latest_assistant():
    from app.gateway.routers.thread_runs import _prepare_regenerate_payload

    human = HumanMessage(id="human-1", content="question")
    old_ai = AIMessage(id="ai-old", content="old")
    latest_ai = AIMessage(id="ai-latest", content="latest")
    base = _checkpoint("ckpt-base", [])
    after_human = _checkpoint("ckpt-human", [human])
    latest = _checkpoint("ckpt-latest", [human, old_ai, latest_ai])
    checkpointer = FakeCheckpointer([latest, after_human, base])
    event_store = FakeEventStore(
        [
            {
                "run_id": "run-old",
                "event_type": "ai_message",
                "category": "message",
                "content": {"id": "ai-old", "type": "ai", "content": "old"},
                "metadata": {"caller": "lead_agent"},
            }
        ]
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(_prepare_regenerate_payload("thread-1", "ai-old", _request(checkpointer, event_store)))

    assert exc.value.status_code == 409
    assert exc.value.detail == "Only the latest assistant message can be regenerated"


def test_prepare_regenerate_payload_falls_back_to_matching_run_when_events_are_missing():
    from app.gateway.routers.thread_runs import _prepare_regenerate_payload

    human = HumanMessage(id="human-1", content="question")
    ai = AIMessage(id="ai-1", content="answer")
    base = _checkpoint("ckpt-base", [])
    after_human = _checkpoint("ckpt-human", [human])
    latest = _checkpoint("ckpt-ai", [human, ai])
    checkpointer = FakeCheckpointer([latest, after_human, base])
    run_manager = FakeRunManager(
        [
            SimpleNamespace(run_id="run-latest", status=RunStatus.success, last_ai_message="answer"),
            SimpleNamespace(run_id="run-older", status=RunStatus.error, last_ai_message="answer"),
        ]
    )

    response = asyncio.run(
        _prepare_regenerate_payload(
            "thread-1",
            "ai-1",
            _request(checkpointer, FakeEventStore([]), run_manager=run_manager),
        )
    )

    assert response.target_run_id == "run-latest"
    assert response.metadata["regenerate_from_run_id"] == "run-latest"


def test_prepare_regenerate_payload_rejects_unverified_run_fallback_when_events_are_missing():
    from app.gateway.routers.thread_runs import _prepare_regenerate_payload

    human = HumanMessage(id="human-1", content="question")
    ai = AIMessage(id="ai-1", content="answer")
    base = _checkpoint("ckpt-base", [])
    after_human = _checkpoint("ckpt-human", [human])
    latest = _checkpoint("ckpt-ai", [human, ai])
    checkpointer = FakeCheckpointer([latest, after_human, base])
    run_manager = FakeRunManager(
        [
            SimpleNamespace(run_id="run-latest", status=RunStatus.success, last_ai_message="different"),
        ]
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            _prepare_regenerate_payload(
                "thread-1",
                "ai-1",
                _request(checkpointer, FakeEventStore([]), run_manager=run_manager),
            )
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "Could not find source run for assistant message"


def test_prepare_regenerate_payload_requires_addressable_checkpoint_before_human():
    from app.gateway.routers.thread_runs import _prepare_regenerate_payload

    human = HumanMessage(id="human-1", content="question")
    ai = AIMessage(id="ai-1", content="answer")
    latest = _checkpoint("ckpt-ai", [human, ai])
    checkpointer = FakeCheckpointer([latest])
    event_store = FakeEventStore(
        [
            {
                "run_id": "run-old",
                "event_type": "llm.ai.response",
                "category": "message",
                "content": {"id": "ai-1", "type": "ai", "content": "answer"},
                "metadata": {"caller": "lead_agent"},
            }
        ]
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(_prepare_regenerate_payload("thread-1", "ai-1", _request(checkpointer, event_store)))

    assert exc.value.status_code == 409
    assert exc.value.detail == "Could not find an addressable checkpoint before the target user message"
    assert checkpointer.alist_limits == [200]


def test_prepare_regenerate_payload_reports_recent_checkpoint_scan_limit():
    from app.gateway.routers.thread_runs import _prepare_regenerate_payload

    human = HumanMessage(id="human-1", content="question")
    ai = AIMessage(id="ai-1", content="answer")
    latest = _checkpoint("ckpt-latest", [human, ai])
    history_without_human = [_checkpoint(f"ckpt-{index}", []) for index in range(201)]
    checkpointer = FakeCheckpointer(history_without_human, latest=latest)
    event_store = FakeEventStore(
        [
            {
                "run_id": "run-old",
                "event_type": "llm.ai.response",
                "category": "message",
                "content": {"id": "ai-1", "type": "ai", "content": "answer"},
                "metadata": {"caller": "lead_agent"},
            }
        ]
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(_prepare_regenerate_payload("thread-1", "ai-1", _request(checkpointer, event_store)))

    assert exc.value.status_code == 409
    assert exc.value.detail == "Could not locate target user message in recent checkpoint history (limit=200)"
    assert checkpointer.alist_limits == [200]
