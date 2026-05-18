"""Builtin DSL pack validator — runs in CI for every push so a regression in
the validator or registry is caught before it hits production users.

Per §11.4.4: a builtin failing validator triggers a fallback for ai-report--daily.
This test ensures we notice that **before** rolling out.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from deerflow.report_templates.script_registry import _build_registry_from_skills
from deerflow.report_templates.validator import validate_dsl


def _repo_root() -> Path:
    """Find the project root (where ``agents/builtin/`` lives)."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "agents" / "builtin").is_dir():
            return parent
    raise RuntimeError("agents/builtin not found anywhere up the tree")


def _all_builtin_template_dirs() -> list[Path]:
    root = _repo_root() / "agents" / "builtin" / "report-templates"
    if not root.exists():
        return []
    return [d for d in root.iterdir() if d.is_dir() and (d / "default.yaml").exists()]


def _registry_from_skills():
    skills_root = _repo_root() / "skills"
    skill_dirs: list[tuple[str, Path, bool]] = []
    for category in ("public", "custom"):
        cat_root = skills_root / category
        if not cat_root.exists():
            continue
        for skill_dir in cat_root.iterdir():
            if not skill_dir.is_dir():
                continue
            if (skill_dir / "report_scripts.yaml").exists():
                skill_dirs.append((skill_dir.name, skill_dir, True))
    return _build_registry_from_skills(skill_dirs)


@pytest.mark.parametrize("template_dir", _all_builtin_template_dirs(), ids=lambda p: p.name)
def test_builtin_template_validates(template_dir: Path):
    """Every shipped DSL under agents/builtin/report-templates must validate clean."""
    dsl = yaml.safe_load((template_dir / "default.yaml").read_text(encoding="utf-8"))
    registry = _registry_from_skills()
    report = validate_dsl(dsl, registry=registry)
    if not report.valid:
        details = "\n".join(
            f"  {e.code} @ {e.path}: {e.message}" for e in report.errors
        )
        raise AssertionError(
            f"builtin template {template_dir.name!r} failed validation:\n{details}"
        )
    # Warnings are tolerated, but we surface them in the test log so noisy
    # warnings get cleaned up over time.
    if report.warnings:
        for w in report.warnings:
            print(f"WARN {w.code} @ {w.path}: {w.message}")


def test_at_least_one_builtin_template_exists():
    """If this fails, the daily-equipment baseline was deleted."""
    dirs = _all_builtin_template_dirs()
    assert any(d.name == "daily-equipment" for d in dirs), (
        "daily-equipment builtin template missing — required by Phase 4"
    )
