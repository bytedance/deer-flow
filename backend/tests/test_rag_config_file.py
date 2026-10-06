"""Seam B tests for the API-writable ``rag_config.json`` (spec 2026-09-10 rag functional-model config).

Covers: field-level override of config.yaml's ``rag:`` block (file wins), deep merge of
the nested ``video`` block, fallback when the file is absent/empty, loud failure on a
malformed file, crash-safe atomic write, hot reload through ``get_app_config()`` when
only the rag file changes, the key sentinel, and the ``file > env`` secret resolution
the ingestion clients rely on.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import pytest
import yaml

from deerflow.config.app_config import AppConfig, get_app_config, reset_app_config
from deerflow.config.rag_config_file import (
    MASKED_SECRET,
    RagConfigFile,
    atomic_write_rag_config,
    merge_rag_config,
    preserve_secret,
)

SANDBOX = {"use": "deerflow.sandbox.local:LocalSandboxProvider"}

YAML_RAG = {
    "qdrant_url": "http://qdrant:6333",
    "embedding_model": "yaml-embedding",
    "rerank_model": "yaml-rerank",
    "vlm_model": "yaml-vlm",
    "extract_model": "yaml-extract",
    "worker_concurrency": 4,
    "video": {"enabled": True, "max_size_mb": 512, "asr_model": "yaml-asr"},
}


def _write_config_yaml(path: Path, rag: dict | None = None) -> Path:
    path.write_text(
        yaml.safe_dump({"sandbox": SANDBOX, "models": [], "rag": rag if rag is not None else dict(YAML_RAG)}),
        encoding="utf-8",
    )
    return path


def _write_rag_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.fixture
def env_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point config.yaml / models / rag files at isolated tmp paths."""
    config_yaml = tmp_path / "config.yaml"
    extensions = tmp_path / "extensions_config.json"
    models_json = tmp_path / "models_config.json"
    rag_json = tmp_path / "rag_config.json"
    extensions.write_text(json.dumps({"mcpServers": {}, "skills": {}}), encoding="utf-8")
    # An empty but present models file keeps the repo-root models_config.json out of
    # the test (an explicit env var is an operator assertion, and the real root file
    # would otherwise be merged into every expectation here).
    models_json.write_text(json.dumps({"models": []}), encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_yaml))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions))
    monkeypatch.setenv("DEER_FLOW_MODELS_CONFIG_PATH", str(models_json))
    monkeypatch.setenv("DEER_FLOW_RAG_CONFIG_PATH", str(rag_json))
    reset_app_config()
    yield config_yaml, rag_json
    reset_app_config()


# ── merge semantics ───────────────────────────────────────────────────────


def test_file_overrides_only_the_fields_it_declares(env_paths):
    config_yaml, rag_json = env_paths
    _write_config_yaml(config_yaml)
    _write_rag_json(
        rag_json,
        {"embedding_model": "ui-embedding", "embedding_api_key": "sk-embed", "extract_model": "ui-extract"},
    )

    rag = get_app_config().rag

    assert rag.embedding_model == "ui-embedding"
    assert rag.embedding_api_key == "sk-embed"
    assert rag.extract_model == "ui-extract"
    # Untouched fields keep the config.yaml values.
    assert rag.rerank_model == "yaml-rerank"
    assert rag.worker_concurrency == 4


def test_video_block_deep_merges(env_paths):
    config_yaml, rag_json = env_paths
    _write_config_yaml(config_yaml)
    _write_rag_json(rag_json, {"video": {"asr_model": "ui-asr", "asr_provider": "whisper"}})

    video = get_app_config().rag.video

    assert video.asr_model == "ui-asr"
    assert video.asr_provider == "whisper"
    # The operator's graph/ingestion switches survive.
    assert video.enabled is True
    assert video.max_size_mb == 512


def test_env_asserted_path_must_exist(env_paths):
    """A set ``DEER_FLOW_RAG_CONFIG_PATH`` is an operator assertion (mirrors models_config)."""
    config_yaml, _rag_json = env_paths
    _write_config_yaml(config_yaml)

    with pytest.raises(FileNotFoundError, match="DEER_FLOW_RAG_CONFIG_PATH"):
        get_app_config()


def test_no_file_configured_keeps_config_yaml_values(env_paths, monkeypatch: pytest.MonkeyPatch):
    """Search mode: no rag file anywhere means config.yaml stands on its own."""
    config_yaml, _rag_json = env_paths
    _write_config_yaml(config_yaml)
    monkeypatch.setattr(RagConfigFile, "resolve_config_path", classmethod(lambda cls, config_path=None: None))
    reset_app_config()

    rag = get_app_config().rag

    assert rag.embedding_model == "yaml-embedding"
    assert rag.rerank_model == "yaml-rerank"
    assert rag.embedding_api_key is None


def test_empty_file_is_a_no_op(env_paths):
    config_yaml, rag_json = env_paths
    _write_config_yaml(config_yaml)
    _write_rag_json(rag_json, {})

    rag = get_app_config().rag

    assert rag.embedding_model == "yaml-embedding"
    assert rag.vlm_model == "yaml-vlm"


def test_malformed_json_raises(env_paths):
    config_yaml, rag_json = env_paths
    _write_config_yaml(config_yaml)
    rag_json.write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError, match="not valid JSON"):
        get_app_config()


def test_unknown_field_is_rejected(env_paths):
    config_yaml, rag_json = env_paths
    _write_config_yaml(config_yaml)
    _write_rag_json(rag_json, {"embedding_modle": "typo"})

    with pytest.raises(ValueError):
        RagConfigFile.from_file()


# ── retired keys: stripped before validation, names only in the warning ────
# Spec 2026-09-23 D10.4/R18: three keys retire together and they do not share a level --
# `vlm_base_url` / `vlm_api_key` sit at the top, `video.caption_model` one level down inside
# a block that forbids extras too. A stored file has to keep loading, so both levels are
# stripped before validation; nothing is written back, and the warning names fields only --
# the addresses and keys are exactly what must not leak into a log line (R22: this assertion
# is new, the `parse_backend` precedent never pinned it).

RETIRED_VLM_BASE_URL = "http://retired-vlm-sentinel.example:9/v1"
RETIRED_VLM_API_KEY = "sk-retired-vlm-sentinel"
RETIRED_CAPTION_MODEL = "retired-caption-sentinel"


def test_retired_keys_are_stripped_from_a_legacy_file(env_paths, caplog):
    config_yaml, rag_json = env_paths
    _write_config_yaml(config_yaml)
    _write_rag_json(
        rag_json,
        {
            "vlm_base_url": RETIRED_VLM_BASE_URL,
            "vlm_api_key": RETIRED_VLM_API_KEY,
            "vlm_model": "ui-vlm",
            "default_model": "ui-default",
            "video": {"caption_model": RETIRED_CAPTION_MODEL, "asr_provider": "whisper", "asr_model": "ui-asr"},
        },
    )

    with caplog.at_level(logging.WARNING, logger="deerflow.config.rag_config_file"):
        declared = RagConfigFile.from_file().model_dump(exclude_none=True)

    assert "vlm_base_url" not in declared
    assert "vlm_api_key" not in declared
    assert declared["vlm_model"] == "ui-vlm"  # the successor field still arrives
    assert declared["default_model"] == "ui-default"
    # The nested strip takes one key, not the block: the video fields the UI still owns are here.
    assert declared["video"] == {"asr_provider": "whisper", "asr_model": "ui-asr"}
    for name in ("vlm_base_url", "vlm_api_key", "video.caption_model"):
        assert name in caplog.text
    for sentinel in (RETIRED_VLM_BASE_URL, RETIRED_VLM_API_KEY, RETIRED_CAPTION_MODEL):
        assert sentinel not in caplog.text


def test_retired_keys_coexist_with_the_mineru_normalization(env_paths, caplog):
    """`parse_backend` keeps its own reason: the VLM keys must not borrow the MinerU one."""
    config_yaml, rag_json = env_paths
    _write_config_yaml(config_yaml)
    _write_rag_json(
        rag_json,
        {"parse_backend": "hybrid", "parse_provider": "mineru-local", "vlm_api_key": RETIRED_VLM_API_KEY, "video": {"caption_model": RETIRED_CAPTION_MODEL}},
    )

    with caplog.at_level(logging.WARNING, logger="deerflow.config.rag_config_file"):
        ui = RagConfigFile.from_file()

    assert ui.parse_provider == "mineru-local"
    assert "parse_tier" in caplog.text  # the MinerU reason survived the change


def test_a_legacy_file_reloads_through_the_real_loader_and_is_stripped_again(env_paths, caplog, monkeypatch: pytest.MonkeyPatch):
    """Auto hot reload keeps working for a file that carries retired keys.

    The signature covers the rag file, so a legacy key arriving on the next save must not
    turn the reload into a failure -- and the loader must really run (counter + log line),
    not just the value change.
    """
    from deerflow.config import app_config as app_config_module

    config_yaml, rag_json = env_paths
    _write_config_yaml(config_yaml)
    _write_rag_json(rag_json, {"rerank_model": "first"})
    assert get_app_config().rag.rerank_model == "first"

    loads: list[str] = []
    original = app_config_module._load_and_cache_app_config
    monkeypatch.setattr(app_config_module, "_load_and_cache_app_config", lambda path=None: loads.append(str(path)) or original(path))

    _write_rag_json(rag_json, {"rerank_model": "second", "vlm_api_key": RETIRED_VLM_API_KEY, "video": {"caption_model": RETIRED_CAPTION_MODEL}})
    with caplog.at_level(logging.INFO, logger="deerflow.config.app_config"):
        after = get_app_config()

    assert len(loads) == 1, "a changed rag file must go through the loader"
    assert "Rag config file changed, reloading AppConfig" in caplog.text
    assert after.rag.rerank_model == "second"
    declared = RagConfigFile.from_file().model_dump(exclude_none=True)
    assert "vlm_api_key" not in declared
    assert "caption_model" not in (declared.get("video") or {})

    assert get_app_config() is after, "an unchanged file still hits the cache"
    assert len(loads) == 1


def test_reading_a_legacy_file_does_not_write_it_back(env_paths):
    config_yaml, rag_json = env_paths
    _write_config_yaml(config_yaml)
    _write_rag_json(rag_json, {"rerank_model": "ui", "vlm_api_key": RETIRED_VLM_API_KEY, "video": {"caption_model": RETIRED_CAPTION_MODEL}})
    before = rag_json.read_bytes()

    RagConfigFile.from_file()
    RagConfigFile.from_file()

    assert rag_json.read_bytes() == before


def test_non_object_json_is_rejected(env_paths):
    config_yaml, rag_json = env_paths
    _write_config_yaml(config_yaml)
    rag_json.write_text("[1, 2, 3]", encoding="utf-8")

    with pytest.raises(ValueError, match="must be a JSON object"):
        RagConfigFile.from_file()


def test_near_miss_and_nested_unknown_keys_are_still_rejected(env_paths):
    """Stripping is not ignoring: only the retired names go, both `extra="forbid"` stay."""
    config_yaml, rag_json = env_paths
    _write_config_yaml(config_yaml)

    _write_rag_json(rag_json, {"vlm_typo": "x"})
    with pytest.raises(ValueError):
        RagConfigFile.from_file()

    _write_rag_json(rag_json, {"video": {"caption_modle": "typo"}})
    with pytest.raises(ValueError):
        RagConfigFile.from_file()


def test_merge_is_pure_and_yaml_input_untouched():
    yaml_rag = {"embedding_model": "yaml", "video": {"enabled": True}}
    ui = RagConfigFile.model_validate({"embedding_model": "ui", "video": {"asr_model": "ui-asr"}})

    merged = merge_rag_config(yaml_rag, ui)

    assert merged["embedding_model"] == "ui"
    assert merged["video"] == {"enabled": True, "asr_model": "ui-asr"}
    assert yaml_rag == {"embedding_model": "yaml", "video": {"enabled": True}}


# ── hot reload ────────────────────────────────────────────────────────────


def test_changing_only_the_rag_file_reloads_app_config(env_paths):
    config_yaml, rag_json = env_paths
    _write_config_yaml(config_yaml)
    _write_rag_json(rag_json, {"rerank_model": "first"})
    assert get_app_config().rag.rerank_model == "first"

    _write_rag_json(rag_json, {"rerank_model": "second"})

    assert get_app_config().rag.rerank_model == "second"


# ── RAG default model: the field, its blank normalisation, its hot reload ──
# Spec 2026-09-23 default model D2/D3 (revisions R1-R28). The field is the merge
# target the RAG resolver reads; the blank rule is what makes "clear it in the
# UI" mean "withdraw the override" rather than "declare an empty name".

MODEL_REFERENCE_FIELDS = ("default_model", "extract_model", "judge_model", "vlm_model", "wiki_model", "synthesis_model")


def test_the_local_blank_rule_list_matches_the_production_one():
    """A stale copy here is how a newly added role escapes the blank rule silently.

    The parametrised case below only covers what this module lists, so the module list and
    ``RagConfigFile``'s own ``MODEL_REFERENCE_FIELDS`` (the validator's argument) must move
    together: diverge and one of them is testing/carrying less than the other claims.
    """
    from deerflow.config import rag_config_file

    assert MODEL_REFERENCE_FIELDS == rag_config_file.MODEL_REFERENCE_FIELDS


def test_default_model_file_overrides_config_yaml_then_undoes(env_paths):
    config_yaml, rag_json = env_paths
    _write_config_yaml(config_yaml, {**dict(YAML_RAG), "default_model": "yaml-default"})
    _write_rag_json(rag_json, {"default_model": "ui-default"})
    assert get_app_config().rag.default_model == "ui-default"

    # Withdrawing the UI override falls back to config.yaml -- it does not force None.
    _write_rag_json(rag_json, {})
    assert get_app_config().rag.default_model == "yaml-default"


def test_default_model_defaults_to_none(env_paths):
    config_yaml, rag_json = env_paths
    _write_config_yaml(config_yaml)
    _write_rag_json(rag_json, {})

    assert get_app_config().rag.default_model is None


@pytest.mark.parametrize("field", MODEL_REFERENCE_FIELDS)
@pytest.mark.parametrize("blank", ["", " ", "\t\n "])
def test_blank_model_reference_withdraws_the_override_instead_of_declaring_it(env_paths, field: str, blank: str):
    """``RagConfigFile``'s field validator turns blank into ``None`` for all four fields.

    Normalising here rather than in the resolver is what makes the *file* side honest:
    ``_prune_empty()`` only drops ``None``/``""``, so without this the whitespace string
    would be written to disk, reported as ``ui`` by ``sources`` and echoed back by GET.
    """
    config_yaml, rag_json = env_paths
    _write_config_yaml(config_yaml, {**dict(YAML_RAG), field: f"yaml-{field}"})
    _write_rag_json(rag_json, {field: blank})

    # The blank declaration is not an override, so config.yaml's own value stands.
    assert getattr(get_app_config().rag, field) == f"yaml-{field}"
    # ... and it is not carried as a declared value either.
    assert field not in RagConfigFile.from_file().model_dump(exclude_none=True)


def test_blank_default_model_with_no_yaml_counterpart_is_none(env_paths):
    config_yaml, rag_json = env_paths
    _write_config_yaml(config_yaml)
    _write_rag_json(rag_json, {"default_model": "   "})

    assert get_app_config().rag.default_model is None


# ── wiki / synthesis: the two roles that had no field at all (spec 2026-09-26) ──


@pytest.mark.parametrize("field", ["wiki_model", "synthesis_model"])
def test_a_role_field_overrides_config_yaml_then_undoes(env_paths, field: str):
    """Same two-step as ``default_model``: the UI file wins, withdrawing it falls back.

    Withdrawing must fall back to config.yaml's own value rather than forcing ``None`` --
    an operator who declared the role in their own file keeps that declaration.
    """
    config_yaml, rag_json = env_paths
    _write_config_yaml(config_yaml, {**dict(YAML_RAG), field: f"yaml-{field}"})
    _write_rag_json(rag_json, {field: f"ui-{field}"})
    assert getattr(get_app_config().rag, field) == f"ui-{field}"

    _write_rag_json(rag_json, {})
    assert getattr(get_app_config().rag, field) == f"yaml-{field}"


@pytest.mark.parametrize("field", ["wiki_model", "synthesis_model"])
def test_a_role_field_with_neither_source_is_none(env_paths, field: str):
    config_yaml, rag_json = env_paths
    _write_config_yaml(config_yaml)
    _write_rag_json(rag_json, {})

    assert getattr(get_app_config().rag, field) is None
    assert field not in RagConfigFile.from_file().model_dump(exclude_none=True)


def test_changing_only_the_rag_default_reloads_through_the_resolver(env_paths):
    """Auto hot reload: the signature covers the rag file, so a default change applies.

    Proven through the *real* resolver rather than by reading the field back, because the
    field alone cannot show whether the next ingest would actually pick the new target.
    """
    from deerflow.knowledge.model_target import resolve_rag_model_name

    config_yaml, rag_json = env_paths
    _write_config_yaml(config_yaml)
    models_json = Path(os.environ["DEER_FLOW_MODELS_CONFIG_PATH"])
    models_json.write_text(
        json.dumps(
            {
                "models": [
                    {"name": "A", "use": "langchain_openai:ChatOpenAI", "model": "gpt-test"},
                    {"name": "B", "use": "langchain_openai:ChatOpenAI", "model": "gpt-test"},
                ]
            }
        ),
        encoding="utf-8",
    )
    _write_rag_json(rag_json, {"default_model": "A"})
    before = get_app_config()
    assert resolve_rag_model_name(before) == "A"

    _write_rag_json(rag_json, {"default_model": "B"})
    after = get_app_config()

    assert after is not before
    assert resolve_rag_model_name(after) == "B"


# ── atomic write + sentinel ───────────────────────────────────────────────


def test_atomic_write_leaves_no_temp_file(tmp_path: Path):
    target = tmp_path / "rag_config.json"

    atomic_write_rag_config(target, {"embedding_model": "x"})

    assert json.loads(target.read_text(encoding="utf-8")) == {"embedding_model": "x"}
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != target.name]
    assert leftovers == []


def test_atomic_write_retries_a_transient_replace_collision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Windows 读方句柄让 os.replace 报 13（spec 2026-10-05 ③）：瞬态撞车要重试，不许打死写方。"""
    target = tmp_path / "rag_config.json"
    calls: list[tuple] = []
    real_replace = os.replace

    def _collide_once(src, dst):
        calls.append((src, dst))
        if len(calls) == 1:
            raise PermissionError(13, "拒绝访问。")
        return real_replace(src, dst)

    monkeypatch.setattr("os.replace", _collide_once)
    atomic_write_rag_config(target, {"embedding_model": "x"})

    assert json.loads(target.read_text(encoding="utf-8")) == {"embedding_model": "x"}
    assert len(calls) == 2, "首试撞车一次，重试后落盘"


def test_atomic_write_gives_up_after_the_bounded_retries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """耗尽必须抛（1 次首试 + 3 次重试）：无界重试会把常驻读方变成任务悬挂。"""
    target = tmp_path / "rag_config.json"
    calls: list[tuple] = []

    def _collide_always(src, dst):
        calls.append((src, dst))
        raise PermissionError(13, "拒绝访问。")

    monkeypatch.setattr("os.replace", _collide_always)
    with pytest.raises(PermissionError):
        atomic_write_rag_config(target, {"embedding_model": "x"})

    assert len(calls) == 4, "1 次首试 + 3 次重试后放弃"


def test_preserve_secret_honors_the_sentinel():
    assert preserve_secret(MASKED_SECRET, "sk-stored") == "sk-stored"
    assert preserve_secret("sk-new", "sk-stored") == "sk-new"


# ── secret resolution for the ingestion clients ───────────────────────────


def test_config_secret_wins_over_env(env_paths, monkeypatch: pytest.MonkeyPatch):
    config_yaml, rag_json = env_paths
    _write_config_yaml(config_yaml)
    _write_rag_json(rag_json, {"embedding_api_key": "sk-file", "rerank_api_key": "sk-rerank-file"})
    monkeypatch.setenv("DASHSCOPE_EMBEDDING_API_KEY", "sk-env")
    monkeypatch.setenv("DASHSCOPE_RERANK_API_KEY", "sk-env")

    from deerflow.knowledge.embedder import DashScopeEmbedder
    from deerflow.knowledge.reranker import DashScopeReranker

    assert DashScopeEmbedder()._read_api_key() == "sk-file"
    assert DashScopeReranker()._read_api_key() == "sk-rerank-file"


def test_env_still_used_when_the_file_declares_no_secret(env_paths, monkeypatch: pytest.MonkeyPatch):
    config_yaml, rag_json = env_paths
    _write_config_yaml(config_yaml)
    _write_rag_json(rag_json, {"embedding_model": "ui-embedding"})
    monkeypatch.setenv("DASHSCOPE_EMBEDDING_API_KEY", "sk-env")

    from deerflow.knowledge.embedder import DashScopeEmbedder

    assert DashScopeEmbedder()._read_api_key() == "sk-env"


def test_explicit_constructor_key_beats_the_file(env_paths):
    config_yaml, rag_json = env_paths
    _write_config_yaml(config_yaml)
    _write_rag_json(rag_json, {"embedding_api_key": "sk-file"})

    from deerflow.knowledge.embedder import DashScopeEmbedder

    assert DashScopeEmbedder(api_key="sk-arg")._read_api_key() == "sk-arg"


def test_missing_secret_raises_with_the_env_hint(env_paths, monkeypatch: pytest.MonkeyPatch):
    config_yaml, rag_json = env_paths
    _write_config_yaml(config_yaml)
    _write_rag_json(rag_json, {})
    monkeypatch.delenv("DASHSCOPE_EMBEDDING_API_KEY", raising=False)

    from deerflow.knowledge.embedder import DashScopeEmbedder, EmbedderAuthError

    with pytest.raises(EmbedderAuthError, match="DASHSCOPE_EMBEDDING_API_KEY"):
        DashScopeEmbedder()._read_api_key()


def test_app_config_can_be_built_without_a_rag_file(env_paths, monkeypatch: pytest.MonkeyPatch):
    """A deployment that only uses config.yaml keeps loading unchanged."""
    config_yaml, _rag_json = env_paths
    _write_config_yaml(config_yaml)
    monkeypatch.setattr(RagConfigFile, "resolve_config_path", classmethod(lambda cls, config_path=None: None))

    config = AppConfig.from_file(str(config_yaml))

    assert config.rag.embedding_model == "yaml-embedding"


# ── eval judge role ───────────────────────────────────────────────────────


def test_judge_model_file_overrides_config_yaml(env_paths):
    """The eval judge is a UI-manageable role like the rest: the file wins, config.yaml is the fallback."""
    config_yaml, rag_json = env_paths
    _write_config_yaml(config_yaml, rag={**YAML_RAG, "judge_model": "yaml-judge"})
    _write_rag_json(rag_json, {"judge_model": "ui-judge"})

    assert get_app_config().rag.judge_model == "ui-judge"

    _write_rag_json(rag_json, {})

    assert get_app_config().rag.judge_model == "yaml-judge"


def test_judge_model_defaults_to_none(env_paths):
    """Unset everywhere reads as None, which the eval path resolves to the config primary model."""
    config_yaml, rag_json = env_paths
    _write_config_yaml(config_yaml)
    _write_rag_json(rag_json, {})

    assert get_app_config().rag.judge_model is None


# ── parse knobs: language / model version (spec 2026-09-29) ──
# 两个都是"值字段"（不是条目引用）：不做空白归一，非枚举值是**硬报错**
# （与 `parse_tier` 今天的形状一致，spec §6.2 已登记）。

PARSE_KNOB_VALUES = {"parse_language": ("en", "japan"), "parse_model_version": ("pipeline", "vlm")}


@pytest.mark.parametrize("field", sorted(PARSE_KNOB_VALUES))
def test_a_parse_knob_overrides_config_yaml_then_undoes(env_paths, field: str):
    """Same two-step as the role fields: the UI file wins, withdrawing it falls back."""
    yaml_value, ui_value = PARSE_KNOB_VALUES[field]
    config_yaml, rag_json = env_paths
    _write_config_yaml(config_yaml, {**dict(YAML_RAG), field: yaml_value})
    _write_rag_json(rag_json, {field: ui_value})
    assert getattr(get_app_config().rag, field) == ui_value

    _write_rag_json(rag_json, {})
    assert getattr(get_app_config().rag, field) == yaml_value


def test_the_parse_knobs_default_when_nobody_declares_them(env_paths):
    """Absent everywhere ⇒ the literal defaults, which is exactly today's behaviour."""
    config_yaml, rag_json = env_paths
    _write_config_yaml(config_yaml, {})
    _write_rag_json(rag_json, {})

    rag = get_app_config().rag
    assert rag.parse_language == "ch"
    assert rag.parse_model_version == "vlm"
    declared = RagConfigFile.from_file().model_dump(exclude_none=True)
    assert not {"parse_language", "parse_model_version"} & set(declared)


@pytest.mark.parametrize("field", sorted(PARSE_KNOB_VALUES))
def test_an_out_of_enum_choice_is_a_loud_load_error(env_paths, field: str):
    """Value fields are validated by their Literal, not silently accepted."""
    config_yaml, rag_json = env_paths
    _write_config_yaml(config_yaml)
    _write_rag_json(rag_json, {field: "not-a-choice"})

    with pytest.raises(ValueError):
        get_app_config()
