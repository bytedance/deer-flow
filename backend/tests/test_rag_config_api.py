"""Seam A tests for the admin RAG config API (``GET/PUT /api/rag/config``).

Spec 2026-09-10 rag functional-model config §4/§6. The settings UI reads the effective
RAG functional-model configuration (secrets masked, each field's origin reported) and
writes the whole set back to the API-writable ``rag_config.json`` only — never to
``config.yaml``. A submitted masking sentinel means "keep the stored key".
"""

from __future__ import annotations

import asyncio
import json
import threading
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
from deerflow.knowledge.providers import provider_ids

SANDBOX = {"use": "deerflow.sandbox.local:LocalSandboxProvider"}

#: Captured before any fixture patches it, so a test that needs its own transport can build on
#: the real class instead of chaining onto whatever stub ran first.
_REAL_ASYNC_CLIENT = httpx.AsyncClient

YAML_RAG = {
    "qdrant_url": "http://qdrant:6333",
    "embedding_model": "yaml-embedding",
    "rerank_model": "yaml-rerank",
    "vlm_model": "yaml-vlm",
    "worker_concurrency": 4,
}

#: The model names this file's payloads declare, as ``config.yaml`` entries. They have to
#: exist: since spec 2026-09-23 D10.1 a save refuses a declared name that is not a configured
#: entry (the not-found mapping below), and the legacy fixtures declared names into an empty
#: model list. They are YAML entries on purpose -- the strict missing-key/address rule covers
#: UI-managed entries only, so an operator's own file stays out of it.
YAML_MODELS = [
    {"name": name, "use": "langchain_openai:ChatOpenAI", "model": "gpt-test", "api_key": "test-key", "base_url": "https://yaml.example/v1"}
    for name in ("B", "default-entry", "rag-default", "ui-default", "yaml-default", "judge-entry", "yaml-vlm")
]


def _write_config_yaml(root: Path, rag: dict | None = None) -> None:
    (root / "config.yaml").write_text(
        yaml.safe_dump({"sandbox": SANDBOX, "models": YAML_MODELS, "rag": rag or YAML_RAG}),
        encoding="utf-8",
    )


def _seed_ui_model(root: Path, *, name: str, api_key: str | None = "sk-ui", base_url: str | None = "https://ui.example/v1") -> None:
    """One UI-managed (models_config.json) entry, complete by default.

    Omitting a value is how a case builds the incomplete target the save-time rule refuses.
    """
    entry: dict = {"name": name, "use": "langchain_openai:ChatOpenAI", "model": "gpt-test"}
    if api_key is not None:
        entry["api_key"] = api_key
    if base_url is not None:
        entry["base_url"] = base_url
    (root / "models_config.json").write_text(json.dumps({"models": [entry]}), encoding="utf-8")


def _write_rag_json(root: Path, payload: dict) -> None:
    (root / "rag_config.json").write_text(json.dumps(payload), encoding="utf-8")


def _read_rag_json(root: Path) -> dict:
    return json.loads((root / "rag_config.json").read_text(encoding="utf-8"))


@pytest.fixture
def config_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config_yaml = tmp_path / "config.yaml"
    models_json = tmp_path / "models_config.json"
    extensions = tmp_path / "extensions_config.json"
    models_json.write_text(json.dumps({"models": []}), encoding="utf-8")
    extensions.write_text(json.dumps({"mcpServers": {}, "skills": {}}), encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_yaml))
    monkeypatch.setenv("DEER_FLOW_MODELS_CONFIG_PATH", str(models_json))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions))
    monkeypatch.setenv("DEER_FLOW_RAG_CONFIG_PATH", str(tmp_path / "rag_config.json"))
    # Keep the secret-source expectations independent of the ambient environment.
    for name in (
        "DASHSCOPE_EMBEDDING_API_KEY",
        "DASHSCOPE_RERANK_API_KEY",
        "DASHSCOPE_API_KEY",
        "MINERU_API_TOKEN",
        "RAG_EMBEDDING_API_KEY",
        "RAG_RERANK_API_KEY",
        "RAG_SPARSE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    _write_config_yaml(tmp_path)
    _write_rag_json(tmp_path, {})
    reset_app_config()
    yield tmp_path
    reset_app_config()


_ENDPOINT_FIXTURE = {
    "embedding_base_url": "http://localhost:8080/v1",
    "rerank_base_url": "http://localhost:8000",
}


class _EndpointSeededClient(TestClient):
    """Both endpoints are required (spec 2026-09-25 rag-endpoint-unlock D1/D3).

    Cases that do not care about them get both seeded; a case about the empty state passes a
    key explicitly (an explicit ``""`` wins here and then fails the save on purpose).
    """

    def put(self, url, json=None, **kwargs):
        if url == "/api/rag/config" and isinstance(json, dict):
            json = {**_ENDPOINT_FIXTURE, **json}
        return super().put(url, json=json, **kwargs)


@pytest.fixture(autouse=True)
def _reembed_libraries_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    """A save that changes the embedding fingerprint now starts a rebuild (spec 2026-10-04
    D3). Cases not about that get a trivial instant success so the flip settles quietly;
    the D3 cases replace the walk stub with their own gated/failing one. The window marks
    and the post-flip delta pass (spec 2026-10-05) are stubbed alongside — the placeholder
    service stores in this file are plain objects, not databases.
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


def _client(*, system_role: str) -> TestClient:
    app = make_authed_test_app(
        user_factory=lambda: User(
            email=f"{system_role}-rag-test@example.com",
            password_hash="x",
            system_role=system_role,
            id=uuid4(),
        )
    )
    app.include_router(rag_config_router.router)
    client = _EndpointSeededClient(app)
    # The gateway always wires a knowledge service; cases that care about its contents
    # call ``_attach_service`` to replace this placeholder.
    from types import SimpleNamespace

    client.app.state.knowledge_service = SimpleNamespace(store=object(), vector_store=object())
    return client


@pytest.fixture(autouse=True)
def _no_outbound_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep this file's saves off the network.

    A PUT that changes an embedding setting now makes one real call (spec 2026-09-17 save-time
    probe), so without a stub these tests would dial whatever address the payload names — the
    golden payload points at ``localhost:8080``. The stub answers a shape both families can read
    (OpenAI's ``data``, DashScope's ``output.embeddings``) at 1024 dimensions, with a sparse half
    so ``sparse_source='provider'`` is satisfied too.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [{"index": 0, "embedding": [0.0] * 1024}],
                "output": {"embeddings": [{"text_index": 0, "embedding": [0.0] * 1024, "sparse_embedding": [{"index": 7, "value": 0.5}]}]},
            },
        )

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_async_client(transport=httpx.MockTransport(handler)))


# ── admin gate ────────────────────────────────────────────────────────────


def test_rag_config_requires_admin(config_env: Path):
    with _client(system_role="user") as client:
        assert client.get("/api/rag/config").status_code == 403
        assert client.put("/api/rag/config", json={"embedding_model": "x"}).status_code == 403
    with _client(system_role="admin") as client:
        assert client.get("/api/rag/config").status_code == 200


# ── read: effective values + masked secrets + per-field origin ────────────


def test_get_reports_effective_values_and_origins(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    _write_rag_json(config_env, {"embedding_model": "ui-embedding", "embedding_api_key": "sk-embed"})
    monkeypatch.setenv("DASHSCOPE_RERANK_API_KEY", "sk-env-rerank")

    with _client(system_role="admin") as client:
        body = client.get("/api/rag/config").json()

    config = body["config"]
    assert config["embedding_model"] == "ui-embedding"  # file wins over config.yaml
    assert config["rerank_model"] == "yaml-rerank"  # untouched -> config.yaml
    assert config["embedding_api_key"] == MASKED_SECRET
    assert config["rerank_api_key"] == ""  # env-backed, never echoed
    assert config["mineru_api_token"] == ""

    sources = body["sources"]
    assert sources["embedding_model"] == "ui"
    assert sources["rerank_model"] == "config_file"
    assert sources["embedding_api_key"] == "ui"
    assert sources["rerank_api_key"] == "env"
    assert sources["mineru_api_token"] == "unset"


def test_get_never_returns_a_stored_secret(config_env: Path):
    _write_rag_json(config_env, {"embedding_api_key": "sk-super-secret"})

    with _client(system_role="admin") as client:
        response = client.get("/api/rag/config")

    assert "sk-super-secret" not in response.text
    assert response.json()["config"]["embedding_api_key"] == MASKED_SECRET


# ── write: validation, masking, and the file-only boundary ───────────────


def test_put_rejects_unknown_field(config_env: Path):
    _write_rag_json(config_env, {"embedding_model": "kept"})

    with _client(system_role="admin") as client:
        response = client.put("/api/rag/config", json={"embedding_modle": "typo"})

    assert response.status_code == 422
    assert _read_rag_json(config_env) == {"embedding_model": "kept"}


def test_put_writes_only_the_rag_file(config_env: Path):
    yaml_before = (config_env / "config.yaml").read_bytes()

    with _client(system_role="admin") as client:
        response = client.put(
            "/api/rag/config",
            json={
                "embedding_model": "ui-embedding",
                "rerank_model": "ui-rerank",
            },
        )
        _settled_reembed(client)

    assert response.status_code == 200
    stored = _read_rag_json(config_env)
    assert stored["embedding_model"] == "ui-embedding"
    assert stored["rerank_model"] == "ui-rerank"
    assert (config_env / "config.yaml").read_bytes() == yaml_before


def test_put_sentinel_preserves_the_stored_secret(config_env: Path):
    _write_rag_json(config_env, {"embedding_api_key": "sk-stored"})

    with _client(system_role="admin") as client:
        response = client.put(
            "/api/rag/config",
            json={"embedding_model": "ui-embedding", "embedding_api_key": MASKED_SECRET},
        )
        _settled_reembed(client)

    assert response.status_code == 200
    stored = _read_rag_json(config_env)
    assert stored["embedding_api_key"] == "sk-stored"
    assert stored["embedding_model"] == "ui-embedding"

    with _client(system_role="admin") as client:
        client.put("/api/rag/config", json={"embedding_model": "ui-embedding", "embedding_api_key": "sk-rotated"})
        _settled_reembed(client)

    assert _read_rag_json(config_env)["embedding_api_key"] == "sk-rotated"


def test_put_omitting_a_field_clears_it(config_env: Path):
    """The whole object is replaced, so dropping a field reverts it to config.yaml."""
    _write_rag_json(config_env, {"rerank_model": "ui-rerank", "embedding_model": "ui-embedding"})

    with _client(system_role="admin") as client:
        assert client.put("/api/rag/config", json={"embedding_model": "ui-embedding"}).status_code == 200

    stored = _read_rag_json(config_env)
    assert "rerank_model" not in stored
    assert get_app_config().rag.rerank_model == "yaml-rerank"  # back to config.yaml


def test_put_round_trip_does_not_materialize_no_op_defaults(config_env: Path):
    """GET→PUT 整对象往返（脚本/探针/集成方的常态姿势）不许把解析兜底物化成声明。

    真栈 A4 实测：整对象 PUT 把 10 个解析默认值写进 rag_config.json（917B→1284B、
    零值变更）。UI 的 buildRagConfigInput 只发「本次编辑 + 文件自有声明」、从不踩；
    这道闸是给非 UI 客户端的结构性防线——没选过的值不许被写成「选过」，否则将来
    兜底一变，旧保存会把它静默钉死。
    """
    # 端点一并预置：测试客户端会把境内地址注进每次 PUT，指纹不变才不会顺带触发
    # 重建/探测——本例测的是往返物化这一件事。
    _write_rag_json(
        config_env,
        {
            "embedding_model": "ui-embedding",
            "parse_language": "en",
            "embedding_base_url": "http://localhost:8080/v1",
            "rerank_base_url": "http://localhost:8000",
        },
    )

    with _client(system_role="admin") as client:
        view = client.get("/api/rag/config").json()["config"]
        assert client.put("/api/rag/config", json=view).status_code == 200
        _settled_reembed(client)

    stored = _read_rag_json(config_env)
    assert stored["embedding_model"] == "ui-embedding", "文件自有声明原样保留（owned ≠ no-op）"
    assert stored["parse_language"] == "en"
    for noise in (
        "qdrant_url",
        "vlm_model",
        "rerank_model",
        "vlm_thinking",
        "parse_provider",
        "parse_model_version",
    ):
        assert noise not in stored, f"{noise} 是解析兜底，不许物化成声明"


def test_put_keeps_identity_fields_even_when_they_equal_the_fallback(config_env: Path):
    """身份四件豁免剥离：显式值=「向量空间的记录」，钉住是本意（防 yaml 兜底一变
    就悄悄换空间/换宽度）；同一次保存里的非身份 no-op 照样不落盘。"""
    _write_rag_json(config_env, {"embedding_base_url": "http://localhost:8080/v1", "rerank_base_url": "http://localhost:8000"})

    with _client(system_role="admin") as client:
        response = client.put(
            "/api/rag/config",
            json={"embedding_dimension": 1024, "qdrant_url": "http://qdrant:6333"},
        )
        _settled_reembed(client)

    assert response.status_code == 200
    stored = _read_rag_json(config_env)
    assert stored["embedding_dimension"] == 1024
    assert "qdrant_url" not in stored


# ── the caption VLM reference (a model reference, never a secret) ─────────


def test_vlm_model_round_trips_as_a_regular_field(config_env: Path):
    with _client(system_role="admin") as client:
        response = client.put("/api/rag/config", json={"vlm_model": "judge-entry"})

    assert response.status_code == 200
    assert _read_rag_json(config_env) == {
        **_ENDPOINT_FIXTURE,
        "vlm_model": "judge-entry",
    }
    body = response.json()
    assert body["config"]["vlm_model"] == "judge-entry"
    assert body["sources"]["vlm_model"] == "ui"

    with _client(system_role="admin") as client:
        read = client.get("/api/rag/config").json()

    assert read["config"]["vlm_model"] == "judge-entry"
    assert read["sources"]["vlm_model"] == "ui"


def test_vlm_model_falls_back_to_config_yaml(config_env: Path):
    with _client(system_role="admin") as client:
        body = client.get("/api/rag/config").json()

    assert body["config"]["vlm_model"] == "yaml-vlm"
    assert body["sources"]["vlm_model"] == "config_file"


# ── the RAG default model (spec 2026-09-23 default model D2) ──────────────
#
# A plain field on the existing whole-object PUT: naming it writes a UI override,
# omitting it withdraws one, and the response reports which of the two happened.


def test_rag_default_model_round_trips_and_reports_its_source(config_env: Path):
    with _client(system_role="admin") as client:
        initial = client.get("/api/rag/config").json()
        assert initial["config"]["default_model"] is None
        assert initial["sources"]["default_model"] == "config_file"

        put = client.put("/api/rag/config", json={"default_model": "default-entry"})
        assert put.status_code == 200
        assert _read_rag_json(config_env) == {**_ENDPOINT_FIXTURE, "default_model": "default-entry"}
        assert put.json()["config"]["default_model"] == "default-entry"
        assert put.json()["sources"]["default_model"] == "ui"

        read = client.get("/api/rag/config").json()

    assert read["config"]["default_model"] == "default-entry"
    assert read["sources"]["default_model"] == "ui"


def test_rag_default_model_falls_back_to_config_yaml(config_env: Path):
    _write_config_yaml(config_env, {**YAML_RAG, "default_model": "yaml-default"})

    with _client(system_role="admin") as client:
        body = client.get("/api/rag/config").json()

    assert body["config"]["default_model"] == "yaml-default"
    assert body["sources"]["default_model"] == "config_file"


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_rag_default_withdraws_the_ui_override(config_env: Path, blank: str):
    """Blank is "undeclared", never a name: it must reach neither the file nor `sources`.

    ``""`` already survives ``_prune_empty()``; the whitespace spelling is the one that needs
    the field validator, because without it the string is written to disk and reported as a
    UI override that the operator never made.
    """
    _write_config_yaml(config_env, {**YAML_RAG, "default_model": "yaml-default"})

    with _client(system_role="admin") as client:
        assert client.put("/api/rag/config", json={"default_model": "ui-default"}).status_code == 200
        assert _read_rag_json(config_env)["default_model"] == "ui-default"

        response = client.put("/api/rag/config", json={"default_model": blank})

    assert response.status_code == 200
    assert "default_model" not in _read_rag_json(config_env)
    # Withdrawn, not forced to None: config.yaml's own value is what takes over again.
    # Asserted on a fresh read, not on the PUT response's `config`: that snapshot is the
    # pre-write one for any field the payload omits (pre-existing; the settings UI refetches).
    assert get_app_config().rag.default_model == "yaml-default"
    # `sources` *is* computed from what was written, so it is already right in that response.
    assert response.json()["sources"]["default_model"] == "config_file"


def test_saving_the_rag_default_touches_no_other_configuration_file(config_env: Path):
    """The save writes `rag_config.json` and nothing else, byte for byte."""
    names = ("config.yaml", "models_config.json", "extensions_config.json")
    before = {name: (config_env / name).read_bytes() for name in names}

    with _client(system_role="admin") as client:
        assert client.put("/api/rag/config", json={"default_model": "rag-default"}).status_code == 200

    assert {name: (config_env / name).read_bytes() for name in names} == before


# ── the save-time target check (spec 2026-09-23 D10.1) ────────────────────
# A save judges the targets the payload (plus config.yaml) declares: a UI-managed entry in
# the protocol grid must carry its own key -- and an address, in the one cell whose SDK has
# no default to borrow -- while a name that is not a configured entry is the not-found error.
# What the system would pick itself is never a refusal reason, so an empty declaration or a
# non-UI entry stays out of it.


def test_save_refuses_a_ui_target_without_a_key(config_env: Path):
    _seed_ui_model(config_env, name="ui-bare", api_key=None)

    with _client(system_role="admin") as client:
        response = client.put("/api/rag/config", json={"vlm_model": "ui-bare"})

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail.startswith("提交后的配置仍不可用：")
    assert "ui-bare" in detail and "api_key" in detail
    assert _read_rag_json(config_env) == {}  # a refused write leaves the file alone


def test_save_refuses_an_openai_compatible_target_without_an_address(config_env: Path):
    _seed_ui_model(config_env, name="ui-noaddr", base_url=None)

    with _client(system_role="admin") as client:
        response = client.put("/api/rag/config", json={"vlm_model": "ui-noaddr"})

    assert response.status_code == 400
    assert "base_url" in response.json()["detail"]


def test_save_accepts_a_complete_ui_target(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    """The positive control: the rule is not refusing the grid, only incomplete entries."""
    _seed_ui_model(config_env, name="ui-complete")

    with _client(system_role="admin") as client:
        response = client.put("/api/rag/config", json={"vlm_model": "ui-complete"})

    assert response.status_code == 200
    assert _read_rag_json(config_env)["vlm_model"] == "ui-complete"


def test_save_does_not_judge_the_fallback_target(config_env: Path):
    """`models[0]` standing in for a blank role is the system's own pick (D3): never a refusal.

    The seeded UI entry is incomplete on purpose -- if the check leaked onto a fallback the
    save would be refused here.
    """
    _seed_ui_model(config_env, name="ui-incomplete", api_key=None)

    with _client(system_role="admin") as client:
        response = client.put("/api/rag/config", json={"embedding_model": "ui-embedding"})

    assert response.status_code == 200


@pytest.mark.parametrize("field", ["default_model", "vlm_model"])
def test_save_maps_a_wrong_role_name_to_400(config_env: Path, field: str):
    """Every declared role, the default included: a name with no entry is a usage error."""
    with _client(system_role="admin") as client:
        response = client.put("/api/rag/config", json={field: "ghost-entry"})

    assert response.status_code == 400
    assert response.json()["detail"] == "提交后的配置仍不可用： / The configuration is still unusable after the save: 配置里没有模型「ghost-entry」 / Model ghost-entry not found in config"
    assert _read_rag_json(config_env) == {}


def test_save_refuses_a_declared_target_when_there_are_no_models_at_all(config_env: Path):
    """A model list with nothing in it cannot contain the declared name either."""
    (config_env / "models_config.json").write_text(json.dumps({"models": []}), encoding="utf-8")
    (config_env / "config.yaml").write_text(yaml.safe_dump({"sandbox": SANDBOX, "models": [], "rag": YAML_RAG}), encoding="utf-8")

    with _client(system_role="admin") as client:
        response = client.put("/api/rag/config", json={"vlm_model": "any-entry"})

    assert response.status_code == 400
    assert response.json()["detail"] == "提交后的配置仍不可用： / The configuration is still unusable after the save: 配置里没有模型「any-entry」 / Model any-entry not found in config"


def test_save_maps_the_retired_prefix_to_the_same_400(config_env: Path):
    """A `dashscope:` name is an ordinary name now (spec D9): no entry, no save."""
    with _client(system_role="admin") as client:
        response = client.put("/api/rag/config", json={"vlm_model": "dashscope:qwen3.8-max"})

    assert response.status_code == 400
    assert response.json()["detail"] == "提交后的配置仍不可用： / The configuration is still unusable after the save: 配置里没有模型「dashscope:qwen3.8-max」 / Model dashscope:qwen3.8-max not found in config"


def test_save_refuses_a_stale_default_at_the_moment_it_is_declared(config_env: Path):
    """The save *is* the declaration, so an unknown name is a usage error here for all four
    fields — the default included. D3's warning-and-fall-back is the runtime path, where a
    default that used to be valid can go stale after a model is removed (pinned in
    `test_model_target.py` and the resolver's own tests)."""
    with _client(system_role="admin") as client:
        response = client.put("/api/rag/config", json={"default_model": "gone-model"})

    assert response.status_code == 400
    assert response.json()["detail"] == "提交后的配置仍不可用： / The configuration is still unusable after the save: 配置里没有模型「gone-model」 / Model gone-model not found in config"
    assert _read_rag_json(config_env) == {}


def test_the_not_found_sentence_is_written_once():
    """R6: the RAG side owns one copy of the factory's sentence; the router carries none."""
    from pathlib import Path as _Path

    from deerflow.knowledge import model_target as model_target_module

    router_source = _Path(rag_config_router.__file__).read_text(encoding="utf-8")
    target_source = _Path(model_target_module.__file__).read_text(encoding="utf-8")

    assert "not found in config" not in router_source  # only the wording helper says it
    assert "model_not_found_message(" in router_source
    assert target_source.count('_NOT_FOUND_SUFFIX = " not found in config"') == 1


def test_the_not_found_sentence_equals_the_factorys_own(config_env: Path):
    """The value pin: the real factory's message must equal the RAG helper's output, word for word."""
    from deerflow.config.app_config import AppConfig
    from deerflow.config.app_config import RagConfig as _RagConfig
    from deerflow.config.sandbox_config import SandboxConfig
    from deerflow.knowledge.model_target import model_not_found_message
    from deerflow.models.factory import create_chat_model

    config = AppConfig(models=[], sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"), rag=_RagConfig())
    with pytest.raises(ValueError) as excinfo:
        create_chat_model(name="ghost", app_config=config)

    # C-1 (② 乙): the helper carries a Chinese half too now — the pin is on its English half,
    # which must stay the upstream factory's own sentence, word for word.
    assert model_not_found_message("ghost").split(" / ")[-1] == str(excinfo.value)


def test_retired_keys_are_rejected_by_a_write_and_dropped_at_load(config_env: Path):
    """The retired-key contract, both faces (``_RETIRED_KEYS`` / ``_drop_retired_keys``).

    A payload that still carries one is refused by the same ``extra="forbid"`` that guards
    every typo — never silently stripped. A *stored* file that still carries one keeps
    loading (an existing ``rag_config.json`` must not break) with the key dropped and a
    warning, so a value with no reader left cannot come back as another field's meaning.
    """
    retired = (
        "parse_backend",
        "vlm_base_url",
        "vlm_api_key",
        "extract_model",
        "judge_model",
        "wiki_model",
        "synthesis_model",
        "extract_thinking",
        "wiki_thinking",
        "judge_thinking",
        "synthesis_thinking",
        "asr_base_url",
        "asr_api_key",
        "video",
    )
    for field in retired:
        with _client(system_role="admin") as client:
            response = client.put("/api/rag/config", json={field: "leftover"})

        assert response.status_code == 422, field
    assert _read_rag_json(config_env) == {}

    _write_rag_json(config_env, {**{field: "leftover" for field in retired}, "embedding_model": "kept"})

    with _client(system_role="admin") as client:
        body = client.get("/api/rag/config").json()

    for field in retired:
        assert field not in body["config"], field
    assert body["config"]["embedding_model"] == "kept", "退役键被丢掉，文件其余部分照常加载"


# ── hot reload through the shared config singleton ────────────────────────


def test_put_takes_effect_without_a_restart(config_env: Path):
    with _client(system_role="admin") as client:
        assert client.get("/api/rag/config").json()["config"]["embedding_model"] == "yaml-embedding"
        assert client.put("/api/rag/config", json={"embedding_model": "ui-embedding"}).status_code == 200
        # 换模型触发重建（D3）：模型字段等重建完成才翻，settle 后才生效。
        _settled_reembed(client)
        body = client.get("/api/rag/config").json()

    assert body["config"]["embedding_model"] == "ui-embedding"
    assert body["sources"]["embedding_model"] == "ui"
    assert get_app_config().rag.embedding_model == "ui-embedding"


# ── support bundle redacts the rag file ───────────────────────────────────


def test_support_bundle_redacts_rag_config(config_env: Path):
    import support_bundle

    _write_rag_json(
        config_env,
        {
            "embedding_model": "ui-embedding",
            "embedding_api_key": "sk-embed-secret",
            "rerank_api_key": "sk-rerank-secret",
            "vlm_api_key": "sk-vlm-secret",
            "mineru_api_token": "mineru-secret",
            "sparse_api_key": "sk-sparse-secret",
        },
    )

    summary = support_bundle.collect_rag_summary(config_env / "rag_config.json")
    blob = json.dumps(summary)

    for secret in ("sk-embed-secret", "sk-rerank-secret", "sk-vlm-secret", "mineru-secret", "sk-sparse-secret"):
        assert secret not in blob
    assert summary["embedding_model"] == "ui-embedding"
    assert summary["embedding_api_key"] == "<redacted>"
    assert summary["mineru_api_token"] == "<redacted>"
    # The sparse key is covered by the same key-name pattern, so it needs no special case.
    assert summary["sparse_api_key"] == "<redacted>"
    # The bundle advertises the artifact it now ships.
    names = [entry["path"] for entry in support_bundle._evidence_files(include_doctor=False, include_thread_summary=False)]
    assert "rag-summary.json" in names


# ── provider dimension (spec 2026-09-14 rag model provider adaptation §4.1) ──


def test_get_reports_the_provider_fields_with_their_origins(config_env: Path):
    """The new fields ride the same generic path as every other non-secret field."""
    with _client(system_role="admin") as client:
        body = client.get("/api/rag/config").json()

    assert body["config"]["embedding_provider"] == "dashscope"
    assert body["config"]["rerank_provider"] == "dashscope"
    assert body["config"]["parse_provider"] == "mineru-cloud"
    assert body["config"]["embedding_sparse_source"] == "provider"
    assert body["sources"]["embedding_provider"] == "config_file"
    assert body["sources"]["parse_base_url"] == "config_file"


def test_put_round_trips_the_provider_fields_and_marks_them_ui(config_env: Path):
    with _client(system_role="admin") as client:
        response = client.put(
            "/api/rag/config",
            json={
                "embedding_provider": "openai-compatible",
                "embedding_base_url": "http://localhost:8080/v1",
                "embedding_sparse_source": "bm25",
                "rerank_provider": "generic-rerank",
                "rerank_base_url": "http://localhost:8000",
                "parse_provider": "mineru-local",
                "parse_base_url": "http://localhost:30000",
                "parse_tier": "flash",
            },
        )
        assert response.status_code == 200
        # 指纹字段（provider/base_url）触发重建（D3）：settle 后读生效值。
        _settled_reembed(client)
        body = client.get("/api/rag/config").json()

    assert body["config"]["embedding_provider"] == "openai-compatible"
    assert body["config"]["parse_tier"] == "flash"
    assert body["sources"]["parse_provider"] == "ui"
    stored = _read_rag_json(config_env)
    assert stored["parse_base_url"] == "http://localhost:30000"
    assert stored["embedding_sparse_source"] == "bm25"


def test_put_rejects_a_provider_outside_the_allowlist(config_env: Path):
    with _client(system_role="admin") as client:
        assert client.put("/api/rag/config", json={"embedding_provider": "some-vendor"}).status_code == 422


def test_put_rejects_the_retired_backend_key(config_env: Path):
    """`parse_backend` 已退役：载荷里带它 ⇒ 422（extra_forbidden），而不是被静默忽略。"""
    with _client(system_role="admin") as client:
        assert client.put("/api/rag/config", json={"parse_backend": "hybrid"}).status_code == 422
        assert client.put("/api/rag/config", json={"parse_tier": "vlm"}).status_code == 422


def test_sparse_api_key_is_treated_as_a_secret(config_env: Path):
    """Left out of ``_SECRET_FIELDS`` this key would come back in plaintext."""
    with _client(system_role="admin") as client:
        assert client.put("/api/rag/config", json={"sparse_api_key": "sk-sparse"}).status_code == 200
        body = client.get("/api/rag/config").json()

    assert body["config"]["sparse_api_key"] == MASKED_SECRET
    assert body["sources"]["sparse_api_key"] == "ui"
    assert "sk-sparse" not in json.dumps(body)

    with _client(system_role="admin") as client:
        assert client.put("/api/rag/config", json={"sparse_api_key": MASKED_SECRET}).status_code == 200
    assert _read_rag_json(config_env)["sparse_api_key"] == "sk-sparse"


def test_embedding_secret_env_source_follows_the_selected_provider(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    """The reported fallback must be the variable the *selected* provider reads."""
    monkeypatch.setenv("DASHSCOPE_EMBEDDING_API_KEY", "env-dashscope")
    with _client(system_role="admin") as client:
        assert client.get("/api/rag/config").json()["sources"]["embedding_api_key"] == "env"
        # A switch to a dense-only provider has to be *usable* to be savable now: it needs an
        # address, and the sparse half has to come from somewhere else in the same write —
        # `embedding_sparse_source` defaults to 'provider' (spec 2026-09-16 §3 D3).
        switched = client.put(
            "/api/rag/config",
            json={
                "embedding_provider": "openai-compatible",
                "embedding_base_url": "http://localhost:8080/v1",
                "embedding_sparse_source": "bm25",
            },
        ).json()
        # A provider switch is a deferred switch (D3): the response reports the file as it
        # stands — still the old provider, so still the old fallback — and the status names
        # the target the flip will write.
        assert switched[_REEMBED_FIELD]["state"] == "running"
        assert switched[_REEMBED_FIELD]["target_provider"] == "openai-compatible"
        assert switched["sources"]["embedding_api_key"] == "env"
        assert _settled_reembed(client)["state"] == "succeeded"
        # The switch re-points the fallback the moment the flip lands — no reload.
        assert client.get("/api/rag/config").json()["sources"]["embedding_api_key"] == "unset"
        monkeypatch.setenv("RAG_EMBEDDING_API_KEY", "env-generic")
        assert client.get("/api/rag/config").json()["sources"]["embedding_api_key"] == "env"


def test_rerank_secret_env_source_follows_the_provider(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DASHSCOPE_RERANK_API_KEY", "env-dashscope")
    with _client(system_role="admin") as client:
        assert client.get("/api/rag/config").json()["sources"]["rerank_api_key"] == "env"
        # The address rides along because the write has to be *savable* now: `generic-rerank`
        # without one is refused at save time (spec 2026-09-17 alignment §3 D2).
        client.put("/api/rag/config", json={"rerank_provider": "generic-rerank", "rerank_base_url": "http://localhost:8000"})
        assert client.get("/api/rag/config").json()["sources"]["rerank_api_key"] == "unset"
        monkeypatch.setenv("RAG_RERANK_API_KEY", "env-generic")
        assert client.get("/api/rag/config").json()["sources"]["rerank_api_key"] == "env"


def test_local_mineru_has_no_secret_fallback(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    """The local MinerU service ships without auth, so its token has no env source."""
    monkeypatch.setenv("MINERU_API_TOKEN", "tok")
    with _client(system_role="admin") as client:
        assert client.get("/api/rag/config").json()["sources"]["mineru_api_token"] == "env"
        # Same reason as the rerank one above: `mineru-local` needs its address to be savable.
        client.put("/api/rag/config", json={"parse_provider": "mineru-local", "parse_base_url": "http://localhost:30000"})
        assert client.get("/api/rag/config").json()["sources"]["mineru_api_token"] == "unset"


def test_sparse_secret_env_source_uses_the_generic_name(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RAG_SPARSE_API_KEY", "env-sparse")
    with _client(system_role="admin") as client:
        assert client.get("/api/rag/config").json()["sources"]["sparse_api_key"] == "env"


# ── embedding provider capabilities (spec 2026-09-16 §3 D1) ──────────────────
#
# The capability block is what lets the settings UI refuse a combination that cannot work
# (a dense-only provider asked to supply the sparse half) before it is ever saved. The
# golden below was captured from the *pre-change* endpoints (see `_precondition` in it), so
# "pure addition" is measured against real bytes rather than a hand-written expectation.

_GOLDEN = json.loads((Path(__file__).parent / "fixtures" / "rag_config" / "response_golden.json").read_text(encoding="utf-8"))
_CAPABILITY_FIELD = "embedding_providers"
#: The rerank leg's own capability block (spec 2026-09-17 alignment §3 D3): the address row is
#: locked by *row capability* there too, so the frontend must stop naming the provider.
_RERANK_CAPABILITY_FIELD = "rerank_providers"
#: The save-time probe's verdict rides every response, GET included — always present, ``null``
#: when there is nothing to say (spec 2026-09-17 save-time probe §3 D3). Registered here rather
#: than subtracted ad hoc so the "pure addition" guards keep their teeth.
_WARNING_FIELD = "warning"
#: The width migration's verdict (spec 2026-09-26 D5-7), same contract: always present, ``null``
#: until a save with a width change starts one.
_MIGRATION_FIELD = "migration"
_MIGRATION_FIELD = "migration"
_REEMBED_FIELD = "reembed"
_ADDED_FIELDS = {_CAPABILITY_FIELD, _RERANK_CAPABILITY_FIELD, _WARNING_FIELD, _MIGRATION_FIELD, _REEMBED_FIELD}


def _assert_pure_addition(body: dict, golden: dict) -> None:
    """The response may only have *gained* the registered fields; nothing else may move.

    Two ordered assertions on purpose: a shape change names the offending key, a value
    change shows the field-by-field diff.
    """
    assert set(body) == set(golden) | _ADDED_FIELDS
    assert {key: value for key, value in body.items() if key not in _ADDED_FIELDS} == golden


def test_get_returns_the_embedding_provider_capabilities(config_env: Path):
    with _client(system_role="admin") as client:
        body = client.get("/api/rag/config").json()

    # The list mirrors the curated allowlist in its own order — never a second copy of it.
    assert [entry["provider_id"] for entry in body[_CAPABILITY_FIELD]] == list(provider_ids("embedding"))
    # Up to 2026-09-17 the two extra keys travel with the row: the address field is locked by
    # *capability* (this provider fixes its own endpoint) instead of by a hardcoded provider id.
    assert {entry["provider_id"]: (entry["emits_sparse"], entry["has_fixed_endpoint"], entry["default_endpoint"]) for entry in body[_CAPABILITY_FIELD]} == {
        "dashscope": (True, True, "https://dashscope.aliyuncs.com"),
        "openai-compatible": (False, False, None),
        "volcengine-ark": (True, True, "https://ark.cn-beijing.volces.com"),
    }


def test_get_returns_the_rerank_provider_capabilities(config_env: Path):
    """The rerank row needs the same *row capability* answer the embedding one gets (§3 D3).

    Its entry has no ``emits_sparse`` — the rerank leg has no "which half" question — so the two
    blocks are deliberately different shapes rather than one generic list.
    """
    with _client(system_role="admin") as client:
        body = client.get("/api/rag/config").json()

    assert [entry["provider_id"] for entry in body[_RERANK_CAPABILITY_FIELD]] == list(provider_ids("rerank"))
    assert {entry["provider_id"]: (entry["has_fixed_endpoint"], entry["default_endpoint"]) for entry in body[_RERANK_CAPABILITY_FIELD]} == {
        "dashscope": (True, "https://dashscope.aliyuncs.com"),
        "generic-rerank": (False, None),
        "tei-rerank": (False, None),
    }
    assert all("emits_sparse" not in entry for entry in body[_RERANK_CAPABILITY_FIELD])


def test_the_rerank_default_endpoint_is_the_clients_own_constant():
    """Anti-drift: the allowlist literal and the client's constant must not move apart.

    Same rule the embedding rows follow — the literal lives in the import-light allowlist module,
    so a test keeps the two equal instead (spec 2026-09-17 alignment §3 D3).
    """
    from deerflow.knowledge.providers import resolve_provider
    from deerflow.knowledge.reranker import DASHSCOPE_RERANK_BASE_URL

    assert resolve_provider("rerank", "dashscope").default_endpoint == DASHSCOPE_RERANK_BASE_URL


def test_get_response_only_gained_the_capability_field(config_env: Path):
    with _client(system_role="admin") as client:
        body = client.get("/api/rag/config").json()

    _assert_pure_addition(body, _GOLDEN["get"])


def test_put_response_only_gained_the_capability_field(config_env: Path):
    with _client(system_role="admin") as client:
        # This payload changes the embedding identity, so the first save takes the deferred
        # channel (D3) and its response reports the held file. The golden, captured from
        # pre-change bytes, pins the settled shape: with the identity already in force a
        # save of the same payload is an ordinary save again — which is the second PUT here.
        first = client.put("/api/rag/config", json=_GOLDEN["put"]["payload"])
        assert first.status_code == 200
        assert first.json()[_REEMBED_FIELD]["state"] == "running"
        assert _settled_reembed(client)["state"] == "succeeded"
        response = client.put("/api/rag/config", json=_GOLDEN["put"]["payload"])

    assert response.status_code == 200
    _assert_pure_addition(response.json(), _GOLDEN["put"]["response"])


# ── save-time validation of the configuration about to be persisted ──────────
#
# Spec 2026-09-16 §3 D3. The PUT refuses a write whose *result* cannot build an embedder, so
# the admin learns while editing instead of on the next ingest. The judgement is the pipeline's
# own construction (`build_embedder`) against the merge the write will actually produce:
# ``config.yaml``'s `rag:` block overlaid with the file being persisted.

#: A dense-only provider asked to supply the sparse half — legal JSON, unusable configuration.
_UNUSABLE = {
    "embedding_provider": "openai-compatible",
    "embedding_base_url": "http://localhost:8080/v1",
    "embedding_sparse_source": "provider",
}


def test_put_rejects_a_configuration_that_cannot_build_an_embedder(config_env: Path):
    with _client(system_role="admin") as client:
        response = client.put("/api/rag/config", json=_UNUSABLE)

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail.startswith("提交后的配置仍不可用：")
    assert "openai-compatible" in detail
    assert "独立稀疏服务" in detail and "本地 BM25" in detail


def test_a_rejected_put_writes_nothing(config_env: Path):
    _write_rag_json(config_env, {"embedding_model": "kept"})

    with _client(system_role="admin") as client:
        assert client.put("/api/rag/config", json=_UNUSABLE).status_code == 400

    assert _read_rag_json(config_env) == {"embedding_model": "kept"}


def test_put_accepts_the_same_write_once_the_sparse_source_is_legal(config_env: Path):
    with _client(system_role="admin") as client:
        response = client.put("/api/rag/config", json={**_UNUSABLE, "embedding_sparse_source": "bm25"})

    assert response.status_code == 200
    assert _read_rag_json(config_env)["embedding_sparse_source"] == "bm25"


def test_put_validates_against_config_yaml_not_the_payload_alone(config_env: Path):
    """The payload omits the provider, so validating it alone would let the section default
    (``dashscope``) stand in and pass. The configuration that will actually be read after this
    write is ``config.yaml``'s dense-only provider, which cannot supply the sparse half."""
    _write_config_yaml(
        config_env,
        {**YAML_RAG, "embedding_provider": "openai-compatible", "embedding_base_url": "http://yaml-embed"},
    )
    reset_app_config()

    with _client(system_role="admin") as client:
        response = client.put("/api/rag/config", json={"embedding_sparse_source": "provider"})

    assert response.status_code == 400
    assert "openai-compatible" in response.json()["detail"]


def test_put_accepts_clearing_a_field_only_the_previous_file_declared(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    """The mirror image: a field the *replaced* file declared must not be judged at its old
    value. ``512`` loads, so a check based on the live ``config.rag`` — which still carries
    that file — would keep seeing 512 and reject a write that is fine. Clearing the
    declaration is itself a width change (512 → the default), so the save starts a
    migration and the file keeps the old value until that finishes."""
    _write_rag_json(config_env, {"embedding_dimension": 512})
    reset_app_config()
    _stub_runner(monkeypatch)

    with _client(system_role="admin") as client:
        _attach_service(client)
        response = client.put("/api/rag/config", json={"embedding_model": "ui-embedding"})
        assert response.status_code == 200, response.text
        assert _settled(client)["state"] == "succeeded"

    assert "embedding_dimension" not in _read_rag_json(config_env), "迁移完成后声明才被清掉"


def _answer_with(monkeypatch: pytest.MonkeyPatch, *, dims: int, recorded: list[httpx.Request]) -> None:
    """Override the file's autouse stub with one that answers a specific dense width.

    Built on ``_REAL_ASYNC_CLIENT``: the autouse fixture has already replaced ``httpx.AsyncClient``,
    so capturing it here would chain onto that patch and silently re-answer at 1024 dimensions.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return httpx.Response(
            200,
            json={"output": {"embeddings": [{"text_index": 0, "embedding": [0.0] * dims, "sparse_embedding": [{"index": 7, "value": 0.5}]}]}},
        )

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler)))


def test_put_judges_a_declared_width_against_the_declaration_not_1024(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    """选 1536 ⇒ 保存期探针按 1536 判（spec 2026-09-26 §4 验收 4）：模型真能给到这个宽度就该放行。

    "放行" 必须靠那一发真调用证明：``warning=null`` 说明探针拿到了答案（"没能验证"也会 200）。
    宽度本身还没生效 —— 那是后台迁移跑完之后的事（见下面的迁移一节）。
    """
    _write_rag_json(config_env, {"embedding_api_key": "sk-probe"})
    reset_app_config()
    recorded: list[httpx.Request] = []
    _answer_with(monkeypatch, dims=1536, recorded=recorded)
    _stub_runner(monkeypatch)

    with _client(system_role="admin") as client:
        _attach_service(client)
        response = client.put("/api/rag/config", json={"embedding_dimension": 1536})

    assert response.status_code == 200, response.text
    assert response.json()[_WARNING_FIELD] is None
    assert json.loads(recorded[0].content)["parameters"]["dimension"] == 1536, "问的就是所选的那个宽度"


def test_put_refuses_a_declared_width_the_model_does_not_return(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    """被忽略/被拒的那一半：实测不是所选值 ⇒ 400，且文案里两种宽度都在（用户要知道谁对不上谁）。"""
    _write_rag_json(config_env, {"embedding_api_key": "sk-probe"})
    reset_app_config()
    _answer_with(monkeypatch, dims=1024, recorded=[])

    with _client(system_role="admin") as client:
        response = client.put("/api/rag/config", json={"embedding_dimension": 1536})

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "1024" in detail and "1536" in detail
    assert "返回" in detail, "判的是那一发实测回来的宽度，不是声明与默认不符"
    assert _read_rag_json(config_env).get("embedding_dimension") is None, "被拒的写不能落盘"


# ── the same check now covers the other two legs (spec 2026-09-17 alignment §3 D2) ──────────
#
# Building the embedder only ever answered for the embedding half: a rerank provider that needs
# an address, or a local parser without one, saved happily and blew up on the next retrieval or
# ingest. Both constructions are offline, so covering them costs no network call — which is the
# counterexample below.


def test_put_refuses_a_rerank_without_its_address(config_env: Path):
    target = config_env / "rag_config.json"
    target.write_text(json.dumps({"rerank_model": "kept"}), encoding="utf-8")
    before = target.read_bytes()

    with _client(system_role="admin") as client:
        response = client.put(
            "/api/rag/config",
            json={"rerank_provider": "generic-rerank", "rerank_base_url": ""},
        )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail.startswith("提交后的配置仍不可用：")
    assert "rerank_base_url" in detail
    assert target.read_bytes() == before


def test_put_refuses_a_tei_rerank_without_its_address(config_env: Path):
    """The TEI row ships no address either (spec 2026-09-24 §4.3 D3 甲).

    Same refusal as the generic row, and it has to be the same one: the save-time construction
    check builds whatever the payload selects, so a new provider that skipped that check would
    save happily and only blow up on the next retrieval.
    """
    target = config_env / "rag_config.json"
    target.write_text(json.dumps({"rerank_model": "kept"}), encoding="utf-8")
    before = target.read_bytes()

    with _client(system_role="admin") as client:
        response = client.put(
            "/api/rag/config",
            json={"rerank_provider": "tei-rerank", "rerank_base_url": ""},
        )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail.startswith("提交后的配置仍不可用：")
    assert "rerank_base_url" in detail
    assert target.read_bytes() == before


def test_put_refuses_a_local_parser_without_its_address(config_env: Path):
    target = config_env / "rag_config.json"
    target.write_text(json.dumps({"rerank_model": "kept"}), encoding="utf-8")
    before = target.read_bytes()

    with _client(system_role="admin") as client:
        response = client.put("/api/rag/config", json={"parse_provider": "mineru-local"})

    assert response.status_code == 400
    assert "parse_base_url" in response.json()["detail"]
    assert target.read_bytes() == before


def test_a_complete_configuration_saves_without_touching_the_network(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    """The three-leg check must not become a fourth network hop (spec 2026-09-17 alignment §2 D2).

    Every construction is offline, so *any* outbound attempt here is a defect — the stub fails
    the test instead of answering, which also means the autouse stub of this module is replaced.
    """

    def _explode(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"the save-time check went out to the network: {request.url}")

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_async_client(transport=httpx.MockTransport(_explode)))

    with _client(system_role="admin") as client:
        response = client.put("/api/rag/config", json={"rerank_model": "ui-rerank"})

    assert response.status_code == 200
    assert _read_rag_json(config_env)["rerank_model"] == "ui-rerank"


def test_put_requires_the_embedding_endpoint(config_env: Path):
    # Spec 2026-09-25 rag-endpoint-unlock D1/D3: with no silent vendor fallback, a save that
    # would leave the embedding endpoint empty is refused with a readable reason.
    with _client(system_role="admin") as client:
        response = client.put(
            "/api/rag/config",
            json={"rerank_base_url": "http://localhost:8000", "embedding_base_url": ""},
        )

    assert response.status_code == 400
    assert "embedding_base_url" in response.json()["detail"]


def test_put_requires_the_rerank_endpoint(config_env: Path):
    with _client(system_role="admin") as client:
        response = client.put(
            "/api/rag/config",
            json={"embedding_base_url": "http://localhost:8080/v1", "rerank_base_url": ""},
        )

    assert response.status_code == 400
    assert "rerank_base_url" in response.json()["detail"]


# ── the width migration (spec 2026-09-26 D5-6 / D5-7) ─────────────────────


class _Recorder:
    """Stands in for the new generation's store: records what the runner did to it."""

    def __init__(self) -> None:
        self.dropped: list[int] = []

    async def drop_collections(self) -> list[str]:
        self.dropped.append(self.dims)
        return ["kb_chunks_1536"]

    async def create_collections(self) -> None:
        return None


def _stub_runner(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail: str | None = None,
    calls: list[tuple] | None = None,
    gate: threading.Event | None = None,
) -> _Recorder:
    """Patch the migration's two heavy ends: the rebuild itself, and the Qdrant store it builds.

    ``gate`` holds the rebuild open so a case can look at the state a *running* migration
    leaves behind without racing the flip; release it to let the run finish.
    """
    from app.gateway.services import rag_migration as migration_module

    recorder = _Recorder()

    async def _migrate(store, *, vector_store, embedder, page_size=None):
        if calls is not None:
            calls.append((store, vector_store))
        if gate is not None:
            # Bounded on purpose: a failing assertion before the release must not leave the
            # app's loop waiting on this thread at teardown.
            await asyncio.to_thread(gate.wait, 10)
        if fail is not None:
            raise RuntimeError(fail)
        return None

    def _store(url, *, dense_size):
        recorder.dims = dense_size
        return recorder

    monkeypatch.setattr(migration_module.dimension_migration, "migrate_collections", _migrate)
    monkeypatch.setattr(migration_module, "KnowledgeVectorStore", _store)
    return recorder


def _attach_service(client: TestClient) -> None:
    """The gateway always wires this; the test app has no knowledge stack of its own."""
    from types import SimpleNamespace

    client.app.state.knowledge_service = SimpleNamespace(store=object(), vector_store=object())


def _migration_of(client: TestClient) -> dict | None:
    response = client.get("/api/rag/config/migration")
    assert response.status_code == 200, response.text
    return response.json()


def _settled(client: TestClient, *, tries: int = 100) -> dict | None:
    """The background task runs on the app's loop; give it a beat to leave ``running``."""
    import time

    state = _migration_of(client)
    for _ in range(tries):
        if state is None or state["state"] != "running":
            return state
        time.sleep(0.02)
        state = _migration_of(client)
    raise AssertionError(f"migration never settled: {state}")


@pytest.fixture(autouse=True)
def _clean_migration_state():
    from app.gateway.services import rag_migration as migration_module

    migration_module.reset_state()
    yield
    migration_module.reset_state()


def test_migration_status_is_null_until_a_width_change_starts_one(config_env: Path):
    with _client(system_role="admin") as client:
        _attach_service(client)
        assert _migration_of(client) is None
        body = client.get("/api/rag/config").json()
    assert body[_MIGRATION_FIELD] is None


def test_a_width_change_defers_the_width_and_starts_the_rebuild(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    """改宽度的那一次保存：其余字段立刻落地，宽度等重建完成后由后台翻（D5-7）。"""
    import threading

    _answer_with(monkeypatch, dims=1536, recorded=[])
    calls: list[tuple] = []
    gate = threading.Event()
    recorder = _stub_runner(monkeypatch, calls=calls, gate=gate)

    with _client(system_role="admin") as client:
        _attach_service(client)
        response = client.put("/api/rag/config", json={"embedding_dimension": 1536, "embedding_model": "ui-embedding"})

        assert response.status_code == 200, response.text
        started = response.json()[_MIGRATION_FIELD]
        assert started["state"] == "running"
        assert started["target_dimension"] == 1536
        # 迁移还卡在闸里 ⇒ 宽度一定还没生效：文件里仍是旧的（未声明 ⇒ 1024），其余字段已经落盘。
        stored = _read_rag_json(config_env)
        assert "embedding_dimension" not in stored
        assert stored["embedding_model"] == "ui-embedding"
        assert len(calls) == 1, "重建必须已经启动"

        gate.set()
        finished = _settled(client)

    assert finished["state"] == "succeeded", finished
    assert _read_rag_json(config_env)["embedding_dimension"] == 1536, "重建完成后才翻配置"
    assert recorder.dropped == [1024], "旧代最后被清掉（best-effort）"


def test_a_migration_that_fails_never_flips_the_width(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    """回滚＝什么都没发生：配置仍是旧宽度、旧代还在（D5-2）。"""
    _answer_with(monkeypatch, dims=1536, recorded=[])
    recorder = _stub_runner(monkeypatch, fail="向量库连不上")

    with _client(system_role="admin") as client:
        _attach_service(client)
        assert client.put("/api/rag/config", json={"embedding_dimension": 1536}).status_code == 200
        failed = _settled(client)

    assert failed["state"] == "failed"
    assert "向量库连不上" in failed["detail"]
    assert "embedding_dimension" not in _read_rag_json(config_env), "没跑完就不许翻"
    assert recorder.dropped == [], "不许删旧代"


def test_a_second_width_change_mid_migration_is_refused(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    import threading

    _answer_with(monkeypatch, dims=1536, recorded=[])
    gate = threading.Event()
    _stub_runner(monkeypatch, gate=gate)

    with _client(system_role="admin") as client:
        _attach_service(client)
        assert client.put("/api/rag/config", json={"embedding_dimension": 1536}).status_code == 200
        # 第一次的迁移还卡在闸里（桩里没让它结束）—— 第二次改宽度必须被挡在门外。
        again = client.put("/api/rag/config", json={"embedding_dimension": 768})
        gate.set()
        assert _settled(client)["state"] == "succeeded"

    assert again.status_code == 409
    assert "迁移" in again.json()["detail"]


def test_an_unrelated_edit_does_not_start_a_migration(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple] = []
    _stub_runner(monkeypatch, calls=calls)

    with _client(system_role="admin") as client:
        _attach_service(client)
        response = client.put("/api/rag/config", json={"rerank_model": "ui-rerank"})

    assert response.status_code == 200
    assert response.json()[_MIGRATION_FIELD] is None
    assert calls == [], "没改宽度就不该有迁移"


# ── 同宽换模型的自动重建（spec 2026-10-04 D3：hold→逐库重嵌→原子 flip）────────


@pytest.fixture(autouse=True)
def _clean_reembed_state():
    from app.gateway.services import rag_reembed as reembed_module

    reembed_module.reset_state()
    yield
    reembed_module.reset_state()


def _stub_reembed(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail: str | None = None,
    calls: list | None = None,
    gate: threading.Event | None = None,
) -> None:
    """Patch the rebuild's heavy end: the per-library re-embedding loop.

    Mirrors ``_stub_runner``: ``gate`` holds the run open so a case can look at the state a
    *running* rebuild leaves behind without racing the flip.
    """
    from app.gateway.services import rag_reembed as reembed_module

    async def _reembed_libraries(store, *, vector_store, embedder):
        if calls is not None:
            calls.append((store, vector_store, embedder))
        if gate is not None:
            await asyncio.to_thread(gate.wait, 10)
        if fail is not None:
            raise RuntimeError(fail)
        return {}

    monkeypatch.setattr(reembed_module, "reembed_libraries", _reembed_libraries)


def _settled_reembed(client: TestClient, *, tries: int = 100) -> dict | None:
    import time

    state = client.get("/api/rag/config").json()["reembed"]
    for _ in range(tries):
        if state is None or state["state"] != "running":
            return state
        time.sleep(0.02)
        state = client.get("/api/rag/config").json()["reembed"]
    raise AssertionError(f"reembed never settled: {state}")


def test_reembed_status_is_null_until_a_model_change_starts_one(config_env: Path):
    with _client(system_role="admin") as client:
        _attach_service(client)
        assert client.get("/api/rag/config").json()["reembed"] is None


def test_a_model_change_defers_the_model_and_rebuilds_in_place(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    """同宽换模型的那一次保存：其余字段立刻落地，模型字段等逐库重嵌完成后由后台原子翻。"""
    import threading

    _answer_with(monkeypatch, dims=1024, recorded=[])
    calls: list = []
    gate = threading.Event()
    _stub_reembed(monkeypatch, calls=calls, gate=gate)

    with _client(system_role="admin") as client:
        _attach_service(client)
        response = client.put("/api/rag/config", json={"embedding_model": "ui-embedding"})

        assert response.status_code == 200, response.text
        assert response.json()["reembed"]["state"] == "running"
        # 响应按「文件现状」报（宽度通道同款）：扣下的字段报的还是生效值，目标挂在状态里。
        assert response.json()["sources"]["embedding_model"] == "config_file"
        assert response.json()["reembed"]["target_model"] == "ui-embedding"
        # 重建还卡在闸里 ⇒ 模型字段一定还没翻：文件里仍是旧的（未声明 ⇒ 继续走 config.yaml）。
        stored = _read_rag_json(config_env)
        assert "embedding_model" not in stored
        assert len(calls) == 1, "逐库重建必须已经启动"

        gate.set()
        finished = _settled_reembed(client)

    assert finished["state"] == "succeeded", finished
    assert _read_rag_json(config_env)["embedding_model"] == "ui-embedding", "重建完成后才原子翻配置"


def test_a_reembed_that_fails_never_flips_the_model(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    """回滚＝什么都没发生：配置仍指旧模型、旧向量继续服务（spec §3 硬约束）。"""
    _answer_with(monkeypatch, dims=1024, recorded=[])
    _stub_reembed(monkeypatch, fail="向量库连不上")

    with _client(system_role="admin") as client:
        _attach_service(client)
        assert client.put("/api/rag/config", json={"embedding_model": "ui-embedding"}).status_code == 200
        failed = _settled_reembed(client)

    assert failed["state"] == "failed"
    assert "向量库连不上" in failed["detail"]
    assert "embedding_model" not in _read_rag_json(config_env), "没跑完就不许翻"


def test_a_second_save_mid_reembed_is_refused(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    import threading

    _answer_with(monkeypatch, dims=1024, recorded=[])
    gate = threading.Event()
    _stub_reembed(monkeypatch, gate=gate)

    with _client(system_role="admin") as client:
        _attach_service(client)
        assert client.put("/api/rag/config", json={"embedding_model": "ui-embedding"}).status_code == 200
        again = client.put("/api/rag/config", json={"embedding_model": "other-model"})
        gate.set()
        finished = _settled_reembed(client)

    assert again.status_code == 409
    assert finished["state"] == "succeeded", finished
    assert _read_rag_json(config_env)["embedding_model"] == "ui-embedding", "被拒的第二次保存什么都不许写"


def test_key_rotation_does_not_start_a_reembed(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    """轮换密钥不触发重建（沿 §2.3-④；指纹不含 api_key）。

    先落一版基线配置：测试客户端会给每个 PUT 注入两个端点（09-25 端点必填），
    基线里得先把它们写进去，第二次保存才是「只换密钥」。
    """
    _write_rag_json(config_env, {"embedding_model": "yaml-embedding", "embedding_base_url": "http://localhost:8080/v1", "embedding_api_key": "sk-old"})
    _answer_with(monkeypatch, dims=1024, recorded=[])
    calls: list = []
    _stub_reembed(monkeypatch, calls=calls)

    with _client(system_role="admin") as client:
        _attach_service(client)
        response = client.put("/api/rag/config", json={"embedding_api_key": "sk-rotated"})

    assert response.status_code == 200
    assert response.json()["reembed"] is None
    assert calls == [], "轮换密钥不该有重建"


def test_the_credential_waits_with_the_identity(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    """换模型连着换钥的那次保存：密钥跟着身份一起扣、一起翻——窗口里旧端点拿到的还是旧钥。

    轮换单独保存仍然立即生效（上一例）；这里钉「和重建同批」的那半：身份整套扣下、
    整套翻过去，窗口里不留「旧端点 + 新钥」的拼接态（spec 2026-10-04 D3）。
    """
    import threading

    _write_rag_json(config_env, {"embedding_model": "old-embedding", "embedding_base_url": "http://localhost:8080/v1", "embedding_api_key": "sk-old"})
    _answer_with(monkeypatch, dims=1024, recorded=[])
    gate = threading.Event()
    _stub_reembed(monkeypatch, gate=gate)

    with _client(system_role="admin") as client:
        _attach_service(client)
        response = client.put("/api/rag/config", json={"embedding_model": "new-embedding", "embedding_api_key": "sk-new"})

        assert response.status_code == 200, response.text
        stored = _read_rag_json(config_env)
        assert stored["embedding_model"] == "old-embedding"
        assert stored["embedding_api_key"] == "sk-old", "窗口里旧端点必须还拿得到旧钥"

        gate.set()
        assert _settled_reembed(client)["state"] == "succeeded"

    landed = _read_rag_json(config_env)
    assert landed["embedding_model"] == "new-embedding"
    assert landed["embedding_api_key"] == "sk-new", "整套身份一次性翻过去"


def test_a_width_change_still_takes_the_width_channel_not_reembed(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    """宽度差仍走先建后切迁移（回归钉住，不许被 D3 改道）。"""
    _answer_with(monkeypatch, dims=1536, recorded=[])
    _stub_runner(monkeypatch)
    calls: list = []
    _stub_reembed(monkeypatch, calls=calls)

    with _client(system_role="admin") as client:
        _attach_service(client)
        response = client.put("/api/rag/config", json={"embedding_dimension": 1536})

    assert response.status_code == 200, response.text
    assert response.json()[_MIGRATION_FIELD]["state"] == "running"
    assert response.json()["reembed"] is None
    assert calls == [], "宽度差走迁移，不该走同宽重建"


# ── 解析的两个旋钮（spec 2026-09-29 D1；OCR 语种那一格 2026-09-30 已撤）──────


def test_the_two_parse_knobs_round_trip_with_their_sources(config_env: Path):
    """Write / read / withdraw for `parse_language`, `parse_model_version`."""
    with _client(system_role="admin") as client:
        saved = client.put(
            "/api/rag/config",
            json={"parse_language": "en", "parse_model_version": "pipeline"},
        )

    assert saved.status_code == 200
    assert saved.json()["sources"]["parse_language"] == "ui"
    assert saved.json()["sources"]["parse_model_version"] == "ui"

    # 清空 = 撤销覆盖。⚠ 枚举字段必须以 **`null`**（不是 `""`）表达"撤销"：`""` 过不了
    # 字段的 Literal 校验 ⇒ 422（既有 `parse_tier` / `sparse_provider` / `rerank_provider`
    # 今天就踩这个坑 —— Task 2 把 `SELECT_FIELDS` 的清空编码改成 `null`，见 plan Task 2）。
    with _client(system_role="admin") as client:
        withdrawn = client.put(
            "/api/rag/config",
            json={"parse_language": None, "parse_model_version": None},
        )

    assert withdrawn.status_code == 200
    assert withdrawn.json()["sources"]["parse_language"] == "config_file"
    assert withdrawn.json()["sources"]["parse_model_version"] == "config_file"

    with _client(system_role="admin") as client:
        after = client.get("/api/rag/config").json()

    assert after["config"]["parse_language"] == "ch"
    assert after["config"]["parse_model_version"] == "vlm"


def test_an_out_of_enum_parse_knob_is_rejected_with_422(config_env: Path):
    with _client(system_role="admin") as client:
        assert client.put("/api/rag/config", json={"parse_language": "not-a-language"}).status_code == 422
        assert client.put("/api/rag/config", json={"parse_model_version": "MinerU-HTML"}).status_code == 422
