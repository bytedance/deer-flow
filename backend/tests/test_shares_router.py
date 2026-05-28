import asyncio
from types import SimpleNamespace

from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.store.memory import InMemoryStore

from app.gateway.routers import shares
from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore


class _ShareTestStore(InMemoryStore):
    def __init__(self, *, supports_ttl: bool = True) -> None:
        super().__init__()
        self.supports_ttl = supports_ttl
        self.put_ttls: list[float | None] = []

    async def aput(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if args and args[0] == shares._SHARES_NS:
            self.put_ttls.append(kwargs.get("ttl"))
        await super().aput(*args, **kwargs)


class _FakeCheckpointer:
    def __init__(self) -> None:
        self.checkpoints: dict[str, dict] = {}

    async def aget_tuple(self, config: dict):
        thread_id = config["configurable"]["thread_id"]
        checkpoint = self.checkpoints.get(thread_id)
        if checkpoint is None:
            return None
        return SimpleNamespace(checkpoint=checkpoint)


def _build_share_app(
    *,
    owner_check_passes: bool = True,
    store_supports_ttl: bool = True,
) -> tuple[TestClient, _ShareTestStore, _FakeCheckpointer]:
    app = make_authed_test_app(owner_check_passes=owner_check_passes)
    store = _ShareTestStore(supports_ttl=store_supports_ttl)
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
                    AIMessage(
                        content="Answer",
                        id="ai-1",
                        additional_kwargs={"private": "not public"},
                        response_metadata={"model": "hidden"},
                    ),
                    AIMessage(
                        content="",
                        id="tool-call-1",
                        tool_calls=[{"name": "search", "args": {}, "id": "call-1"}],
                    ),
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
    assert body["messages"][1] == {"type": "ai", "content": "Answer", "id": "ai-1"}
    assert "response_metadata" not in body["messages"][1]
    assert "additional_kwargs" not in body["messages"][1]
    assert store.put_ttls == [shares._SHARE_TTL_MINUTES]


def test_create_share_keeps_intentional_empty_title() -> None:
    client, store, checkpointer = _build_share_app()
    _seed_thread(store, checkpointer, "thread-share")

    response = client.post(
        "/api/shares/threads/thread-share",
        json={"message_ids": ["human-1", "ai-1"], "title": ""},
    )

    assert response.status_code == 200, response.text
    assert response.json()["title"] == ""


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


def test_create_share_returns_503_without_checkpointer() -> None:
    client, store, _checkpointer = _build_share_app()
    _seed_thread(store, _checkpointer, "thread-share")
    client.app.state.checkpointer = None

    response = client.post(
        "/api/shares/threads/thread-share",
        json={"message_ids": ["human-1", "ai-1"]},
    )

    assert response.status_code == 503


def test_get_share_deletes_expired_snapshot_when_ttl_is_unavailable() -> None:
    client, store, checkpointer = _build_share_app(store_supports_ttl=False)
    _seed_thread(store, checkpointer, "thread-share")

    response = client.post(
        "/api/shares/threads/thread-share",
        json={"message_ids": ["human-1", "ai-1"]},
    )
    assert response.status_code == 200, response.text
    share_id = response.json()["share_id"]

    async def _expire_share() -> None:
        item = await store.aget(shares._SHARES_NS, share_id)
        assert item is not None
        value = dict(item.value)
        value["expires_at"] = "2000-01-01T00:00:00+00:00"
        await store.aput(shares._SHARES_NS, share_id, value)

    asyncio.run(_expire_share())

    public_response = client.get(f"/api/shares/{share_id}")
    assert public_response.status_code == 404

    async def _assert_deleted() -> None:
        assert await store.aget(shares._SHARES_NS, share_id) is None

    asyncio.run(_assert_deleted())


def test_create_share_cleans_expired_snapshots_beyond_first_batch_without_ttl() -> None:
    client, store, checkpointer = _build_share_app(store_supports_ttl=False)
    _seed_thread(store, checkpointer, "thread-share")

    async def _seed_expired_shares() -> None:
        for index in range(shares._EXPIRED_SHARE_CLEANUP_BATCH_SIZE + 5):
            await store.aput(
                shares._SHARES_NS,
                f"expired-share-{index:03d}",
                {
                    "created_at": "2000-01-01T00:00:00+00:00",
                    "expires_at": "2000-01-02T00:00:00+00:00",
                    "messages": [],
                },
            )

    asyncio.run(_seed_expired_shares())

    response = client.post(
        "/api/shares/threads/thread-share",
        json={"message_ids": ["human-1", "ai-1"]},
    )

    assert response.status_code == 200, response.text

    async def _assert_expired_deleted() -> None:
        items = await store.asearch(shares._SHARES_NS, limit=200, refresh_ttl=False)
        assert not [item.key for item in items if item.key.startswith("expired-share-")]

    asyncio.run(_assert_expired_deleted())


def test_get_share_normalizes_stored_messages() -> None:
    client, store, _checkpointer = _build_share_app()

    async def _seed_share() -> None:
        await store.aput(
            shares._SHARES_NS,
            "share-with-metadata",
            {
                "title": "Legacy share",
                "created_at": "2026-05-28T00:00:00+00:00",
                "messages": [
                    {
                        "id": "ai-1",
                        "type": "ai",
                        "content": "Answer",
                        "response_metadata": {"model": "hidden"},
                        "additional_kwargs": {"private": "not public"},
                    },
                    {
                        "id": "tool-call-1",
                        "type": "ai",
                        "content": "",
                        "tool_calls": [{"name": "search", "args": {}, "id": "call-1"}],
                    },
                ],
            },
        )

    asyncio.run(_seed_share())

    response = client.get("/api/shares/share-with-metadata")

    assert response.status_code == 200, response.text
    assert response.json()["messages"] == [{"type": "ai", "content": "Answer", "id": "ai-1"}]
