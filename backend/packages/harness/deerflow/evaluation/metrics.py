"""RAG retrieval quality metrics — MRR, NDCG, Recall@K, Precision@K."""

from __future__ import annotations

import math


def calculate_mrr(ranked_lists: list[list[int]]) -> float:
    """Mean Reciprocal Rank.

    Args:
        ranked_lists: Each inner list contains relevance labels (1=relevant, 0=not)
            for ranked documents in a single query.

    Returns:
        Mean reciprocal rank across all queries.
    """
    if not ranked_lists:
        return 0.0
    reciprocal_ranks: list[float] = []
    for ranked in ranked_lists:
        for i, label in enumerate(ranked):
            if label == 1:
                reciprocal_ranks.append(1.0 / (i + 1))
                break
        else:
            reciprocal_ranks.append(0.0)
    return sum(reciprocal_ranks) / len(reciprocal_ranks)


def _dcg(relevance: list[float]) -> float:
    """Discounted Cumulative Gain."""
    return sum(
        (2**rel - 1) / math.log2(i + 2)
        for i, rel in enumerate(relevance)
    )


def calculate_ndcg(
    ranked_lists: list[list[float]],
    relevance_scores: list[list[float]],
) -> float:
    """Normalized Discounted Cumulative Gain.

    Args:
        ranked_lists: Predicted ranking scores per query.
        relevance_scores: Ideal relevance scores per query.

    Returns:
        Average NDCG across all queries.
    """
    if not ranked_lists:
        return 0.0
    ndcg_scores: list[float] = []
    for ranked, ideal in zip(ranked_lists, relevance_scores):
        dcg_val = _dcg(ranked)
        idcg_val = _dcg(sorted(ideal, reverse=True))
        ndcg_scores.append(dcg_val / idcg_val if idcg_val > 0 else 0.0)
    return sum(ndcg_scores) / len(ndcg_scores)


def calculate_recall_at_k(
    ranked_lists: list[list[int]],
    relevant_docs: list[set[int]],
    k: int = 10,
) -> float:
    """Recall@K.

    Args:
        ranked_lists: Each inner list contains doc IDs in ranked order.
        relevant_docs: Each set contains the IDs of relevant documents for that query.
        k: Cutoff rank.

    Returns:
        Average Recall@K across all queries.
    """
    if not ranked_lists:
        return 0.0
    recalls: list[float] = []
    for ranked, relevant in zip(ranked_lists, relevant_docs):
        if not relevant:
            recalls.append(1.0)
            continue
        top_k = set(ranked[:k])
        recalls.append(len(top_k & relevant) / len(relevant))
    return sum(recalls) / len(recalls)


def calculate_precision_at_k(
    ranked_lists: list[list[int]],
    relevant_docs: list[set[int]],
    k: int = 10,
) -> float:
    """Precision@K.

    Args:
        ranked_lists: Each inner list contains doc IDs in ranked order.
        relevant_docs: Each set contains the IDs of relevant documents for that query.
        k: Cutoff rank.

    Returns:
        Average Precision@K across all queries.
    """
    if not ranked_lists:
        return 0.0
    precisions: list[float] = []
    for ranked, relevant in zip(ranked_lists, relevant_docs):
        top_k = set(ranked[:k])
        precisions.append(len(top_k & relevant) / k if k > 0 else 0.0)
    return sum(precisions) / len(precisions)
