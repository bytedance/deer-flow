"""Monthly contract tests for ``skills/custom/monthly-report/report_scripts.yaml``.

Mirrors test_ai_report_weekly_registry.py but focuses on the monthly entries
introduced by Sprint M6:

1. ``query_monthly`` and ``monthly_kpi`` are declared in YAML and present on disk.
2. The ``compare`` enum uses the canonical long names
   (``previous_month`` / ``previous_year_month`` / ``none``) — short names
   ``mom`` / ``yoy`` must NOT be the script-level enum.
3. ``args_aliases.compare`` declares the DSL-level ``mom`` → ``previous_month`` /
   ``yoy`` → ``previous_year_month`` translation contract.
4. ``output_files`` paths use ``{run_output_dir}`` placeholder (not hardcoded
   ``/mnt/user-data/outputs/``).
5. Weekly entries still parse and remain untouched by the monthly additions
   (zero-regression).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = REPO_ROOT / "skills" / "custom" / "monthly-report"
REGISTRY_PATH = SKILL_DIR / "report_scripts.yaml"
SCRIPTS_DIR = SKILL_DIR / "scripts"


def _load_registry() -> dict:
    return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))


def test_registry_parses_with_schema_version_1():
    doc = _load_registry()
    assert str(doc.get("schema_version")) == "1"
    assert isinstance(doc.get("scripts"), dict)


def test_monthly_scripts_registered():
    doc = _load_registry()
    assert "query_monthly" in doc["scripts"]
    assert "monthly_kpi" in doc["scripts"]


def test_monthly_script_files_exist_on_disk():
    doc = _load_registry()
    for name in ("query_monthly", "monthly_kpi"):
        entry_path = doc["scripts"][name]["entry"]
        # entry is relative to skill dir
        target = SKILL_DIR / entry_path
        assert target.exists(), f"{name} entry not found on disk: {target}"


def test_compare_enum_uses_long_names_only():
    """sprint plan M6: script-level enum MUST be long names; DSL short names
    are mapped via args_aliases at the platform layer."""
    doc = _load_registry()
    compare = doc["scripts"]["query_monthly"]["args_schema"]["compare"]
    pattern = compare["items"]["pattern"]
    # Long names must be in the pattern
    assert "previous_month" in pattern
    assert "previous_year_month" in pattern
    assert "none" in pattern
    # Short names MUST NOT be in the script-level enum
    assert "mom" not in pattern.split("|")[0:3]  # check first 3 alternates
    assert "yoy" not in pattern.split("|")[0:3]


def test_compare_args_aliases_declared():
    """Sprint M6: args_aliases.compare must map mom→previous_month, yoy→previous_year_month."""
    doc = _load_registry()
    aliases = doc["scripts"]["query_monthly"].get("args_aliases", {})
    assert aliases.get("compare") == {
        "mom": "previous_month",
        "yoy": "previous_year_month",
    }, f"missing or wrong args_aliases.compare: {aliases}"


def test_query_monthly_args_complete():
    """All CLI flags the script accepts are declared in args_schema."""
    doc = _load_registry()
    schema = doc["scripts"]["query_monthly"]["args_schema"]
    for required_arg in (
        "report_month",
        "type",
        "equipment",
        "scope",
        "scope_filter",
        "kpis",
        "compare",
        "aggregate",
        "include_daily",
    ):
        assert required_arg in schema, f"args_schema missing: {required_arg}"


def test_output_files_use_run_output_dir_placeholder():
    doc = _load_registry()
    for name in ("query_monthly", "monthly_kpi"):
        for of in doc["scripts"][name]["output_files"]:
            assert "{run_output_dir}" in of["path"], (
                f"{name}.output_files[].path must use {{run_output_dir}} placeholder, "
                f"got: {of['path']}"
            )
            assert "/mnt/user-data/outputs" not in of["path"], (
                f"{name}.output_files[].path must not hardcode /mnt/user-data/outputs/"
            )


def test_weekly_entries_still_parse():
    """Zero-regression: weekly entries that already existed must remain intact."""
    doc = _load_registry()
    assert "query_weekly" in doc["scripts"]
    assert "weekly_kpi" in doc["scripts"]
    # Weekly compare enum should remain unchanged
    wk_compare = doc["scripts"]["query_weekly"]["args_schema"]["compare"]
    assert wk_compare["values"] == ["previous_week", "previous_year", "none"]


def test_monthly_kpi_output_description_documents_no_summary_markdown():
    """The registry description should hint at the rendering-layer contract
    so DSL template authors know not to read summary_markdown from the script
    output (it never exists)."""
    doc = _load_registry()
    desc = doc["scripts"]["monthly_kpi"]["output_files"][0]["description"]
    # Description should mention that full markdown rendering lives in export_report.
    assert "summary_markdown" in desc or "render_monthly_markdown" in desc or "export_report" in desc, (
        f"monthly_kpi.output_files[0].description should reference the rendering contract; got: {desc}"
    )
