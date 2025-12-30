# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Unit tests for the combined report evaluator."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.eval.evaluator import CombinedEvaluation, ReportEvaluator, score_to_grade
from src.eval.llm_judge import (
    EVALUATION_CRITERIA,
    MAX_REPORT_LENGTH,
    EvaluationResult,
    LLMJudge,
)
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


class TestLLMJudgeParseResponse:
    """Tests for LLMJudge._parse_response method."""

    @pytest.fixture
    def judge(self):
        """Create LLMJudge with mock LLM."""
        return LLMJudge(llm=MagicMock())

    @pytest.fixture
    def valid_response_data(self):
        """Valid evaluation response data."""
        return {
            "scores": {
                "factual_accuracy": 8,
                "completeness": 7,
                "coherence": 9,
                "relevance": 8,
                "citation_quality": 6,
                "writing_quality": 8,
            },
            "overall_score": 8,
            "strengths": ["Well researched", "Clear structure"],
            "weaknesses": ["Could use more citations"],
            "suggestions": ["Add more sources"],
        }

    def test_parse_valid_json(self, judge, valid_response_data):
        """Test parsing valid JSON response."""
        response = json.dumps(valid_response_data)
        result = judge._parse_response(response)

        assert result["scores"]["factual_accuracy"] == 8
        assert result["overall_score"] == 8
        assert "Well researched" in result["strengths"]

    def test_parse_json_in_markdown_block(self, judge, valid_response_data):
        """Test parsing JSON wrapped in markdown code block."""
        response = f"```json\n{json.dumps(valid_response_data)}\n```"
        result = judge._parse_response(response)

        assert result["scores"]["coherence"] == 9
        assert result["overall_score"] == 8

    def test_parse_json_in_generic_code_block(self, judge, valid_response_data):
        """Test parsing JSON in generic code block."""
        response = f"```\n{json.dumps(valid_response_data)}\n```"
        result = judge._parse_response(response)

        assert result["scores"]["relevance"] == 8

    def test_parse_malformed_json_returns_defaults(self, judge):
        """Test that malformed JSON returns default scores."""
        response = "This is not valid JSON at all"
        result = judge._parse_response(response)

        assert result["scores"]["factual_accuracy"] == 5
        assert result["scores"]["completeness"] == 5
        assert result["overall_score"] == 5
        assert "Unable to parse evaluation" in result["strengths"]
        assert "Evaluation parsing failed" in result["weaknesses"]

    def test_parse_incomplete_json(self, judge):
        """Test parsing incomplete JSON."""
        response = '{"scores": {"factual_accuracy": 8}'  # Missing closing braces
        result = judge._parse_response(response)

        # Should return defaults due to parse failure
        assert result["overall_score"] == 5

    def test_parse_json_with_extra_text(self, judge, valid_response_data):
        """Test parsing JSON with surrounding text."""
        response = f"Here is my evaluation:\n```json\n{json.dumps(valid_response_data)}\n```\nHope this helps!"
        result = judge._parse_response(response)

        assert result["scores"]["factual_accuracy"] == 8


class TestLLMJudgeCalculateWeightedScore:
    """Tests for LLMJudge._calculate_weighted_score method."""

    @pytest.fixture
    def judge(self):
        """Create LLMJudge with mock LLM."""
        return LLMJudge(llm=MagicMock())

    def test_calculate_with_all_scores(self, judge):
        """Test weighted score calculation with all criteria."""
        scores = {
            "factual_accuracy": 10,  # weight 0.25
            "completeness": 10,  # weight 0.20
            "coherence": 10,  # weight 0.20
            "relevance": 10,  # weight 0.15
            "citation_quality": 10,  # weight 0.10
            "writing_quality": 10,  # weight 0.10
        }
        result = judge._calculate_weighted_score(scores)
        assert result == 10.0

    def test_calculate_with_varied_scores(self, judge):
        """Test weighted score with varied scores."""
        scores = {
            "factual_accuracy": 8,  # 8 * 0.25 = 2.0
            "completeness": 6,  # 6 * 0.20 = 1.2
            "coherence": 7,  # 7 * 0.20 = 1.4
            "relevance": 9,  # 9 * 0.15 = 1.35
            "citation_quality": 5,  # 5 * 0.10 = 0.5
            "writing_quality": 8,  # 8 * 0.10 = 0.8
        }
        # Total: 7.25
        result = judge._calculate_weighted_score(scores)
        assert result == 7.25

    def test_calculate_with_partial_scores(self, judge):
        """Test weighted score with only some criteria."""
        scores = {
            "factual_accuracy": 8,  # weight 0.25
            "completeness": 6,  # weight 0.20
        }
        # (8 * 0.25 + 6 * 0.20) / (0.25 + 0.20) = 3.2 / 0.45 = 7.11
        result = judge._calculate_weighted_score(scores)
        assert abs(result - 7.11) < 0.01

    def test_calculate_with_unknown_criteria(self, judge):
        """Test that unknown criteria are ignored."""
        scores = {
            "factual_accuracy": 10,
            "unknown_criterion": 1,  # Should be ignored
        }
        result = judge._calculate_weighted_score(scores)
        assert result == 10.0

    def test_calculate_with_empty_scores(self, judge):
        """Test with empty scores dict."""
        result = judge._calculate_weighted_score({})
        assert result == 0.0

    def test_weights_sum_to_one(self):
        """Verify that all criteria weights sum to 1.0."""
        total_weight = sum(c["weight"] for c in EVALUATION_CRITERIA.values())
        assert abs(total_weight - 1.0) < 0.001


class TestLLMJudgeEvaluate:
    """Tests for LLMJudge.evaluate method with mocked LLM."""

    @pytest.fixture
    def valid_llm_response(self):
        """Create a valid LLM response."""
        return json.dumps(
            {
                "scores": {
                    "factual_accuracy": 8,
                    "completeness": 7,
                    "coherence": 9,
                    "relevance": 8,
                    "citation_quality": 7,
                    "writing_quality": 8,
                },
                "overall_score": 8,
                "strengths": ["Comprehensive coverage", "Well structured"],
                "weaknesses": ["Some claims need more support"],
                "suggestions": ["Add more academic sources"],
            }
        )

    @pytest.mark.asyncio
    async def test_successful_evaluation(self, valid_llm_response):
        """Test successful LLM evaluation."""
        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = valid_llm_response
        mock_llm.ainvoke.return_value = mock_response

        judge = LLMJudge(llm=mock_llm)
        result = await judge.evaluate("Test report", "Test query")

        assert isinstance(result, EvaluationResult)
        assert result.scores["factual_accuracy"] == 8
        assert result.overall_score == 8
        assert result.weighted_score > 0
        assert "Comprehensive coverage" in result.strengths
        assert result.raw_response == valid_llm_response

    @pytest.mark.asyncio
    async def test_evaluation_with_llm_failure(self):
        """Test that LLM failures are handled gracefully."""
        mock_llm = AsyncMock()
        mock_llm.ainvoke.side_effect = Exception("LLM service unavailable")

        judge = LLMJudge(llm=mock_llm)
        result = await judge.evaluate("Test report", "Test query")

        assert isinstance(result, EvaluationResult)
        assert result.overall_score == 0
        assert result.weighted_score == 0
        assert all(score == 0 for score in result.scores.values())
        assert any("failed" in w.lower() for w in result.weaknesses)

    @pytest.mark.asyncio
    async def test_evaluation_with_malformed_response(self):
        """Test handling of malformed LLM response."""
        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "I cannot evaluate this report properly."
        mock_llm.ainvoke.return_value = mock_response

        judge = LLMJudge(llm=mock_llm)
        result = await judge.evaluate("Test report", "Test query")

        # Should return default scores
        assert result.scores["factual_accuracy"] == 5
        assert result.overall_score == 5

    @pytest.mark.asyncio
    async def test_evaluation_passes_report_style(self):
        """Test that report_style is passed to LLM."""
        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = json.dumps(
            {
                "scores": {k: 7 for k in EVALUATION_CRITERIA.keys()},
                "overall_score": 7,
                "strengths": [],
                "weaknesses": [],
                "suggestions": [],
            }
        )
        mock_llm.ainvoke.return_value = mock_response

        judge = LLMJudge(llm=mock_llm)
        await judge.evaluate("Test report", "Test query", report_style="academic")

        # Verify the prompt contains the report style
        call_args = mock_llm.ainvoke.call_args
        messages = call_args[0][0]
        user_message_content = messages[1].content
        assert "academic" in user_message_content

    @pytest.mark.asyncio
    async def test_evaluation_truncates_long_reports(self):
        """Test that very long reports are truncated."""
        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = json.dumps(
            {
                "scores": {k: 7 for k in EVALUATION_CRITERIA.keys()},
                "overall_score": 7,
                "strengths": [],
                "weaknesses": [],
                "suggestions": [],
            }
        )
        mock_llm.ainvoke.return_value = mock_response

        judge = LLMJudge(llm=mock_llm)
        long_report = "x" * (MAX_REPORT_LENGTH + 5000)
        await judge.evaluate(long_report, "Test query")

        call_args = mock_llm.ainvoke.call_args
        messages = call_args[0][0]
        user_message_content = messages[1].content
        # The report content in the message should be truncated to MAX_REPORT_LENGTH
        assert len(user_message_content) < len(long_report) + 500


class TestEvaluationResult:
    """Tests for EvaluationResult dataclass."""

    def test_to_dict(self):
        """Test EvaluationResult.to_dict method."""
        result = EvaluationResult(
            scores={"factual_accuracy": 8, "completeness": 7},
            overall_score=7.5,
            weighted_score=7.6,
            strengths=["Good research"],
            weaknesses=["Needs more detail"],
            suggestions=["Expand section 2"],
            raw_response="test response",
        )

        d = result.to_dict()
        assert d["scores"]["factual_accuracy"] == 8
        assert d["overall_score"] == 7.5
        assert d["weighted_score"] == 7.6
        assert "Good research" in d["strengths"]
        # raw_response should not be in dict
        assert "raw_response" not in d
