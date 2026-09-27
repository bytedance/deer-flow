from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .io import load_yaml


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DatasetConfig(StrictModel):
    repository: str
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    filename: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PoolConfig(StrictModel):
    size: int = Field(ge=2)
    capacities: list[int]
    qa_capacity: int = Field(ge=1)
    distractors: int = Field(ge=1)
    distractor_bank_size: int = Field(ge=1)
    distractor_types: list[str]
    distractor_min_evidence_chars: int = Field(ge=0)
    distractor_max_evidence_chars: int = Field(ge=1)
    offset_namespace: str
    fact_order: Literal["fact-id"]

    @model_validator(mode="after")
    def validate_shape(self) -> PoolConfig:
        if self.distractors != self.size - 1:
            raise ValueError("pool.distractors must equal pool.size - 1")
        if self.distractor_bank_size < self.distractors:
            raise ValueError("pool.distractor_bank_size must cover all distractors")
        if not self.distractor_types or len(self.distractor_types) != len(set(self.distractor_types)):
            raise ValueError("pool.distractor_types must be non-empty and unique")
        if not self.capacities or len(self.capacities) != len(set(self.capacities)):
            raise ValueError("pool.capacities must be non-empty and unique")
        if any(capacity < 1 or capacity >= self.size for capacity in self.capacities):
            raise ValueError("pool capacities must be between 1 and pool.size - 1")
        if self.qa_capacity not in self.capacities:
            raise ValueError("pool.qa_capacity must appear in pool.capacities")
        if self.distractor_min_evidence_chars > self.distractor_max_evidence_chars:
            raise ValueError("distractor evidence bounds are reversed")
        return self


class ConfidencePolicyConfig(StrictModel):
    policy: Literal["confidence"] = "confidence"


class HybridPolicyConfig(StrictModel):
    policy: Literal["hybrid-v1"] = "hybrid-v1"
    weights: dict[Literal["confidence", "confirmation", "access"], float]
    confirmation_half_life_days: int = Field(ge=1)
    access_half_life_days: int = Field(ge=1)
    correction_reserved_fraction: float = Field(ge=0.0, le=1.0)
    correction_reserved_max: int = Field(ge=0)

    @field_validator("weights")
    @classmethod
    def validate_weights(cls, value: dict[str, float]) -> dict[str, float]:
        if set(value) != {"confidence", "confirmation", "access"}:
            raise ValueError("hybrid-v1 weights must define confidence, confirmation, and access")
        if any(weight < 0.0 or weight > 1.0 for weight in value.values()):
            raise ValueError("hybrid-v1 weights must be bounded between 0 and 1")
        if not math.isclose(sum(value.values()), 1.0, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("hybrid-v1 weights must sum to 1.0")
        return value


class PoliciesConfig(StrictModel):
    confidence: ConfidencePolicyConfig
    hybrid_v1: HybridPolicyConfig


class PromptFileConfig(StrictModel):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class QAConfig(StrictModel):
    answer_prompt: PromptFileConfig
    grader_version: str
    provider: Literal["openai-compatible"]
    api_key_env: str
    base_url_env: str
    model: str
    temperature: float
    max_tokens: int = Field(ge=1)
    stream: bool
    timeout_seconds: int = Field(ge=1)
    max_attempts: int = Field(ge=1)
    workers: int = Field(ge=1)


class StatisticsConfig(StrictModel):
    bootstrap_seed: int
    bootstrap_iterations: int = Field(ge=1)
    alpha: float = Field(gt=0.0, lt=1.0)


class EvaluationConfig(StrictModel):
    schema_version: Literal[1]
    protocol_id: str
    required_policy_version: Literal["hybrid-v1"]
    evaluation_time: datetime
    dataset: DatasetConfig
    pool: PoolConfig
    policies: PoliciesConfig
    qa: QAConfig
    statistics: StatisticsConfig

    @field_validator("evaluation_time")
    @classmethod
    def require_aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("evaluation_time must include a timezone")
        return value.astimezone(UTC)


def load_evaluation_config(path: Path) -> EvaluationConfig:
    return EvaluationConfig.model_validate(load_yaml(path))
