"""Suite loading and immutable snapshot helpers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from deerflow.evaluation.schema import EvalSuite


@dataclass(frozen=True)
class LoadedSuite:
    suite: EvalSuite
    path: Path
    snapshot: dict[str, Any]
    digest: str


def suite_digest(snapshot: dict[str, Any]) -> str:
    payload = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_suite_data(path: str | Path) -> dict[str, Any]:
    suite_path = Path(path)
    suffix = suite_path.suffix.lower()
    raw = suite_path.read_text(encoding="utf-8")
    if suffix in {".yaml", ".yml"}:
        data = yaml.safe_load(raw)
    elif suffix == ".json":
        data = json.loads(raw)
    else:
        raise ValueError(f"Unsupported eval suite format: {suite_path.suffix!r}")
    if not isinstance(data, dict):
        raise ValueError("Eval suite must be a YAML/JSON object")
    return data


def load_eval_suite(path: str | Path) -> LoadedSuite:
    suite_path = Path(path).expanduser().resolve()
    data = load_suite_data(suite_path)
    suite = EvalSuite.model_validate(data)
    snapshot = suite.normalized_snapshot()
    return LoadedSuite(suite=suite, path=suite_path, snapshot=snapshot, digest=suite_digest(snapshot))


def normalize_suite_snapshot(data: dict[str, Any]) -> tuple[EvalSuite, dict[str, Any], str]:
    suite = EvalSuite.model_validate(data)
    snapshot = suite.normalized_snapshot()
    return suite, snapshot, suite_digest(snapshot)
