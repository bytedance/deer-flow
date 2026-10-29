from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import quote

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.auth.models import User
from app.gateway.deps import get_config
from app.gateway.routers import knowledge
from deerflow.extensions import ExtensionRegistry, reset_loaded_extensions
from deerflow.knowledge import KnowledgeCapabilities, RetrievalCatalogPage
from deerflow.knowledge.providers import GENERIC_KNOWLEDGE_TOOL


def setup_provider(operations):
    provider = SimpleNamespace(
        capabilities=KnowledgeCapabilities(operations=frozenset(operations)),
        search=AsyncMock(),
        search_scoped=AsyncMock(),
        catalog=AsyncMock(return_value=RetrievalCatalogPage(items=[{"id": "tenant:private/kb", "name": "Private", "selectable": True}], page=1, page_size=20, total=1)),
        documents=AsyncMock(return_value=RetrievalCatalogPage(items=[], page=1, page_size=20, total=0)),
    )
    registry = ExtensionRegistry()
    with registry.attributed_to("test:install"):
        registry.knowledge_provider("test", provider)
    user = User(email="catalog@example.com", password_hash="x", system_role="user")
    app = make_authed_test_app(user_factory=lambda: user, bind_current_user=True)
    app.state.extensions = registry.build()
    app.include_router(knowledge.router)
    tool = SimpleNamespace(use=GENERIC_KNOWLEDGE_TOOL, model_extra={"provider": "test"})
    config = SimpleNamespace(knowledge_base=SimpleNamespace(enabled=True, scope_selection_enabled=True), get_tool_config=lambda _: tool)
    app.dependency_overrides[get_config] = lambda: config
    return app, provider, user


@pytest.fixture(autouse=True)
def no_singleton_provider():
    reset_loaded_extensions()
    yield
    reset_loaded_extensions()


def test_catalog_uses_app_snapshot_and_authenticated_identity():
    app, provider, user = setup_provider({"search", "catalog", "dataset_filter"})
    with TestClient(app) as client:
        cap = client.get("/api/knowledge/capabilities?agent_name=lead_agent")
        response = client.get("/api/knowledge/retrieval-catalog/datasets?agent_name=lead_agent&user_id=mallory")
    assert cap.json() == {"operations": ["catalog", "dataset_filter", "search"], "scope_selection_enabled": True}
    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == "tenant:private/kb"
    context = provider.catalog.await_args.kwargs["context"]
    assert context.user_id == str(user.id)
    assert context.user_id != "mallory"
    assert context.agent_name == "lead_agent"
    assert context.scope is None


def test_search_only_provider_is_available_without_catalog():
    app, provider, _ = setup_provider({"search"})
    with TestClient(app) as client:
        response = client.get("/api/knowledge/capabilities?agent_name=lead_agent")
        assert response.json() == {"operations": ["search"], "scope_selection_enabled": False}
        assert client.get("/api/knowledge/retrieval-catalog/datasets?agent_name=lead_agent").status_code == 409
    provider.catalog.assert_not_awaited()


def test_catalog_without_document_capability_never_calls_documents():
    app, provider, _ = setup_provider({"search", "catalog", "dataset_filter"})
    with TestClient(app) as client:
        response = client.get("/api/knowledge/retrieval-catalog/datasets/private/documents?agent_name=lead_agent")
    assert response.status_code == 409
    provider.documents.assert_not_awaited()


def test_provider_opaque_ids_are_not_constrained_to_ragflow_uuid_syntax():
    app, provider, _ = setup_provider({"search", "catalog", "documents", "dataset_filter", "document_filter"})
    dataset_id = "tenant:private/kb with spaces"
    with TestClient(app) as client:
        response = client.get(f"/api/knowledge/retrieval-catalog/datasets/{quote(dataset_id, safe='')}/documents?agent_name=lead_agent")
    assert response.status_code == 200
    assert provider.documents.await_args.args == (dataset_id,)


@pytest.mark.parametrize(("length", "status"), [(256, 200), (257, 422)])
def test_document_route_preserves_bounded_opaque_id_or_rejects_it(length, status):
    app, provider, _ = setup_provider({"search", "catalog", "documents", "dataset_filter", "document_filter"})
    dataset_id = "😀" * length
    with TestClient(app) as client:
        response = client.get(f"/api/knowledge/retrieval-catalog/datasets/{quote(dataset_id, safe='')}/documents?agent_name=lead_agent")
    assert response.status_code == status
    if status == 200:
        assert provider.documents.await_args.args == (dataset_id,)
    else:
        provider.documents.assert_not_awaited()


@pytest.mark.parametrize(("error", "status"), [(PermissionError("credential=secret"), 403), (FileNotFoundError("private"), 404), (RuntimeError("credential=secret"), 502)])
def test_catalog_errors_are_safe_and_do_not_retry(error, status):
    app, provider, _ = setup_provider({"search", "catalog", "dataset_filter"})
    provider.catalog.side_effect = error
    with TestClient(app) as client:
        response = client.get("/api/knowledge/retrieval-catalog/datasets?agent_name=lead_agent")
    assert response.status_code == status
    assert "secret" not in response.text
    assert provider.catalog.await_count == 1
    provider.search.assert_not_awaited()


def test_malformed_catalog_cannot_expose_provider_fields():
    app, provider, _ = setup_provider({"search", "catalog", "dataset_filter"})
    provider.catalog.return_value = {"items": [], "page": 1, "page_size": 20, "total": 0, "api_key": "secret"}
    with TestClient(app) as client:
        response = client.get("/api/knowledge/retrieval-catalog/datasets?agent_name=lead_agent")
    assert response.status_code == 502
    assert "secret" not in response.text
