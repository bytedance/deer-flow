"""Embedding computation for semantic memory retrieval.

Strategy (in order of preference):

1. **API-based** (when ``memory.embedding.model`` is configured):
   Uses the configured LLM provider's ``/v1/embeddings`` endpoint. Best quality.

2. **Character n-gram** (fallback, zero dependencies):
   Computes a fixed-length vector from character 2/3/4-gram frequencies.
   Language-agnostic, deterministic, no API call needed.

Embeddings are computed at **fact save time** and stored inline in the fact dict.
At query time, only the query embedding needs to be computed, then we do
in-memory cosine similarity against all stored fact embeddings.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from collections import Counter
from typing import Any

logger = logging.getLogger(__name__)

# Embedding dimension for the character n-gram fallback.
# Powers of 2 are conventional; 128 balances quality vs storage.
_NGRAM_EMBEDDING_DIM = 128

# Hard cap so a single embedding never blows the JSON file.
_MAX_TOKENS_PER_EMBEDDING = 512


def _tokenize(text: str) -> list[str]:
    """Simple whitespace-aware tokenization for API embedding."""
    return re.findall(r"[^\s]+", text)


def _compute_ngram_embedding(text: str) -> list[float]:
    """Compute a character n-gram TF-IDF-like embedding.

    Uses 2/3/4-grams with log-frequency weighting, hashed to a fixed
    dimension, then L2-normalized. No external dependencies.
    """
    ngrams: Counter[str] = Counter()
    for n in range(2, 5):
        for i in range(len(text) - n + 1):
            ngrams[text[i : i + n]] += 1

    if not ngrams:
        return [0.0] * _NGRAM_EMBEDDING_DIM

    top = ngrams.most_common(_NGRAM_EMBEDDING_DIM)
    max_count = top[0][1] if top else 1

    embedding = [0.0] * _NGRAM_EMBEDDING_DIM
    for gram, count in top:
        # Hash each n-gram to a stable index and sign
        h = hashlib.md5(gram.encode()).digest()
        idx = int.from_bytes(h[:2], "big") % _NGRAM_EMBEDDING_DIM
        sign = 1.0 if (h[2] % 2 == 0) else -1.0
        embedding[idx] += sign * math.log1p(count) / math.log1p(max_count)

    # L2 normalize
    norm = math.sqrt(sum(v * v for v in embedding))
    if norm > 0:
        embedding = [v / norm for v in embedding]
    return embedding


def _compute_api_embedding(text: str, model: str) -> list[float] | None:
    """Compute embedding via the configured LLM provider's API.

    Returns ``None`` if the API call fails, so callers can fall back.
    """
    try:
        from deerflow.config import get_app_config
        from deerflow.models import create_chat_model

        # Use the existing model infrastructure to get a provider client
        config = get_app_config()
        model_cfg = config.get_model_config(model) if model else None
        if model_cfg is None:
            logger.warning("Embedding model %r not found in config", model)
            return None

        # For OpenAI-compatible providers, call /v1/embeddings
        base_url = getattr(model_cfg, "base_url", None) or "https://api.openai.com/v1"
        api_key = getattr(model_cfg, "api_key", None)

        import httpx

        url = f"{base_url.rstrip('/')}/embeddings"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": model_cfg.model,
            "input": text[:_MAX_TOKENS_PER_EMBEDDING],
        }

        with httpx.Client(timeout=10) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data["data"][0]["embedding"]
    except Exception:
        logger.warning("API embedding failed for model %r, falling back to n-gram", model, exc_info=True)
        return None


# Cache: embedding model name → tuple of (embedding_dim, is_api)
_EMBEDDING_CACHE: dict[str, tuple[int | None, bool]] = {}

# Sentinel: "no embedding model configured, use n-gram"
_EMBEDDING_CONFIG_NONE = object()


def _resolve_embedding_config() -> tuple[str | None, bool]:
    """Return ``(model_name_or_None, use_api)`` from memory config.

    Reads the new ``memory.embedding_model`` field.  When set, facts are
    ranked by vector similarity using the configured model's
    ``/v1/embeddings`` endpoint.  When ``None`` (default), falls back to
    character n-gram embedding (zero external dependencies).
    """
    try:
        from deerflow.config.memory_config import get_memory_config

        mem_cfg = get_memory_config()
        model = mem_cfg.embedding_model
        if model:
            return str(model), True
    except Exception:
        pass
    return None, False


def compute_embedding(text: str) -> list[float]:
    """Compute embedding vector for *text*.

    Uses the configured embedding model if available, otherwise falls back
    to character n-gram embedding (zero external dependencies).
    """
    model, use_api = _resolve_embedding_config()

    if use_api and model:
        api_emb = _compute_api_embedding(text, model)
        if api_emb is not None:
            logger.debug("Computed API embedding (model=%s, dim=%d)", model, len(api_emb))
            return api_emb
        # API failed; fall through to n-gram

    return _compute_ngram_embedding(text)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors.

    Returns 0.0 for empty or zero-norm vectors.
    """
    if not a or not b:
        return 0.0
    dot = sum(av * bv for av, bv in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(av * av for av in a))
    norm_b = math.sqrt(sum(bv * bv for bv in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def has_embedding_model_configured() -> bool:
    """Return whether an API embedding model is configured.

    Used by the injection path to decide whether to rely on vector ranking.
    """
    _, use_api = _resolve_embedding_config()
    return use_api
