from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.benchmark.deermem_eviction.config import load_evaluation_config
from scripts.benchmark.deermem_eviction.dataset import EvidenceRecord
from scripts.benchmark.deermem_eviction.policy import evaluate_case
from scripts.benchmark.deermem_eviction.pool import PreparedCase, build_case
from scripts.benchmark.deermem_eviction.results import summarize_policy_results, write_policy_run

BACKEND_ROOT = Path(__file__).parents[1]
EVAL_ROOT = BACKEND_ROOT / "scripts" / "benchmark" / "deermem_eviction"


def _case() -> PreparedCase:
    support = EvidenceRecord("support", "knowledge-update", "private question", "private answer", None, "private support text")
    distractors = [EvidenceRecord(f"d{i}", "single-session-user", "q", "a", None, f"private distractor {i}") for i in range(9)]
    return build_case(
        support=support,
        distractors=distractors,
        scenario="confirmation_help",
        loss_rank=8,
        evaluation_time=datetime(2026, 8, 13, tzinfo=UTC),
    )


def test_summary_keeps_policy_and_scenario_groups_separate() -> None:
    case = _case()
    rows = [
        evaluate_case(case, policy_name="confidence", capacity=7),
        evaluate_case(case, policy_name="hybrid-v1", capacity=7),
    ]

    summary = summarize_policy_results(rows)

    assert [(item["policy"], item["support_all_retained"]) for item in summary] == [
        ("confidence", 0),
        ("hybrid-v1", 1),
    ]


def test_public_policy_run_omits_dataset_text_and_refuses_overwrite(tmp_path: Path) -> None:
    config_path = EVAL_ROOT / "configs" / "pr4789-reproduction-v1.yaml"
    official_manifest_path = EVAL_ROOT / "manifests" / "longmemeval-pr4789-v1.json"
    synthetic_manifest_path = EVAL_ROOT / "manifests" / "synthetic-corrections-pr4789-v1.json"
    prompt_path = EVAL_ROOT / "prompts" / "answer-v1.txt"
    config = load_evaluation_config(config_path)
    case = _case()
    rows = [evaluate_case(case, policy_name="confidence", capacity=7), evaluate_case(case, policy_name="hybrid-v1", capacity=7)]
    dataset_path = tmp_path / "private-dataset.json"
    dataset_path.write_text("[]")
    output_dir = tmp_path / "run"

    write_policy_run(
        output_dir,
        results=rows,
        config=config,
        config_path=config_path,
        official_manifest_path=official_manifest_path,
        synthetic_manifest_path=synthetic_manifest_path,
        prompt_path=prompt_path,
        dataset_path=dataset_path,
        backend_root=BACKEND_ROOT,
    )

    raw_text = (output_dir / "policy.raw.jsonl").read_text()
    assert "private question" not in raw_text
    assert "private answer" not in raw_text
    assert "private support text" not in raw_text
    assert len([json.loads(line) for line in raw_text.splitlines()]) == 2
    assert json.loads((output_dir / "summary.json").read_text())["protocol_id"] == config.protocol_id
    assert json.loads((output_dir / "run.json").read_text())["dataset"]["filename"] == config.dataset.filename

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        write_policy_run(
            output_dir,
            results=rows,
            config=config,
            config_path=config_path,
            official_manifest_path=official_manifest_path,
            synthetic_manifest_path=synthetic_manifest_path,
            prompt_path=prompt_path,
            dataset_path=dataset_path,
            backend_root=BACKEND_ROOT,
        )
