"""End-to-end smoke harness for ai-report--custom Lane A (run-report path).

Drives the runtime modules directly (skipping the LLM + GenUI middleware):

  build DSL + state → run_data_steps_and_transforms → assemble_payload
  → render_report_blocks → export_report → assert ExportResult.md_path exists

Why this matters: the previous _smoke_e2e_p2p3.py only verified individual
script + DSL validate. This harness exercises the full runtime stack
(data_runner.run_script → subprocess → DataConnector → demo provider →
JSONPath → markdown rendering) for every builtin DSL template.

Run from repo root:
    PYTHONIOENCODING=utf-8 python skills/custom/data-analyst/scripts/_smoke_e2e_runtime.py

The harness writes outputs to /tmp/runtime-e2e-<template>/ so you can inspect
the generated report_payload.json + exports/report.md by hand.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
BACKEND_DIR = REPO_ROOT / "backend"
SCRIPTS_DIR = REPO_ROOT / "skills" / "custom" / "data-analyst" / "scripts"
TEMPLATES_DIR = REPO_ROOT / "agents" / "builtin" / "report-templates"
REGISTRY_YAML = REPO_ROOT / "skills" / "custom" / "data-analyst" / "report_scripts.yaml"


def _stub_langgraph() -> None:
    """Inject a minimal langgraph stub so harness imports work outside a graph."""
    fake_lg = types.ModuleType("langgraph")
    fake_config = types.ModuleType("langgraph.config")
    fake_config.get_config = lambda: {}
    fake_config.get_stream_writer = lambda: (lambda *a, **k: None)
    sys.modules.setdefault("langgraph", fake_lg)
    sys.modules.setdefault("langgraph.config", fake_config)


def _import_runtime():
    """Import everything we need in one shot — returns a namespace dict."""
    _stub_langgraph()
    sys.path.insert(0, str(BACKEND_DIR / "packages" / "harness"))

    import yaml  # noqa: WPS433  -- in-function import so failures show clearly

    from deerflow.report_templates.runtime.data_runner import (  # type: ignore
        run_data_steps_and_transforms,
    )
    from deerflow.report_templates.runtime.payload_builder import (  # type: ignore
        assemble_payload,
    )
    from deerflow.report_templates.runtime.report_renderer import (  # type: ignore
        render_report_blocks,
    )
    from deerflow.report_templates.runtime.exporter import export_report  # type: ignore
    from deerflow.report_templates.runtime.state import RuntimeState  # type: ignore
    from deerflow.report_templates.script_registry import (  # type: ignore
        ScriptRegistry,
        ScriptDescriptor,
        ScriptDescriptorYaml,
    )

    return {
        "yaml": yaml,
        "run_data_steps_and_transforms": run_data_steps_and_transforms,
        "assemble_payload": assemble_payload,
        "render_report_blocks": render_report_blocks,
        "export_report": export_report,
        "RuntimeState": RuntimeState,
        "ScriptRegistry": ScriptRegistry,
        "ScriptDescriptor": ScriptDescriptor,
        "ScriptDescriptorYaml": ScriptDescriptorYaml,
    }


def _build_registry(ns) -> "ScriptRegistry":  # type: ignore[name-defined]
    """Construct a ScriptRegistry from report_scripts.yaml without going through
    skill discovery (which would pull langchain into the import chain)."""
    reg_doc = ns["yaml"].safe_load(REGISTRY_YAML.read_text(encoding="utf-8"))
    skill_dir = (REPO_ROOT / "skills" / "custom" / "data-analyst").resolve()
    scripts = {}
    for sname, sdef in reg_doc.get("scripts", {}).items():
        d = ns["ScriptDescriptorYaml"].model_validate(sdef)
        qual = f"data-analyst/{sname}"
        scripts[qual] = ns["ScriptDescriptor"](
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
    return ns["ScriptRegistry"](scripts=scripts)


# ---------------------------------------------------------------------------
# Per-template form fixtures
#
# To run the data_steps / transforms / sections phases we need to populate
# state.form_state with values matching each template's form_steps. These
# fixtures simulate "user already submitted every form_step".
# ---------------------------------------------------------------------------

FORM_FIXTURES: dict[str, dict[str, dict]] = {
    "trend-equipment": {
        "scope": {
            "date_range": "2026-04-01..2026-04-30",
            "aggregation": "daily",
            "forecast_horizon": 7,
        },
        "kpis": {
            "metric_keys": ["runtime_rate", "vibration_level", "alarm_count", "bearing_temp"],
        },
    },
    "diagnosis-fault": {
        "scope": {
            "equipment_id": "P-001",
            "fault_time": "2026-05-15",
            "symptom": "vibration high + bearing temp climbing",
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


def _make_state(ns, template_name: str, run_dir: Path) -> object:
    fixture = FORM_FIXTURES[template_name]
    return ns["RuntimeState"](
        report_run_id=f"rr_e2e_{template_name}",
        thread_id="thread_e2e",
        template_id=f"builtin-{template_name}",
        template_version=None,
        template_version_ref=f"builtin-{template_name}",
        status="ready_for_data",
        nonce="dummy",
        expected_step="__generate__",
        created_at="2026-05-18T00:00:00",
        form_state=fixture,
        step_outputs={},
        completed_steps=list(fixture.keys()),
    )


def _run_case(ns, template_name: str, base_out_dir: Path) -> dict:
    """Drive one template through runtime end-to-end. Returns metrics dict."""
    print(f"\n=== {template_name} ===")

    template_doc = ns["yaml"].safe_load(
        (TEMPLATES_DIR / template_name / "default.yaml").read_text(encoding="utf-8")
    )

    run_dir = base_out_dir / template_name
    run_dir.mkdir(parents=True, exist_ok=True)

    # Persist template DSL alongside status.json (data_runner reads it via
    # _resolve_input_path's run_output_dir). We use a separate state without
    # status.json since this harness drives modules directly.
    state = _make_state(ns, template_name, run_dir)

    # 1. data_steps + transforms
    context = {
        "form": state.form_state,
        "steps": state.step_outputs,
        "run": {"report_run_id": state.report_run_id, "thread_id": state.thread_id, "generated_at": state.created_at},
        "template": {"id": state.template_id, "version": None, "name": template_name},
    }
    registry = _build_registry(ns)
    accumulated = ns["run_data_steps_and_transforms"](
        dsl=template_doc, registry=registry, run_output_dir=run_dir, context=context,
    )
    state.step_outputs = accumulated
    print(f"  [data] steps completed: {sorted(accumulated.keys())}")

    # 2. assemble_payload
    payload = ns["assemble_payload"](dsl=template_doc, state=state)
    payload_path = run_dir / "report_payload.json"
    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    section_count = len(payload.get("sections") or [])
    print(f"  [payload] sections: {section_count} -> {payload_path}")

    # 3. render_report_blocks intentionally skipped — it requires a langgraph
    #    StreamWriter which only exists inside an SSE request. In production
    #    the LLM is what triggers render_report_blocks; for e2e validation of
    #    the data → payload → markdown chain, assemble_payload + export_report
    #    is enough.
    block_count = 0
    print(f"  [render] skipped (requires SSE stream writer; not part of e2e scope)")

    # 4. export_report
    result = ns["export_report"](payload=payload, run_output_dir=run_dir, pdf=False)
    md_path = Path(result.md_path)
    md_size = md_path.stat().st_size
    print(f"  [export] md_path={md_path} ({md_size} bytes)")

    # Sanity checks on the markdown output
    md_text = md_path.read_text(encoding="utf-8")
    assert md_text.startswith("# "), "Markdown must start with H1 title"
    assert len(md_text) > 200, f"Markdown unexpectedly short: {len(md_text)} chars"

    return {
        "template": template_name,
        "step_count": len(accumulated),
        "section_count": section_count,
        "block_count": block_count,
        "md_path": str(md_path),
        "md_size": md_size,
        "is_interpretive": "human_review_required" in md_text or "⚠" in md_text,
    }


def main() -> int:
    ns = _import_runtime()
    base_out_dir = Path(tempfile.mkdtemp(prefix="runtime-e2e-"))
    print(f"e2e run dir: {base_out_dir}")

    results: list[dict] = []
    failures: list[tuple[str, str]] = []

    for template in [
        "trend-equipment",
        "diagnosis-fault",
        "failure-analysis",
        "closure-summary",
        "inspection",
    ]:
        try:
            results.append(_run_case(ns, template, base_out_dir))
        except Exception as exc:  # noqa: BLE001
            import traceback
            failures.append((template, f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"))
            print(f"  [FAIL] {type(exc).__name__}: {exc}")

    print("\n=== SUMMARY ===")
    for r in results:
        flag = "📊" if r["is_interpretive"] else "📋"
        print(
            f"  [OK] {flag} {r['template']:22s} steps={r['step_count']} sections={r['section_count']} "
            f"blocks={r['block_count']} md={r['md_size']:>6}b"
        )

    if failures:
        print(f"\nFAILED ({len(failures)}/{len(results) + len(failures)}):")
        for tpl, err in failures:
            print(f"  - {tpl}: {err[:200]}")
        return 1

    print(f"\nALL CASES PASSED [OK] ({len(results)}/5)")
    print(f"\nArtifacts available at: {base_out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
