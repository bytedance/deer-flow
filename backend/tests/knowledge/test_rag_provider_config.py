"""Task 1 (spec 2026-09-14 rag model provider adaptation): the provider dimension.

Covers the config-layer half of the adaptation:

* the new ``rag.*`` provider fields — typed defaults on ``RagConfig`` and the
  all-optional mirror on the UI-writable ``RagConfigFile``;
* the **old-config guard**, which is the load-bearing case: a ``config.yaml``
  that only sets ``embedding_model`` / ``rerank_model`` must resolve to exactly
  the providers it does today;
* the curated provider allowlist (leg + provider id -> implementation, endpoint
  key, and secret env var), and its refusal of anything outside it — a free-text
  class path here would be the same code-execution surface as ``plugins:``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from deerflow.config.app_config import RagConfig, reset_app_config
from deerflow.config.rag_config_file import RagConfigFile
from deerflow.knowledge.providers import (
    PROVIDER_ALLOWLIST,
    provider_ids,
    resolve_provider,
    secret_env_var,
)

SANDBOX = {"use": "deerflow.sandbox.local:LocalSandboxProvider"}

#: The pre-adaptation ``rag:`` block — no provider, no base_url, no sparse keys.
LEGACY_YAML_RAG = {
    "qdrant_url": "http://qdrant:6333",
    "embedding_model": "yaml-embedding",
    "rerank_model": "yaml-rerank",
    "vlm_model": "yaml-vlm",
}


def _write_config_yaml(path: Path, rag: dict) -> Path:
    path.write_text(
        yaml.safe_dump({"sandbox": SANDBOX, "models": [], "rag": rag}),
        encoding="utf-8",
    )
    return path


def _write_rag_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.fixture
def env_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point every config file at an isolated tmp path, so the repo root's real
    ``models_config.json`` / ``rag_config.json`` can never leak into expectations."""
    config_yaml = tmp_path / "config.yaml"
    extensions = tmp_path / "extensions_config.json"
    models_json = tmp_path / "models_config.json"
    rag_json = tmp_path / "rag_config.json"
    extensions.write_text(json.dumps({"mcpServers": {}, "skills": {}}), encoding="utf-8")
    models_json.write_text(json.dumps({"models": []}), encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_yaml))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions))
    monkeypatch.setenv("DEER_FLOW_MODELS_CONFIG_PATH", str(models_json))
    monkeypatch.setenv("DEER_FLOW_RAG_CONFIG_PATH", str(rag_json))
    reset_app_config()
    yield config_yaml, rag_json
    reset_app_config()


# ── old-config guard ──────────────────────────────────────────────────────


def test_legacy_yaml_only_sets_models_and_keeps_provider_defaults(env_paths):
    """A config.yaml written before this feature must resolve to today's providers."""
    config_yaml, _ = env_paths
    _write_config_yaml(config_yaml, LEGACY_YAML_RAG)

    rag = RagConfig.model_validate(LEGACY_YAML_RAG)

    assert rag.embedding_model == "yaml-embedding"
    assert rag.embedding_provider == "dashscope"
    assert rag.rerank_provider == "dashscope"
    assert rag.parse_provider == "mineru-cloud"
    assert rag.embedding_sparse_source == "provider"
    # Empty means "use the provider default" / "probe at enable time".
    assert rag.embedding_base_url is None
    assert rag.embedding_dimension is None
    assert rag.rerank_base_url is None
    assert rag.parse_base_url is None
    assert rag.parse_tier is None


def test_legacy_rag_json_without_new_fields_still_loads(env_paths):
    """The UI-writable file is all-optional, so an existing one keeps loading."""
    _, rag_json = env_paths
    _write_rag_json(rag_json, {"embedding_model": "ui-embedding", "mineru_api_token": "tok"})

    ui = RagConfigFile.from_file()

    assert ui.embedding_model == "ui-embedding"
    assert ui.embedding_provider is None
    assert ui.embedding_sparse_source is None
    assert ui.sparse_provider is None
    assert ui.parse_provider is None


def test_a_retired_parse_backend_key_is_stripped_with_a_warning(env_paths, caplog):
    """3.4.5 的 `parse_backend` 已退役：老文件仍可载，但键被剥掉（不是把文件判死）。"""
    _, rag_json = env_paths
    _write_rag_json(
        rag_json,
        {"parse_provider": "mineru-local", "parse_base_url": "http://localhost:30000", "parse_backend": "hybrid"},
    )

    with caplog.at_level(logging.WARNING, logger="deerflow.config.rag_config_file"):
        ui = RagConfigFile.from_file()

    assert ui.parse_provider == "mineru-local"
    assert ui.parse_tier is None, "旧值不做映射：vlm / hybrid 在 4.x 没有对应语义（D2）"
    assert "parse_backend" in caplog.text


def test_a_retired_parse_backend_key_in_yaml_is_ignored():
    """config.yaml 侧静默忽略（pydantic 未知键的默认行为；登记为知情选择）—— 文档要写这句。"""
    rag = RagConfig.model_validate({"parse_backend": "hybrid"})

    assert rag.parse_tier is None


def test_sparse_keys_declared_in_yaml_are_carried_by_rag_config():
    rag = RagConfig.model_validate(
        {
            "embedding_provider": "openai-compatible",
            "embedding_base_url": "http://localhost:8080/v1",
            "embedding_dimension": 1024,
            "embedding_sparse_source": "bm25",
            "rerank_provider": "generic-rerank",
            "rerank_base_url": "http://localhost:8000",
            "parse_provider": "mineru-local",
            "parse_base_url": "http://localhost:30000",
            "parse_tier": "advanced",
        }
    )

    assert rag.embedding_provider == "openai-compatible"
    assert rag.embedding_base_url == "http://localhost:8080/v1"
    assert rag.embedding_dimension == 1024
    assert rag.embedding_sparse_source == "bm25"
    assert rag.rerank_provider == "generic-rerank"
    assert rag.parse_provider == "mineru-local"
    assert rag.parse_tier == "advanced"


# ── the provider allowlist ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("leg", "provider_id", "expected_impl", "expected_endpoint_key"),
    [
        ("embedding", "dashscope", "deerflow.knowledge.embedder:DashScopeEmbedder", "base_url"),
        ("embedding", "volcengine-ark", "deerflow.knowledge.embedder_ark:ArkEmbedder", "base_url"),
        ("embedding", "openai-compatible", "deerflow.knowledge.embedder_openai:OpenAICompatibleEmbedder", "base_url"),
        ("rerank", "dashscope", "deerflow.knowledge.reranker:DashScopeReranker", "base_url"),
        ("rerank", "generic-rerank", "deerflow.knowledge.reranker_generic:GenericReranker", "base_url"),
        ("rerank", "tei-rerank", "deerflow.knowledge.reranker_tei:TEIReranker", "base_url"),
        ("parse", "mineru-cloud", "deerflow.knowledge.parser:MineruCloudParseProvider", "base_url"),
        ("parse", "mineru-local", "deerflow.knowledge.parse_local:MineruLocalParseProvider", "base_url"),
        ("sparse", "tei-sparse", "deerflow.knowledge.sparse:TEISparseEncoder", "base_url"),
    ],
)
def test_allowlist_resolves_each_supported_provider(leg, provider_id, expected_impl, expected_endpoint_key):
    spec = resolve_provider(leg, provider_id)

    assert spec.leg == leg
    assert spec.provider_id == provider_id
    assert spec.implementation == expected_impl
    assert spec.endpoint_key == expected_endpoint_key


def test_provider_ids_lists_the_curated_set_per_leg():
    # Declaration order is what the settings UI renders, and the two dual-path providers sit
    # together (spec 2026-09-17): both return dense+sparse in one call.
    assert provider_ids("embedding") == ("dashscope", "volcengine-ark", "openai-compatible")
    assert provider_ids("rerank") == ("dashscope", "generic-rerank", "tei-rerank")
    assert provider_ids("parse") == ("mineru-cloud", "mineru-local")
    assert provider_ids("sparse") == ("tei-sparse",)


def test_sparse_leg_path_is_pinned_to_the_verified_shape():
    """P3 定的形状：Text Embeddings Inference 的 ``/embed_sparse``（上游源码核对）。

    ``path`` 曾经刻意留空（形状未定）；现在钉住它，客户端按同一常量发请求。
    """
    assert resolve_provider("sparse", "tei-sparse").path == "/embed_sparse"


def test_tei_rerank_row_is_pinned_to_the_verified_shape():
    """D3 甲（spec 2026-09-24 §4.3）：TEI 只有一条 ``/rerank`` 路由，且没有内置地址。

    ``takes_model=False`` 是这一行与另两行的真差别：请求里没有 ``model`` 字段，客户端也就
    不该收这个参数 —— 工厂按**能力**决定要不要把它交下去，不按 provider id。
    """
    spec = resolve_provider("rerank", "tei-rerank")

    assert spec.path == "/rerank"
    assert spec.secret_env_var == "RAG_RERANK_API_KEY"
    assert spec.has_fixed_endpoint is False and spec.default_endpoint is None
    assert spec.takes_model is False


def test_allowlist_rejects_an_unknown_provider_id():
    with pytest.raises(ValueError, match="embedding"):
        resolve_provider("embedding", "not-a-provider")


def test_allowlist_rejects_a_free_text_class_path():
    """A class path smuggled in as a provider id must never resolve."""
    with pytest.raises(ValueError):
        resolve_provider("embedding", "evil.module:EvilEmbedder")


def test_allowlist_rejects_an_unknown_leg():
    with pytest.raises(ValueError):
        resolve_provider("transcription", "dashscope")


def test_allowlist_leg_keys_match_the_declared_legs():
    assert set(PROVIDER_ALLOWLIST) == {"embedding", "rerank", "parse", "sparse"}


# ── per-provider secret env fallback ──────────────────────────────────────


def test_secret_env_var_keeps_the_existing_names_for_dashscope():
    assert secret_env_var("embedding", "dashscope") == "DASHSCOPE_EMBEDDING_API_KEY"
    assert secret_env_var("rerank", "dashscope") == "DASHSCOPE_RERANK_API_KEY"
    assert secret_env_var("parse", "mineru-cloud") == "MINERU_API_TOKEN"


def test_secret_env_var_uses_a_generic_name_for_new_providers():
    assert secret_env_var("embedding", "openai-compatible") == "RAG_EMBEDDING_API_KEY"
    assert secret_env_var("rerank", "generic-rerank") == "RAG_RERANK_API_KEY"
    assert secret_env_var("sparse", "tei-sparse") == "RAG_SPARSE_API_KEY"


def test_local_parse_needs_no_secret():
    """The local MinerU service ships without auth, so there is no fallback name."""
    assert secret_env_var("parse", "mineru-local") is None


def test_dashscope_secret_env_names_agree_with_the_legacy_table():
    """``SECRET_ENV_VARS`` predates the allowlist and is what the ingestion clients
    import. The dashscope rows must not drift from it, or the name the admin API
    reports as the current source differs from the one the client actually reads."""
    from deerflow.config.rag_config_file import SECRET_ENV_VARS

    assert secret_env_var("embedding", "dashscope") == SECRET_ENV_VARS["embedding_api_key"]
    assert secret_env_var("rerank", "dashscope") == SECRET_ENV_VARS["rerank_api_key"]
    assert secret_env_var("parse", "mineru-cloud") == SECRET_ENV_VARS["mineru_api_token"]


def test_sparse_emission_is_declared_per_embedding_provider():
    """Task 6's cross-check reads this: only a dual-emitting provider may be
    paired with ``sparse_source=provider``."""
    assert resolve_provider("embedding", "dashscope").emits_sparse is True
    assert resolve_provider("embedding", "openai-compatible").emits_sparse is False


# ── literal validation ────────────────────────────────────────────────────


def test_parse_provider_rejects_an_unknown_value():
    with pytest.raises(ValidationError):
        RagConfig.model_validate({"parse_provider": "mineru-remote"})


def test_parse_tier_accepts_the_four_service_tiers():
    """4.x 的档位是 flash|basic|standard|advanced；3.4.5 的 vlm/hybrid 不再接受。"""
    for tier in ("flash", "basic", "standard", "advanced"):
        assert RagConfig.model_validate({"parse_tier": tier}).parse_tier == tier
    for retired in ("vlm", "hybrid", "pipeline"):
        with pytest.raises(ValidationError):
            RagConfig.model_validate({"parse_tier": retired})


def test_sparse_source_rejects_an_unknown_value():
    with pytest.raises(ValidationError):
        RagConfig.model_validate({"embedding_sparse_source": "splade"})


def test_embedding_provider_rejects_an_unknown_value():
    with pytest.raises(ValidationError):
        RagConfig.model_validate({"embedding_provider": "some-vendor"})
