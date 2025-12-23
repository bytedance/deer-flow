# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Unit tests for the combined report evaluator."""

import pytest

from src.eval.evaluator import CombinedEvaluation, ReportEvaluator, score_to_grade
from src.eval.metrics import ReportMetrics


class TestScoreToGrade:
    """Tests for score to grade conversion."""

    def test_excellent_scores(self):
        assert score_to_grade(9.5) == "A+"
        assert score_to_grade(9.0) == "A+"
        assert score_to_grade(8.7) == "A"
        assert score_to_grade(8.5) == "A"
        assert score_to_grade(8.2) == "A-"

    def test_good_scores(self):
        assert score_to_grade(7.8) == "B+"
        assert score_to_grade(7.5) == "B+"
        assert score_to_grade(7.2) == "B"
        assert score_to_grade(7.0) == "B"
        assert score_to_grade(6.7) == "B-"

    def test_average_scores(self):
        assert score_to_grade(6.2) == "C+"
        assert score_to_grade(5.8) == "C"
        assert score_to_grade(5.5) == "C"
        assert score_to_grade(5.2) == "C-"

    def test_poor_scores(self):
        assert score_to_grade(4.5) == "D"
        assert score_to_grade(4.0) == "D"
        assert score_to_grade(3.0) == "F"
        assert score_to_grade(1.0) == "F"


class TestReportEvaluator:
    """Tests for ReportEvaluator class."""

    @pytest.fixture
    def evaluator(self):
        """Create evaluator without LLM for metrics-only tests."""
        return ReportEvaluator(use_llm=False)

    @pytest.fixture
    def sample_report(self):
        """Sample report for testing."""
        return """
# Comprehensive Research Report

## Key Points
- Important finding number one with significant implications
- Critical discovery that changes our understanding
- Key insight that provides actionable recommendations
- Notable observation from the research data

## Overview
This report presents a comprehensive analysis of the research topic.
The findings are based on extensive data collection and analysis.

## Detailed Analysis

### Section 1: Background
The background of this research involves multiple factors.
[Source 1](https://example.com/source1) provides foundational context.

### Section 2: Methodology
Our methodology follows established research practices.
[Source 2](https://research.org/methods) outlines the approach.

### Section 3: Findings
The key findings include several important discoveries.
![Research Data](https://example.com/chart.png)

[Source 3](https://academic.edu/paper) supports these conclusions.

## Key Citations
- [Example Source](https://example.com/source1)
- [Research Methods](https://research.org/methods)
- [Academic Paper](https://academic.edu/paper)
- [Additional Reference](https://reference.com/doc)
        """

    def test_evaluate_metrics_only(self, evaluator, sample_report):
        """Test metrics-only evaluation."""
        result = evaluator.evaluate_metrics_only(sample_report)

        assert "metrics" in result
        assert "score" in result
        assert "grade" in result
        assert result["score"] > 0
        assert result["grade"] in ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D", "F"]

    def test_evaluate_metrics_only_structure(self, evaluator, sample_report):
        """Test that metrics contain expected fields."""
        result = evaluator.evaluate_metrics_only(sample_report)
        metrics = result["metrics"]

        assert "word_count" in metrics
        assert "citation_count" in metrics
        assert "unique_sources" in metrics
        assert "image_count" in metrics
        assert "section_coverage_score" in metrics

    def test_evaluate_minimal_report(self, evaluator):
        """Test evaluation of minimal report."""
        minimal_report = "Just some text."
        result = evaluator.evaluate_metrics_only(minimal_report)

        assert result["score"] < 5.0
        assert result["grade"] in ["D", "F"]

    def test_metrics_score_calculation(self, evaluator):
        """Test that metrics score is calculated correctly."""
        good_report = """
# Title

## Key Points
- Point 1
- Point 2

## Overview
Overview content here.

## Detailed Analysis
Analysis with [cite](https://a.com) and [cite2](https://b.com) 
and [cite3](https://c.com) and more [refs](https://d.com).

![Image](https://img.com/1.png)

## Key Citations
- [A](https://a.com)
- [B](https://b.com)
        """
        result = evaluator.evaluate_metrics_only(good_report)
        assert result["score"] > 5.0

    def test_combined_evaluation_to_dict(self):
        """Test CombinedEvaluation to_dict method."""
        metrics = ReportMetrics(
            word_count=1000,
            citation_count=5,
            unique_sources=3,
        )
        evaluation = CombinedEvaluation(
            metrics=metrics,
            llm_evaluation=None,
            final_score=7.5,
            grade="B+",
            summary="Test summary",
        )

        result = evaluation.to_dict()
        assert result["final_score"] == 7.5
        assert result["grade"] == "B+"
        assert result["metrics"]["word_count"] == 1000


class TestReportEvaluatorIntegration:
    """Integration tests for evaluator (may require LLM)."""

    @pytest.mark.asyncio
    async def test_full_evaluation_without_llm(self):
        """Test full evaluation with LLM disabled."""
        evaluator = ReportEvaluator(use_llm=False)

        report = """
# Test Report

## Key Points
- Key point 1

## Overview
Test overview.

## Key Citations
- [Test](https://test.com)
        """

        result = await evaluator.evaluate(report, "test query")

        assert isinstance(result, CombinedEvaluation)
        assert result.final_score > 0
        assert result.grade is not None
        assert result.summary is not None
        assert result.llm_evaluation is None
