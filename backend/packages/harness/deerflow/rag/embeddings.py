"""Embedding provider abstraction and factory."""

import abc
import logging
from typing import Any

from deerflow.config.rag_config import get_rag_config

logger = logging.getLogger(__name__)


class EmbeddingProvider(abc.ABC):
    """Abstract base class for embedding model providers."""

    @property
    @abc.abstractmethod
    def dimension(self) -> int:
        raise NotImplementedError

    @abc.abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts. Returns a list of embedding vectors."""
        raise NotImplementedError

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query text."""
        results = self.embed([text])
        return results[0]


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI-compatible embedding API provider."""

    def __init__(self, model: str, api_key: str, base_url: str | None = None) -> None:
        self._model = model
        self._api_key = api_key
        self._base_url = base_url
        self._client: Any = None
        self._dimension: int | None = None

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            self._dimension = self._resolve_dimension()
        return self._dimension

    def _get_client(self) -> Any:
        if self._client is None:
            from openai import OpenAI

            kwargs: dict[str, Any] = {"api_key": self._api_key}
            if self._base_url:
                kwargs["base_url"] = self._base_url
            self._client = OpenAI(**kwargs)
        return self._client

    def _resolve_dimension(self) -> int:
        try:
            result = self.embed(["test"])
            return len(result[0])
        except Exception:
            logger.warning("Could not resolve embedding dimension, defaulting to 1536")
            return 1536

    def embed(self, texts: list[str]) -> list[list[float]]:
        client = self._get_client()
        # OpenAI supports up to 2048 inputs per batch
        all_embeddings: list[list[float]] = []
        batch_size = 2048
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            resp = client.embeddings.create(model=self._model, input=batch)
            sorted_embeddings = sorted(resp.data, key=lambda e: e.index)
            all_embeddings.extend([e.embedding for e in sorted_embeddings])
        return all_embeddings


class LocalEmbeddingProvider(EmbeddingProvider):
    """Local sentence-transformers / HuggingFace embedding provider.

    Requires ``sentence-transformers`` to be installed.
    """

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._model: Any = None

    @property
    def dimension(self) -> int:
        self._ensure_loaded()
        return self._model.get_sentence_embedding_dimension()

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError(
                "sentence-transformers is required for local embeddings. "
                "Install it with: uv add sentence-transformers"
            )
        self._model = SentenceTransformer(self._model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        self._ensure_loaded()
        embeddings = self._model.encode(texts, normalize_embeddings=True)
        return [e.tolist() for e in embeddings]


def get_embedding_provider() -> EmbeddingProvider:
    """Create an embedding provider from the current RAG configuration.

    Parses the ``embedding_model`` field in ``provider:model`` format.
    Supported providers: ``openai``, ``local``.
    """
    config = get_rag_config()
    raw = config.embedding_model
    if ":" not in raw:
        raise ValueError(f"Invalid embedding_model format: {raw!r}. Expected 'provider:model'.")

    provider_name, model = raw.split(":", 1)
    api_key = config.embedding_api_key

    if provider_name == "openai":
        return OpenAIEmbeddingProvider(model=model, api_key=api_key)
    if provider_name == "local":
        return LocalEmbeddingProvider(model_name=model)

    raise ValueError(f"Unknown embedding provider: {provider_name!r}. Supported: 'openai', 'local'.")
