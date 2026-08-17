"""Resumable orchestration for the live answer calls.

Every row (case x policy at the QA capacity) is persisted as its own JSON file
as soon as its provider call succeeds, so a partial paid run can be resumed
without repeating completed calls. Row files contain the prediction and
non-secret metadata only — never questions, reference answers, memory content,
credentials, or response headers. A run directory is bound to one config
identity; resuming with a different config is rejected.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

from .config import EvaluationConfig
from .io import load_json, sha256_file
from .provider import ProviderCallError, request_answer
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


def ensure_run_config_identity(output_dir: Path, *, config: EvaluationConfig, config_path: Path, dataset_path: Path, backend_root: Path) -> None:
    marker_path = output_dir / "qa_run.json"
    config_sha256 = sha256_file(config_path)
    if marker_path.exists():
        marker = load_json(marker_path)
        if marker.get("artifacts", {}).get("config_sha256") != config_sha256:
            raise ValueError(f"{marker_path} was produced with a different config; use a new output directory")
        return
    marker = {
        "schema_version": 1,
        "protocol_id": config.protocol_id,
        "created_at": datetime.now(UTC).isoformat().removesuffix("+00:00") + "Z",
        "git": _git_metadata(backend_root),
        "dataset": {
            "repository": config.dataset.repository,
            "revision": config.dataset.revision,
            "filename": config.dataset.filename,
            "sha256": sha256_file(dataset_path),
        },
        "artifacts": {"config_sha256": config_sha256},
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


def run_answer_calls(tasks: list[AnswerTask], *, config: EvaluationConfig, client: httpx.Client, output_dir: Path, backoff_seconds: float | None = None) -> AnswerRunReport:
    if len({task.row_id for task in tasks}) != len(tasks):
        raise ValueError("answer tasks must have unique row IDs")
    pending = [task for task in tasks if load_completed_row(response_path(output_dir, task.row_id)) is None]
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
