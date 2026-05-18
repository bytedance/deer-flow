"""End-to-end runtime tests for ai-report--custom Lane A.

Drives the report-templates runtime modules directly (skipping the LLM +
GenUI middleware) to validate the full pipeline:

  form input → data_runner.run_script (subprocess) → DataConnector demo
  → payload_builder.assemble_payload → exporter.export_report → Markdown

This test catches integration bugs the per-script tests miss, e.g.:
- Windows + Chinese stderr encoding regressions in data_runner
- payload_builder ↔ generic_renderer card/table prop mismatches
- DSL field-name drift across the 5 builtin templates

The harness skips render_report_blocks (which requires a langgraph
StreamWriter that only exists in an active SSE request) — that path is
covered by per-tool unit tests elsewhere.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
SCRIPTS_DIR = REPO_ROOT / "skills" / "custom" / "data-analyst" / "scripts"
TEMPLATES_DIR = REPO_ROOT / "agents" / "builtin" / "report-templates"
REGISTRY_YAML = REPO_ROOT / "skills" / "custom" / "data-analyst" / "report_scripts.yaml"


@pytest.fixture(scope="module")
def runtime():
    """Import everything the harness needs, with a langgraph stub."""
    fake_lg = types.ModuleType("langgraph")
    fake_config = types.ModuleType("langgraph.config")
    fake_config.get_config = lambda: {}
    fake_config.get_stream_writer = lambda: (lambda *a, **k: None)
    sys.modules.setdefault("langgraph", fake_lg)
    sys.modules.setdefault("langgraph.config", fake_config)
    sys.path.insert(0, str(BACKEND_DIR / "packages" / "harness"))

    import yaml

    from deerflow.report_templates.runtime.data_runner import run_data_steps_and_transforms
    from deerflow.report_templates.runtime.payload_builder import assemble_payload
    from deerflow.report_templates.runtime.exporter import export_report
    from deerflow.report_templates.runtime.state import RuntimeState
    from deerflow.report_templates.script_registry import (
        ScriptRegistry,
        ScriptDescriptor,
        ScriptDescriptorYaml,
    )

    return {
        "yaml": yaml,
        "run_data_steps_and_transforms": run_data_steps_and_transforms,
        "assemble_payload": assemble_payload,
        "export_report": export_report,
        "RuntimeState": RuntimeState,
        "ScriptRegistry": ScriptRegistry,
        "ScriptDescriptor": ScriptDescriptor,
        "ScriptDescriptorYaml": ScriptDescriptorYaml,
    }


@pytest.fixture(scope="module")
def registry(runtime):
    """Build a ScriptRegistry by parsing report_scripts.yaml directly.

    We can't use ``load_registry()`` because the skill-discovery chain pulls
    in langchain via the broader ``deerflow.skills`` package.
    """
    reg_doc = runtime["yaml"].safe_load(REGISTRY_YAML.read_text(encoding="utf-8"))
    skill_dir = (REPO_ROOT / "skills" / "custom" / "data-analyst").resolve()
    scripts = {}
    for sname, sdef in reg_doc.get("scripts", {}).items():
        d = runtime["ScriptDescriptorYaml"].model_validate(sdef)
        qual = f"data-analyst/{sname}"
        scripts[qual] = runtime["ScriptDescriptor"](
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
    return runtime["ScriptRegistry"](scripts=scripts)


FORM_FIXTURES: dict[str, dict[str, dict]] = {
    "trend-equipment": {
        "scope": {
            "date_range": "2026-04-01..2026-04-30",
            "aggregation": "daily",
            "forecast_horizon": 7,
        },
        "kpis": {"metric_keys": ["runtime_rate", "vibration_level", "alarm_count"]},
    },
    "diagnosis-fault": {
        "scope": {
            "equipment_id": "P-001",
            "fault_time": "2026-05-15",
            "symptom": "vibration high",
            "include_related": True,
        },
    },
    "failure-analysis": {
        "scope": {
            "asset_id": "P-001",
            "failure_mode": "轴承卡死",
            "analysis_method": "five_why",
            "evidence_range": "2026-01-01..2026-05-18",
        },
    },
    "closure-summary": {
        "scope": {
            "issue_ids": "ISSUE-001,ISSUE-002,ISSUE-003,ISSUE-004,ISSUE-005,ISSUE-006,ISSUE-007",
            "owner_department": "运行部",
            "verification_period": "2026-04-01..2026-05-15",
        },
    },
    "inspection": {
        "scope": {
            "inspection_date": "2026-05-15",
            "route": "RT-A",
            "area": "A区",
            "severity_min": "low",
        },
    },
}


def _drive_template(runtime, registry, template_name: str, run_dir: Path) -> dict:
    """Drive one builtin template end-to-end. Returns the parsed payload."""
    template_doc = runtime["yaml"].safe_load(
        (TEMPLATES_DIR / template_name / "default.yaml").read_text(encoding="utf-8")
    )
    fixture = FORM_FIXTURES[template_name]
    state = runtime["RuntimeState"](
        report_run_id=f"rr_test_{template_name}",
        thread_id="thread_test",
        template_id=f"builtin-{template_name}",
        template_version=None,
        template_version_ref=f"builtin-{template_name}",
        status="ready_for_data",
        nonce="test",
        expected_step="__generate__",
        created_at="2026-05-18T00:00:00",
        form_state=fixture,
        step_outputs={},
        completed_steps=list(fixture.keys()),
    )

    context = {
        "form": state.form_state,
        "steps": state.step_outputs,
        "run": {
            "report_run_id": state.report_run_id,
            "thread_id": state.thread_id,
            "generated_at": state.created_at,
        },
        "template": {"id": state.template_id, "version": None, "name": template_name},
    }

    # 1. Run data_steps + transforms (subprocess + DataConnector demo path)
    accumulated = runtime["run_data_steps_and_transforms"](
        dsl=template_doc, registry=registry, run_output_dir=run_dir, context=context,
    )
    state.step_outputs = accumulated

    # 2. Assemble payload
    payload = runtime["assemble_payload"](dsl=template_doc, state=state)
    (run_dir / "report_payload.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 3. Export Markdown (PDF skipped — weasyprint optional)
    result = runtime["export_report"](payload=payload, run_output_dir=run_dir, pdf=False)

    return {
        "template_name": template_name,
        "payload": payload,
        "md_path": Path(result.md_path),
        "md_text": Path(result.md_path).read_text(encoding="utf-8"),
        "step_outputs": accumulated,
    }


# ---------------------------------------------------------------------------
# Parametrized e2e — every builtin template must round-trip to Markdown
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "template_name",
    ["trend-equipment", "diagnosis-fault", "failure-analysis", "closure-summary", "inspection"],
)
def test_e2e_template_renders_to_markdown(runtime, registry, tmp_path, template_name):
    result = _drive_template(runtime, registry, template_name, tmp_path)

    # Markdown is required (export raises if it fails)
    assert result["md_path"].exists()
    assert result["md_path"].stat().st_size > 200, "Markdown unexpectedly small"

    # Output must be Markdown (H1 title at top)
    assert result["md_text"].startswith("# "), "Markdown must start with H1"

    # Every template's title must appear in the output
    template_display = runtime["yaml"].safe_load(
        (TEMPLATES_DIR / template_name / "default.yaml").read_text(encoding="utf-8")
    ).get("display_name", "")
    assert template_display in result["md_text"], (
        f"display_name {template_display!r} must appear in rendered markdown"
    )


# ---------------------------------------------------------------------------
# §13.2 interpretive reports — banner + evidence trail must reach markdown
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("template_name", ["trend-equipment", "diagnosis-fault", "failure-analysis"])
def test_e2e_interpretive_report_has_review_banner(runtime, registry, tmp_path, template_name):
    """The 'human_review_required' banner must render as a quote-block warning."""
    result = _drive_template(runtime, registry, template_name, tmp_path)
    md = result["md_text"]
    # generic_renderer renders style:warning cards as a ``> ⚠ ...`` quote block
    assert "> ⚠" in md, f"{template_name} missing §13.2 review banner"
    assert "人工复核" in md or "human review" in md.lower(), (
        f"{template_name} banner must mention human review"
    )


@pytest.mark.parametrize("template_name", ["trend-equipment", "diagnosis-fault", "failure-analysis"])
def test_e2e_interpretive_report_has_evidence_table(runtime, registry, tmp_path, template_name):
    """Evidence trail table must surface source_type / source_id columns."""
    result = _drive_template(runtime, registry, template_name, tmp_path)
    md = result["md_text"]
    # Either header is acceptable depending on column labels chosen in DSL
    assert "源类型" in md or "source_type" in md or "来源类型" in md, (
        f"{template_name} missing evidence source_type column"
    )


# ---------------------------------------------------------------------------
# Factual reports — must NOT have §13.2 banner
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("template_name", ["closure-summary", "inspection"])
def test_e2e_factual_report_has_no_review_banner(runtime, registry, tmp_path, template_name):
    result = _drive_template(runtime, registry, template_name, tmp_path)
    md = result["md_text"]
    assert "> ⚠" not in md, f"factual {template_name} must NOT have §13.2 review banner"
    assert "human_review_required" not in md, (
        f"factual {template_name} must NOT mention human_review_required"
    )


# ---------------------------------------------------------------------------
# Regression: subprocess UTF-8 encoding (Windows + Chinese stderr)
# ---------------------------------------------------------------------------


def test_subprocess_handles_chinese_stdout(runtime, registry, tmp_path):
    """The data_runner must use UTF-8 explicitly; otherwise Windows + Chinese
    stderr produces ``completed.stderr=None`` and crashes the error path.
    Regression for the bug surfaced during e2e harness development."""
    result = _drive_template(runtime, registry, "diagnosis-fault", tmp_path)
    # Demo data includes Chinese strings (设备/告警/振动) — if subprocess decode
    # had failed, run_data_steps_and_transforms would have raised before
    # producing a fault_context.json.
    assert "fault_context" in result["step_outputs"]
    assert result["step_outputs"]["fault_context"]
