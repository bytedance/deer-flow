"""Contract tests for ``skills/custom/weekly-report/report_scripts.yaml``.

The YAML is the **contract surface** between this skill and the AI Report
Custom Template platform (design §9.1.1). These tests verify three invariants
that would silently break the contract if drifted:

1. The YAML parses and follows the schema_version=1 shape.
2. Every script declared in YAML actually exists on disk under
   ``skills/custom/weekly-report/scripts/`` and its CLI accepts every
   declared arg.
3. Field names align with the weekly DSL draft in
   ``docs/plans/2026-05-14-ai-report-custom-template-design.md`` §13.3
   (``week_start`` / ``equipment_type`` / ``equipment_ids`` / ``kpi_keys`` /
   ``compare_with``) — this keeps the native SOUL.md path and the future
   DSL builtin template (``weekly-equipment``) sharing the same scripts.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = REPO_ROOT / "skills" / "custom" / "weekly-report"
REGISTRY_PATH = SKILL_DIR / "report_scripts.yaml"
SCRIPTS_DIR = SKILL_DIR / "scripts"
WEEKLY_TEMPLATE_DIR = REPO_ROOT / "agents" / "builtin" / "report-templates" / "weekly-equipment"


def _load_registry() -> dict:
    return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))


def _load_weekly_builtin_template() -> dict:
    return yaml.safe_load((WEEKLY_TEMPLATE_DIR / "default.yaml").read_text(encoding="utf-8"))


def _load_weekly_sample_parameters() -> dict:
    return json.loads((WEEKLY_TEMPLATE_DIR / "examples" / "sample_parameters.json").read_text(encoding="utf-8"))


def _load_script_module(script_filename: str):
    path = SCRIPTS_DIR / script_filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# 1. YAML shape
# ---------------------------------------------------------------------------


def test_yaml_parses():
    """report_scripts.yaml must parse as valid YAML."""
    registry = _load_registry()
    assert isinstance(registry, dict)


def test_yaml_schema_version_is_one():
    """Locked to schema_version: 1 so the platform loader knows how to read it."""
    registry = _load_registry()
    assert registry.get("schema_version") == "1"


def test_yaml_declares_scripts_section():
    registry = _load_registry()
    assert "scripts" in registry
    assert isinstance(registry["scripts"], dict)
    assert len(registry["scripts"]) >= 2  # at minimum: query_weekly + weekly_kpi


def test_each_script_has_required_fields():
    """Per design §9.1.1: entry, kind, args_schema, output_files, timeout_seconds, max_output_bytes.

    ``form_options`` scripts use ``outputs_schema`` instead of ``output_files`` because
    their outputs are returned inline to the form runner rather than written to the run dir.
    """
    registry = _load_registry()
    for name, decl in registry["scripts"].items():
        assert "entry" in decl, f"{name}: missing entry"
        assert "kind" in decl, f"{name}: missing kind"
        assert "args_schema" in decl, f"{name}: missing args_schema"
        assert "timeout_seconds" in decl, f"{name}: missing timeout_seconds"
        assert "max_output_bytes" in decl, f"{name}: missing max_output_bytes"
        assert isinstance(decl["kind"], list) and decl["kind"], f"{name}: kind must be non-empty list"
        kinds = set(decl["kind"])
        if kinds == {"form_options"}:
            assert "outputs_schema" in decl, f"{name}: form_options scripts must declare outputs_schema"
        else:
            assert "output_files" in decl, f"{name}: missing output_files"


def test_output_files_use_run_output_dir_placeholder():
    """All output paths must use {run_output_dir} so the platform can rebase them per-run."""
    registry = _load_registry()
    for name, decl in registry["scripts"].items():
        for output in decl.get("output_files", []):
            assert "{run_output_dir}" in output["path"], (
                f"{name}.output_files[{output.get('id')}] hardcodes a path; "
                f"must use {{run_output_dir}} placeholder"
            )


def test_output_file_ids_are_unique_per_script():
    registry = _load_registry()
    for name, decl in registry["scripts"].items():
        ids = [o["id"] for o in decl.get("output_files", [])]
        assert len(ids) == len(set(ids)), f"{name}: duplicate output ids {ids}"


# ---------------------------------------------------------------------------
# 2. Scripts exist on disk and accept declared args
# ---------------------------------------------------------------------------


def test_declared_entry_files_exist():
    registry = _load_registry()
    for name, decl in registry["scripts"].items():
        entry_path = SKILL_DIR / decl["entry"]
        assert entry_path.is_file(), f"{name}: entry {decl['entry']} not found on disk"


def test_query_weekly_args_match_cli():
    """Every arg declared in YAML must be accepted by query_weekly.py argparse."""
    registry = _load_registry()
    qw_args = set(registry["scripts"]["query_weekly"]["args_schema"].keys())

    qw = _load_script_module("query_weekly.py")
    # Inspect argparse by introspecting the script's argument names — by convention
    # the script's argument names match the CLI flags (dash → underscore).
    cli_flags = _extract_argparse_flags(qw)

    # Map YAML keys to the CLI flags the script declares.
    # YAML keys use the un-dashed form ('week_start') and CLI uses dashed
    # ('--week-start'); both map to the same Python attribute.
    for arg_name in qw_args:
        flag_underscore = arg_name
        flag_dashed = arg_name.replace("_", "-")
        assert (
            flag_underscore in cli_flags
            or flag_dashed in cli_flags
            or f"--{flag_dashed}" in cli_flags
        ), f"query_weekly.py CLI missing arg matching YAML key '{arg_name}'"


def test_weekly_kpi_args_match_cli():
    registry = _load_registry()
    wk_args = set(registry["scripts"]["weekly_kpi"]["args_schema"].keys())

    wk = _load_script_module("weekly_kpi.py")
    cli_flags = _extract_argparse_flags(wk)

    for arg_name in wk_args:
        assert (
            arg_name in cli_flags
            or arg_name.replace("_", "-") in cli_flags
            or f"--{arg_name.replace('_', '-')}" in cli_flags
        ), f"weekly_kpi.py CLI missing arg matching YAML key '{arg_name}'"


def _extract_argparse_flags(module) -> set[str]:
    """Inspect a script's source to extract declared argparse flag names.

    Avoids actually invoking main(): the goal is to verify the CLI surface
    statically. The source is regex-scanned for ``add_argument("--...")``.
    """
    source = Path(module.__file__).read_text(encoding="utf-8")
    flags: set[str] = set()
    for match in re.finditer(r'add_argument\(\s*[\'"](--[\w-]+)[\'"]', source):
        raw = match.group(1)
        flags.add(raw)
        flags.add(raw.lstrip("-"))
        flags.add(raw.lstrip("-").replace("-", "_"))
    return flags


# ---------------------------------------------------------------------------
# 3. Field names align with the DSL §13.3 weekly draft
# ---------------------------------------------------------------------------


def test_weekly_dsl_field_names_align():
    """Names in §13.3 weekly DSL draft must match this YAML's arg names.

    DSL draft (excerpt from design doc §13.3):
        form_steps:
          - id: scope
            fields:
              - name: week_start          ← matches query_weekly.args_schema.week_start
              - name: equipment_type      ← maps to query_weekly --type
              - name: compare_with        ← maps to query_weekly --compare
          - id: equipment
            fields:
              - name: equipment_ids       ← maps to query_weekly --equipment (CSV)
          - id: kpis
            fields:
              - name: kpi_keys            ← maps to query_weekly --kpis (CSV)

    The DSL draft is the user-facing contract; this test ensures the script
    side won't silently drift away from those names (or their well-known
    CLI aliases).
    """
    registry = _load_registry()
    qw_args = registry["scripts"]["query_weekly"]["args_schema"]
    # The DSL field names map to these YAML keys (and CLI flags):
    #   week_start    → 'week_start'      (identical)
    #   equipment_type→ 'type'             (CLI alias --type; YAML uses 'type')
    #   compare_with  → 'compare'          (CLI alias --compare; YAML uses 'compare')
    #   equipment_ids → 'equipment'        (CSV, CLI alias --equipment)
    #   kpi_keys      → 'kpis'             (CSV, CLI alias --kpis)
    expected_yaml_keys = {"week_start", "type", "compare", "equipment", "kpis"}
    actual_keys = set(qw_args.keys())
    missing = expected_yaml_keys - actual_keys
    assert not missing, (
        f"query_weekly args_schema missing DSL-aligned keys: {missing}. "
        f"§13.3 weekly DSL draft cannot be wired through to this script."
    )


def test_query_weekly_kind_includes_data_step():
    registry = _load_registry()
    assert "data_step" in registry["scripts"]["query_weekly"]["kind"]


def test_weekly_kpi_kind_includes_transform():
    registry = _load_registry()
    assert "transform" in registry["scripts"]["weekly_kpi"]["kind"]


def test_weekly_builtin_template_section_sources_match_weekly_kpi_contract():
    """The builtin weekly DSL must consume the current weekly_kpi.py output names.

    This guards the exact regression where the template kept the old
    ``trend_chart`` / ``top_anomalies`` / ``compare_summary`` / ``next_focus``
    sources after the script contract moved to
    ``daily_trend_chart`` / ``anomaly_top_n`` / ``alarm_table`` /
    ``next_week_focus``.
    """
    dsl = _load_weekly_builtin_template()
    actual = {section["id"]: section["source"] for section in dsl["sections"]}
    expected = {
        "overview": "$.steps.weekly_kpi.weekly_kpi.overall_status.summary",
        "kpi_cards": "$.steps.weekly_kpi.weekly_kpi.kpi_summary",
        "daily_trend": "$.steps.weekly_kpi.weekly_kpi.daily_trend_chart",
        "anomalies": "$.steps.weekly_kpi.weekly_kpi.anomaly_top_n",
        "alarms": "$.steps.weekly_kpi.weekly_kpi.alarm_table",
        "next_focus": "$.steps.weekly_kpi.weekly_kpi.next_week_focus",
    }
    assert actual == expected


def test_weekly_sample_parameters_kpis_match_selected_type():
    """Example parameters should stay runnable against list_equipment metadata."""
    params = _load_weekly_sample_parameters()
    eq_type = params["scope"]["equipment_type"]
    selected_kpis = set(params["kpis"]["kpi_keys"])
    list_equipment = _load_script_module("list_equipment.py")
    supported_kpis = set(list_equipment.EQUIPMENT_TYPE_KPIS[eq_type])
    unsupported = sorted(selected_kpis - supported_kpis)
    assert not unsupported, (
        f"weekly sample parameters pick unsupported KPI(s) for {eq_type}: {unsupported}"
    )


# ---------------------------------------------------------------------------
# 4. Resource limits are sane
# ---------------------------------------------------------------------------


def test_timeouts_are_positive_and_bounded():
    """Timeouts must be set and within a reasonable range (1s ~ 10min)."""
    registry = _load_registry()
    for name, decl in registry["scripts"].items():
        t = decl["timeout_seconds"]
        assert isinstance(t, int) and 1 <= t <= 600, f"{name}: timeout_seconds {t} out of range"


def test_max_output_bytes_are_positive():
    registry = _load_registry()
    for name, decl in registry["scripts"].items():
        b = decl["max_output_bytes"]
        assert isinstance(b, int) and b > 0, f"{name}: max_output_bytes {b} invalid"
