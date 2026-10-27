from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.routers import knowledge_base as kb
from deerflow.community.ragflow.client import RAGFlowClient, RAGFlowConnectionError
from deerflow.community.ragflow.tools import _RAGFlowRetrievalSettings


@pytest.mark.anyio
async def test_document_client_upload_list_and_parse():
    async def handler(request):
        assert request.headers["Authorization"] == "Bearer secret"
        if request.method == "GET":
            assert request.url.params["page"] == "2"
            assert request.url.params["page_size"] == "20"
            return httpx.Response(200, json={"code": 0, "data": {"docs": [{"id": "doc1", "name": "notes.txt"}], "total": 21}})
        if request.url.path.endswith("/chunks"):
            assert request.content == b'{"document_ids":["doc1"]}'
            return httpx.Response(200, json={"code": 0})
        assert b'name="file"; filename="notes.txt"' in request.content
        assert b"hello knowledge" in request.content
        return httpx.Response(200, json={"code": 0, "data": [{"id": "doc1", "name": "notes.txt"}]})

    client = RAGFlowClient(base_url="http://ragflow.test", api_key="secret", transport=httpx.MockTransport(handler))
    assert (await client.upload_document("ds1", filename="notes.txt", content=b"hello knowledge", content_type="text/plain"))[0]["id"] == "doc1"
    assert (await client.list_documents("ds1", page=2, page_size=20))["total"] == 21
    await client.parse_documents("ds1", ["doc1"])


@pytest.fixture
def client(monkeypatch):
    settings = _RAGFlowRetrievalSettings(base_url="http://ragflow.test", api_key="private-key", datasets=["ds1"])
    remote = SimpleNamespace(
        list_datasets=AsyncMock(return_value=[{"id": "ds1", "name": "Team knowledge", "document_count": 1, "secret": "private-key"}, {"id": "ds2", "name": "Excluded"}]),
        list_documents=AsyncMock(return_value={"docs": [{"id": "doc1", "name": "notes.txt", "run": "UNSTART", "progress": 0, "size": 5}], "total": 1}),
        upload_document=AsyncMock(return_value=[{"id": "doc1", "name": "notes.txt", "run": "UNSTART"}]),
        parse_documents=AsyncMock(),
        create_dataset=AsyncMock(return_value={"id": "ds3", "name": "New"}),
    )
    monkeypatch.setattr(kb, "_build_client", lambda _: remote)
    monkeypatch.setattr(
        kb, "get_app_config", lambda: SimpleNamespace(authorization=SimpleNamespace(enabled=False), get_tool_config=lambda _: SimpleNamespace(use="deerflow.community.ragflow.tools:knowledge_search_tool", model_extra=settings.model_dump()))
    )
    app = FastAPI()
    app.include_router(kb.router)

    @app.middleware("http")
    async def identity(request, call_next):
        role = request.headers.get("x-role", "admin")
        request.state.auth_source = request.headers.get("x-source", "session")
        if role != "anonymous":
            request.state.user = SimpleNamespace(id="alice", system_role=role)
        return await call_next(request)

    with TestClient(app) as http:
        yield http, remote, settings


def test_lists_only_allowed_datasets_and_safe_metadata(client):
    http, _, _ = client
    response = http.get("/api/knowledge-base/datasets")
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["datasets"]] == ["ds1"]
    assert "private-key" not in response.text
    assert response.json()["can_upload"] is True
    assert response.json()["can_create"] is False


def test_upload_transfers_bytes_and_starts_parsing(client):
    http, remote, _ = client
    response = http.post("/api/knowledge-base/datasets/ds1/documents", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert response.status_code == 200
    assert response.json()["parsing_started"] is True
    remote.upload_document.assert_awaited_once_with("ds1", filename="notes.txt", content=b"hello", content_type="text/plain")
    remote.parse_documents.assert_awaited_once_with("ds1", ["doc1"])


def test_parse_failure_preserves_upload_success_for_retry(client):
    http, remote, _ = client
    remote.parse_documents.side_effect = RAGFlowConnectionError("private-key")
    response = http.post("/api/knowledge-base/datasets/ds1/documents", files={"file": ("notes.txt", b"hello")})
    assert response.status_code == 200
    assert response.json()["parsing_started"] is False
    assert response.json()["documents"][0]["id"] == "doc1"
    assert "private-key" not in response.text


@pytest.mark.parametrize("suffix,method", [("/documents", "get"), ("/documents", "post"), ("/documents/doc1/parse", "post")])
def test_allowlist_enforced_on_every_dataset_operation(client, suffix, method):
    http, remote, _ = client
    response = getattr(http, method)("/api/knowledge-base/datasets/ds2" + suffix)
    assert response.status_code == 404
    remote.upload_document.assert_not_awaited()
    remote.parse_documents.assert_not_awaited()
    remote.list_documents.assert_not_awaited()


def test_session_and_administrator_required_for_upload_before_body_parsing(client):
    http, remote, _ = client
    for headers, code in [({"x-role": "user"}, 403), ({"x-source": "pat"}, 403), ({"x-role": "anonymous"}, 401)]:
        response = http.post("/api/knowledge-base/datasets/ds1/documents", content=b"invalid form", headers=headers)
        assert response.status_code == code
    remote.upload_document.assert_not_awaited()


def test_upload_rejects_large_empty_multiple_and_path_filenames(client, monkeypatch):
    http, remote, _ = client
    monkeypatch.setattr(kb, "MAX_FILE_BYTES", 5)
    for files, code in [({"file": ("big.txt", b"123456")}, 413), ({"file": ("empty.txt", b"")}, 422), ({"file": ("../bad.txt", b"hi")}, 422), ([("file", ("a.txt", b"a")), ("file", ("b.txt", b"b"))], 400)]:
        assert http.post("/api/knowledge-base/datasets/ds1/documents", files=files).status_code == code
    remote.upload_document.assert_not_awaited()


def test_provider_failure_does_not_expose_credentials(client):
    http, remote, _ = client
    remote.list_datasets.side_effect = RAGFlowConnectionError("private-key")
    response = http.get("/api/knowledge-base/datasets")
    assert response.status_code == 502
    assert "private-key" not in response.text


def test_missing_configuration_is_actionable(client, monkeypatch):
    http, _, _ = client
    monkeypatch.setattr(kb, "get_app_config", lambda: SimpleNamespace(authorization=SimpleNamespace(enabled=False), get_tool_config=lambda _: None))
    response = http.get("/api/knowledge-base/datasets")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "ragflow_not_configured"


def test_create_respects_allowlist_and_admin_boundary(client):
    http, remote, settings = client
    assert http.post("/api/knowledge-base/datasets", json={"name": "New"}).status_code == 403
    settings.datasets = None
    assert http.post("/api/knowledge-base/datasets", json={"name": "New"}, headers={"x-role": "user"}).status_code == 403
    assert http.post("/api/knowledge-base/datasets", json={"name": " New "}).status_code == 200
    remote.create_dataset.assert_awaited_once_with("New")


def test_tool_policy_is_checked_on_each_request_and_fails_closed(client, monkeypatch):
    from deerflow.authz.provider import AuthzDecision

    http, remote, settings = client
    config = SimpleNamespace(authorization=SimpleNamespace(enabled=True), get_tool_config=lambda _: SimpleNamespace(use="deerflow.community.ragflow.tools:knowledge_search_tool", model_extra=settings.model_dump()))
    monkeypatch.setattr(kb, "get_app_config", lambda: config)
    provider = SimpleNamespace(aauthorize=AsyncMock(return_value=AuthzDecision(allow=True)))
    monkeypatch.setattr(kb, "resolve_authorization_provider", lambda _: provider)
    assert http.get("/api/knowledge-base/datasets", headers={"x-role": "user"}).status_code == 200
    request = provider.aauthorize.call_args.args[0]
    assert (request.principal.user_id, request.principal.role, request.resource, request.target) == ("alice", "user", "tool", "knowledge_search")
    remote.list_datasets.reset_mock()
    provider.aauthorize.return_value = AuthzDecision(allow=False)
    assert http.get("/api/knowledge-base/datasets", headers={"x-role": "user"}).status_code == 403
    provider.aauthorize.side_effect = RuntimeError("policy unavailable")
    assert http.get("/api/knowledge-base/datasets").status_code == 403
    remote.list_datasets.assert_not_awaited()


def test_document_parse_checks_membership_and_pagination(client):
    http, remote, _ = client
    response = http.get("/api/knowledge-base/datasets/ds1/documents?page=3&page_size=10")
    assert response.status_code == 200
    remote.list_documents.assert_awaited_with("ds1", page=3, page_size=10)
    assert http.get("/api/knowledge-base/datasets/ds1/documents?page_size=1000").status_code == 422
    assert http.post("/api/knowledge-base/datasets/ds1/documents/foreign/parse").status_code == 404
    remote.parse_documents.assert_not_awaited()
    assert http.post("/api/knowledge-base/datasets/ds1/documents/doc1/parse").status_code == 200


@pytest.mark.parametrize("raw,expected", [("0", "pending"), ("RUNNING", "parsing"), ("DONE", "ready"), ("4", "failed"), ("FAIL", "failed"), ("CANCEL", "cancelled"), ("unexpected", "unknown")])
def test_provider_status_normalization(raw, expected):
    result = kb._document_view({"id": "doc", "run": raw, "progress": float("nan")})
    assert result["status"] == expected
    assert result["progress"] == 0
