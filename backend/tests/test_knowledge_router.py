from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.gateway.auth.models import User
from app.gateway.deps import get_config
from app.gateway.knowledge.watcher import KnowledgeEvent
from app.gateway.routers import knowledge
from deerflow.community.ragflow.client import RAGFlowAPIError, RAGFlowConnectionError


def _config(*, enabled: bool = True, api_key: str | None = "ragflow-secret") -> SimpleNamespace:
    return SimpleNamespace(
        knowledge_base=SimpleNamespace(
            enabled=enabled,
            base_url="http://ragflow.test",
            api_key=SecretStr(api_key) if api_key is not None else None,
            timeout=30,
        )
    )


def _user(*, admin: bool = False) -> User:
    return User(
        email="router-test@example.com",
        password_hash="x",
        system_role="admin" if admin else "user",
    )


def _app(monkeypatch: pytest.MonkeyPatch, client: object, *, config: SimpleNamespace | None = None, admin: bool = False):
    app = make_authed_test_app(user_factory=lambda: _user(admin=admin))
    app.include_router(knowledge.router)
    app.dependency_overrides[get_config] = lambda: config or _config()
    monkeypatch.setattr(knowledge, "_build_client", lambda settings: client)
    return app


def test_dataset_and_document_routes_proxy_ragflow_contracts(monkeypatch: pytest.MonkeyPatch) -> None:
    ragflow = SimpleNamespace(
        list_datasets_page=AsyncMock(return_value={"code": 0, "data": [{"id": "dataset-1"}]}),
        create_dataset=AsyncMock(return_value={"code": 0, "data": {"id": "dataset-1"}}),
        list_documents=AsyncMock(return_value={"code": 0, "data": {"docs": [], "total": 0}}),
        parse_documents=AsyncMock(return_value={"code": 0, "data": True}),
    )

    with TestClient(_app(monkeypatch, ragflow)) as client:
        datasets = client.get("/api/knowledge/datasets?page=2&page_size=20")
        created = client.post("/api/knowledge/datasets", json={"name": "Policies", "description": "Shared"})
        documents = client.get("/api/knowledge/datasets/dataset-1/documents?page=3&keywords=leave")
        parsed = client.post(
            "/api/knowledge/datasets/dataset-1/parse",
            json={"document_ids": ["document-1"]},
        )

    assert datasets.json() == {"code": 0, "data": [{"id": "dataset-1"}]}
    assert created.json() == {"code": 0, "data": {"id": "dataset-1"}}
    assert documents.json() == {"code": 0, "data": {"docs": [], "total": 0}}
    assert parsed.json() == {"code": 0, "data": True}
    ragflow.list_datasets_page.assert_awaited_once_with(params=[("page", "2"), ("page_size", "20")])
    ragflow.create_dataset.assert_awaited_once_with({"name": "Policies", "description": "Shared"})
    ragflow.list_documents.assert_awaited_once_with(
        "dataset-1",
        params=[("page", "3"), ("keywords", "leave")],
    )
    ragflow.parse_documents.assert_awaited_once_with("dataset-1", ["document-1"])


def test_disabled_or_unconfigured_integration_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    ragflow = SimpleNamespace(list_datasets_page=AsyncMock())

    with TestClient(_app(monkeypatch, ragflow, config=_config(enabled=False))) as client:
        disabled = client.get("/api/knowledge/datasets")
    with TestClient(_app(monkeypatch, ragflow, config=_config(api_key=None))) as client:
        missing_key = client.get("/api/knowledge/datasets")

    assert disabled.status_code == 503
    assert missing_key.status_code == 503
    assert "API Key" not in disabled.text
    assert "API Key" in missing_key.text
    ragflow.list_datasets_page.assert_not_awaited()


def test_dataset_id_rejects_upstream_path_injection(monkeypatch: pytest.MonkeyPatch) -> None:
    ragflow = SimpleNamespace(list_documents=AsyncMock())

    with TestClient(_app(monkeypatch, ragflow)) as client:
        response = client.get("/api/knowledge/datasets/dataset%3Fpage=999/documents")

    assert response.status_code == 422
    ragflow.list_documents.assert_not_awaited()


def test_proxy_errors_use_rfc_statuses_and_redact_api_key(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    rejected = SimpleNamespace(list_datasets_page=AsyncMock(side_effect=RAGFlowAPIError("invalid credential ragflow-secret", code=101)))
    unreachable = SimpleNamespace(list_datasets_page=AsyncMock(side_effect=RAGFlowConnectionError("ragflow-secret refused")))

    with TestClient(_app(monkeypatch, rejected)) as client:
        rejected_response = client.get("/api/knowledge/datasets")
    with TestClient(_app(monkeypatch, unreachable)) as client:
        unreachable_response = client.get("/api/knowledge/datasets")

    assert rejected_response.status_code == 400
    assert "invalid credential" in rejected_response.text
    assert unreachable_response.status_code == 502
    assert "ragflow-secret" not in rejected_response.text
    assert "ragflow-secret" not in unreachable_response.text
    assert "ragflow-secret" not in caplog.text


def test_delete_routes_require_admin_and_forward_only_explicit_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    ragflow = SimpleNamespace(
        delete_dataset=AsyncMock(return_value={"code": 0, "data": True}),
        delete_documents=AsyncMock(return_value={"code": 0, "data": True}),
    )

    with TestClient(_app(monkeypatch, ragflow, admin=False)) as client:
        denied_dataset = client.delete("/api/knowledge/datasets/dataset-1")
        denied_documents = client.request(
            "DELETE",
            "/api/knowledge/datasets/dataset-1/documents",
            json={"ids": ["document-1"]},
        )

    assert denied_dataset.status_code == 403
    assert denied_documents.status_code == 403
    ragflow.delete_dataset.assert_not_awaited()
    ragflow.delete_documents.assert_not_awaited()

    with TestClient(_app(monkeypatch, ragflow, admin=True)) as client:
        rejected_delete_all = client.request(
            "DELETE",
            "/api/knowledge/datasets/dataset-1/documents",
            json={"ids": []},
        )
        deleted_dataset = client.delete("/api/knowledge/datasets/dataset-1")
        deleted_documents = client.request(
            "DELETE",
            "/api/knowledge/datasets/dataset-1/documents",
            json={"ids": ["document-1"]},
        )

    assert rejected_delete_all.status_code == 422
    assert deleted_dataset.status_code == 200
    assert deleted_documents.status_code == 200
    ragflow.delete_dataset.assert_awaited_once_with("dataset-1")
    ragflow.delete_documents.assert_awaited_once_with("dataset-1", ["document-1"])


class _StreamingRAGFlow:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bytes]] = []

    async def upload_documents(
        self,
        dataset_id: str,
        *,
        content_type: str,
        content: AsyncIterator[bytes],
    ) -> dict:
        body = b"".join([chunk async for chunk in content])
        self.calls.append((dataset_id, content_type, body))
        return {"code": 0, "data": [{"id": "document-1"}]}

    async def parse_documents(self, dataset_id: str, document_ids: list[str]) -> dict:
        return {"code": 0, "data": {"dataset_id": dataset_id, "document_ids": document_ids}}


def test_upload_streams_original_multipart_without_uploadfile_spooling(monkeypatch: pytest.MonkeyPatch) -> None:
    ragflow = _StreamingRAGFlow()

    with TestClient(_app(monkeypatch, ragflow)) as client:
        response = client.post(
            "/api/knowledge/datasets/dataset-1/documents",
            files=[("file", ("notes.txt", b"hello", "text/plain"))],
        )

    assert response.status_code == 200
    assert response.json() == {"code": 0, "data": [{"id": "document-1"}]}
    assert len(ragflow.calls) == 1
    dataset_id, content_type, body = ragflow.calls[0]
    assert dataset_id == "dataset-1"
    assert content_type.startswith("multipart/form-data; boundary=")
    assert b'filename="notes.txt"' in body
    assert b"hello" in body
    assert "UploadFile" not in str(knowledge.upload_documents.__annotations__)


@pytest.mark.parametrize(
    ("limit_name", "files"),
    [
        ("_MAX_UPLOAD_FILE_BYTES", [("file", ("large.txt", b"1234", "text/plain"))]),
        (
            "_MAX_UPLOAD_FILES",
            [
                ("file", ("one.txt", b"1", "text/plain")),
                ("file", ("two.txt", b"2", "text/plain")),
            ],
        ),
    ],
)
def test_upload_rejects_per_file_and_file_count_limits(
    monkeypatch: pytest.MonkeyPatch,
    limit_name: str,
    files: list[tuple[str, tuple[str, bytes, str]]],
) -> None:
    ragflow = _StreamingRAGFlow()
    monkeypatch.setattr(knowledge, limit_name, 3 if limit_name.endswith("BYTES") else 1)

    with TestClient(_app(monkeypatch, ragflow)) as client:
        response = client.post("/api/knowledge/datasets/dataset-1/documents", files=files)

    assert response.status_code == 413
    assert "ragflow-secret" not in response.text


def test_upload_rejects_total_request_limit_before_proxying(monkeypatch: pytest.MonkeyPatch) -> None:
    ragflow = _StreamingRAGFlow()
    monkeypatch.setattr(knowledge, "_MAX_UPLOAD_REQUEST_BYTES", 8)

    with TestClient(_app(monkeypatch, ragflow)) as client:
        response = client.post(
            "/api/knowledge/datasets/dataset-1/documents",
            files=[("file", ("notes.txt", b"hello", "text/plain"))],
        )

    assert response.status_code == 413
    assert ragflow.calls == []


def test_upload_requires_multipart_form_data(monkeypatch: pytest.MonkeyPatch) -> None:
    ragflow = _StreamingRAGFlow()

    with TestClient(_app(monkeypatch, ragflow)) as client:
        response = client.post(
            "/api/knowledge/datasets/dataset-1/documents",
            content=b"not multipart",
            headers={"content-type": "application/octet-stream"},
        )

    assert response.status_code == 400
    assert ragflow.calls == []


def test_upload_and_parse_explicitly_wake_watcher(monkeypatch: pytest.MonkeyPatch) -> None:
    ragflow = _StreamingRAGFlow()
    watcher = MagicMock()
    monkeypatch.setattr(knowledge, "get_knowledge_watcher", lambda: watcher)

    with TestClient(_app(monkeypatch, ragflow)) as client:
        uploaded = client.post(
            "/api/knowledge/datasets/dataset-1/documents",
            files=[("file", ("notes.txt", b"hello", "text/plain"))],
        )
        parsed = client.post(
            "/api/knowledge/datasets/dataset-1/parse",
            json={"document_ids": ["document-1"]},
        )

    assert uploaded.status_code == 200
    assert parsed.status_code == 200
    assert watcher.wake.call_count == 2


class _OneEventWatcher:
    async def subscribe(self):
        yield KnowledgeEvent(
            event="dataset_parsing_progress",
            data={"dataset_id": "dataset-1", "running_count": 1},
        )


def test_events_route_streams_named_sse_events(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(knowledge, "get_knowledge_watcher", lambda: _OneEventWatcher())
    ragflow = SimpleNamespace()

    with TestClient(_app(monkeypatch, ragflow)) as client:
        response = client.get("/api/knowledge/events")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert "event: dataset_parsing_progress\n" in response.text
    assert 'data: {"dataset_id":"dataset-1","running_count":1}\n\n' in response.text
