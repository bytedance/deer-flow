from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import cast

from deerflow.agents.memory.eval.types import RankingStrategy, ReplayResult
from deerflow.agents.memory.retrieval_trace import CandidateFact

logger = logging.getLogger(__name__)

type TraceDict = dict[str, object]


def _read_all_lines(path: Path) -> list[str]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError as exc:
        logger.warning("Failed to read trace file %s: %s", path, exc)
        return []

    return [line for line in lines if line.strip()]


def _parse_traces(raw_lines: list[str]) -> list[TraceDict]:
    traces: list[TraceDict] = []
    for line in raw_lines:
        try:
            parsed = cast(object, json.loads(line))
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Skipping malformed trace line: %s", exc)
            continue

        if isinstance(parsed, dict):
            traces.append(cast(TraceDict, parsed))
            continue

        logger.warning("Skipping malformed trace line: expected object")
    return traces


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) else None


def _required_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _required_float(value: object) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None


def _build_candidates(trace: TraceDict) -> list[CandidateFact]:
    candidates_obj = trace.get("candidates", [])
    result: list[CandidateFact] = []
    if not isinstance(candidates_obj, list):
        return result
    candidates = cast(list[object], candidates_obj)

    for candidate_dict in candidates:
        if not isinstance(candidate_dict, dict):
            logger.warning("Skipping malformed candidate in trace %s", trace.get("trace_id", ""))
            continue

        candidate = cast(dict[str, object], candidate_dict)
        fact_id = _required_str(candidate.get("fact_id"))
        content_preview = _required_str(candidate.get("content_preview"))
        category = _required_str(candidate.get("category"))
        confidence = _required_float(candidate.get("confidence"))

        if fact_id is None or content_preview is None or category is None or confidence is None:
            logger.warning("Skipping malformed candidate in trace %s", trace.get("trace_id", ""))
            continue

        result.append(
            CandidateFact(
                fact_id=fact_id,
                content_preview=content_preview,
                category=category,
                confidence=confidence,
                layer=_optional_str(candidate.get("layer")),
                created_at=_optional_str(candidate.get("created_at")),
            )
        )

    return result


def _get_max_tokens(trace: TraceDict) -> int:
    max_tokens = trace.get("max_tokens", 0)
    if isinstance(max_tokens, bool):
        logger.warning("Invalid max_tokens in trace %s: %r", trace.get("trace_id", ""), max_tokens)
        return 0

    if isinstance(max_tokens, int):
        return max_tokens

    if isinstance(max_tokens, float | str):
        try:
            return int(max_tokens)
        except ValueError:
            logger.warning("Invalid max_tokens in trace %s: %r", trace.get("trace_id", ""), max_tokens)
            return 0

    logger.warning("Invalid max_tokens in trace %s: %r", trace.get("trace_id", ""), max_tokens)
    return 0


class ReplayEvaluator:
    def __init__(self, strategies: list[RankingStrategy], baseline: str = "confidence_only"):
        self.strategies: list[RankingStrategy] = strategies
        strategy_names = {strategy.name for strategy in strategies}
        if baseline not in strategy_names:
            raise ValueError(f"baseline '{baseline}' not found in strategies: {sorted(strategy_names)}")
        self.baseline: str = baseline

    def load_traces(self, trace_path: Path, *, window: int = 50) -> list[TraceDict]:
        raw_lines = _read_all_lines(trace_path)
        traces = _parse_traces(raw_lines)
        if window <= 0:
            return []
        return traces[-window:]

    def replay_trace(self, trace_dict: TraceDict, strategy: RankingStrategy) -> ReplayResult:
        candidates = _build_candidates(trace_dict)
        max_tokens = _get_max_tokens(trace_dict)
        ranked_facts = strategy.rank(candidates, max_tokens=max_tokens)
        tokens_used = sum(ranked_fact.token_cost for ranked_fact in ranked_facts if ranked_fact.included)
        selected_count = sum(1 for ranked_fact in ranked_facts if ranked_fact.included)
        dropped_count = sum(1 for ranked_fact in ranked_facts if not ranked_fact.included)

        return ReplayResult(
            trace_id=str(trace_dict.get("trace_id", "")),
            strategy_name=strategy.name,
            ranked_facts=ranked_facts,
            selected_count=selected_count,
            dropped_count=dropped_count,
            tokens_used=tokens_used,
            tokens_remaining=max_tokens - tokens_used,
        )

    def evaluate(self, trace_path: Path, *, window: int = 50) -> dict[str, list[ReplayResult]]:
        traces = self.load_traces(trace_path, window=window)
        if not traces:
            return {}

        results: dict[str, list[ReplayResult]] = {strategy.name: [] for strategy in self.strategies}
        for trace in traces:
            candidates = _build_candidates(trace)
            if not candidates:
                continue

            for strategy in self.strategies:
                results[strategy.name].append(self.replay_trace(trace, strategy))

        return results
