"""Tests for ``RagConfig.embedding_batch_size`` plumbing.

The DashScope-compatible aliyun proxy hosting ``text-embedding-v4`` caps
``input`` to 10 items per request. Without a configurable batch size,
the OpenAI provider's hardcoded 2048 caused every multi-chunk indexing
job against that proxy to fail with:

    400 InvalidParameter: batch size is invalid, it should not be larger than 10.

These tests pin the contract:
* ``OpenAIEmbeddingProvider`` honors ``batch_size`` when slicing the
  input list and issues exactly one API call per slice.
* ``get_embedding_provider`` reads ``RagConfig.embedding_batch_size``
  and forwards it into the provider.
* The config defaults remain backwards-compatible.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from deerflow.config.rag_config import RagConfig, set_rag_config
from deerflow.rag.embeddings import OpenAIEmbeddingProvider, get_embedding_provider


def _fake_response(batch: list[str]) -> SimpleNamespace:
    """Mimic the OpenAI SDK's embeddings.create return shape."""
    data = [
        SimpleNamespace(index=i, embedding=[float(i)] * 4) for i in range(len(batch))
    ]
    return SimpleNamespace(data=data)


class TestOpenAIEmbeddingProviderBatchSize:
    def test_default_batch_size_is_2048(self) -> None:
        provider = OpenAIEmbeddingProvider(model="text-embedding-3-small", api_key="k")
        assert provider._batch_size == 2048

    def test_batch_size_floor_is_one(self) -> None:
        provider = OpenAIEmbeddingProvider(
            model="m", api_key="k", batch_size=0
        )
        assert provider._batch_size == 1

    def test_embed_slices_input_into_configured_batches(self) -> None:
        provider = OpenAIEmbeddingProvider(
            model="text-embedding-v4",
            api_key="k",
            base_url="https://aiapi.shenguyun.com/v1",
            batch_size=10,
        )

        client = MagicMock()
        client.embeddings.create.side_effect = lambda model, input: _fake_response(input)
        provider._client = client

        texts = [f"chunk-{i}" for i in range(25)]
        out = provider.embed(texts)

        assert len(out) == 25
        # 25 texts at batch_size=10 → 3 calls of sizes 10, 10, 5.
        call_sizes = [
            len(call.kwargs["input"]) for call in client.embeddings.create.call_args_list
        ]
        assert call_sizes == [10, 10, 5]

    def test_embed_single_call_when_under_batch_size(self) -> None:
        provider = OpenAIEmbeddingProvider(
            model="m", api_key="k", batch_size=10
        )
        client = MagicMock()
        client.embeddings.create.side_effect = lambda model, input: _fake_response(input)
        provider._client = client

        provider.embed(["a", "b", "c"])
        assert client.embeddings.create.call_count == 1


class TestGetEmbeddingProviderForwardsBatchSize:
    def teardown_method(self) -> None:
        set_rag_config(RagConfig())

    def test_factory_passes_config_batch_size_to_openai_provider(self) -> None:
        set_rag_config(
            RagConfig(
                enabled=True,
                embedding_model="openai:text-embedding-v4",
                embedding_api_key="sk-test",
                embedding_base_url="https://aiapi.shenguyun.com/v1",
                embedding_batch_size=10,
            )
        )

        captured: dict = {}

        def fake_provider_init(self, **kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            self._model = kwargs["model"]
            self._api_key = kwargs["api_key"]
            self._base_url = kwargs.get("base_url")
            self._batch_size = kwargs.get("batch_size", 2048)
            self._client = None
            self._dimension = None

        with patch.object(OpenAIEmbeddingProvider, "__init__", fake_provider_init):
            provider = get_embedding_provider()

        assert isinstance(provider, OpenAIEmbeddingProvider)
        assert captured["model"] == "text-embedding-v4"
        assert captured["api_key"] == "sk-test"
        assert captured["base_url"] == "https://aiapi.shenguyun.com/v1"
        assert captured["batch_size"] == 10

    def test_factory_default_batch_size_for_openai(self) -> None:
        set_rag_config(
            RagConfig(
                enabled=True,
                embedding_model="openai:text-embedding-3-small",
                embedding_api_key="sk-test",
            )
        )

        provider = get_embedding_provider()
        assert isinstance(provider, OpenAIEmbeddingProvider)
        # RagConfig default is 64.
        assert provider._batch_size == 64


class TestRagConfigBatchSizeValidation:
    def test_default_value(self) -> None:
        assert RagConfig().embedding_batch_size == 64

    def test_accepts_min_one(self) -> None:
        cfg = RagConfig(embedding_batch_size=1)
        assert cfg.embedding_batch_size == 1

    def test_accepts_max_2048(self) -> None:
        cfg = RagConfig(embedding_batch_size=2048)
        assert cfg.embedding_batch_size == 2048

    def test_rejects_zero(self) -> None:
        with pytest.raises(Exception):
            RagConfig(embedding_batch_size=0)

    def test_rejects_above_max(self) -> None:
        with pytest.raises(Exception):
            RagConfig(embedding_batch_size=4096)
