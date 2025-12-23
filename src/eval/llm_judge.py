# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
LLM-as-Judge evaluation for report quality.

Uses an LLM to evaluate reports on multiple quality dimensions,
providing more nuanced assessment than automated metrics alone.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

EVALUATION_CRITERIA = {
    "factual_accuracy": {
        "description": "Are claims supported by cited sources? Is information accurate and verifiable?",
        "weight": 0.25,
    },
    "completeness": {
        "description": "Does the report comprehensively cover all aspects of the topic?",
        "weight": 0.20,
    },
    "coherence": {
        "description": "Is the report logically structured, well-organized, and easy to follow?",
        "weight": 0.20,
    },
    "relevance": {
        "description": "Does the content directly address the research question without unnecessary tangents?",
        "weight": 0.15,
    },
    "citation_quality": {
        "description": "Are sources credible, diverse, and properly cited?",
        "weight": 0.10,
    },
    "writing_quality": {
        "description": "Is the writing clear, professional, and appropriate for the target audience?",
        "weight": 0.10,
    },
}

JUDGE_SYSTEM_PROMPT = """You are an expert report quality evaluator. Your task is to objectively assess the quality of research reports.

Evaluate the report on the following criteria, scoring each from 1-10:

1. **Factual Accuracy** (1-10): Are claims supported by cited sources? Is information accurate?
2. **Completeness** (1-10): Does the report cover all aspects of the topic comprehensively?
3. **Coherence** (1-10): Is the report logically structured and easy to follow?
4. **Relevance** (1-10): Does content directly address the research question?
5. **Citation Quality** (1-10): Are sources credible, diverse, and properly cited?
6. **Writing Quality** (1-10): Is the writing clear and appropriate for the audience?

Respond ONLY with a valid JSON object in this exact format:
{
    "scores": {
        "factual_accuracy": <1-10>,
        "completeness": <1-10>,
        "coherence": <1-10>,
        "relevance": <1-10>,
        "citation_quality": <1-10>,
        "writing_quality": <1-10>
    },
    "overall_score": <1-10>,
    "strengths": ["strength1", "strength2"],
    "weaknesses": ["weakness1", "weakness2"],
    "suggestions": ["suggestion1", "suggestion2"]
}

Be objective and thorough in your evaluation."""


@dataclass
class EvaluationResult:
    """Container for LLM evaluation results."""

    scores: Dict[str, int]
    overall_score: float
    weighted_score: float
    strengths: List[str]
    weaknesses: List[str]
    suggestions: List[str]
    raw_response: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert evaluation result to dictionary."""
        return {
            "scores": self.scores,
            "overall_score": self.overall_score,
            "weighted_score": self.weighted_score,
            "strengths": self.strengths,
            "weaknesses": self.weaknesses,
            "suggestions": self.suggestions,
        }


class LLMJudge:
    """LLM-based report quality evaluator."""

    def __init__(self, llm: Any = None):
        """
        Initialize the LLM Judge.

        Args:
            llm: LangChain-compatible LLM instance. If None, will be created on demand.
        """
        self._llm = llm

    def _get_llm(self):
        """Get or create the LLM instance."""
        if self._llm is None:
            from src.llms.llm import get_llm_by_type

            self._llm = get_llm_by_type("basic")
        return self._llm

    def _calculate_weighted_score(self, scores: Dict[str, int]) -> float:
        """Calculate weighted average score based on criteria weights."""
        total_weight = 0
        weighted_sum = 0

        for criterion, score in scores.items():
            if criterion in EVALUATION_CRITERIA:
                weight = EVALUATION_CRITERIA[criterion]["weight"]
                weighted_sum += score * weight
                total_weight += weight

        if total_weight > 0:
            return round(weighted_sum / total_weight, 2)
        return 0.0

    def _parse_response(self, response: str) -> Dict[str, Any]:
        """Parse LLM response into structured format."""
        try:
            json_match = response
            if "```json" in response:
                json_match = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_match = response.split("```")[1].split("```")[0]

            return json.loads(json_match.strip())
        except (json.JSONDecodeError, IndexError) as e:
            logger.warning(f"Failed to parse LLM response: {e}")
            return {
                "scores": {
                    "factual_accuracy": 5,
                    "completeness": 5,
                    "coherence": 5,
                    "relevance": 5,
                    "citation_quality": 5,
                    "writing_quality": 5,
                },
                "overall_score": 5,
                "strengths": ["Unable to parse evaluation"],
                "weaknesses": ["Evaluation parsing failed"],
                "suggestions": ["Please re-run evaluation"],
            }

    async def evaluate(
        self,
        report: str,
        query: str,
        report_style: str = "default",
    ) -> EvaluationResult:
        """
        Evaluate a report using LLM-as-Judge.

        Args:
            report: The report text to evaluate
            query: The original research query
            report_style: The style of report for context

        Returns:
            EvaluationResult with scores and feedback
        """
        llm = self._get_llm()

        user_prompt = f"""Please evaluate the following research report.

**Original Research Query:** {query}

**Report Style:** {report_style}

**Report to Evaluate:**
{report[:15000]}  # Truncate if too long

Provide your evaluation in the specified JSON format."""

        messages = [
            SystemMessage(content=JUDGE_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]

        try:
            response = await llm.ainvoke(messages)
            response_text = (
                response.content if hasattr(response, "content") else str(response)
            )

            parsed = self._parse_response(response_text)

            scores = parsed.get("scores", {})
            weighted_score = self._calculate_weighted_score(scores)

            return EvaluationResult(
                scores=scores,
                overall_score=parsed.get("overall_score", 5),
                weighted_score=weighted_score,
                strengths=parsed.get("strengths", []),
                weaknesses=parsed.get("weaknesses", []),
                suggestions=parsed.get("suggestions", []),
                raw_response=response_text,
            )

        except Exception as e:
            logger.error(f"LLM evaluation failed: {e}")
            return EvaluationResult(
                scores={
                    "factual_accuracy": 0,
                    "completeness": 0,
                    "coherence": 0,
                    "relevance": 0,
                    "citation_quality": 0,
                    "writing_quality": 0,
                },
                overall_score=0,
                weighted_score=0,
                strengths=[],
                weaknesses=[f"Evaluation failed: {str(e)}"],
                suggestions=["Please retry evaluation"],
            )

    def evaluate_sync(
        self,
        report: str,
        query: str,
        report_style: str = "default",
    ) -> EvaluationResult:
        """
        Synchronous version of evaluate.

        Args:
            report: The report text to evaluate
            query: The original research query
            report_style: The style of report for context

        Returns:
            EvaluationResult with scores and feedback
        """
        import asyncio

        return asyncio.run(self.evaluate(report, query, report_style))


async def evaluate_with_llm(
    report: str,
    query: str,
    report_style: str = "default",
    llm: Any = None,
) -> EvaluationResult:
    """
    Convenience function to evaluate a report with LLM.

    Args:
        report: The report text to evaluate
        query: The original research query
        report_style: The style of report for context
        llm: Optional LLM instance to use

    Returns:
        EvaluationResult with scores and feedback
    """
    judge = LLMJudge(llm=llm)
    return await judge.evaluate(report, query, report_style)
