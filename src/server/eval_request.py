# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Request models for report evaluation endpoint."""

from typing import Optional

from pydantic import BaseModel, Field


class EvaluateReportRequest(BaseModel):
    """Request model for report evaluation."""

    content: str = Field(description="Report markdown content to evaluate")
    query: str = Field(description="Original research query")
    report_style: Optional[str] = Field(
        default="default", description="Report style (academic, news, etc.)"
    )
    use_llm: bool = Field(
        default=False,
        description="Whether to use LLM for deep evaluation (slower but more detailed)",
    )


class EvaluationMetrics(BaseModel):
    """Automated metrics result."""

    word_count: int
    citation_count: int
    unique_sources: int
    image_count: int
    section_count: int
    section_coverage_score: float
    sections_found: list[str]
    sections_missing: list[str]
    has_title: bool
    has_key_points: bool
    has_overview: bool
    has_citations_section: bool


class LLMEvaluationScores(BaseModel):
    """LLM evaluation scores."""

    factual_accuracy: int = 0
    completeness: int = 0
    coherence: int = 0
    relevance: int = 0
    citation_quality: int = 0
    writing_quality: int = 0


class LLMEvaluation(BaseModel):
    """LLM evaluation result."""

    scores: LLMEvaluationScores
    overall_score: float
    weighted_score: float
    strengths: list[str]
    weaknesses: list[str]
    suggestions: list[str]


class EvaluateReportResponse(BaseModel):
    """Response model for report evaluation."""

    metrics: EvaluationMetrics
    score: float
    grade: str
    llm_evaluation: Optional[LLMEvaluation] = None
    summary: Optional[str] = None
