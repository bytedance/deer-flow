"""Dataset loading utilities for academic eval cases."""

from __future__ import annotations

import json
from pathlib import Path

from .schemas import AcademicEvalCase


def load_eval_cases(path: Path) -> list[AcademicEvalCase]:
    """Load eval cases from JSON file.

    Supported formats:
    - Raw list: `[ {case...}, ... ]`
    - Envelope: `{ "metadata": {...}, "cases": [ {case...}, ... ] }`
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    metadata: dict = {}
    raw_cases: list
    if isinstance(payload, list):
        raw_cases = payload
    elif isinstance(payload, dict) and isinstance(payload.get("cases"), list):
        raw_cases = payload["cases"]
        metadata = payload.get("metadata", {}) if isinstance(payload.get("metadata"), dict) else {}
    else:
        raise ValueError("Eval dataset must be a JSON array or an object with a `cases` array")

    split = str(metadata.get("benchmark_split") or "unspecified")
    source_name = metadata.get("source_name")
    source_name = str(source_name) if isinstance(source_name, str) and source_name.strip() else None
    enriched = []
    for item in raw_cases:
        if not isinstance(item, dict):
            continue
        data = dict(item)
        data.setdefault("benchmark_split", split)
        if source_name is not None:
            data.setdefault("source_name", source_name)
        enriched.append(AcademicEvalCase.model_validate(data))
    return enriched


def load_builtin_eval_cases(dataset_name: str) -> list[AcademicEvalCase]:
    """Load bundled benchmark datasets under `src/evals/academic/datasets`."""
    normalized = (dataset_name or "").strip().lower()
    if not normalized:
        raise ValueError("dataset_name is required")
    base_dir = Path(__file__).resolve().parent / "datasets"
    path = base_dir / f"{normalized}.json"
    if not path.exists():
        raise FileNotFoundError(f"Builtin academic eval dataset not found: {dataset_name}")
    return load_eval_cases(path)
