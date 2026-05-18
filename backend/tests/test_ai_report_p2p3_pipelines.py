"""End-to-end pipeline tests for the 5 P2/P3 report types.

Sprint S6 — single file covers query→transform→DSL validate for all 5
report types (trend / diagnosis / failure-analysis / closure / inspection)
to keep test discovery fast. Per-report deep contract tests live in the
dedicated test files.

For each report:
1. Run query script → produces source JSON
2. Run transform script(s) → produces analysis JSON
3. Load the corresponding builtin DSL template + validate against the registry
4. Assert §13.2 contract holds where applicable (trend / diagnosis / failure-analysis)
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "skills" / "custom" / "data-analyst" / "scripts"
TEMPLATES_DIR = REPO_ROOT / "agents" / "builtin" / "report-templates"
REGISTRY_YAML = REPO_ROOT / "skills" / "custom" / "data-analyst" / "report_scripts.yaml"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def stub_helpers():
    _load("_stub_helpers", SCRIPTS_DIR / "_stub_helpers.py")


@pytest.fixture()
def validator_bundle():
    """Build a validator + manual ScriptRegistry from report_scripts.yaml.

    We bypass the real loader (it depends on langchain via the skill discovery
    chain) by parsing the YAML directly and constructing ScriptDescriptor objects.
    """
    # Stub langgraph to allow importing report_templates.* without the runtime
    fake_lg = types.ModuleType("langgraph")
    fake_config = types.ModuleType("langgraph.config")
    fake_config.get_config = lambda: {}
    fake_config.get_stream_writer = lambda: (lambda *a, **k: None)
    sys.modules.setdefault("langgraph", fake_lg)
    sys.modules.setdefault("langgraph.config", fake_config)

    sys.path.insert(0, str(REPO_ROOT / "backend" / "packages" / "harness"))
    from deerflow.report_templates.validator import validate_dsl  # type: ignore
    from deerflow.report_templates.script_registry import (  # type: ignore
        ScriptRegistry,
        ScriptDescriptor,
        ScriptDescriptorYaml,
    )

    reg_doc = yaml.safe_load(REGISTRY_YAML.read_text(encoding="utf-8"))
    scripts = {}
    skill_dir = (REPO_ROOT / "skills" / "custom" / "data-analyst").resolve()
    for sname, sdef in reg_doc.get("scripts", {}).items():
        d = ScriptDescriptorYaml.model_validate(sdef)
        qual = f"data-analyst/{sname}"
        scripts[qual] = ScriptDescriptor(
            qualified_name=qual,
            skill_name="data-analyst",
            script_name=sname,
            skill_dir=skill_dir,
            entry=d.entry,
            kinds=tuple(d.kind),
            description=d.description or "",
            args_schema=d.args_schema or {},
            args_aliases=d.args_aliases or {},
            outputs_schema=d.outputs_schema,
            output_files=tuple(d.output_files or []),
            timeout_seconds=d.timeout_seconds,
            max_output_bytes=d.max_output_bytes,
        )
    return validate_dsl, ScriptRegistry(scripts=scripts)


def _validate_template(validator_bundle, template_name):
    validate_dsl, registry = validator_bundle
    doc = yaml.safe_load((TEMPLATES_DIR / template_name / "default.yaml").read_text(encoding="utf-8"))
    return validate_dsl(doc, registry=registry)


# --- Trend pipeline -----------------------------------------------------------
def test_trend_pipeline(tmp_path, validator_bundle):
    qm = _load("query_trend", SCRIPTS_DIR / "query_trend.py")
    tr = _load("trend_analysis", SCRIPTS_DIR / "trend_analysis.py")

    sys.argv = [
        "query_trend.py",
        "--metric-keys", "runtime_rate,vibration_level,alarm_count",
        "--date-range", "2026-04-01..2026-04-30",
        "--aggregation", "daily",
        "--forecast-horizon", "7",
        "--output-dir", str(tmp_path),
    ]
    assert qm.main() == 0
    sys.argv = ["trend_analysis.py", "--input", str(tmp_path / "data" / "trend_data.json"), "--output-dir", str(tmp_path)]
    assert tr.main() == 0

    analysis = json.loads((tmp_path / "data" / "trend_analysis.json").read_text(encoding="utf-8"))
    # §13.2 contract
    assert analysis["human_review_required"] is True
    assert "summary_markdown" not in analysis
    assert analysis["findings"] and analysis["evidence"]

    # DSL validate
    report = _validate_template(validator_bundle, "trend-equipment")
    assert report.valid, f"trend-equipment errors: {[e.message for e in report.errors]}"


# --- Diagnosis pipeline -------------------------------------------------------
def test_diagnosis_pipeline(tmp_path, validator_bundle):
    qm = _load("query_fault_context", SCRIPTS_DIR / "query_fault_context.py")
    tl = _load("build_fault_timeline", SCRIPTS_DIR / "build_fault_timeline.py")
    da = _load("diagnosis_analysis", SCRIPTS_DIR / "diagnosis_analysis.py")

    sys.argv = [
        "query_fault_context.py",
        "--fault-time", "2026-05-15",
        "--equipment-id", "P-001",
        "--symptom", "vibration high",
        "--include-related-equipment",
        "--output-dir", str(tmp_path),
    ]
    assert qm.main() == 0
    sys.argv = ["build_fault_timeline.py", "--input", str(tmp_path / "data" / "fault_context.json"), "--output-dir", str(tmp_path)]
    assert tl.main() == 0
    sys.argv = [
        "diagnosis_analysis.py",
        "--input", str(tmp_path / "data" / "fault_context.json"),
        "--timeline", str(tmp_path / "data" / "fault_timeline.json"),
        "--output-dir", str(tmp_path),
    ]
    assert da.main() == 0

    analysis = json.loads((tmp_path / "data" / "diagnosis_analysis.json").read_text(encoding="utf-8"))
    assert analysis["human_review_required"] is True
    assert "summary_markdown" not in analysis
    # Diagnosis-specific S2 strict requirements
    src_types = {e["source_type"] for e in analysis["evidence"]}
    assert len({"timeseries", "alarm", "work_order", "maintenance_record"} & src_types) >= 3

    report = _validate_template(validator_bundle, "diagnosis-fault")
    assert report.valid, f"diagnosis-fault errors: {[e.message for e in report.errors]}"


# --- Failure-analysis pipeline (all 3 methods) --------------------------------
@pytest.mark.parametrize("method", ["five_why", "fishbone", "fmea"])
def test_failure_analysis_pipeline(tmp_path, validator_bundle, method):
    qm = _load("query_failure_data", SCRIPTS_DIR / "query_failure_data.py")
    fa = _load("failure_analysis", SCRIPTS_DIR / "failure_analysis.py")

    sys.argv = [
        "query_failure_data.py",
        "--asset-id", "P-001",
        "--failure-mode", "轴承卡死",
        "--analysis-method", method,
        "--output-dir", str(tmp_path),
    ]
    assert qm.main() == 0
    sys.argv = ["failure_analysis.py", "--input", str(tmp_path / "data" / "failure_data.json"), "--output-dir", str(tmp_path)]
    assert fa.main() == 0

    analysis = json.loads((tmp_path / "data" / "failure_analysis.json").read_text(encoding="utf-8"))
    assert analysis["human_review_required"] is True
    assert "summary_markdown" not in analysis
    assert analysis["method_block"]["method"] == method

    # FMEA-specific: RPN must equal severity × occurrence × detection
    if method == "fmea":
        for row in analysis["method_block"]["fmea_rows"]:
            assert row["rpn"] == row["severity"] * row["occurrence"] * row["detection"]

    report = _validate_template(validator_bundle, "failure-analysis")
    assert report.valid, f"failure-analysis errors: {[e.message for e in report.errors]}"


# --- Closure pipeline (factual) -----------------------------------------------
def test_closure_pipeline(tmp_path, validator_bundle):
    qm = _load("query_closure_items", SCRIPTS_DIR / "query_closure_items.py")
    cs = _load("closure_summary", SCRIPTS_DIR / "closure_summary.py")

    sys.argv = [
        "query_closure_items.py",
        "--issue-ids", "ISSUE-001,ISSUE-002,ISSUE-003,ISSUE-004,ISSUE-005,ISSUE-006,ISSUE-007",
        "--owner-department", "运行部",
        "--verification-period", "2026-04-01..2026-05-15",
        "--output-dir", str(tmp_path),
    ]
    assert qm.main() == 0
    sys.argv = ["closure_summary.py", "--input", str(tmp_path / "data" / "closure_items.json"), "--output-dir", str(tmp_path)]
    assert cs.main() == 0

    summary = json.loads((tmp_path / "data" / "closure_summary.json").read_text(encoding="utf-8"))
    # Factual: no §13.2 fields
    for forbidden in ("findings", "evidence", "confidence", "human_review_required", "summary_markdown"):
        assert forbidden not in summary

    report = _validate_template(validator_bundle, "closure-summary")
    assert report.valid, f"closure-summary errors: {[e.message for e in report.errors]}"


# --- Inspection pipeline (factual) --------------------------------------------
def test_inspection_pipeline(tmp_path, validator_bundle):
    qm = _load("query_inspection", SCRIPTS_DIR / "query_inspection.py")
    su = _load("inspection_summary", SCRIPTS_DIR / "inspection_summary.py")
    at = _load("inspection_attachment_summary", SCRIPTS_DIR / "inspection_attachment_summary.py")

    sys.argv = [
        "query_inspection.py",
        "--inspection-date", "2026-05-15",
        "--route", "RT-A",
        "--area", "A区",
        "--severity-min", "low",
        "--output-dir", str(tmp_path),
    ]
    assert qm.main() == 0
    sys.argv = ["inspection_summary.py", "--input", str(tmp_path / "data" / "inspection_data.json"), "--output-dir", str(tmp_path)]
    assert su.main() == 0
    sys.argv = ["inspection_attachment_summary.py", "--input", str(tmp_path / "data" / "inspection_data.json"), "--output-dir", str(tmp_path)]
    assert at.main() == 0

    summary = json.loads((tmp_path / "data" / "inspection_summary.json").read_text(encoding="utf-8"))
    for forbidden in ("findings", "evidence", "confidence", "human_review_required", "summary_markdown"):
        assert forbidden not in summary

    report = _validate_template(validator_bundle, "inspection")
    assert report.valid, f"inspection errors: {[e.message for e in report.errors]}"


# --- Daily/Weekly/Monthly zero regression ------------------------------------
@pytest.mark.parametrize("template_name", ["daily-equipment", "weekly-equipment", "monthly-equipment"])
def test_pre_existing_templates_still_validate(validator_bundle, template_name):
    """Sprint plan S6 acceptance: daily/weekly/monthly DSL templates must
    still pass validator after the P2/P3 additions (no registry collisions)."""
    report = _validate_template(validator_bundle, template_name)
    assert report.valid, f"{template_name} regression: {[e.message for e in report.errors]}"
