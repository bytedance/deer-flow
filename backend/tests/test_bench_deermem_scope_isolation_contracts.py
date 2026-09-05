from __future__ import annotations

from pathlib import Path

import pytest

from scripts.benchmark.deermem_scope_isolation.cli import main
from scripts.benchmark.deermem_scope_isolation.manifest import all_canaries, load_manifest, validate_production_contract

BACKEND_ROOT = Path(__file__).parents[1]
EVAL_ROOT = BACKEND_ROOT / "scripts" / "benchmark" / "deermem_scope_isolation"
MANIFEST_PATH = EVAL_ROOT / "manifests" / "scope-isolation-v1.json"
PROMPT_PATH = BACKEND_ROOT / "packages" / "harness" / "deerflow" / "agents" / "memory" / "backends" / "deermem" / "deermem" / "core" / "prompts" / "memory_update.chat.yaml"


def test_committed_manifest_is_small_synthetic_and_pins_production_prompt() -> None:
    manifest = load_manifest(MANIFEST_PATH)

    assert manifest.schema_version == 1
    assert manifest.protocol_id == "deermem-scope-isolation-v1"
    assert len(manifest.semantic_cases) == 6
    assert len(manifest.identity_cases) == 1
    assert {case.scenario for case in manifest.semantic_cases} == {
        "durable_preference",
        "task_constraint",
        "project_constraint",
        "transactional_authority",
        "mixed_scope",
        "user_correction",
    }
    canaries = all_canaries(manifest)
    assert len(canaries) == len(set(canaries))
    assert all(canary.startswith("DFMEM_") for canary in canaries)
    validate_production_contract(manifest, PROMPT_PATH)


def test_manifest_contains_no_real_identity_or_repository_data() -> None:
    raw = MANIFEST_PATH.read_text(encoding="utf-8")

    assert "PeaceMaker" not in raw
    assert "bytedance" not in raw.lower()
    assert "github.com" not in raw.lower()
    assert "@" not in raw


def test_validate_contracts_cli_is_offline(capsys) -> None:
    assert main(["validate-contracts"]) == 0
    output = capsys.readouterr().out
    assert "validated 6 semantic and 1 identity cases" in output


def test_production_prompt_drift_requires_protocol_review(tmp_path: Path) -> None:
    manifest = load_manifest(MANIFEST_PATH)
    changed_prompt = tmp_path / "memory_update.chat.yaml"
    changed_prompt.write_bytes(PROMPT_PATH.read_bytes() + b"\n# intentional drift\n")

    with pytest.raises(ValueError, match="production memory prompt changed"):
        validate_production_contract(manifest, changed_prompt)
