"""Description optimization must evaluate the same YAML scalars as the loader."""

import importlib.util
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).resolve().parents[2] / "skills/public/skill-creator"


def load_script(name):
    spec = importlib.util.spec_from_file_location("skill_creator_" + name, SKILL_ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
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
