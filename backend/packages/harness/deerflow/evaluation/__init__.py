"""Evaluation framework — metrics, LLM-as-Judge, dataset loading, and test running."""

from deerflow.evaluation.dataset import EvalCase, load_dataset
from deerflow.evaluation.judge import LLMJudge
from deerflow.evaluation.metrics import (
    calculate_mrr,
    calculate_ndcg,
    calculate_precision_at_k,
    calculate_recall_at_k,
)
from deerflow.evaluation.runner import EvalReport, EvalRunner

__all__ = [
    "EvalCase",
    "EvalReport",
    "EvalRunner",
    "LLMJudge",
    "calculate_mrr",
    "calculate_ndcg",
    "calculate_precision_at_k",
    "calculate_recall_at_k",
    "load_dataset",
]
