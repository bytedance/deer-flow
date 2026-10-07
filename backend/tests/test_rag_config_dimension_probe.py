"""The dimension probe and the per-leg connectivity probe (spec 2026-09-26 §3).

Two admin-only, read-only routes back the settings view's 维度 row and its two title dots:

- ``POST /api/rag/config/probe-dimensions`` answers *which* widths the model accepts, in the
  probe family's shape (``status`` + payload + ``detail``, never persisted, never blocking).
- ``POST /api/rag/config/probe-connectivity`` makes one real call per leg and keeps the two
  refusals apart: ``refused``/``unreachable`` (the model never answered) versus
  ``dimension_unavailable`` (it answered, and the width we asked for is not on offer).

Nothing here touches the network: every transport is stubbed, and what went out is asserted.
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

# The real class, captured before any test monkeypatches it: a second stub inside one test
# must wrap the real client, not the previous stub (a lambda captures the patched attribute).
_REAL_ASYNC_CLIENT = httpx.AsyncClient

_DIMENSIONS = "/api/rag/config/probe-dimensions"
_CONNECTIVITY = "/api/rag/config/probe-connectivity"
_FAKE_KEY = "sk-dimension-probe-never-echoed"


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
    for name in ("DASHSCOPE_EMBEDDING_API_KEY", "RAG_EMBEDDING_API_KEY", "DASHSCOPE_RERANK_API_KEY", "RAG_RERANK_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    reset_app_config()
    yield tmp_path
    reset_app_config()


def _client(*, system_role: str = "admin") -> TestClient:
    app = make_authed_test_app(
        user_factory=lambda: User(
            email=f"{system_role}-dimprobe-test@example.com",
            password_hash="x",
            system_role=system_role,
            id=uuid4(),
        )
    )
    extension = KnowledgeExtensionService()
    app.include_router(rag_config_router.build_router(extension))
    return TestClient(app)


def _stub_embedding(monkeypatch: pytest.MonkeyPatch, answer) -> list[httpx.Request]:
    """Answer embedding calls locally; ``answer(dimension) -> (status, width)``.

    The DashScope leg's own shape is used (``output.embeddings`` + ``parameters.dimension``), so
    the assertions see exactly what the runtime client would send.
    """
    recorded: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        body = json.loads(request.content)
        asked = (body.get("parameters") or {}).get("dimension")
        status, width = answer(asked)
        if status != 200:
            return httpx.Response(status, json={"code": "InvalidParameter", "message": "refused"})
        # The sparse half rides along because the default sparse source is the provider itself:
        # without it the runtime's own guard would answer before the route ever sees a vector.
        return httpx.Response(200, json={"output": {"embeddings": [{"text_index": 0, "embedding": [0.0] * width, "sparse_embedding": [{"index": 7, "value": 0.5}]}]}})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler)))
    return recorded


def _stub_rerank(monkeypatch: pytest.MonkeyPatch, *, status: int = 200) -> list[httpx.Request]:
    recorded: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        if status != 200:
            return httpx.Response(status, json={"message": "no"})
        return httpx.Response(200, json={"results": [{"index": 0, "relevance_score": 0.5}]})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler)))
    return recorded


def _stub_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("cannot reach it", request=request)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler)))


def _probe_dimensions(client: TestClient, **overrides: object) -> httpx.Response:
    body = {
        "embedding_provider": "dashscope",
        "embedding_model": "candidate-model",
        "embedding_base_url": "https://dashscope.local",
        "embedding_api_key": _FAKE_KEY,
        **overrides,
    }
    return client.post(_DIMENSIONS, json=body)


# ── probe-dimensions: the three answers, relayed ──────────────────────────


def test_reports_a_tiered_model_with_its_candidates(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    passing = {256, 1024}
    recorded = _stub_embedding(monkeypatch, lambda asked: (200, 1024) if asked is None else ((200, asked) if asked in passing else (400, 0)))

    with _client() as client:
        response = _probe_dimensions(client)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["type"] == "tiered"
    assert body["native"] == 1024
    assert body["values"] == [256, 1024]
    assert body["candidates"], "候选表由后端下发，前端不另抄一份"
    assert body["detail"].strip() != ""
    assert any(json.loads(request.content).get("parameters", {}).get("dimension") == 333 for request in recorded)


def test_reports_a_range_model_with_its_native_width(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    _stub_embedding(monkeypatch, lambda asked: (200, asked if asked is not None else 1536))

    with _client() as client:
        body = _probe_dimensions(client).json()

    assert body["type"] == "range"
    assert body["native"] == 1536
    assert body["values"] == [1536]


def test_reports_a_fixed_model_with_a_single_value(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    _stub_embedding(monkeypatch, lambda asked: (200, 768))

    with _client() as client:
        body = _probe_dimensions(client).json()

    assert body["type"] == "fixed"
    assert body["values"] == [768]


def test_an_unreachable_model_is_reported_as_a_state_not_a_500(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    _stub_unreachable(monkeypatch)

    with _client() as client:
        response = _probe_dimensions(client)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unreachable"
    assert body["detail"].strip() != ""
    assert body["type"] is None


def test_an_unknown_provider_is_refused_before_any_call(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    recorded = _stub_embedding(monkeypatch, lambda asked: (200, 1024))

    with _client() as client:
        assert _probe_dimensions(client, embedding_provider="generic-rerank").status_code == 422
        assert _probe_dimensions(client, embedding_provider="").status_code == 422

    assert recorded == []


def test_the_body_forbids_undeclared_fields(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    _stub_embedding(monkeypatch, lambda asked: (200, 1024))

    with _client() as client:
        assert _probe_dimensions(client, sparse_provider="tei-sparse").status_code == 422


def test_probe_dimensions_persists_nothing_never_echoes_the_key_and_needs_admin(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    _stub_embedding(monkeypatch, lambda asked: (200, 1024))
    before = (config_env / "rag_config.json").read_bytes()

    with _client() as client:
        response = _probe_dimensions(client)
        assert response.status_code == 200
        assert _FAKE_KEY not in response.text
    with _client(system_role="user") as client:
        assert _probe_dimensions(client).status_code == 403

    assert (config_env / "rag_config.json").read_bytes() == before


# ── probe-connectivity: one real call per leg ─────────────────────────────


def _probe_connectivity(client: TestClient, **overrides: object) -> httpx.Response:
    body = {
        "leg": "embedding",
        "provider": "dashscope",
        "model": "candidate-model",
        "base_url": "https://dashscope.local",
        "api_key": _FAKE_KEY,
        **overrides,
    }
    return client.post(_CONNECTIVITY, json=body)


def test_connectivity_ok_carries_the_asked_dimension(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    # 1024 is the width this build can construct (the factory's guard still pins it until Task 4);
    # asking for a width the model *gives* must still go out on the wire and come back ok.
    recorded = _stub_embedding(monkeypatch, lambda asked: (200, asked if asked is not None else 1024))

    with _client() as client:
        response = _probe_connectivity(client, embedding_dimension=1024)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["measured_dimension"] == 1024
    assert json.loads(recorded[0].content)["parameters"]["dimension"] == 1024


def test_a_dimension_the_model_will_not_give_is_its_own_state(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    # 200 answers the call but the width is not the one we asked for (the flash clamp, §3.1).
    _stub_embedding(monkeypatch, lambda asked: (200, 512))

    with _client() as client:
        body = _probe_connectivity(client, embedding_dimension=1024).json()

    assert body["status"] == "dimension_unavailable"
    assert body["measured_dimension"] == 512
    assert "1024" in body["detail"] and "512" in body["detail"]


def test_a_promised_sparse_half_that_did_not_come_is_its_own_state(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    """连得上、凭据对、宽度对，但稀疏那一半没给 —— 这是一个"答案"，不是"没能连上"。

    同一个输入在保存那一刻是 400 + 可执行文案（保存期探针）；连通点此前把它归进
    ``unreachable``（状态词撒谎），现在有自己的一态。
    """
    recorded: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return httpx.Response(200, json={"output": {"embeddings": [{"text_index": 0, "embedding": [0.0] * 1024}]}})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler)))

    with _client() as client:
        body = _probe_connectivity(client, embedding_dimension=1024).json()

    assert body["status"] == "half_missing"
    assert "稀疏" in body["detail"]
    # 可执行的那条出路也在里面（改稀疏来源或换模型），与保存期的文案同源。
    assert "独立稀疏服务" in body["detail"] or "本地 BM25" in body["detail"]


def test_refused_and_unreachable_stay_apart(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    _stub_embedding(monkeypatch, lambda asked: (401, 0))
    with _client() as client:
        assert _probe_connectivity(client).json()["status"] == "refused"

    _stub_unreachable(monkeypatch)
    with _client() as client:
        assert _probe_connectivity(client).json()["status"] == "unreachable"


def test_the_rerank_leg_sends_one_minimal_call_and_has_no_dimension_state(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    recorded = _stub_rerank(monkeypatch)

    with _client() as client:
        body = _probe_connectivity(client, leg="rerank", provider="generic-rerank", base_url="http://rerank.local").json()

    assert body["status"] == "ok"
    assert body["measured_dimension"] is None
    # 悬浮那句只说"能用"：解释"这一腿为什么没有维度这一问"是我们的设计，不是给用户看的。
    assert "连通正常" in body["detail"] and "维度" not in body["detail"]
    assert len(recorded) == 1
    asked = json.loads(recorded[0].content)
    assert asked["query"] == "probe" and asked["documents"] == ["probe"], "query 与唯一 doc 都用探针文本"
    assert recorded[0].url.path == "/rerank"


def test_the_provider_must_come_from_that_legs_allowlist(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    _stub_embedding(monkeypatch, lambda asked: (200, 1024))

    with _client() as client:
        assert _probe_connectivity(client, leg="rerank", provider="openai-compatible").status_code == 422
        assert _probe_connectivity(client, leg="embedding", provider="generic-rerank").status_code == 422


def test_connectivity_never_echoes_the_key_and_needs_admin(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    _stub_embedding(monkeypatch, lambda asked: (200, 1024))

    with _client() as client:
        response = _probe_connectivity(client)
        assert response.json()["status"] == "ok"
        assert _FAKE_KEY not in response.text
    with _client(system_role="user") as client:
        assert _probe_connectivity(client).status_code == 403
