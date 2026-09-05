from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.benchmark.deermem_scope_isolation.manifest import load_manifest
from scripts.benchmark.deermem_scope_isolation.runner import ManifestReplayModel, response_path, run_live

BACKEND_ROOT = Path(__file__).parents[1]
EVAL_ROOT = BACKEND_ROOT / "scripts" / "benchmark" / "deermem_scope_isolation"
MANIFEST_PATH = EVAL_ROOT / "manifests" / "scope-isolation-v1.json"
PROMPT_PATH = BACKEND_ROOT / "packages" / "harness" / "deerflow" / "agents" / "memory" / "backends" / "deermem" / "deermem" / "core" / "prompts" / "memory_update.chat.yaml"


def test_live_run_is_resumable_and_rejects_reassigned_rows(tmp_path: Path) -> None:
    manifest = load_manifest(MANIFEST_PATH)
    output_dir = tmp_path / "live"
    model = ManifestReplayModel(manifest)

    first = run_live(
        manifest,
        model=model,
        model_name="replay-model",
        temperature=0.0,
        output_dir=output_dir,
        manifest_path=MANIFEST_PATH,
        prompt_path=PROMPT_PATH,
        backend_root=BACKEND_ROOT,
    )
    assert (first.reused, first.called, first.failed) == (0, 6, ())
    assert len(model.prompts) == 6
    assert all("Scope and Safety Classification" in prompt for prompt in model.prompts)

    second_model = ManifestReplayModel(manifest)
    second = run_live(
        manifest,
        model=second_model,
        model_name="replay-model",
        temperature=0.0,
        output_dir=output_dir,
        manifest_path=MANIFEST_PATH,
        prompt_path=PROMPT_PATH,
        backend_root=BACKEND_ROOT,
    )
    assert (second.reused, second.called, second.failed) == (6, 0, ())
    assert second_model.prompts == []

    target = response_path(output_dir, manifest.semantic_cases[0].id)
    tampered = json.loads(target.read_text(encoding="utf-8"))
    tampered["case_id"] = manifest.semantic_cases[1].id
    target.write_text(json.dumps(tampered), encoding="utf-8")

    repair_model = ManifestReplayModel(manifest)
    repaired = run_live(
        manifest,
        model=repair_model,
        model_name="replay-model",
        temperature=0.0,
        output_dir=output_dir,
        manifest_path=MANIFEST_PATH,
        prompt_path=PROMPT_PATH,
        backend_root=BACKEND_ROOT,
    )
    assert (repaired.reused, repaired.called, repaired.failed) == (5, 1, ())
    assert len(repair_model.prompts) == 1


def test_live_run_directory_is_bound_to_model_settings(tmp_path: Path) -> None:
    manifest = load_manifest(MANIFEST_PATH)
    output_dir = tmp_path / "live"
    run_live(
        manifest,
        model=ManifestReplayModel(manifest),
        model_name="replay-model",
        temperature=0.0,
        output_dir=output_dir,
        manifest_path=MANIFEST_PATH,
        prompt_path=PROMPT_PATH,
        backend_root=BACKEND_ROOT,
    )

    with pytest.raises(ValueError, match="different run identity"):
        run_live(
            manifest,
            model=ManifestReplayModel(manifest),
            model_name="another-model",
            temperature=0.0,
            output_dir=output_dir,
            manifest_path=MANIFEST_PATH,
            prompt_path=PROMPT_PATH,
            backend_root=BACKEND_ROOT,
        )
