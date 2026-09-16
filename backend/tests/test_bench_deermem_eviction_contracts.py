from __future__ import annotations

import json
from pathlib import Path

from scripts.benchmark.deermem_eviction.config import load_evaluation_config
from scripts.benchmark.deermem_eviction.io import sha256_file
from scripts.benchmark.deermem_eviction.manifest import load_official_manifest, load_synthetic_manifest

EVAL_ROOT = Path(__file__).parents[1] / "scripts" / "benchmark" / "deermem_eviction"


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for child in value.values() for key in _all_keys(child)}
    if isinstance(value, list):
        return {key for child in value for key in _all_keys(child)}
    return set()


def test_committed_protocol_is_pinned_and_does_not_copy_longmemeval_text() -> None:
    config = load_evaluation_config(EVAL_ROOT / "configs" / "pr4789-reproduction-v1.yaml")
    official = load_official_manifest(EVAL_ROOT / "manifests" / "longmemeval-pr4789-v1.json")
    synthetic = load_synthetic_manifest(EVAL_ROOT / "manifests" / "synthetic-corrections-pr4789-v1.json")

    assert config.schema_version == 1
    assert config.protocol_id == "deermem-hybrid-v1-pr4789-reproduction-v1"
    assert config.dataset.revision == "98d7416c24c778c2fee6e6f3006e7a073259d48f"
    assert config.dataset.sha256 == "821a2034d219ab45846873dd14c14f12cfe7776e73527a483f9dac095d38620c"
    assert config.pool.size == 10
    assert config.pool.capacities == [5, 7, 9]
    assert config.pool.qa_capacity == 7
    assert sum(config.policies.hybrid_v1.weights.values()) == 1.0

    official_ids = [question_id for question_ids in official.scenarios.values() for question_id in question_ids]
    assert len(official_ids) == 40
    assert len(set(official_ids)) == 40
    assert set(official.scenarios) == {
        "confirmation_help",
        "access_help",
        "confidence_control",
        "noisy_signal_control",
    }
    assert official.scenario_order == [
        "confirmation_help",
        "access_help",
        "confidence_control",
        "noisy_signal_control",
    ]
    assert len(synthetic.cases) == 5

    raw_official = json.loads((EVAL_ROOT / "manifests" / "longmemeval-pr4789-v1.json").read_text())
    assert not ({"question", "answer", "content", "haystack_sessions"} & _all_keys(raw_official))

    prompt_path = EVAL_ROOT / config.qa.answer_prompt.path
    assert sha256_file(prompt_path) == config.qa.answer_prompt.sha256


def test_cli_contract_validation_is_offline(capsys) -> None:
    from scripts.benchmark.deermem_eviction.cli import main

    assert main(["validate-contracts"]) == 0
    assert "validated 40 official and 5 synthetic cases" in capsys.readouterr().out


def test_required_policy_version_is_checked_against_production() -> None:
    import pytest

    from deerflow.agents.memory.backends.deermem.deermem.core.eviction import EVICTION_POLICY_HYBRID_V1
    from scripts.benchmark.deermem_eviction.policy import require_production_policy

    config = load_evaluation_config(EVAL_ROOT / "configs" / "pr4789-reproduction-v1.yaml")
    assert config.required_policy_version == EVICTION_POLICY_HYBRID_V1
    require_production_policy(config.required_policy_version)
    with pytest.raises(ValueError, match="production implements"):
        require_production_policy("hybrid-v2")
