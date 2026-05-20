"""Schema validation for the 10 new skills added by OpenSpec change
`wire-equipment-reports-real-data` §11.

Covers the 9 InS multi-series data-access skill directories
(ins-get-trend-data-{2k,6k,9k} / ins-extract-trend-features-{2k,6k,9k} /
ins-device-analysis-{2k,6k,9k}) plus the upper-layer corrosion diagnosis skill
`static-equipment-corrosion-diagnosis`.

Behavioural / pipeline tests for the 9 InS wrappers live in
``docker/sandbox/features-tool/tests/test_tools.py`` — that suite mocks
``InsApiClient.get_trend_data`` and asserts ``endpoint_series`` passthrough.
This file complements those by ensuring the **skill packaging** is valid
(frontmatter parses, run.sh exists for data-access skills, references file
exists for the diagnosis skill, fault-family codes documented).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deerflow.skills.validation import _validate_skill_frontmatter

SKILLS_CUSTOM_DIR = Path(__file__).resolve().parents[2] / "skills" / "custom"

DATA_ACCESS_SKILLS = [
    "ins-get-trend-data-2k",
    "ins-get-trend-data-6k",
    "ins-get-trend-data-9k",
    "ins-extract-trend-features-2k",
    "ins-extract-trend-features-6k",
    "ins-extract-trend-features-9k",
    "ins-device-analysis-2k",
    "ins-device-analysis-6k",
    "ins-device-analysis-9k",
]

DIAGNOSIS_SKILL = "static-equipment-corrosion-diagnosis"

CORROSION_FAULT_CODES = (
    "corrosion_rate_anomaly",
    "thickness_remaining_life",
    "thinning_rate_step_change",
    "process_temperature_coupling",
)


@pytest.mark.parametrize("skill_name", DATA_ACCESS_SKILLS)
def test_data_access_skill_frontmatter_valid(skill_name: str) -> None:
    skill_dir = SKILLS_CUSTOM_DIR / skill_name
    assert skill_dir.is_dir(), f"missing skill directory: {skill_dir}"

    valid, msg, name = _validate_skill_frontmatter(skill_dir)
    assert valid, f"{skill_name}: {msg}"
    assert name == skill_name, f"{skill_name}: frontmatter name mismatch ({name!r})"


@pytest.mark.parametrize("skill_name", DATA_ACCESS_SKILLS)
def test_data_access_skill_has_run_script(skill_name: str) -> None:
    run_sh = SKILLS_CUSTOM_DIR / skill_name / "scripts" / "run.sh"
    assert run_sh.is_file(), f"{skill_name}: scripts/run.sh missing"

    body = run_sh.read_text(encoding="utf-8")
    assert "FEATURES_TOOL_ROOT" in body, f"{skill_name}: run.sh missing FEATURES_TOOL_ROOT guard"

    # Each *-2k / *-6k / *-9k wrapper must invoke the matching series tool.
    series = skill_name.rsplit("-", 1)[-1]
    assert series in {"2k", "6k", "9k"}, f"unexpected series in {skill_name}"
    assert f"_{series}_tool.py" in body, (
        f"{skill_name}: run.sh does not invoke the matching *_{series}_tool.py wrapper"
    )


def test_static_equipment_corrosion_diagnosis_frontmatter_valid() -> None:
    skill_dir = SKILLS_CUSTOM_DIR / DIAGNOSIS_SKILL
    assert skill_dir.is_dir(), f"missing skill directory: {skill_dir}"

    valid, msg, name = _validate_skill_frontmatter(skill_dir)
    assert valid, f"{DIAGNOSIS_SKILL}: {msg}"
    assert name == DIAGNOSIS_SKILL


def test_static_equipment_corrosion_diagnosis_references_present() -> None:
    rules = (
        SKILLS_CUSTOM_DIR / DIAGNOSIS_SKILL / "references" / "diagnosis-rules.md"
    )
    assert rules.is_file(), f"{DIAGNOSIS_SKILL}: references/diagnosis-rules.md missing"

    body = rules.read_text(encoding="utf-8")
    # Rule reference must enumerate the 4 documented rule ids so SKILL.md and
    # references file stay in sync. (rule ids come from OpenSpec §11.4.3.)
    for rule_id in (
        "static-corrosion-rate-r1",
        "static-thickness-life-r1",
        "static-thinning-step-r1",
        "static-temperature-coupling-r1",
    ):
        assert rule_id in body, f"{DIAGNOSIS_SKILL}: missing rule id {rule_id}"


def test_static_equipment_corrosion_diagnosis_documents_fault_codes() -> None:
    skill_md = SKILLS_CUSTOM_DIR / DIAGNOSIS_SKILL / "SKILL.md"
    assert skill_md.is_file()

    body = skill_md.read_text(encoding="utf-8")
    for code in CORROSION_FAULT_CODES:
        assert code in body, f"{DIAGNOSIS_SKILL}: SKILL.md must reference fault code `{code}`"
