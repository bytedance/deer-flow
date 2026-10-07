"""Tests for the RAG knowledge-base configuration section (``rag:``)."""

import pytest

from deerflow.config.app_config import AppConfig, RagConfig

_SANDBOX = {"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}}


class TestRagConfig:
    def test_loads_defaults(self):
        config = RagConfig()

        assert config.qdrant_url == "http://localhost:6333"
        assert config.embedding_model is None  # the vendor literal default retired (2026-09-30, A-1)
        assert config.rerank_model is None  # the vendor literal default retired (2026-09-30, A-1)
        assert config.vlm_model is None  # the vendor literal default retired (2026-09-23 D10.3)
        assert config.worker_concurrency == 2

    def test_overridable_from_dict(self):
        config = RagConfig(
            **{
                "qdrant_url": "http://qdrant:6333",
                "embedding_model": "custom-embedding",
                "rerank_model": "custom-rerank",
                "vlm_model": "custom-vlm",
                "worker_concurrency": 8,
            }
        )

        assert config.qdrant_url == "http://qdrant:6333"
        assert config.embedding_model == "custom-embedding"
        assert config.rerank_model == "custom-rerank"
        assert config.vlm_model == "custom-vlm"
        assert config.worker_concurrency == 8

    def test_unknown_keys_tolerated(self):
        """AppConfig uses ``extra="allow"``; section models ignore unknown keys
        (pydantic default), matching SchedulerConfig and the other sections."""
        config = RagConfig(**{"qdrant_url": "http://qdrant:6333", "future_key": True})

        assert config.qdrant_url == "http://qdrant:6333"
        assert not hasattr(config, "future_key")

    def test_rejects_invalid_worker_concurrency(self):
        with pytest.raises(ValueError):
            RagConfig(worker_concurrency=0)

    def test_caption_generation_defaults(self):
        """A-4 (spec 2026-09-30 D1): the two caption knobs keep today's literal defaults."""
        config = RagConfig()

        assert config.caption_max_tokens == 1024
        assert config.caption_temperature == 0.15

    def test_caption_generation_overridable_from_dict(self):
        config = RagConfig(caption_max_tokens=2048, caption_temperature=0.7)

        assert config.caption_max_tokens == 2048
        assert config.caption_temperature == 0.7

    def test_rejects_out_of_range_caption_generation_params(self):
        with pytest.raises(ValueError):
            RagConfig(caption_max_tokens=0)
        with pytest.raises(ValueError):
            RagConfig(caption_temperature=-0.1)
        with pytest.raises(ValueError):
            RagConfig(caption_temperature=2.1)


class TestAppConfigRagSection:
    def test_rag_section_has_defaults(self):
        config = AppConfig.model_validate(_SANDBOX)

        assert config.rag.qdrant_url == "http://localhost:6333"
        assert config.rag.embedding_model is None  # no literal default since 2026-09-30 (A-1)
        assert config.rag.rerank_model is None  # no literal default since 2026-09-30 (A-1)
        assert config.rag.vlm_model is None  # follows the RAG default, then the first model
        assert config.rag.worker_concurrency == 2

    def test_rag_section_overridable_from_dict(self):
        config = AppConfig.model_validate(
            {
                **_SANDBOX,
                "rag": {
                    "qdrant_url": "http://qdrant:6333",
                    "worker_concurrency": 4,
                },
            }
        )

        assert config.rag.qdrant_url == "http://qdrant:6333"
        assert config.rag.worker_concurrency == 4
        # Untouched fields keep their defaults.
        assert config.rag.embedding_model is None  # a missing model is a configuration error now (A-1)

    def test_rag_section_tolerates_unknown_keys(self):
        config = AppConfig.model_validate(
            {
                **_SANDBOX,
                "rag": {"qdrant_url": "http://qdrant:6333", "future_key": True},
            }
        )

        assert config.rag.qdrant_url == "http://qdrant:6333"

    def test_null_rag_section_falls_back_to_defaults(self):
        """A commented-out ``rag:`` block parses as None and must not crash the
        documented ``cp config.example.yaml config.yaml`` first-run flow."""
        config = AppConfig.model_validate({**_SANDBOX, "rag": None})

        assert config.rag.qdrant_url == "http://localhost:6333"


class TestRagTableConfig:
    """表格入库配置段（spec 2026-09-09 §4）：首期构建默认开启，
    enabled 只管电子表格三后缀（.csv 恒不门控）。"""

    def test_loads_defaults(self):
        config = RagConfig()

        assert config.table.enabled is True
        assert config.table.max_size_mb == 50
        assert config.table.card_mode == "markdown"

    def test_overridable_from_dict(self):
        config = RagConfig(**{"table": {"enabled": False, "max_size_mb": 8, "card_mode": "linearized"}})

        assert config.table.enabled is False
        assert config.table.max_size_mb == 8
        assert config.table.card_mode == "linearized"

    def test_rejects_invalid_literal(self):
        with pytest.raises(ValueError):
            RagConfig(**{"table": {"card_mode": "html"}})

    def test_rejects_invalid_numeric_bounds(self):
        with pytest.raises(ValueError):
            RagConfig(**{"table": {"max_size_mb": 0}})

    def test_shipped_example_block_matches_model_defaults(self):
        """config.example.yaml 是首跑模板（cp → config.yaml）：新增段必须能被
        模型吃下，且模板值与文档默认一致（防止缩进/键名漂移）。"""
        from pathlib import Path

        import yaml

        data = yaml.safe_load((Path(__file__).resolve().parents[2] / "config.example.yaml").read_text(encoding="utf-8"))
        table = data["rag"]["table"]

        config = RagConfig(**{"table": table})

        assert config.table.enabled is True
        assert config.table.max_size_mb == 50
        assert config.table.card_mode == "markdown"
