from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from deerflow.agents.memory.backends.deermem.deermem.core.paths import DEFAULT_AGENT_BUCKET
from scripts.benchmark.deermem_scope_isolation import runner
from scripts.benchmark.deermem_scope_isolation.contract import load_protocol
from scripts.benchmark.deermem_scope_isolation.grading import grade_routing_row, grade_semantic_rows
from scripts.benchmark.deermem_scope_isolation.report import RowIntegrityError, build_report, collect_rows, write_report
from scripts.benchmark.deermem_scope_isolation.runner import ROOT, ensure_run_identity, run

MANIFEST = ROOT / "manifest.json"


def test_contract_is_versioned_and_canaries_are_unique() -> None:
    protocol = load_protocol(MANIFEST)

    assert protocol.protocol_id == "deermem-scope-isolation-v1"
    assert len(protocol.semantic_cases) == 6
    canaries = [canary for case in protocol.semantic_cases for canary in (*case.expected_persisted_canaries, *case.expected_rejected_canaries, *case.expected_removed_canaries)] + [protocol.routing_case.canary]
    assert len(canaries) == len(set(canaries))


def test_contract_rejects_duplicate_canary(tmp_path: Path) -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    canary = manifest["semantic_cases"][0]["expected_persisted_canaries"][0]
    case = manifest["semantic_cases"][1]
    case["expected_rejected_canaries"] = [canary]
    case["messages"][0]["content"] += f" {canary}"
    case["offline_output"]["newFacts"][0]["content"] += f" {canary}"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="canary .* is reused"):
        load_protocol(path)


def test_offline_runner_executes_production_scope_and_routing_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    protocol = load_protocol(MANIFEST)
    monkeypatch.setattr(
        "scripts.benchmark.deermem_scope_isolation.runner.build_llm",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("offline mode must not build a provider model")),
    )

    result = run(protocol, manifest_path=MANIFEST, output_dir=tmp_path, mode="offline")
    marker = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    semantic, routing = collect_rows(protocol, tmp_path, marker)

    assert result.executed == 7
    assert all(row["update_succeeded"] for row in semantic)
    assert grade_semantic_rows(semantic)["durable_retention_rate"] == 1.0
    assert grade_semantic_rows(semantic)["unsafe_persistence_rate"] == 0.0
    assert grade_semantic_rows(semantic)["atomic_correction_success_rate"] == 1.0
    assert routing is not None
    assert routing["checked_scopes"]["default"]["agent_name"] == DEFAULT_AGENT_BUCKET
    assert grade_routing_row(routing)["cross_agent_contamination_rate"] == 0.0
    assert grade_routing_row(routing)["cross_user_contamination_rate"] == 0.0
    assert grade_routing_row(routing)["custom_agent_bootstrap_success"] is True


def test_resume_reuses_protocol_bound_rows_and_rejects_changed_manifest(tmp_path: Path) -> None:
    protocol = load_protocol(MANIFEST)
    first = run(protocol, manifest_path=MANIFEST, output_dir=tmp_path / "run", mode="offline")
    second = run(protocol, manifest_path=MANIFEST, output_dir=tmp_path / "run", mode="offline")

    assert first.executed == 7
    assert second.executed == 0
    assert second.reused == 7

    changed = tmp_path / "changed.json"
    raw = json.loads(MANIFEST.read_text(encoding="utf-8"))
    raw["protocol_id"] = "changed"
    changed.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="different protocol"):
        ensure_run_identity(tmp_path / "run", mode="offline", protocol=load_protocol(changed), manifest_path=changed, settings=None)


def test_report_recomputes_metrics_and_rejects_tampered_outcome(tmp_path: Path) -> None:
    protocol = load_protocol(MANIFEST)
    run(protocol, manifest_path=MANIFEST, output_dir=tmp_path, mode="offline")
    marker = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))

    report = build_report(protocol, tmp_path, marker)

    assert report["semantic_model_quality"]["durable_retention_rate"] == 1.0
    assert report["deterministic_identity_routing"]["cross_agent_contamination_rate"] == 0.0

    path = tmp_path / "rows" / "durable-preference.json"
    row = json.loads(path.read_text(encoding="utf-8"))
    row["expected_persisted_canaries"] = []
    path.write_text(json.dumps(row), encoding="utf-8")
    with pytest.raises(RowIntegrityError, match="result-integrity"):
        collect_rows(protocol, tmp_path, marker)


def test_contract_rejects_reused_routing_canary(tmp_path):
    raw = json.loads(MANIFEST.read_text(encoding="utf-8"))
    raw["routing_case"]["canary"] = raw["semantic_cases"][0]["expected_persisted_canaries"][0]
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="routing canary must be unique"):
        load_protocol(path)


@pytest.mark.parametrize("group,section", [("user", "workContext"), ("user", "personalContext"), ("user", "topOfMind"), ("history", "recentMonths"), ("history", "earlierContext"), ("history", "longTermBackground")])
@pytest.mark.parametrize("scope,unsafe", [("user", True), ("project", False)])
def test_semantic_verdict_checks_persisted_summaries(tmp_path, group, section, scope, unsafe):
    protocol = load_protocol(MANIFEST)
    case = protocol.semantic_cases[1]
    canary = case.expected_rejected_canaries[0]
    output = {"user": {}, "history": {}, "newFacts": [], "factsToRemove": []}
    output[group][section] = {"shouldUpdate": True, "summary": canary, "scope": scope, "authority": "descriptive"}
    protocol = replace(protocol, semantic_cases=(replace(case, offline_output=output),))
    run(protocol, manifest_path=MANIFEST, output_dir=tmp_path, mode="offline")
    marker = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    semantic, _ = collect_rows(protocol, tmp_path, marker)
    assert semantic[0]["rejected_canaries_present"] == ([canary] if unsafe else [])
    assert grade_semantic_rows(semantic)["unsafe_persistence_rate"] == float(unsafe)


def test_missing_live_key_fails_before_model_construction(tmp_path, monkeypatch):
    monkeypatch.delenv("DEERMEM_BENCH_TEST_KEY", raising=False)
    monkeypatch.setattr(runner, "build_llm", lambda *_: pytest.fail("model construction reached without a key"))
    settings = runner.LiveSettings("openai", "test", 0.0, "DEERMEM_BENCH_TEST_KEY", None)
    with pytest.raises(ValueError, match="required API key"):
        run(load_protocol(MANIFEST), manifest_path=MANIFEST, output_dir=tmp_path, mode="live", settings=settings)


def test_report_refuses_to_overwrite_evidence(tmp_path):
    protocol = load_protocol(MANIFEST)
    run(protocol, manifest_path=MANIFEST, output_dir=tmp_path, mode="offline")
    report = write_report(protocol, manifest_path=MANIFEST, output_dir=tmp_path)
    original = report.read_bytes()
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        write_report(protocol, manifest_path=MANIFEST, output_dir=tmp_path)
    assert report.read_bytes() == original


@pytest.mark.parametrize("failure", ["provider", "json"])
def test_failed_live_extraction_is_not_sealed_and_resume_retries(tmp_path, monkeypatch, failure):
    protocol = load_protocol(MANIFEST)
    settings = runner.LiveSettings("openai", "test", 0.0, "DEERMEM_BENCH_TEST_KEY", None)
    monkeypatch.setenv(settings.api_key_env, "synthetic-test-key")
    cases = iter(enumerate(protocol.semantic_cases))

    def fail_invoke(*args, **kwargs):
        if failure == "provider":
            raise TimeoutError("synthetic provider timeout")
        return SimpleNamespace(content="not JSON")

    def build(*args):
        index, case = next(cases)
        return SimpleNamespace(invoke=fail_invoke) if index == 1 else runner._StaticModel(case.offline_output)

    monkeypatch.setattr(runner, "build_llm", build)
    with pytest.raises(RuntimeError, match="project-constraint"):
        run(protocol, manifest_path=MANIFEST, output_dir=tmp_path, mode="live", settings=settings)
    assert sorted(path.stem for path in (tmp_path / "rows").glob("*.json")) == ["durable-preference"]
    with pytest.raises(RowIntegrityError, match="missing or invalid"):
        write_report(protocol, manifest_path=MANIFEST, output_dir=tmp_path)
    remaining = iter(protocol.semantic_cases[1:])
    monkeypatch.setattr(runner, "build_llm", lambda *_: runner._StaticModel(next(remaining).offline_output))
    resumed = run(protocol, manifest_path=MANIFEST, output_dir=tmp_path, mode="live", settings=settings)
    assert (resumed.reused, resumed.executed) == (1, 5)
    write_report(protocol, manifest_path=MANIFEST, output_dir=tmp_path)


def test_unsuccessful_rows_are_rejected_and_not_reused(tmp_path):
    protocol = load_protocol(MANIFEST)
    run(protocol, manifest_path=MANIFEST, output_dir=tmp_path, mode="offline")
    path = tmp_path / "rows" / "project-constraint.json"
    row = json.loads(path.read_text(encoding="utf-8"))
    row["update_succeeded"] = False
    path.write_text(json.dumps(runner._seal_row(row)), encoding="utf-8")
    with pytest.raises(RowIntegrityError, match="failed"):
        write_report(protocol, manifest_path=MANIFEST, output_dir=tmp_path)
    with pytest.raises(ValueError, match="failed"):
        grade_semantic_rows([row])
    resumed = run(protocol, manifest_path=MANIFEST, output_dir=tmp_path, mode="offline")
    assert (resumed.executed, resumed.reused) == (1, 6)


def test_legacy_fact_only_rows_are_not_reported_or_reused(tmp_path):
    protocol = load_protocol(MANIFEST)
    run(protocol, manifest_path=MANIFEST, output_dir=tmp_path, mode="offline")
    path = tmp_path / "rows" / "project-constraint.json"
    row = json.loads(path.read_text(encoding="utf-8"))
    row["schema_version"] = 1
    path.write_text(json.dumps(runner._seal_row(row)), encoding="utf-8")
    with pytest.raises(RowIntegrityError, match="unsupported benchmark row"):
        write_report(protocol, manifest_path=MANIFEST, output_dir=tmp_path)
    resumed = run(protocol, manifest_path=MANIFEST, output_dir=tmp_path, mode="offline")
    assert (resumed.executed, resumed.reused) == (1, 6)


def test_routing_does_not_treat_shared_summaries_as_agent_leaks(tmp_path, monkeypatch):
    protocol = load_protocol(MANIFEST)
    canary = protocol.routing_case.canary
    original_invoke = runner._StaticModel.invoke

    def invoke(self, prompt, config=None):
        response = original_invoke(self, prompt, config)
        output = json.loads(response.content)
        if any(canary in fact["content"] for fact in output["newFacts"]):
            output["user"]["workContext"] = {"shouldUpdate": True, "summary": canary, "scope": "user", "authority": "descriptive"}
        response.content = json.dumps(output)
        return response

    monkeypatch.setattr(runner._StaticModel, "invoke", invoke)
    run(protocol, manifest_path=MANIFEST, output_dir=tmp_path, mode="offline")
    marker = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    _, routing = collect_rows(protocol, tmp_path, marker)
    assert routing["selected_present"] is True
    assert routing["default_present"] is False
    assert routing["other_agent_present"] is False
    assert routing["other_user_present"] is False


def test_storage_failure_does_not_produce_a_semantic_row(tmp_path, monkeypatch):
    protocol = load_protocol(MANIFEST)
    finalize = runner.MemoryUpdater._finalize_update

    def fail_save(*args, **kwargs):
        raise OSError("synthetic storage failure")

    monkeypatch.setattr(runner.MemoryUpdater, "_finalize_update", fail_save)
    with pytest.raises(RuntimeError, match="durable-preference"):
        run(protocol, manifest_path=MANIFEST, output_dir=tmp_path, mode="offline")
    assert not (tmp_path / "rows").exists()
    monkeypatch.setattr(runner.MemoryUpdater, "_finalize_update", finalize)
    assert run(protocol, manifest_path=MANIFEST, output_dir=tmp_path, mode="offline").executed == 7
