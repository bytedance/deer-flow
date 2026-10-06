"""Tests for the manual knowledge card CRUD API (Phase-3 Batch-1 P6, Task 7).

Manual cards are fully user-managed entries living outside the AI wiki
lifecycle — never auto-regenerated, never disqualified (spec §8). Each card
carries an ``include_in_wiki_search`` toggle (default off): toggled-on cards
are embedded into Qdrant so the Task-8 wiki-path merge can retrieve them;
toggled-off / deleted cards lose their vector point. Vector failures on the
delete path are swallowed (module cascade rule); the write path surfaces
failures as 500 (same contract as chunk editing, Task 4 收尾).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.gateway.auth.models import User
from app.gateway.routers import knowledge_bases
from app.gateway.services import knowledge_service as ks_module
from app.gateway.services.knowledge_service import KnowledgeService
from deerflow.knowledge.store import KnowledgeStore

from .conftest import spy_embed_text

pytestmark = pytest.mark.asyncio

OWNER_ID = str(UUID(int=1234567890))


def _owner() -> User:
    return User(email="owner@example.com", password_hash="x", system_role="user", id=UUID(OWNER_ID))


@pytest.fixture
def service(session_factory, tmp_path) -> KnowledgeService:
    vector_store = MagicMock()
    vector_store.upsert_manual_cards = AsyncMock()  # P6 Task 7: card vector write path
    vector_store.delete_manual_cards = AsyncMock()
    vector_store.delete_by_kb = AsyncMock()
    return KnowledgeService(
        store=KnowledgeStore(session_factory),
        vector_store=vector_store,
        worker=MagicMock(submit=AsyncMock()),
        data_dir=tmp_path,
    )


def _client(service: KnowledgeService, user_factory=_owner) -> TestClient:
    from _router_auth_helpers import make_authed_test_app

    app = make_authed_test_app(user_factory=user_factory)
    app.state.knowledge_service = service
    app.include_router(knowledge_bases.router)
    return TestClient(app)


def _client_no_raise(service: KnowledgeService, user_factory=_owner) -> TestClient:
    """5xx surfaces as a response instead of raising (constructor-time flag —
    assignment on an existing client is a no-op)."""
    from _router_auth_helpers import make_authed_test_app

    app = make_authed_test_app(user_factory=user_factory)
    app.state.knowledge_service = service
    app.include_router(knowledge_bases.router)
    return TestClient(app, raise_server_exceptions=False)


def _create_kb(client: TestClient, name: str = "产品资料") -> dict:
    response = client.post("/api/knowledge-bases", json={"name": name, "description": "d"})
    assert response.status_code == 201, response.text
    return response.json()


def _cards_url(kb_id: str) -> str:
    return f"/api/knowledge-bases/{kb_id}/manual-knowledge"


def _mock_embedder(monkeypatch) -> MagicMock:
    """Patch the embedder factory the service calls (spec 2026-09-14 §4.2: the service
    builds its embedder through ``build_embedder()``, so the patch target is that name in
    the service module's namespace — not the provider class it happens to resolve to)."""
    from qdrant_client.models import SparseVector

    from deerflow.knowledge.embedder import EmbeddingResult

    embedder = MagicMock()
    embedder.embed = AsyncMock(return_value=[EmbeddingResult(dense=[0.25] * 1024, sparse=SparseVector(indices=[3], values=[0.7]))])
    monkeypatch.setattr(ks_module, "build_embedder", lambda: embedder)
    return embedder


async def test_create_card_422_without_required_fields(service):
    client = _client(service)
    kb = _create_kb(client)
    url = _cards_url(kb["id"])

    assert client.post(url, json={}).status_code == 422
    assert client.post(url, json={"title": "只有标题"}).status_code == 422
    assert client.post(url, json={"title": "  ", "content": "x"}).status_code == 422
    assert client.post(url, json={"title": "t", "content": "  "}).status_code == 422


async def test_create_card_defaults_flag_off_and_skips_vector(service, monkeypatch):
    embedder = _mock_embedder(monkeypatch)
    client = _client(service)
    kb = _create_kb(client)

    response = client.post(_cards_url(kb["id"]), json={"title": "部署 runbook", "content": "明天凌晨执行"})

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["title"] == "部署 runbook"
    assert body["include_in_wiki_search"] is False  # spec §8: default off
    assert body["tags"] == []
    assert body["owner_id"] == OWNER_ID
    assert body["kb_id"] == kb["id"]
    assert body["created_at"] and body["updated_at"]
    # flag off → no embedding call, no vector point
    embedder.embed.assert_not_called()
    service.vector_store.upsert_manual_cards.assert_not_called()
    # persisted for real
    stored = await service.store.get_manual_card(body["id"])
    assert stored is not None and stored["content"] == "明天凌晨执行"


async def test_create_card_with_flag_on_embeds_and_upserts(service, monkeypatch):
    embedder = _mock_embedder(monkeypatch)
    helper_calls = spy_embed_text(monkeypatch, "app.gateway.services.knowledge_service", "manual_card_embed_text")
    client = _client(service)
    kb = _create_kb(client)

    response = client.post(
        _cards_url(kb["id"]),
        json={"title": "线上禁令", "content": "周五不发布", "tags": ["ops"], "include_in_wiki_search": True},
    )

    assert response.status_code == 201, response.text
    embedder.embed.assert_awaited_once_with(["线上禁令\n周五不发布"])
    service.vector_store.upsert_manual_cards.assert_awaited_once()
    # Same-source pin (spec 2026-09-24 §4.1): the card embed text comes from the shared helper.
    assert helper_calls == [("线上禁令", "周五不发布")], "card embedding must use the shared helper"
    upserted = list(service.vector_store.upsert_manual_cards.call_args[0][0])
    assert [c.card_id for c in upserted] == [response.json()["id"]]
    assert upserted[0].kb_id == kb["id"]
    assert upserted[0].title == "线上禁令"
    assert upserted[0].dense == [0.25] * 1024


async def test_list_cards_paginates(service):
    client = _client(service)
    kb = _create_kb(client)
    url = _cards_url(kb["id"])
    for i in range(3):
        assert client.post(url, json={"title": f"卡片{i}", "content": f"内容{i}"}).status_code == 201

    page1 = client.get(url, params={"limit": 2}).json()
    assert page1["total"] == 3
    assert len(page1["items"]) == 2
    assert page1["limit"] == 2 and page1["offset"] == 0
    page2 = client.get(url, params={"limit": 2, "offset": 2}).json()
    assert len(page2["items"]) == 1
    titles = {item["title"] for item in page1["items"] + page2["items"]}
    assert titles == {"卡片0", "卡片1", "卡片2"}
    # List payload carries a summary, not the full content (wiki-list pattern).
    assert "summary" in page1["items"][0]
    assert "content" not in page1["items"][0]


async def test_list_cards_filters_by_include_flag(service, monkeypatch):
    _mock_embedder(monkeypatch)
    client = _client(service)
    kb = _create_kb(client)
    url = _cards_url(kb["id"])
    assert client.post(url, json={"title": "混入", "content": "x", "include_in_wiki_search": True}).status_code == 201
    assert client.post(url, json={"title": "不混入", "content": "x"}).status_code == 201

    only_on = client.get(url, params={"include_in_wiki_search": True}).json()
    assert [item["title"] for item in only_on["items"]] == ["混入"]
    assert only_on["total"] == 1
    only_off = client.get(url, params={"include_in_wiki_search": False}).json()
    assert [item["title"] for item in only_off["items"]] == ["不混入"]


async def test_list_cards_stable_order_survives_updates(service):
    """Updates (incl. toggle flips) must NOT reshuffle the list: ordering is
    ``created_at``-stable (newest first), not ``updated_at``. With updated_at
    ordering the card you just toggled jumps to the top — visually reading as
    "the row above lit up"."""
    client = _client(service)
    kb = _create_kb(client)
    url = _cards_url(kb["id"])
    ids = [client.post(url, json={"title": f"卡片{i}", "content": "x"}).json()["id"] for i in range(3)]

    before = [item["id"] for item in client.get(url).json()["items"]]
    assert client.patch(f"{url}/{ids[1]}", json={"title": "改名"}).status_code == 200
    after = [item["id"] for item in client.get(url).json()["items"]]

    assert after == before


async def test_get_card_detail_and_404(service):
    client = _client(service)
    kb = _create_kb(client)
    other_kb = _create_kb(client, name="另一个库")
    created = client.post(_cards_url(kb["id"]), json={"title": "t", "content": "完整正文"}).json()

    detail = client.get(f"{_cards_url(kb['id'])}/{created['id']}")
    assert detail.status_code == 200
    assert detail.json()["content"] == "完整正文"

    assert client.get(f"{_cards_url(kb['id'])}/nonexistent").status_code == 404
    # Cross-KB reads must not leak another library's card.
    assert client.get(f"{_cards_url(other_kb['id'])}/{created['id']}").status_code == 404


async def test_update_card_toggle_drives_vector_lifecycle(service, monkeypatch):
    embedder = _mock_embedder(monkeypatch)
    helper_calls = spy_embed_text(monkeypatch, "app.gateway.services.knowledge_service", "manual_card_embed_text")
    client = _client(service)
    kb = _create_kb(client)
    url = _cards_url(kb["id"])
    card = client.post(url, json={"title": "旧标题", "content": "v1"}).json()
    card_url = f"{url}/{card['id']}"

    # Plain rename with the flag off → no vector work at all.
    renamed = client.patch(card_url, json={"title": "新标题"})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["title"] == "新标题"
    assert renamed.json()["content"] == "v1"
    embedder.embed.assert_not_called()
    service.vector_store.upsert_manual_cards.assert_not_called()

    # Toggle on → embed + upsert.
    toggled = client.patch(card_url, json={"include_in_wiki_search": True})
    assert toggled.status_code == 200 and toggled.json()["include_in_wiki_search"] is True
    embedder.embed.assert_awaited_once_with(["新标题\nv1"])
    service.vector_store.upsert_manual_cards.assert_awaited_once()

    # Content edit while the flag is on → re-embed + overwrite the same point.
    edited = client.patch(card_url, json={"content": "v2"})
    assert edited.status_code == 200 and edited.json()["content"] == "v2"
    assert embedder.embed.await_count == 2
    assert service.vector_store.upsert_manual_cards.await_count == 2

    # Toggle off → the vector point goes (card stays searchable nowhere).
    off = client.patch(card_url, json={"include_in_wiki_search": False})
    assert off.status_code == 200 and off.json()["include_in_wiki_search"] is False
    service.vector_store.delete_manual_cards.assert_awaited_once_with([card["id"]])

    assert client.patch(f"{url}/nonexistent", json={"title": "x"}).status_code == 404
    # Same-source pin (spec 2026-09-24 §4.1): both update-path embeds ride the shared helper.
    assert helper_calls == [("新标题", "v1"), ("新标题", "v2")], "card re-embed must use the shared helper"


async def test_delete_card_removes_row_and_point(service, monkeypatch):
    _mock_embedder(monkeypatch)
    client = _client(service)
    kb = _create_kb(client)
    url = _cards_url(kb["id"])
    card = client.post(url, json={"title": "t", "content": "x", "include_in_wiki_search": True}).json()

    response = client.delete(f"{url}/{card['id']}")

    assert response.status_code == 204
    assert await service.store.get_manual_card(card["id"]) is None
    service.vector_store.delete_manual_cards.assert_awaited_with([card["id"]])
    # Already gone → 404 (not a silent 204).
    assert client.delete(f"{url}/{card['id']}").status_code == 404


async def test_delete_card_swallows_vector_failure(service, monkeypatch):
    """Module cascade rule: a Qdrant outage must never strand the business row."""
    _mock_embedder(monkeypatch)
    service.vector_store.delete_manual_cards = AsyncMock(side_effect=RuntimeError("qdrant down"))
    client = _client_no_raise(service)
    kb = _create_kb(client)
    url = _cards_url(kb["id"])
    card = client.post(url, json={"title": "t", "content": "x", "include_in_wiki_search": True}).json()

    response = client.delete(f"{url}/{card['id']}")

    assert response.status_code == 204
    assert await service.store.get_manual_card(card["id"]) is None


async def test_delete_kb_cascade_includes_manual_cards(service):
    """KB deletion wipes its manual cards too (business-table cascade)."""
    client = _client(service)
    kb = _create_kb(client)
    card = client.post(_cards_url(kb["id"]), json={"title": "t", "content": "x"}).json()

    assert client.delete(f"/api/knowledge-bases/{kb['id']}").status_code == 204
    assert await service.store.get_manual_card(card["id"]) is None


async def test_update_card_upsert_failure_leaves_flag_off_and_retry_converges(service, monkeypatch):
    """Ordering contract (2026-08-16 fix): the vector write runs BEFORE the DB
    write. An upsert failure surfaces as 500 with the flag still off in the DB
    — retrying the toggle converges. The old order (DB first) stranded cards
    in a stuck state: flag on, no vector point, and re-PATCHing ``on`` never
    re-upserted because ``turning_on`` no longer held."""
    embedder = _mock_embedder(monkeypatch)
    service.vector_store.upsert_manual_cards = AsyncMock(side_effect=RuntimeError("qdrant down"))
    client = _client_no_raise(service)
    kb = _create_kb(client)
    url = _cards_url(kb["id"])
    card = client.post(url, json={"title": "发布禁令", "content": "周五不发布"}).json()
    card_url = f"{url}/{card['id']}"

    failed = client.patch(card_url, json={"include_in_wiki_search": True})
    assert failed.status_code == 500
    # Flag stays off in the DB — no stuck "on but vectorless" card.
    assert (await service.store.get_manual_card(card["id"]))["include_in_wiki_search"] is False

    # Qdrant recovers → the same toggle click converges.
    service.vector_store.upsert_manual_cards = AsyncMock()
    retried = client.patch(card_url, json={"include_in_wiki_search": True})
    assert retried.status_code == 200, retried.text
    assert retried.json()["include_in_wiki_search"] is True
    service.vector_store.upsert_manual_cards.assert_awaited_once()
    # 两次 PATCH 各 embed 一次（失败那次 + 收敛那次），文本均为当前卡片内容。
    assert embedder.embed.await_count == 2
    embedder.embed.assert_awaited_with(["发布禁令\n周五不发布"])


async def test_update_card_explicit_on_reasserts_missing_vector_point(service, monkeypatch):
    """Self-heal: an explicit ``include_in_wiki_search: true`` PATCH re-embeds
    and re-upserts even when the DB flag is already on (same point id — an
    idempotent overwrite), converging legacy cards stuck without a point."""
    embedder = _mock_embedder(monkeypatch)
    client = _client(service)
    kb = _create_kb(client)
    url = _cards_url(kb["id"])
    card = client.post(url, json={"title": "发布禁令", "content": "周五不发布"}).json()
    # Simulate the legacy stuck state: flag on at the store layer, no vector.
    await service.store.update_manual_card(card["id"], include_in_wiki_search=True)
    embedder.embed.reset_mock()
    service.vector_store.upsert_manual_cards.reset_mock()

    response = client.patch(f"{url}/{card['id']}", json={"include_in_wiki_search": True})

    assert response.status_code == 200, response.text
    embedder.embed.assert_awaited_once_with(["发布禁令\n周五不发布"])
    service.vector_store.upsert_manual_cards.assert_awaited_once()


async def test_create_card_upsert_failure_leaves_no_row(service, monkeypatch):
    """create follows the same contract: upsert BEFORE the DB insert — an
    upsert failure (500) leaves no flag-on vectorless row behind."""
    _mock_embedder(monkeypatch)
    service.vector_store.upsert_manual_cards = AsyncMock(side_effect=RuntimeError("qdrant down"))
    client = _client_no_raise(service)
    kb = _create_kb(client)
    url = _cards_url(kb["id"])

    response = client.post(url, json={"title": "t", "content": "x", "include_in_wiki_search": True})

    assert response.status_code == 500
    assert await service.store.list_manual_cards(kb["id"]) == []
