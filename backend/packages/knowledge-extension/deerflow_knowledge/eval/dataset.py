"""Golden dataset loading and validation for retrieval evaluation (spec 2026-08-23 §5).

The golden dataset is a single git-versioned JSONL file, one question per
line. Validation is deliberately strict — dirty questions silently pollute
every metric built on top of them, so the guard test in
``tests/knowledge/eval/test_dataset.py`` loads the real file on every run.

``category`` is the report's grouping axis (RFC v3 §8.1): ``text`` /
``table`` / ``image`` partition the bank by the document form the answer
depends on, so an image-chain failure shows up as its own group instead of
being averaged away (the first-phase slice replaced the retired
fact/relation/concept/global axis — relation/concept targeted the cut
graph/wiki paths).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CATEGORIES = ("text", "table", "image")
EXPECTED_PATHS = ("vector",)

# chunk ids are "<doc_id>#NNNN" — a 32-char lowercase hex doc id plus a
# zero-padded 4-digit chunk index (see deerflow_knowledge.indexer).
_CHUNK_ID_RE = re.compile(r"[0-9a-f]{32}#\d{4}")

# Expected-path is the one either/or pair: legacy ``expected_path`` (single
# value, pre-2026-08-28 files) or ``expected_paths`` (non-empty list, the
# canonical new format). Exactly one must be present; the loader normalizes
# both into ``GoldenQuestion.expected_paths`` (spec 2026-08-28 §3/§9 — zero
# file migration, compatibility lives in the validator alone).
_REQUIRED_FIELDS = ("id", "query", "relevant_chunk_ids", "relevant_entities", "category")
_KNOWN_FIELDS = frozenset({*_REQUIRED_FIELDS, "expected_path", "expected_paths", "reference_answer"})


class GoldenDatasetError(ValueError):
    """A golden dataset file or question violates the schema."""


@dataclass(frozen=True)
class GoldenQuestion:
    id: str
    query: str
    expected_paths: tuple[str, ...]
    relevant_chunk_ids: tuple[str, ...]
    relevant_entities: tuple[str, ...]
    category: str
    reference_answer: str | None = None


def _fail(source: str, message: str) -> None:
    raise GoldenDatasetError(f"{source}: {message}")


def _require_str(raw: dict, field: str, source: str, *, allow_blank: bool = False) -> str:
    value = raw[field]
    if not isinstance(value, str) or (not allow_blank and not value.strip()):
        _fail(source, f"{field} must be a non-empty string")
    return value


def _require_str_list(raw: dict, field: str, source: str) -> tuple[str, ...]:
    value = raw[field]
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        _fail(source, f"{field} must be a list of strings")
    return tuple(value)


def _require_expected_paths(raw: dict, source: str) -> tuple[str, ...]:
    """Normalize the either/or expected-path fields into a deduped tuple."""
    has_single = "expected_path" in raw
    has_multi = "expected_paths" in raw
    if has_single and has_multi:
        _fail(source, "expected_path and expected_paths are mutually exclusive — use exactly one")
    if not has_single and not has_multi:
        _fail(source, "missing required field: expected_path or expected_paths")

    if has_single:
        value = raw["expected_path"]
        if value not in EXPECTED_PATHS:
            _fail(source, f"expected_path must be one of {EXPECTED_PATHS}, got {value!r}")
        return (value,)

    value = raw["expected_paths"]
    if not isinstance(value, list) or not value or any(item not in EXPECTED_PATHS for item in value):
        _fail(source, f"expected_paths must be a non-empty list drawn from {EXPECTED_PATHS}, got {value!r}")
    # Dedupe preserving order: {vector, graph} and {graph, vector, graph} mean the same expectation.
    return tuple(dict.fromkeys(value))


def validate_question(raw: Any, *, source: str = "<question>") -> GoldenQuestion:
    """Validate one raw JSON object and return it as a GoldenQuestion."""
    if not isinstance(raw, dict):
        _fail(source, f"question must be a JSON object, got {type(raw).__name__}")

    unknown = sorted(set(raw) - _KNOWN_FIELDS)
    if unknown:
        _fail(source, f"unknown field(s): {', '.join(unknown)}")
    for field in _REQUIRED_FIELDS:
        if field not in raw:
            _fail(source, f"missing required field: {field}")

    qid = _require_str(raw, "id", source)
    query = _require_str(raw, "query", source)

    expected_paths = _require_expected_paths(raw, source)

    category = raw["category"]
    if category not in CATEGORIES:
        _fail(source, f"category must be one of {CATEGORIES}, got {category!r}")

    chunk_ids = _require_str_list(raw, "relevant_chunk_ids", source)
    for chunk_id in chunk_ids:
        if not _CHUNK_ID_RE.fullmatch(chunk_id):
            _fail(source, f"relevant_chunk_ids entries must match '<doc_id>#NNNN', got {chunk_id!r}")

    entities = _require_str_list(raw, "relevant_entities", source)

    reference = raw.get("reference_answer")
    if reference is not None and (not isinstance(reference, str) or not reference.strip()):
        _fail(source, "reference_answer must be a non-empty string when present")

    return GoldenQuestion(
        id=qid,
        query=query,
        expected_paths=expected_paths,
        relevant_chunk_ids=chunk_ids,
        relevant_entities=entities,
        category=category,
        reference_answer=reference,
    )


def load_golden(path: str | Path) -> list[GoldenQuestion]:
    """Load and validate a golden JSONL file, skipping blank lines."""
    path = Path(path)
    if not path.exists():
        raise GoldenDatasetError(f"golden dataset not found: {path}")

    questions: list[GoldenQuestion] = []
    seen_ids: set[str] = set()
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        source = f"{path.name}:{lineno}"
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise GoldenDatasetError(f"{source}: invalid JSON on line {lineno}: {exc.msg}") from exc
        question = validate_question(raw, source=source)
        if question.id in seen_ids:
            _fail(source, f"duplicate question id {question.id!r}")
        seen_ids.add(question.id)
        questions.append(question)
    return questions
