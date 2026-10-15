"""The standalone validator must reject unusable required skill metadata."""

import runpy
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

VALIDATOR = (
    Path(__file__).resolve().parents[2]
    / "skills/public/skill-creator/scripts/quick_validate.py"
)
validate_skill = runpy.run_path(str(VALIDATOR))["validate_skill"]


def write_skill(directory, **overrides):
    metadata = {"name": "example-skill", "description": "Use for example tasks."}
    metadata.update(overrides)
    text = "---\n" + yaml.safe_dump(metadata, allow_unicode=True) + "---\nBody.\n"
    (directory / "SKILL.md").write_text(text, encoding="utf-8")
    return text


@pytest.mark.parametrize("field", ["name", "description"])
@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_rejects_blank_required_metadata(tmp_path, field, value):
    original = write_skill(tmp_path, **{field: value})

    valid, message = validate_skill(tmp_path)

    assert valid is False
    assert message == f"{field.capitalize()} cannot be empty"
    assert (tmp_path / "SKILL.md").read_text(encoding="utf-8") == original


@pytest.mark.parametrize("field", ["name", "description"])
@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_cli_rejects_blank_required_metadata(tmp_path, field, value):
    write_skill(tmp_path, **{field: value})

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), str(tmp_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert f"{field.capitalize()} cannot be empty" in result.stdout


@pytest.mark.parametrize(
    ("name", "description"),
    [
        ("example-skill", "Use for example tasks."),
        ("  example-skill  ", "  用于示例任务。  "),
    ],
)
def test_accepts_nonempty_required_metadata(tmp_path, name, description):
    original = write_skill(tmp_path, name=name, description=description)

    assert validate_skill(tmp_path) == (True, "Skill is valid!")
    assert (tmp_path / "SKILL.md").read_text(encoding="utf-8") == original


@pytest.mark.parametrize("description", ["Use for example tasks.", "用于示例任务。"])
def test_cli_accepts_nonempty_required_metadata(tmp_path, description):
    write_skill(tmp_path, description=description)

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), str(tmp_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Skill is valid!" in result.stdout


@pytest.mark.parametrize("field", ["name", "description"])
@pytest.mark.parametrize("value", [None, 0, []])
def test_nonstring_required_metadata_still_reports_type(tmp_path, field, value):
    write_skill(tmp_path, **{field: value})

    valid, message = validate_skill(tmp_path)

    assert valid is False
    assert (
        message == f"{field.capitalize()} must be a string, got {type(value).__name__}"
    )
