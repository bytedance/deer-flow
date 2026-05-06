"""Scenario dataset loader — JSONL format for evaluation test cases."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class EvalCase:
    """A single evaluation test case."""

    conversation: list[dict] = field(default_factory=list)
    expected_tools: list[str] = field(default_factory=list)
    expected_topics: list[str] = field(default_factory=list)
    min_score: float = 0.7

    @classmethod
    def from_dict(cls, d: dict) -> EvalCase:
        return cls(
            conversation=d.get("conversation", []),
            expected_tools=d.get("expected_tools", []),
            expected_topics=d.get("expected_topics", []),
            min_score=d.get("min_score", 0.7),
        )


def load_dataset(path: str | Path) -> list[EvalCase]:
    """Load evaluation cases from a JSONL file.

    Each line is a JSON object with:
        conversation: list of message dicts
        expected_tools: list of tool names that should be called
        expected_topics: list of topics that should be covered
        min_score: minimum acceptable score (default 0.7)
    """
    cases: list[EvalCase] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            cases.append(EvalCase.from_dict(json.loads(line)))
    return cases
