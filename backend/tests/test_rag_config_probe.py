"""The embedding-capability probe (spec 2026-09-16 §3 D3).

The guard added on 2026-09-16 judges "can this provider supply the sparse half" at the
*provider* level, but the truth is per *model*: on one platform some embedding models return
dense + sparse in a single call and some return dense only. The probe answers that one question
by making the same call the pipeline makes, and reports **three** states — with `unverifiable`
reserved for everything that is not an answer (unreachable, unauthenticated, wrong dimension),
because "could not check" must never be read as "cannot do it".

Nothing here touches the network: the DashScope client's transport is stubbed, and the probe's
own request shape is asserted to match the runtime's.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import yaml
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.auth.models import User
from app.gateway.routers import rag_config as rag_config_router
from deerflow.config.app_config import reset_app_config

SANDBOX = {"use": "deerflow.sandbox.local:LocalSandboxProvider"}
YAML_RAG = {
    "qdrant_url": "http://qdrant:6333",
    "embedding_model": "yaml-embedding",
    "rerank_model": "yaml-rerank",
    "vlm_model": "yaml-vlm",
    "worker_concurrency": 4,
}

_PROBE = "/api/rag/config/probe-embedding"
_FAKE_KEY = "sk-probe-must-never-come-back"


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
    for name in ("DASHSCOPE_EMBEDDING_API_KEY", "RAG_EMBEDDING_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    reset_app_config()
    yield tmp_path
    reset_app_config()


def _client(*, system_role: str = "admin") -> TestClient:
    app = make_authed_test_app(
        user_factory=lambda: User(
            email=f"{system_role}-probe-test@example.com",
            password_hash="x",
            system_role=system_role,
            id=uuid4(),
        )
    )
    app.include_router(rag_config_router.router)
    return TestClient(app)


def _stub_dashscope(monkeypatch: pytest.MonkeyPatch, *, dense: int = 1024, sparse: bool = True, status: int = 200) -> list[httpx.Request]:
    """Answer the DashScope embedding call locally; record what the probe asked for."""
    recorded: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        if status != 200:
            return httpx.Response(status, json={"code": "InvalidApiKey", "message": "rejected"})
        item: dict[str, object] = {"text_index": 0, "embedding": [0.0] * dense}
        if sparse:
            item["sparse_embedding"] = [{"index": 7, "value": 0.5}]
        return httpx.Response(200, json={"output": {"embeddings": [item]}})

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_async_client(transport=httpx.MockTransport(handler)))
    return recorded


def _stub_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("probe cannot reach the platform", request=request)

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_async_client(transport=httpx.MockTransport(handler)))


def _probe(client: TestClient, **overrides: object) -> httpx.Response:
    body = {
        "embedding_provider": "dashscope",
        "embedding_model": "candidate-model",
        "embedding_api_key": _FAKE_KEY,
        **overrides,
    }
    return client.post(_PROBE, json=body)


# ── the three states ──────────────────────────────────────────────────────


def test_reports_a_model_that_returns_the_sparse_half(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    recorded = _stub_dashscope(monkeypatch, sparse=True)

    with _client() as client:
        response = _probe(client)

    assert response.status_code == 200
    assert response.json()["status"] == "supported"
    # The probe asks the same question the pipeline asks: native path, both halves requested.
    assert len(recorded) == 1
    assert recorded[0].url.path == "/api/v1/services/embeddings/text-embedding/text-embedding"
    asked = json.loads(recorded[0].content)
    assert asked["parameters"]["output_type"] == "dense&sparse"
    assert asked["model"] == "candidate-model"


def test_reports_a_model_that_returns_dense_only(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    _stub_dashscope(monkeypatch, sparse=False)

    with _client() as client:
        response = _probe(client)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unsupported"
    # The admin is told what to do instead, in the same words the UI and the runtime use.
    assert "独立稀疏服务" in body["detail"]
    assert "本地 BM25" in body["detail"]
    # And the verdict came from the run-time guard itself (spec §3 D5), not from a second,
    # independently written reading of the response — the two must not drift apart.
    assert "返回了空的稀疏向量" in body["detail"]


def test_an_unreachable_platform_is_unverifiable_not_unsupported(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    _stub_unreachable(monkeypatch)

    with _client() as client:
        response = _probe(client)

    assert response.status_code == 200
    body = response.json()
    # "Could not check" must never be reported as "cannot do it": a network outage would
    # otherwise refuse a configuration that works.
    assert body["status"] == "unverifiable"
    assert body["detail"].strip() != ""


def test_a_refused_call_is_unverifiable_with_its_own_reason(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    """A 401 is not an answer to the sparse question, so it must not be reported as one.

    (A wrong *dimension* cannot happen on this path: the only embedding provider the probe ever
    calls pins its dimension in the request, so no guard wraps it — and the other one is
    dense-only by allowlist, which the probe answers from the list without calling at all.)
    """
    _stub_dashscope(monkeypatch, status=401)

    with _client() as client:
        response = _probe(client)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unverifiable"
    assert "401" in body["detail"]


def test_a_dense_only_provider_is_answered_without_calling_the_platform(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    """The allowlist already knows this one, so the probe answers from the list, not the wire."""
    recorded = _stub_dashscope(monkeypatch)

    with _client() as client:
        response = _probe(client, embedding_provider="openai-compatible", embedding_base_url="http://x/v1")

    assert response.status_code == 200
    assert response.json()["status"] == "unsupported"
    assert recorded == []


# ── observational only ────────────────────────────────────────────────────


def test_probe_persists_nothing(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    _stub_dashscope(monkeypatch)
    before = (config_env / "rag_config.json").read_bytes()

    with _client() as client:
        assert _probe(client).status_code == 200

    assert (config_env / "rag_config.json").read_bytes() == before


def test_probe_never_echoes_the_key(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    _stub_dashscope(monkeypatch)

    with _client() as client:
        response = _probe(client)

    # A successful probe, so this asserts about the *answer* rather than about some 404 body.
    assert response.json()["status"] == "supported"
    assert _FAKE_KEY not in response.text


def test_probe_requires_admin(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    _stub_dashscope(monkeypatch)

    with _client(system_role="user") as client:
        assert _probe(client).status_code == 403
