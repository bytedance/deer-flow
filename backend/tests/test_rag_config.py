"""Tests for RAG configuration."""

import pytest

from deerflow.config.rag_config import (
    RagConfig,
    get_rag_config,
    load_rag_config_from_dict,
    set_rag_config,
)


class TestRagConfigDefaults:
    def test_default_disabled(self):
        config = RagConfig()
        assert config.enabled is False

    def test_default_embedding_model(self):
        config = RagConfig()
        assert config.embedding_model == "openai:text-embedding-3-small"

    def test_default_backend(self):
        config = RagConfig()
        assert config.vector_store_backend == "chroma"

    def test_default_chunk_size(self):
        config = RagConfig()
        assert config.chunk_size == 1000
        assert config.chunk_overlap == 200

    def test_default_retrieval(self):
        config = RagConfig()
        assert config.retrieval_top_k == 5
        assert config.score_threshold == 0.0

    def test_default_injection(self):
        config = RagConfig()
        assert config.injection_enabled is True
        assert config.tool_enabled is True
        assert config.max_injection_chunks == 3
        assert config.max_injection_tokens == 2000


class TestRagConfigValidation:
    def test_chunk_size_min(self):
        config = RagConfig(chunk_size=100)
        assert config.chunk_size == 100

    def test_chunk_size_max(self):
        config = RagConfig(chunk_size=8000)
        assert config.chunk_size == 8000

    def test_chunk_size_below_min_raises(self):
        with pytest.raises(ValueError):
            RagConfig(chunk_size=50)

    def test_retrieval_top_k_range(self):
        config = RagConfig(retrieval_top_k=1)
        assert config.retrieval_top_k == 1
        config = RagConfig(retrieval_top_k=50)
        assert config.retrieval_top_k == 50

    def test_score_threshold_range(self):
        config = RagConfig(score_threshold=0.0)
        assert config.score_threshold == 0.0
        config = RagConfig(score_threshold=1.0)
        assert config.score_threshold == 1.0


class TestRagConfigSingleton:
    def test_get_rag_config_returns_default(self):
        config = get_rag_config()
        assert isinstance(config, RagConfig)
        assert config.enabled is False

    def test_set_rag_config(self):
        original = get_rag_config()
        new_config = RagConfig(enabled=True, embedding_model="local:all-MiniLM-L6-v2")
        set_rag_config(new_config)
        try:
            assert get_rag_config().enabled is True
            assert get_rag_config().embedding_model == "local:all-MiniLM-L6-v2"
        finally:
            set_rag_config(original)

    def test_load_rag_config_from_dict(self):
        original = get_rag_config()
        load_rag_config_from_dict({
            "enabled": True,
            "embedding_model": "openai:text-embedding-3-large",
            "chunk_size": 500,
        })
        try:
            config = get_rag_config()
            assert config.enabled is True
            assert config.embedding_model == "openai:text-embedding-3-large"
            assert config.chunk_size == 500
        finally:
            set_rag_config(original)
