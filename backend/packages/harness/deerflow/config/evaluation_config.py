"""Evaluation configuration — metrics, judge model, and CI thresholds."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RagMetricsConfig(BaseModel):
    enabled: bool = Field(default=True, description="Enable RAG retrieval quality metrics")


class EvaluationConfig(BaseModel):
    enabled: bool = Field(default=False, description="Enable evaluation framework")
    judge_model: str = Field(default="", description="Model name for LLM-as-Judge evaluation")
    metrics: list[str] = Field(
        default_factory=lambda: ["accuracy", "completeness", "safety", "tool_usage"],
        description="Evaluation dimensions",
    )
    rag_metrics: RagMetricsConfig = Field(default_factory=RagMetricsConfig)
    ci_threshold: float = Field(default=0.7, description="Minimum pass rate for CI gate")


_evaluation_config: EvaluationConfig | None = None


def get_evaluation_config() -> EvaluationConfig:
    global _evaluation_config
    if _evaluation_config is None:
        _evaluation_config = EvaluationConfig()
    return _evaluation_config


def load_evaluation_config_from_dict(data: dict) -> EvaluationConfig:
    global _evaluation_config
    _evaluation_config = EvaluationConfig.model_validate(data)
    return _evaluation_config


def reset_evaluation_config() -> None:
    global _evaluation_config
    _evaluation_config = None
