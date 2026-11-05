"""Description optimization must evaluate the same YAML scalars as the loader."""

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).resolve().parents[2] / "skills/public/skill-creator"


def load_script(name, skill_root=SKILL_ROOT):
    spec = importlib.util.spec_from_file_location("skill_creator_" + name, skill_root / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


@pytest.mark.parametrize(
    ("description_yaml", "expected"),
    [
        ('"Use \\"quoted\\" examples"', 'Use "quoted" examples'),
        ("'Write the user''s report'", "Write the user's report"),
        ("Research papers # maintainer note", "Research papers"),
        ("|-\n  First line\n  Second line", "First line\nSecond line"),
        (">-\n  First paragraph\n\n  Second paragraph", "First paragraph\nSecond paragraph"),
        ("|2-\n  Keep this line\n  And this one", "Keep this line\nAnd this one"),
        ("Plain description", "Plain description"),
    ],
)
@pytest.mark.parametrize("name_yaml", ["example", "example # comment"])
def test_optimizer_reads_validated_yaml_values(tmp_path, description_yaml, expected, name_yaml):
    content = "---\nname: " + name_yaml + "\ndescription: " + description_yaml + "\n---\n# Body\n"
    (tmp_path / "SKILL.md").write_text(content, encoding="utf-8")
    assert load_script("quick_validate").validate_skill(tmp_path)[0]
    name, description, body = load_script("utils").parse_skill_md(tmp_path)
    assert name == "example"
    assert description == expected
    assert body == content


@pytest.mark.parametrize("frontmatter", ["- item", "name: example\ndescription: [not, text]", "name: true\ndescription: text", "name: example\ndescription: ["])
def test_optimizer_rejects_invalid_metadata(tmp_path, frontmatter):
    (tmp_path / "SKILL.md").write_text("---\n" + frontmatter + "\n---\nbody", encoding="utf-8")
    with pytest.raises(ValueError):
        load_script("utils").parse_skill_md(tmp_path)


@pytest.mark.parametrize("name", ["utils", "quick_validate"])
def test_script_loader_preserves_bytecode_setting(monkeypatch, tmp_path, name):
    isolated = tmp_path / "skill"
    shutil.copytree(SKILL_ROOT, isolated, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    module = load_script(name, isolated)
    assert not list(isolated.rglob("*.pyc"))
    assert sys.dont_write_bytecode is False
    assert sys.modules[module.__name__] is module


@pytest.mark.parametrize("command", ["run_eval", "run_loop", "improve_description"])
@pytest.mark.parametrize("metadata", ["name: example\ndescription: [", "name: true\ndescription: example", "missing frontmatter"])
def test_cli_reports_invalid_frontmatter_without_traceback(tmp_path, command, metadata):
    skill = tmp_path / "input-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\n" + metadata + "\n---\nBody", encoding="utf-8")
    inputs = tmp_path / "eval.json"
    inputs.write_text("{}" if command == "improve_description" else "[]", encoding="utf-8")
    args = ["--skill-path", str(skill)]
    if command == "improve_description":
        args += ["--eval-results", str(inputs), "--model", "offline-test"]
    else:
        args += ["--eval-set", str(inputs)]
    if command == "run_loop":
        args += ["--model", "offline-test", "--report", "none"]
    result = subprocess.run(
        [sys.executable, "-B", "-m", "scripts." + command, *args],
        cwd=SKILL_ROOT,
        env={**os.environ, "PATH": "", "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert result.stderr.startswith("Error: ")
    assert "Traceback" not in result.stderr
    assert result.stdout == ""
