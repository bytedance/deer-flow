"""持有实例随配置换新（spec 2026-10-05 D1）用例。

pin 住的契约：
- ``refreshed_store(held)``：真实例且 url 已知才自检；宽度差 ⇒ 复用同一 client 换新、
  集合名带新宽度；url 差 ⇒ 重建（新 client）；一致 ⇒ 同一实例；假体与 url 未知
  （client 注入）⇒ 直通且**不读配置**（后者是死循环式重建的回归钉）。
- worker ``_vector_store`` 与 service ``vector_store`` 两取值口 = 自检属性（fake 原样）。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from deerflow_knowledge.services.knowledge_service import KnowledgeService
from deerflow_knowledge.store import KnowledgeStore
from deerflow_knowledge.vector_store import KnowledgeVectorStore, refreshed_store
from deerflow_knowledge.worker import KnowledgeIndexWorker

CFG_URL = "http://cfg:6333"


class _FakeClient:
    """极简 client 双——换新构造不对 client 做任何调用。"""


def _stub_config(monkeypatch, *, url: str = CFG_URL, width: int = 1024) -> None:
    rag = SimpleNamespace(qdrant_url=url, embedding_dimension=None if width == 1024 else width)
    monkeypatch.setattr("deerflow.config.app_config.get_app_config", lambda: SimpleNamespace(rag=rag))


def _config_forbidden(monkeypatch) -> None:
    def _boom():
        raise AssertionError("get_app_config must not be called")

    monkeypatch.setattr("deerflow.config.app_config.get_app_config", _boom)


def _held(*, url: str = CFG_URL, width: int = 1024, client=None) -> KnowledgeVectorStore:
    return KnowledgeVectorStore(url=url, client=client or _FakeClient(), dense_size=width)


def test_width_change_refreshes_reusing_client(monkeypatch):
    client = _FakeClient()
    held = _held(width=1024, client=client)
    _stub_config(monkeypatch, width=1536)

    refreshed = refreshed_store(held)

    assert refreshed is not held
    assert refreshed.dense_size == 1536
    assert refreshed._client is client  # 复用同一 client
    assert refreshed.url == CFG_URL
    assert "kb_chunks_1536" in refreshed.collection_names


def test_matching_config_keeps_the_same_instance(monkeypatch):
    held = _held()
    _stub_config(monkeypatch)

    assert refreshed_store(held) is held


def test_url_change_rebuilds(monkeypatch):
    client = _FakeClient()
    held = _held(url=CFG_URL, client=client)
    _stub_config(monkeypatch, url="http://other:6333")

    refreshed = refreshed_store(held)

    assert refreshed is not held
    assert refreshed.url == "http://other:6333"
    assert refreshed._client is not client  # 地址变了 ⇒ 新 client


def test_fakes_pass_through_without_reading_config(monkeypatch):
    _config_forbidden(monkeypatch)
    for fake in (MagicMock(), SimpleNamespace(), object()):
        assert refreshed_store(fake) is fake


def test_client_injected_store_passes_through(monkeypatch):
    """url 未知（client= 注入）⇒ 直通不重建；否则每次取值都判不符 ⇒ 死循环式换新。"""
    _config_forbidden(monkeypatch)
    held = KnowledgeVectorStore(client=_FakeClient(), dense_size=1024)

    assert refreshed_store(held) is held


async def test_worker_getter_self_checks(session_factory, monkeypatch):
    store = KnowledgeStore(session_factory)
    client = _FakeClient()
    worker = KnowledgeIndexWorker(store=store, vector_store=_held(client=client), sweep_enabled=False)
    _stub_config(monkeypatch, width=1536)

    refreshed = worker._vector_store

    assert refreshed.dense_size == 1536
    assert refreshed._client is client
    assert worker._vector_store is refreshed  # 第二次取值稳定（不再重建）


async def test_worker_getter_fake_passes(session_factory):
    store = KnowledgeStore(session_factory)
    fake = MagicMock()
    worker = KnowledgeIndexWorker(store=store, vector_store=fake, sweep_enabled=False)

    assert worker._vector_store is fake


async def test_service_getter_self_checks(session_factory, tmp_path, monkeypatch):
    store = KnowledgeStore(session_factory)
    client = _FakeClient()
    service = KnowledgeService(store=store, vector_store=_held(client=client), data_dir=tmp_path)
    _stub_config(monkeypatch, width=1536)

    refreshed = service.vector_store

    assert refreshed.dense_size == 1536
    assert refreshed._client is client
    assert service.vector_store is refreshed  # 第二次取值稳定


async def test_service_getter_fake_passes(session_factory, tmp_path):
    store = KnowledgeStore(session_factory)
    fake = MagicMock()
    service = KnowledgeService(store=store, vector_store=fake, data_dir=tmp_path)

    assert service.vector_store is fake
