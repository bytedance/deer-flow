"""The save-time embedding probe (spec 2026-09-17 save-time probe §3 D1–D5).

``build_embedder`` only *wraps*; both the width verdict and the empty-sparse verdict used to
fire on the first real ingest. So a PUT could persist a configuration that cannot work, and
the admin met it days later as "some chunks failed" (G1) or as a dense-only model quietly
asked to supply the sparse half (G2). The PUT now makes one real call **before** it writes,
and splits the outcome in two:

- an **answer** ("this cannot work") ⇒ 400, in the runtime's own words;
- **not getting an answer** (unreachable, timed out, credentials refused) ⇒ 200 plus a
  ``warning`` — changing the configuration is often exactly what an admin does to escape a
  broken one, so refusing the write would block the only exit.

The call is made only when one of the six embedding settings really changes, so an unrelated
edit (rerank, parse, …) keeps today's latency. ``warning`` is **always present** and ``null``
when there is nothing to say (deliberately not ``exclude_none``: that is recursive and would
also strip every ``null`` inside ``config``).

Nothing here touches the network: the provider clients' transport is stubbed and the stub
records what the probe asked for.
"""

from __future__ import annotations

import asyncio
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
from deerflow.config.app_config import get_app_config, reset_app_config
from deerflow.config.rag_config_file import MASKED_SECRET
from deerflow.knowledge.embedder import RagConfigurationError
from deerflow.knowledge.embedder_factory import build_embedder

SANDBOX = {"use": "deerflow.sandbox.local:LocalSandboxProvider"}

#: The names this file's payloads and ``YAML_RAG`` declare must exist as entries: since spec
#: 2026-09-23 D10.1 a save refuses a declared name with no entry. YAML entries on purpose --
#: the strict missing-key/address rule covers UI-managed entries only.
_YAML_MODELS = [{"name": name, "use": "langchain_openai:ChatOpenAI", "model": "gpt-test", "api_key": "test-key", "base_url": "https://yaml.example/v1"} for name in ("rag-default", "yaml-vlm")]

YAML_RAG = {
    "qdrant_url": "http://qdrant:6333",
    "embedding_model": "yaml-embedding",
    "embedding_base_url": "http://127.0.0.1:8123/v1",
    "rerank_model": "yaml-rerank",
    "rerank_base_url": "http://127.0.0.1:8124",
    "vlm_model": "yaml-vlm",
    "worker_concurrency": 4,
}

_PUT = "/api/rag/config"
_EMBEDDING_URL = "http://127.0.0.1:8123/v1"
_SPARSE_PATH = "/embed_sparse"

#: What a wrong dense width must say — the runtime guard's own sentence (D5: the save-time
#: refusal reuses it rather than growing a second wording for the same fact).
_WRONG_WIDTH_MESSAGE = (
    "嵌入模型返回 2560 维，而当前生效宽度是 1024 维 ⇒ 拒绝启用。 / The embedding model returned 2560 dimensions while the width in force is 1024 — refusing to enable it. "
    "请改用该模型支持的维度（到「设置 → 模型 → 功能模型 → 高级设置 → 维度」改，改值会触发全库重建），或换模型。 / Use a model that returns the width in force "
    "(change it under Settings → Models → Functional models → Advanced → Dimension; a change rebuilds every collection), or switch models."
)

#: Anything outside the six watched fields must not make the probe fire (D2).
_UNRELATED = {"rerank_model": "ui-rerank"}

_INVALID_WIDTH_PAYLOAD = {
    "embedding_provider": "openai-compatible",
    "embedding_base_url": _EMBEDDING_URL,
    "embedding_model": "stub-embedding",
    "embedding_sparse_source": "bm25",
}


@pytest.fixture
def config_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump({"sandbox": SANDBOX, "models": _YAML_MODELS, "rag": YAML_RAG}),
        encoding="utf-8",
    )
    (tmp_path / "models_config.json").write_text(json.dumps({"models": []}), encoding="utf-8")
    (tmp_path / "extensions_config.json").write_text(json.dumps({"mcpServers": {}, "skills": {}}), encoding="utf-8")
    (tmp_path / "rag_config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(tmp_path / "config.yaml"))
    monkeypatch.setenv("DEER_FLOW_MODELS_CONFIG_PATH", str(tmp_path / "models_config.json"))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(tmp_path / "extensions_config.json"))
    monkeypatch.setenv("DEER_FLOW_RAG_CONFIG_PATH", str(tmp_path / "rag_config.json"))
    # Keep the probe's credential resolution independent of the ambient environment.
    for name in ("DASHSCOPE_EMBEDDING_API_KEY", "RAG_EMBEDDING_API_KEY", "RAG_SPARSE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    reset_app_config()
    yield tmp_path
    reset_app_config()


def _client(*, system_role: str = "admin") -> TestClient:
    app = make_authed_test_app(
        user_factory=lambda: User(
            email=f"{system_role}-save-probe-test@example.com",
            password_hash="x",
            system_role=system_role,
            id=uuid4(),
        )
    )
    app.include_router(rag_config_router.router)
    client = TestClient(app)
    # The gateway always wires a knowledge service; a save that changes the embedding
    # identity now starts a rebuild off it (spec 2026-10-04 D3).
    from types import SimpleNamespace

    client.app.state.knowledge_service = SimpleNamespace(store=object(), vector_store=object())
    return client


@pytest.fixture(autouse=True)
def _reembed_libraries_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    """A save that changes the embedding identity starts a rebuild (spec 2026-10-04 D3).

    These cases are about the save-time probe, not the rebuild: give them a trivial instant
    success so the flip settles quietly, and forget the verdict between cases so one case's
    still-running task cannot 409 the next one's save.
    """
    from app.gateway.services import rag_reembed as reembed_module

    async def _noop(store, *, vector_store, embedder):
        return {}

    async def _noop_marks(store):
        return {}

    async def _noop_delta(store, *, vector_store, embedder, marks, main_complete):
        return 0

    monkeypatch.setattr(reembed_module, "reembed_libraries", _noop)
    monkeypatch.setattr(reembed_module, "collect_window_marks", _noop_marks)
    monkeypatch.setattr(reembed_module, "reembed_window_delta", _noop_delta)
    reembed_module.reset_state()
    yield
    reembed_module.reset_state()


def _settled_reembed(client: TestClient) -> dict | None:
    """Wait for the rebuild a save started, so a file assertion reads the flipped file."""
    import time

    state = client.get("/api/rag/config").json()["reembed"]
    for _ in range(100):
        if state is None or state["state"] != "running":
            return state
        time.sleep(0.02)
        state = client.get("/api/rag/config").json()["reembed"]
    raise AssertionError(f"reembed never settled: {state}")


def _stub(monkeypatch: pytest.MonkeyPatch, handler) -> list[httpx.Request]:
    """Answer every provider call locally; the recorded requests are the probe's call log."""
    recorded: list[httpx.Request] = []

    def dispatch(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return handler(request)

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_async_client(transport=httpx.MockTransport(dispatch)))
    return recorded


def _openai_body(width: int) -> dict:
    return {"data": [{"index": 0, "embedding": [0.0] * width}]}


def _dashscope_body(sparse: list[dict] | None = None) -> dict:
    row = {"text_index": 0, "embedding": [0.0] * 1024, "sparse_embedding": sparse or []}
    return {"output": {"embeddings": [row]}}


def _healthy(width: int = 1024):
    """A dense-only provider answering with ``width`` dimensions."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_openai_body(width))

    return handler


def _dense_ok_sparse_dead(request: httpx.Request) -> httpx.Response:
    """The dense half connects; the external sparse service does not."""
    if request.url.path == _SPARSE_PATH:
        raise httpx.ConnectError("sparse service is down", request=request)
    return httpx.Response(200, json=_openai_body(1024))


def _dead(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("no route to host", request=request)


def _refused(request: httpx.Request) -> httpx.Response:
    return httpx.Response(401, json={"error": "bad key"})


def _read_rag_json(root: Path) -> dict:
    return json.loads((root / "rag_config.json").read_text(encoding="utf-8"))


# ── an answer: the configuration cannot work ⇒ 400, before anything is written ──


def test_a_wrong_dense_width_is_refused_in_the_runtime_wording(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    _stub(monkeypatch, _healthy(width=2560))

    with _client() as client:
        first = client.put(_PUT, json=_INVALID_WIDTH_PAYLOAD)
        # Twice on purpose: the runtime's width verdict is cached per (provider, url, model), so a
        # probe that merely *relied on that wrapper* would refuse the first write and let the second
        # one through. The save-time judgement has to measure the vector it was handed (D6).
        second = client.put(_PUT, json=_INVALID_WIDTH_PAYLOAD)

    for response in (first, second):
        assert response.status_code == 400
        assert response.json()["detail"] == f"提交后的配置仍不可用： / The configuration is still unusable after the save: {_WRONG_WIDTH_MESSAGE}"


def test_the_save_time_refusal_says_what_the_runtime_would_say(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    """The same fact must not grow a second wording (D5)."""
    _stub(monkeypatch, _healthy(width=2560))
    config = get_app_config()
    pending = config.rag.model_copy(
        update={
            "embedding_provider": "openai-compatible",
            "embedding_base_url": "http://127.0.0.1:8125/v1",
            "embedding_model": "stub-embedding",
            "embedding_sparse_source": "bm25",
        }
    )

    with pytest.raises(RagConfigurationError) as caught:
        asyncio.run(build_embedder(config, rag=pending).embed(["probe"]))

    assert str(caught.value) == _WRONG_WIDTH_MESSAGE


def test_an_empty_sparse_half_is_refused_with_its_two_ways_out(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    _stub(monkeypatch, lambda request: httpx.Response(200, json=_dashscope_body(sparse=[])))

    with _client() as client:
        response = client.put(
            _PUT,
            json={
                "embedding_provider": "dashscope",
                "embedding_model": "stub-embedding",
                "embedding_api_key": "sk-stub",
                "embedding_sparse_source": "provider",
            },
        )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail.startswith("提交后的配置仍不可用：")
    assert "独立稀疏服务" in detail and "本地 BM25" in detail


def test_the_same_endpoint_is_accepted_when_the_sparse_half_comes_from_elsewhere(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    """Only the pair is unusable — an endpoint that returns no terms is still a fine dense source."""
    _stub(monkeypatch, lambda request: httpx.Response(200, json=_dashscope_body(sparse=[])))

    with _client() as client:
        response = client.put(
            _PUT,
            json={
                "embedding_provider": "dashscope",
                "embedding_model": "stub-embedding",
                "embedding_api_key": "sk-stub",
                "embedding_sparse_source": "bm25",
            },
        )

    assert response.status_code == 200
    assert response.json()["warning"] is None


def test_a_refused_write_leaves_the_file_byte_identical(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    _stub(monkeypatch, _healthy(width=2560))
    target = config_env / "rag_config.json"
    target.write_text(json.dumps({"embedding_model": "kept"}), encoding="utf-8")
    before = target.read_bytes()

    with _client() as client:
        assert client.put(_PUT, json=_INVALID_WIDTH_PAYLOAD).status_code == 400

    assert target.read_bytes() == before


# ── no answer: save anyway, with one sentence saying so (D3) ────────────────────


def test_a_dead_sparse_service_is_a_warning_not_a_refusal(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    """`external` + a service that is down: the dense leg built fine, so this is "could not check"."""
    _stub(monkeypatch, _dense_ok_sparse_dead)

    with _client() as client:
        response = client.put(
            _PUT,
            json={
                **_INVALID_WIDTH_PAYLOAD,
                "embedding_sparse_source": "external",
                "sparse_provider": "tei-sparse",
                "sparse_base_url": "http://127.0.0.1:8199",
            },
        )

    assert response.status_code == 200
    warning = response.json()["warning"]
    assert warning and warning.startswith("提交后的配置已保存，但未能验证")
    assert "未能连通" in warning


def test_an_unreachable_endpoint_saves_with_a_warning(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    _stub(monkeypatch, _dead)

    with _client() as client:
        response = client.put(_PUT, json=_INVALID_WIDTH_PAYLOAD)
        # The identity change takes the deferred channel (D3); wait for the flip before
        # reading the file, and while it runs the file still declares the old model.
        assert _settled_reembed(client)["state"] == "succeeded"

    assert response.status_code == 200
    assert "未能验证" in response.json()["warning"]
    stored = _read_rag_json(config_env)
    assert stored["embedding_model"] == "stub-embedding"
    assert stored["embedding_sparse_source"] == "bm25"


def test_a_refused_credential_says_so_rather_than_blaming_the_connection(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    _stub(monkeypatch, _refused)

    with _client() as client:
        response = client.put(_PUT, json={**_INVALID_WIDTH_PAYLOAD, "embedding_api_key": "sk-wrong"})

    assert response.status_code == 200
    warning = response.json()["warning"]
    assert "凭据被拒" in warning
    assert "未能连通" not in warning


# ── only when a watched field really changed (D2) ───────────────────────────────


def test_an_unrelated_change_probes_nothing(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    recorded = _stub(monkeypatch, _healthy())

    with _client() as client:
        response = client.put(_PUT, json=_UNRELATED)

    assert response.status_code == 200
    assert recorded == []
    assert response.json()["warning"] is None


def test_changing_only_the_rag_default_probes_nothing(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    """The RAG default is a model *reference*, not an embedding setting (D2's watched six).

    Paired with a positive control on the same stub: a real embedding change must still make
    it record a call, otherwise `recorded == []` would only prove the stub swallowed
    everything.
    """
    recorded = _stub(monkeypatch, _healthy())

    with _client() as client:
        picked = client.put(_PUT, json={"default_model": "rag-default"})

    assert picked.status_code == 200
    assert picked.json()["warning"] is None
    assert _read_rag_json(config_env)["default_model"] == "rag-default"
    assert recorded == []

    with _client() as client:
        assert client.put(_PUT, json={**_INVALID_WIDTH_PAYLOAD, "default_model": "rag-default"}).status_code == 200

    assert recorded != [], "the positive control must reach the network"


def test_changing_only_a_new_role_field_probes_nothing(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    """``vlm_model`` is a model reference, not an embedding setting (D2).

    Same shape as the default-model case above, positive control included.
    """
    recorded = _stub(monkeypatch, _healthy())

    with _client() as client:
        picked = client.put(_PUT, json={"vlm_model": "rag-default"})

    assert picked.status_code == 200
    assert picked.json()["warning"] is None
    assert _read_rag_json(config_env)["vlm_model"] == "rag-default"
    assert recorded == []

    with _client() as client:
        assert client.put(_PUT, json={**_INVALID_WIDTH_PAYLOAD, "vlm_model": "rag-default"}).status_code == 200

    assert recorded != [], "the positive control must reach the network"


def test_resubmitting_the_same_embedding_settings_probes_nothing(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    """The judgement is on *values*, not on which keys the payload carried — and a masking
    sentinel resolves to the stored key, which is the value already in force (D2)."""
    recorded = _stub(monkeypatch, _healthy())

    with _client() as client:
        unchanged = client.put(
            _PUT,
            json={
                "embedding_provider": "dashscope",
                "embedding_model": "yaml-embedding",
                "embedding_sparse_source": "provider",
            },
        )

    assert unchanged.status_code == 200
    assert recorded == []

    (config_env / "rag_config.json").write_text(json.dumps({"embedding_model": "kept", "embedding_api_key": "sk-stored"}), encoding="utf-8")
    reset_app_config()

    with _client() as client:
        sentinel = client.put(_PUT, json={"embedding_model": "kept", "embedding_api_key": MASKED_SECRET})

    assert sentinel.status_code == 200
    assert recorded == []
    assert _read_rag_json(config_env)["embedding_api_key"] == "sk-stored"


# ── the response contract (D3) ──────────────────────────────────────────────────


def test_warning_is_always_present_and_never_strips_null_fields(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    """``warning`` is ``null`` when silent, not absent — and adding it must not turn the response
    into an ``exclude_none`` dump, which would delete every ``null`` inside ``config``."""
    _stub(monkeypatch, _healthy())

    with _client() as client:
        body = client.put(_PUT, json=_UNRELATED).json()

    assert "warning" in body and body["warning"] is None
    assert "default_model" in body["config"] and body["config"]["default_model"] is None
    assert body["config"]["embedding_base_url"] == "http://127.0.0.1:8123/v1"


def test_a_missing_embedding_model_is_refused_at_save_time(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    """A-1 (spec 2026-09-30 D1): the save-time build refuses a config that never declared a
    model name — the admin meets the refusal here, before anything is written."""
    without_model = {key: value for key, value in YAML_RAG.items() if key != "embedding_model"}
    (config_env / "config.yaml").write_text(
        yaml.safe_dump({"sandbox": SANDBOX, "models": _YAML_MODELS, "rag": without_model}),
        encoding="utf-8",
    )
    reset_app_config()

    with _client() as client:
        response = client.put(_PUT, json={"rerank_model": "ui-rerank"})

    assert response.status_code == 400
    assert "embedding_model" in response.json()["detail"]
