from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.auth.models import User
from app.gateway.deps import get_config
from app.gateway.routers import knowledge


def _config(
    *,
    enabled: bool = True,
    api_key: str | None = "ragflow-secret",
    scope_selection_enabled: bool = False,
    datasets: list[str] | None = None,
    provider: str = "deerflow.community.ragflow.tools:knowledge_search_tool",
) -> SimpleNamespace:
    tool = SimpleNamespace(
        use=provider,
        model_extra={
            "base_url": "http://ragflow.test",
            "api_key": api_key,
            "timeout": 30,
            **({"datasets": datasets} if datasets is not None else {}),
        },
    )
    return SimpleNamespace(
        knowledge_base=SimpleNamespace(
            enabled=enabled,
            scope_selection_enabled=scope_selection_enabled,
        ),
        get_tool_config=lambda name: tool if name == "knowledge_search" else None,
    )


def _user() -> User:
    return User(
        email="router-test@example.com",
        password_hash="x",
        system_role="user",
    )


def _app(
    monkeypatch: pytest.MonkeyPatch,
    client: object,
    *,
    config: SimpleNamespace | None = None,
):
    app = make_authed_test_app(user_factory=_user)
    app.include_router(knowledge.router)
    app.dependency_overrides[get_config] = lambda: config or _config()
    monkeypatch.setattr(
        knowledge,
        "_build_retrieval_client",
        lambda settings: client,
    )
    return app


def _enable_scope_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        knowledge,
        "load_agent_config",
        lambda name, *, user_id: SimpleNamespace(
            name=name,
            tool_groups=["knowledge"],
        ),
    )


def test_retrieval_catalog_enforces_allowlist_and_normalizes_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_scope_catalog(monkeypatch)
    ragflow = SimpleNamespace(
        list_datasets=AsyncMock(
            side_effect=[
                [
                    {
                        "id": "dataset-1",
                        "name": "Policies",
                        "embedding_model": "embed-a",
                        "chunk_count": 3,
                    }
                ],
                [
                    {
                        "id": "dataset-2",
                        "name": "Empty",
                        "embedding_model": "",
                        "chunk_count": 0,
                    }
                ],
            ]
        )
    )
    config = _config(
        scope_selection_enabled=True,
        datasets=["dataset-1", "dataset-2"],
    )

    with TestClient(_app(monkeypatch, ragflow, config=config)) as client:
        response = client.get(
            "/api/knowledge/retrieval-catalog/datasets",
            params={"agent_name": "researcher", "page": 1, "page_size": 20},
        )

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {"id": "dataset-1", "name": "Policies", "selectable": True},
            {"id": "dataset-2", "name": "Empty", "selectable": False},
        ],
        "page": 1,
        "page_size": 20,
        "total": 2,
    }
    assert [call.kwargs["dataset_id"] for call in ragflow.list_datasets.await_args_list] == ["dataset-1", "dataset-2"]


def test_retrieval_catalog_accepts_main_assistant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_scope_catalog(monkeypatch)
    ragflow = SimpleNamespace(
        list_datasets=AsyncMock(
            return_value=[
                {
                    "id": "dataset-1",
                    "name": "Policies",
                    "embedding_model": "embed-a",
                    "chunk_count": 3,
                }
            ]
        )
    )
    config = _config(scope_selection_enabled=True, datasets=["dataset-1"])

    with TestClient(_app(monkeypatch, ragflow, config=config)) as client:
        response = client.get(
            "/api/knowledge/retrieval-catalog/datasets",
            params={"agent_name": "lead_agent"},
        )

    assert response.status_code == 200
    assert response.json()["items"] == [
        {"id": "dataset-1", "name": "Policies", "selectable": True}
    ]


def test_retrieval_catalog_documents_reject_outside_allowlist_without_provider_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_scope_catalog(monkeypatch)
    ragflow = SimpleNamespace(
        list_datasets=AsyncMock(),
        list_documents=AsyncMock(),
    )
    config = _config(scope_selection_enabled=True, datasets=["dataset-1"])

    with TestClient(_app(monkeypatch, ragflow, config=config)) as client:
        response = client.get(
            "/api/knowledge/retrieval-catalog/datasets/dataset-2/documents",
            params={"agent_name": "researcher"},
        )

    assert response.status_code == 404
    ragflow.list_datasets.assert_not_awaited()
    ragflow.list_documents.assert_not_awaited()


def test_retrieval_catalog_documents_marks_only_searchable_files_selectable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_scope_catalog(monkeypatch)
    ragflow = SimpleNamespace(
        list_datasets=AsyncMock(
            return_value=[
                {
                    "id": "dataset-1",
                    "name": "Policies",
                    "embedding_model": "embed-a",
                    "chunk_count": 3,
                }
            ]
        ),
        list_documents=AsyncMock(
            return_value={
                "code": 0,
                "data": {
                    "total": 3,
                    "docs": [
                        {
                            "id": "doc-1",
                            "name": "Ready.pdf",
                            "run": "DONE",
                            "chunk_count": 2,
                        },
                        {
                            "id": "doc-2",
                            "name": "Parsing.pdf",
                            "run": "RUNNING",
                            "chunk_count": 0,
                        },
                        {
                            "id": "doc-3",
                            "name": "Empty.pdf",
                            "run": "DONE",
                            "chunk_count": 0,
                        },
                    ],
                },
            }
        ),
    )
    config = _config(scope_selection_enabled=True, datasets=["dataset-1"])

    with TestClient(_app(monkeypatch, ragflow, config=config)) as client:
        response = client.get(
            "/api/knowledge/retrieval-catalog/datasets/dataset-1/documents",
            params={
                "agent_name": "researcher",
                "search": "ready",
                "page": 2,
                "page_size": 10,
            },
        )

    assert response.status_code == 200
    assert response.json()["items"] == [
        {"id": "doc-1", "name": "Ready.pdf", "selectable": True},
        {"id": "doc-2", "name": "Parsing.pdf", "selectable": False},
        {"id": "doc-3", "name": "Empty.pdf", "selectable": False},
    ]
    ragflow.list_documents.assert_awaited_once_with(
        "dataset-1",
        params=[("page", "2"), ("page_size", "10"), ("keywords", "ready")],
    )


@pytest.mark.parametrize(
    "config",
    [
        _config(enabled=False, scope_selection_enabled=True),
        _config(scope_selection_enabled=False),
        _config(
            scope_selection_enabled=True,
            provider=("deerflow.community.lightrag.tools:knowledge_search_tool"),
        ),
    ],
)
def test_retrieval_catalog_fails_closed_when_capability_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    config: SimpleNamespace,
) -> None:
    _enable_scope_catalog(monkeypatch)
    ragflow = SimpleNamespace(list_datasets=AsyncMock())

    with TestClient(_app(monkeypatch, ragflow, config=config)) as client:
        response = client.get(
            "/api/knowledge/retrieval-catalog/datasets",
            params={"agent_name": "researcher"},
        )

    assert response.status_code == 409
    ragflow.list_datasets.assert_not_awaited()


def test_management_routes_are_not_exposed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TestClient(_app(monkeypatch, SimpleNamespace())) as client:
        assert client.get("/api/knowledge/datasets").status_code == 404
        assert (
            client.post(
                "/api/knowledge/datasets",
                json={"name": "Deferred"},
            ).status_code
            == 404
        )
        assert client.get("/api/knowledge/events").status_code == 404
