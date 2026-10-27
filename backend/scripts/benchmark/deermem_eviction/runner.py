"""Resumable orchestration for the live answer calls.

Every row (case x policy at the QA capacity) is persisted as its own JSON file
as soon as its provider call succeeds, so a partial paid run can be resumed
without repeating completed calls. Row files contain the prediction and
non-secret metadata only — never questions, reference answers, memory content,
credentials, or response headers. A run directory is bound to the full
protocol identity — config, official and synthetic manifests, answer prompt,
and dataset — and resuming with any changed artifact is rejected. A stored
row is reused only when its identity, kept facts, and request fingerprint all
match the task recomputed from the current protocol; anything else is
re-called.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from .config import EvaluationConfig
from .io import load_json, sha256_file
from .provider import ProviderCallError, request_answer, request_fingerprint
from .qa import AnswerTask
from .results import _atomic_write_text, _git_metadata

RESPONSES_DIRNAME = "responses"
ROW_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class AnswerRunReport:
    reused: int
    called: int
    failed: tuple[str, ...]


def response_path(output_dir: Path, row_id: str) -> Path:
    return output_dir / RESPONSES_DIRNAME / f"{row_id}.json"


def load_completed_row(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        row = load_json(path)
    except (OSError, ValueError):
        return None
    if not isinstance(row, dict) or row.get("schema_version") != ROW_SCHEMA_VERSION or not isinstance(row.get("prediction"), str):
        return None
    return row


def _write_row(path: Path, task: AnswerTask, prediction: str, *, attempts: int, request_fingerprint: str, response_model: str | None, usage: dict[str, int]) -> None:
    row = {
        "schema_version": ROW_SCHEMA_VERSION,
        "row_id": task.row_id,
        "case_id": task.case_id,
        "source": task.source,
        "scenario": task.scenario,
        "policy": task.policy,
        "capacity": task.capacity,
        "kept_fact_ids": list(task.kept_fact_ids),
        "prediction": prediction,
        "attempts": attempts,
        "request_fingerprint": request_fingerprint,
        "response_model": response_model,
        "usage": usage,
        "created_at": datetime.now(UTC).isoformat().removesuffix("+00:00") + "Z",
    }
    _atomic_write_text(path, json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _protocol_artifact_hashes(*, config_path: Path, official_manifest_path: Path, synthetic_manifest_path: Path, prompt_path: Path, dataset_path: Path) -> dict[str, str]:
    return {
        "config_sha256": sha256_file(config_path),
        "official_manifest_sha256": sha256_file(official_manifest_path),
        "synthetic_manifest_sha256": sha256_file(synthetic_manifest_path),
        "answer_prompt_sha256": sha256_file(prompt_path),
        "dataset_sha256": sha256_file(dataset_path),
    }


def _changed_artifacts(marker: dict[str, Any], artifacts: dict[str, str]) -> list[str]:
    stored = marker.get("artifacts", {})
    return sorted(name for name in artifacts if stored.get(name) != artifacts[name])


def verify_run_identity(output_dir: Path, *, config_path: Path, official_manifest_path: Path, synthetic_manifest_path: Path, prompt_path: Path, dataset_path: Path) -> None:
    """Read-only check that a completed run directory was produced by the current protocol artifacts."""
    marker_path = output_dir / "qa_run.json"
    if not marker_path.exists():
        raise ValueError(f"{marker_path} is missing; grading requires the marker written by run-qa")
    artifacts = _protocol_artifact_hashes(config_path=config_path, official_manifest_path=official_manifest_path, synthetic_manifest_path=synthetic_manifest_path, prompt_path=prompt_path, dataset_path=dataset_path)
    changed = _changed_artifacts(load_json(marker_path), artifacts)
    if changed:
        raise ValueError(f"{marker_path} was produced with different protocol artifacts ({', '.join(changed)}); refusing to grade")


def ensure_run_config_identity(
    output_dir: Path,
    *,
    config: EvaluationConfig,
    config_path: Path,
    official_manifest_path: Path,
    synthetic_manifest_path: Path,
    prompt_path: Path,
    dataset_path: Path,
    backend_root: Path,
) -> None:
    marker_path = output_dir / "qa_run.json"
    artifacts = _protocol_artifact_hashes(config_path=config_path, official_manifest_path=official_manifest_path, synthetic_manifest_path=synthetic_manifest_path, prompt_path=prompt_path, dataset_path=dataset_path)
    if marker_path.exists():
        changed = _changed_artifacts(load_json(marker_path), artifacts)
        if changed:
            raise ValueError(f"{marker_path} was produced with different protocol artifacts ({', '.join(changed)}); use a new output directory")
        return
    marker = {
        "schema_version": 2,
        "protocol_id": config.protocol_id,
        "created_at": datetime.now(UTC).isoformat().removesuffix("+00:00") + "Z",
        "git": _git_metadata(backend_root),
        "dataset": {
            "repository": config.dataset.repository,
            "revision": config.dataset.revision,
            "filename": config.dataset.filename,
            "sha256": artifacts["dataset_sha256"],
        },
        "artifacts": artifacts,
        "qa": {
            "capacity": config.pool.qa_capacity,
            "model": config.qa.model,
            "temperature": config.qa.temperature,
            "max_tokens": config.qa.max_tokens,
            "stream": config.qa.stream,
            "timeout_seconds": config.qa.timeout_seconds,
            "max_attempts": config.qa.max_attempts,
            "workers": config.qa.workers,
            "grader_version": config.qa.grader_version,
            "api_key_env": config.qa.api_key_env,
            "base_url_env": config.qa.base_url_env,
        },
    }
    _atomic_write_text(marker_path, json.dumps(marker, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _row_matches_task(row: dict[str, Any], task: AnswerTask, expected_fingerprint: str) -> bool:
    return (
        row.get("row_id") == task.row_id
        and row.get("case_id") == task.case_id
        and row.get("source") == task.source
        and row.get("scenario") == task.scenario
        and row.get("policy") == task.policy
        and row.get("capacity") == task.capacity
        and tuple(row.get("kept_fact_ids", ())) == task.kept_fact_ids
        and row.get("request_fingerprint") == expected_fingerprint
    )


def run_answer_calls(tasks: list[AnswerTask], *, config: EvaluationConfig, client: httpx.Client, output_dir: Path, backoff_seconds: float | None = None) -> AnswerRunReport:
    if len({task.row_id for task in tasks}) != len(tasks):
        raise ValueError("answer tasks must have unique row IDs")
    pending = []
    for task in tasks:
        row = load_completed_row(response_path(output_dir, task.row_id))
        if row is None or not _row_matches_task(row, task, request_fingerprint(config.qa, task.messages)):
            pending.append(task)
    reused = len(tasks) - len(pending)
    failed: list[str] = []
    call_kwargs = {} if backoff_seconds is None else {"backoff_seconds": backoff_seconds}

    def call(task: AnswerTask) -> str | None:
        try:
            answer = request_answer(client, config.qa, task.messages, **call_kwargs)
        except ProviderCallError as error:
            return f"{task.row_id}: {error}"
        _write_row(
            response_path(output_dir, task.row_id),
            task,
            answer.prediction,
            attempts=answer.attempts,
            request_fingerprint=answer.request_fingerprint,
            response_model=answer.response_model,
            usage=answer.usage,
        )
        return None

    if pending:
        with ThreadPoolExecutor(max_workers=config.qa.workers) as executor:
            failed = [error for error in executor.map(call, pending) if error is not None]
    return AnswerRunReport(reused=reused, called=len(pending) - len(failed), failed=tuple(sorted(failed)))
