"""Tests for ``compute_effective_top_k`` + ``rerank_recall_factor`` (Sprint A.11).

When the reranker is OFF, retrieval should ask for exactly
``max_injection_chunks``. When it's ON, retrieval needs a wider recall
pool so the reranker can promote a chunk that vector search ranked
low — multiplied by ``rerank_recall_factor`` and capped by
``retrieval_top_k``.
"""

from __future__ import annotations

from deerflow.config.rag_config import RagConfig, compute_effective_top_k


class TestComputeEffectiveTopK:
    def test_no_rerank_returns_injection_count(self) -> None:
        cfg = RagConfig(
            reranker_enabled=False,
            max_injection_chunks=5,
            retrieval_top_k=20,
            rerank_recall_factor=3.0,
        )
        assert compute_effective_top_k(cfg) == 5

    def test_no_rerank_capped_by_retrieval_top_k(self) -> None:
        # Pathological config: someone set max_injection_chunks > retrieval_top_k.
        # We trust retrieval_top_k as the upper bound.
        cfg = RagConfig(
            reranker_enabled=False,
            max_injection_chunks=10,
            retrieval_top_k=5,
            rerank_recall_factor=3.0,
        )
        assert compute_effective_top_k(cfg) == 5

    def test_rerank_widens_pool_by_factor(self) -> None:
        cfg = RagConfig(
            reranker_enabled=True,
            max_injection_chunks=3,
            retrieval_top_k=20,
            rerank_recall_factor=3.0,
        )
        assert compute_effective_top_k(cfg) == 9

    def test_rerank_pool_capped_by_retrieval_top_k(self) -> None:
        cfg = RagConfig(
            reranker_enabled=True,
            max_injection_chunks=4,
            retrieval_top_k=10,
            rerank_recall_factor=5.0,
        )
        # 4 × 5 = 20, but retrieval_top_k=10 caps it.
        assert compute_effective_top_k(cfg) == 10

    def test_rerank_factor_below_one_clamped(self) -> None:
        # rerank_recall_factor cannot be < 1.0 per Field constraint, but
        # compute_effective_top_k still defends against it numerically.
        cfg = RagConfig(
            reranker_enabled=True,
            max_injection_chunks=5,
            retrieval_top_k=20,
            rerank_recall_factor=1.0,
        )
        # factor=1 means recall == injection.
        assert compute_effective_top_k(cfg) == 5

    def test_default_config_no_rerank(self) -> None:
        cfg = RagConfig()
        assert cfg.reranker_enabled is False
        # Default max_injection_chunks=3 ≤ retrieval_top_k=5 → returns 3.
        assert compute_effective_top_k(cfg) == 3

    def test_rerank_recall_factor_default(self) -> None:
        cfg = RagConfig()
        assert cfg.rerank_recall_factor == 3.0
