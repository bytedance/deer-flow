"""The external sparse service's connectivity probe (spec 2026-09-16 connectivity §3 D1–D3).

The sparse leg's refusal used to be invisible until ingest: `TEISparseEncoder`'s constructor only
checks that an address is *present*, so a wrong port, a service that is not up, or a wrong path all
survived the save and surfaced later as "some chunks failed". This probe makes the same call the
runtime makes and reports **three** states — `ok`, `empty` (reachable, right shape, but no terms
came back: the silent degradation this line exists for) and `unreachable` (everything else, with
its own reason).

Nothing here touches the network: the encoder's transport is stubbed, and what the probe asks for
is asserted to match the runtime's request shape.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import yaml
from _router_auth_helpers import make_authed_test_app
from deerflow_knowledge.routers import rag_config as rag_config_router
from deerflow_knowledge.service import KnowledgeExtensionService
from fastapi.testclient import TestClient

from app.gateway.auth.models import User
from deerflow.config.app_config import reset_app_config

SANDBOX = {"use": "deerflow.sandbox.local:LocalSandboxProvider"}
YAML_RAG = {
    "qdrant_url": "http://qdrant:6333",
    "embedding_model": "yaml-embedding",
    "rerank_model": "yaml-rerank",
    "vlm_model": "yaml-vlm",
    "worker_concurrency": 4,
}

_PROBE = "/api/rag/config/probe-sparse"
_BASE_URL = "http://127.0.0.1:8081"
_FAKE_KEY = "sk-sparse-probe-must-never-come-back"
_SPARSE_PATH = "/embed_sparse"


@pytest.fixture
def config_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "config.yaml").write_text(yaml.safe_dump({"sandbox": SANDBOX, "models": [], "rag": YAML_RAG}), encoding="utf-8")
    (tmp_path / "models_config.json").write_text(json.dumps({"models": []}), encoding="utf-8")
    (tmp_path / "extensions_config.json").write_text(json.dumps({"mcpServers": {}, "skills": {}}), encoding="utf-8")
    (tmp_path / "rag_config.json").write_text(json.dumps({"default_model": "kept"}), encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(tmp_path / "config.yaml"))
    monkeypatch.setenv("DEER_FLOW_MODELS_CONFIG_PATH", str(tmp_path / "models_config.json"))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(tmp_path / "extensions_config.json"))
    monkeypatch.setenv("DEER_FLOW_RAG_CONFIG_PATH", str(tmp_path / "rag_config.json"))
    monkeypatch.delenv("RAG_SPARSE_API_KEY", raising=False)
    reset_app_config()
    yield tmp_path
    reset_app_config()


def _client(*, system_role: str = "admin") -> TestClient:
    app = make_authed_test_app(
        user_factory=lambda: User(
            email=f"{system_role}-sparse-probe-test@example.com",
            password_hash="x",
            system_role=system_role,
            id=uuid4(),
        )
    )
    extension = KnowledgeExtensionService()
    app.include_router(rag_config_router.build_router(extension))
    return TestClient(app)


def _stub_sparse(
    monkeypatch: pytest.MonkeyPatch,
    *,
    rows: list[list[dict[str, object]]] | None = None,
    status: int = 200,
) -> list[httpx.Request]:
    """Answer the TEI `/embed_sparse` call locally; record what the probe asked for.

    ``rows=None`` means "one row with one term" — the healthy answer.
    """
    recorded: list[httpx.Request] = []
    payload = [[{"index": 7, "value": 0.5}]] if rows is None else rows

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        if status != 200:
            return httpx.Response(status, json={"detail": "rejected"})
        return httpx.Response(200, json=payload)

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_async_client(transport=httpx.MockTransport(handler)))
    return recorded


def _stub_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("probe cannot reach the sparse service", request=request)

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_async_client(transport=httpx.MockTransport(handler)))


def _probe(client: TestClient, **overrides: object) -> httpx.Response:
    body = {"sparse_provider": "tei-sparse", "sparse_base_url": _BASE_URL, **overrides}
    return client.post(_PROBE, json=body)


def test_reports_a_reachable_service(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    recorded = _stub_sparse(monkeypatch)

    with _client() as client:
        response = _probe(client)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    # Same shape the runtime sends: one POST to the pinned path, body {"inputs": [...]}.
    assert len(recorded) == 1
    assert str(recorded[0].url) == f"{_BASE_URL}{_SPARSE_PATH}"
    assert json.loads(recorded[0].content.decode()) == {"inputs": ["probe"]}


def test_a_service_that_returns_no_terms_is_empty_not_ok(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    """Reachable and shaped right, but every term list is empty — the silent degradation itself.

    Reporting this as `ok` would say "fine" about a service that quietly removes the sparse half
    from every search; reporting it as `unreachable` would send the admin to the wrong field.
    """
    _stub_sparse(monkeypatch, rows=[[]])

    with _client() as client:
        response = _probe(client)

    assert response.status_code == 200
    assert response.json()["status"] == "empty"


def test_a_malformed_answer_is_unreachable_with_its_reason(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    """A service answering something that is not the pinned shape is not a working service.

    The row count is what the *encoder* pins (`_encode_batch` compares it to the batch), so this
    arrives at the route as an exception — the probe reports it rather than letting a wrong shape
    pass as `ok`.
    """
    _stub_sparse(monkeypatch, rows=[[{"index": 7, "value": 0.5}], [{"index": 8, "value": 0.1}]])

    with _client() as client:
        response = _probe(client)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unreachable"
    assert body["detail"]


def test_an_unreachable_service_is_reported_with_its_reason(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    _stub_unreachable(monkeypatch)

    with _client() as client:
        response = _probe(client)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unreachable"
    assert body["detail"]


def test_a_refused_call_is_unreachable_with_its_status_code(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    _stub_sparse(monkeypatch, status=401)

    with _client() as client:
        response = _probe(client)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unreachable"
    assert "401" in body["detail"]


def test_probe_persists_nothing(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    _stub_sparse(monkeypatch)
    target = config_env / "rag_config.json"
    before = target.read_bytes()

    with _client() as client:
        response = _probe(client)

    # Assert the probe *ran* first: a 404 leaves the file alone too, and that would read as a pass.
    assert response.json()["status"] == "ok"
    assert target.read_bytes() == before


def test_probe_never_echoes_the_key(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    """Assert on a *successful* answer: a 404 body would not contain the key either."""
    _stub_sparse(monkeypatch)

    with _client() as client:
        response = _probe(client, sparse_api_key=_FAKE_KEY)

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert _FAKE_KEY not in response.text


def test_an_unknown_or_empty_provider_is_refused(config_env: Path):
    """This leg has no "let the service decide": `external` requires a concrete allowlisted id."""
    with _client() as client:
        assert _probe(client, sparse_provider="not-a-provider").status_code == 422
        assert _probe(client, sparse_provider="").status_code == 422


def test_probe_requires_admin(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    _stub_sparse(monkeypatch)

    with _client(system_role="user") as client:
        assert _probe(client).status_code == 403
