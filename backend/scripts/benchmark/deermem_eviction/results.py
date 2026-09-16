from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import EvaluationConfig
from .io import sha256_file
from .policy import PolicyResult


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary_path = Path(handle.name)
    os.replace(temporary_path, path)


def _git_metadata(backend_root: Path) -> dict[str, Any]:
    def run(*args: str) -> str:
        completed = subprocess.run(["git", *args], cwd=backend_root, check=True, capture_output=True, text=True)
        return completed.stdout.strip()

    return {
        "head": run("rev-parse", "HEAD"),
        "dirty": bool(run("status", "--porcelain")),
    }


def summarize_policy_results(results: Iterable[PolicyResult]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, int, str], list[PolicyResult]] = defaultdict(list)
    for result in results:
        groups[(result.source, result.scenario, result.capacity, result.policy)].append(result)
    summary: list[dict[str, Any]] = []
    for (source, scenario, capacity, policy), rows in sorted(groups.items()):
        retained = sum(row.support_all_retained for row in rows)
        summary.append(
            {
                "source": source,
                "scenario": scenario,
                "capacity": capacity,
                "policy": policy,
                "cases": len(rows),
                "support_all_retained": retained,
                "support_all_retained_rate": retained / len(rows),
                "mean_support_recall": sum(row.support_recall for row in rows) / len(rows),
            }
        )
    return summary


def write_policy_run(
    output_dir: Path,
    *,
    results: list[PolicyResult],
    config: EvaluationConfig,
    config_path: Path,
    official_manifest_path: Path,
    synthetic_manifest_path: Path,
    prompt_path: Path,
    dataset_path: Path,
    backend_root: Path,
) -> None:
    targets = [output_dir / "run.json", output_dir / "policy.raw.jsonl", output_dir / "summary.json"]
    existing = [path for path in targets if path.exists()]
    if existing:
        raise FileExistsError(f"refusing to overwrite existing result files: {', '.join(str(path) for path in existing)}")
    raw_lines = "".join(json.dumps(result.to_public_dict(), ensure_ascii=False, sort_keys=True) + "\n" for result in results)
    summary = {"schema_version": 1, "protocol_id": config.protocol_id, "groups": summarize_policy_results(results)}
    run = {
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
        "artifacts": {
            "config_sha256": sha256_file(config_path),
            "official_manifest_sha256": sha256_file(official_manifest_path),
            "synthetic_manifest_sha256": sha256_file(synthetic_manifest_path),
            "answer_prompt_sha256": sha256_file(prompt_path),
        },
        "evaluation_time": config.evaluation_time.isoformat(),
        "policies": ["confidence", "hybrid-v1"],
        "capacities": config.pool.capacities,
    }
    _atomic_write_text(output_dir / "policy.raw.jsonl", raw_lines)
    _atomic_write_text(output_dir / "summary.json", json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    _atomic_write_text(output_dir / "run.json", json.dumps(run, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
