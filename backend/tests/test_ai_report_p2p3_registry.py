"""Sprint S6 — registry / DSL template alignment for P2+P3 reports.

Verifies that every CLI flag used by the enhanced stub scripts is declared in
the script's ``args_schema`` block in report_scripts.yaml, and that DSL
templates only reference scripts present in the registry. This catches drift
where a script grows a new flag but the registry forgets to register it.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "skills" / "custom" / "data-analyst" / "scripts"
TEMPLATES_DIR = REPO_ROOT / "agents" / "builtin" / "report-templates"
REGISTRY_YAML = REPO_ROOT / "skills" / "custom" / "data-analyst" / "report_scripts.yaml"


@pytest.fixture()
def registry_doc():
    return yaml.safe_load(REGISTRY_YAML.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "script_name,expected_args",
    [
        (
            "query_fault_context",
            {"fault_time", "equipment_id", "symptom", "include_related_equipment"},
        ),
        ("build_fault_timeline", {"input"}),
        (
            "query_failure_data",
            {"asset_id", "failure_mode", "analysis_method", "evidence_range"},
        ),
        ("failure_analysis", {"input"}),
        (
            "query_closure_items",
            {"issue_ids", "owner_department", "verification_period"},
        ),
        ("closure_summary", {"input"}),
        (
            "query_inspection",
            {"inspection_date", "route", "area", "severity_min"},
        ),
        ("inspection_summary", {"input"}),
        ("inspection_attachment_summary", {"input"}),
    ],
)
def test_registry_args_cover_cli_flags(registry_doc, script_name, expected_args):
    """For each script, registry args_schema must include all CLI flags the
    new (sprint S1-S5) script implementation accepts."""
    entry = registry_doc["scripts"].get(script_name)
    assert entry is not None, f"{script_name} not in registry"
    declared = set(entry.get("args_schema", {}).keys())
    missing = expected_args - declared
    assert not missing, (
        f"{script_name}: registry args_schema is missing CLI flag(s) {missing}; "
        f"declared={sorted(declared)}"
    )


@pytest.mark.parametrize(
    "template_name",
    ["failure-analysis", "closure-summary", "inspection"],
)
def test_template_references_only_registered_scripts(registry_doc, template_name):
    """No DSL template should reference a script not in the registry."""
    template = yaml.safe_load((TEMPLATES_DIR / template_name / "default.yaml").read_text(encoding="utf-8"))
    registered = set(registry_doc["scripts"].keys())
    referenced: set[str] = set()
    # Walk data_steps + transforms + form_steps[].before_step
    for step in template.get("data_steps") or []:
        if step.get("name", "").startswith("data-analyst/"):
            referenced.add(step["name"].removeprefix("data-analyst/"))
    for step in template.get("transforms") or []:
        if step.get("name", "").startswith("data-analyst/"):
            referenced.add(step["name"].removeprefix("data-analyst/"))
    for fs in template.get("form_steps") or []:
        before = fs.get("before_step")
        if before and before.get("name", "").startswith("data-analyst/"):
            referenced.add(before["name"].removeprefix("data-analyst/"))

    missing = referenced - registered
    assert not missing, f"{template_name} references unregistered scripts: {missing}"


@pytest.mark.parametrize(
    "template_name",
    ["failure-analysis", "closure-summary", "inspection"],
)
def test_template_passes_dsl_validator(template_name):
    """Sprint plan S6 acceptance — all 5 P2/P3 templates pass validate_dsl."""
    # Stub langgraph for runtime imports
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
    registry = ScriptRegistry(scripts=scripts)

    doc = yaml.safe_load((TEMPLATES_DIR / template_name / "default.yaml").read_text(encoding="utf-8"))
    report = validate_dsl(doc, registry=registry)
    assert report.valid, f"{template_name} validate errors: {[e.message for e in report.errors]}"
