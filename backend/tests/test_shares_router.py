import asyncio
from types import SimpleNamespace

from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.store.memory import InMemoryStore

from app.gateway.routers import shares
from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore


class _FakeCheckpointer:
    def __init__(self) -> None:
        self.checkpoints: dict[str, dict] = {}

    async def aget_tuple(self, config: dict):
        thread_id = config["configurable"]["thread_id"]
        checkpoint = self.checkpoints.get(thread_id)
        if checkpoint is None:
            return None
        return SimpleNamespace(checkpoint=checkpoint)


def _build_share_app(*, owner_check_passes: bool = True) -> tuple[TestClient, InMemoryStore, _FakeCheckpointer]:
    app = make_authed_test_app(owner_check_passes=owner_check_passes)
    store = InMemoryStore()
    checkpointer = _FakeCheckpointer()
    app.state.store = store
    app.state.checkpointer = checkpointer
    app.include_router(shares.router)
    return TestClient(app), store, checkpointer


def _seed_thread(store: InMemoryStore, checkpointer: _FakeCheckpointer, thread_id: str) -> None:
    async def _seed() -> None:
        await MemoryThreadMetaStore(store).create(thread_id, metadata={})
        checkpointer.checkpoints[thread_id] = {
            "channel_values": {
                "title": "Share source",
                "messages": [
                    HumanMessage(content="Question", id="human-1"),
                    AIMessage(content="Answer", id="ai-1"),
                    AIMessage(content="", id="tool-call-1", tool_calls=[{"name": "search", "args": {}, "id": "call-1"}]),
                    HumanMessage(content="Follow-up", id="human-2"),
                ],
            },
        }

    asyncio.run(_seed())


def test_create_share_snapshots_selected_messages_and_public_read() -> None:
    client, store, checkpointer = _build_share_app()
    _seed_thread(store, checkpointer, "thread-share")

    response = client.post(
        "/api/shares/threads/thread-share",
        json={"message_ids": ["human-1", "ai-1"]},
    )

    assert response.status_code == 200, response.text
    share_id = response.json()["share_id"]

    public_response = client.get(f"/api/shares/{share_id}")
    assert public_response.status_code == 200, public_response.text
    body = public_response.json()
    assert body["title"] == "Share source"
    assert [message["id"] for message in body["messages"]] == ["human-1", "ai-1"]
    assert [message["content"] for message in body["messages"]] == ["Question", "Answer"]


def test_create_share_rejects_unknown_message_id() -> None:
    client, store, checkpointer = _build_share_app()
    _seed_thread(store, checkpointer, "thread-share")

    response = client.post(
        "/api/shares/threads/thread-share",
        json={"message_ids": ["missing-message"]},
    )

    assert response.status_code == 400
    assert "missing-message" in response.json()["detail"]


def test_create_share_requires_selected_message_ids() -> None:
    client, store, checkpointer = _build_share_app()
    _seed_thread(store, checkpointer, "thread-share")

    response = client.post("/api/shares/threads/thread-share", json={})

    assert response.status_code == 422


def test_create_share_rejects_non_shareable_message_id() -> None:
    client, store, checkpointer = _build_share_app()
    _seed_thread(store, checkpointer, "thread-share")

    response = client.post(
        "/api/shares/threads/thread-share",
        json={"message_ids": ["tool-call-1"]},
    )

    assert response.status_code == 400
    assert "not shareable" in response.json()["detail"]


def test_create_share_requires_thread_access() -> None:
    client, store, checkpointer = _build_share_app(owner_check_passes=False)
    _seed_thread(store, checkpointer, "thread-share")

    response = client.post(
        "/api/shares/threads/thread-share",
        json={"message_ids": ["human-1", "ai-1"]},
    )

    assert response.status_code == 404
