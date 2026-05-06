"""LLM-as-Judge evaluator — uses a configured model to score agent responses."""

from __future__ import annotations

import json
import logging

from deerflow.config.evaluation_config import get_evaluation_config
from deerflow.models.factory import create_chat_model

logger = logging.getLogger(__name__)

JUDGE_PROMPT = """You are an expert evaluator for AI agent responses. Score the following response on these dimensions:

{dimensions}

For each dimension, provide a score from 0.0 to 1.0 and a brief justification.

Response to evaluate:
{response}

Expected behavior / criteria:
{criteria}

Return ONLY a JSON object with dimension names as keys and objects with "score" and "justification" fields.
Example: {{"accuracy": {{"score": 0.85, "justification": "..."}}, "completeness": {{"score": 0.7, "justification": "..."}}}}"""


class LLMJudge:
    """Evaluates agent responses using an LLM as judge."""

    def __init__(self, model_name: str | None = None) -> None:
        config = get_evaluation_config()
        self._model_name = model_name or config.judge_model
        self._dimensions = config.metrics

    def _build_prompt(self, response: str, criteria: str) -> str:
        dims = "\n".join(f"- {d}" for d in self._dimensions)
        return JUDGE_PROMPT.format(dimensions=dims, response=response, criteria=criteria)

    def evaluate(self, response: str, expected: str = "", criteria: str = "") -> dict[str, float]:
        """Score a response on all configured dimensions.

        Args:
            response: The agent's response text.
            expected: Expected or reference response (optional).
            criteria: Free-form evaluation criteria.

        Returns:
            Dict mapping dimension name to score (0.0-1.0).
        """
        if not self._model_name:
            logger.warning("No judge_model configured, returning empty scores")
            return {d: 0.0 for d in self._dimensions}

        full_criteria = criteria
        if expected:
            full_criteria = f"Expected: {expected}\n{criteria}" if criteria else f"Expected: {expected}"

        prompt = self._build_prompt(response, full_criteria)
        try:
            model = create_chat_model(self._model_name)
            result = model.invoke(prompt)
            text = result.content if hasattr(result, "content") else str(result)
            return self._parse_scores(text)
        except Exception:
            logger.exception("LLM judge evaluation failed")
            return {d: 0.0 for d in self._dimensions}

    def _parse_scores(self, text: str) -> dict[str, float]:
        """Extract scores from judge LLM output."""
        try:
            # Find JSON block
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(text[start:end])
            else:
                data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            logger.warning("Failed to parse judge output as JSON: %s", text[:200])
            return {d: 0.0 for d in self._dimensions}

        scores: dict[str, float] = {}
        for dim in self._dimensions:
            entry = data.get(dim, {})
            if isinstance(entry, dict):
                scores[dim] = float(entry.get("score", 0.0))
            elif isinstance(entry, (int, float)):
                scores[dim] = float(entry)
            else:
                scores[dim] = 0.0
        return scores
