"""Exercise the skill packager through its standalone and module entry points."""

import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

SKILL_CREATOR = Path(__file__).resolve().parents[2] / "skills/public/skill-creator"


@pytest.mark.parametrize("entrypoint", ["script", "module"])
@pytest.mark.parametrize("valid", [True, False], ids=["valid", "invalid"])
def test_packager_cli(tmp_path, entrypoint, valid):
    skill = tmp_path / "example-skill"
    skill.mkdir()
    content = "---\nname: example-skill\ndescription: Example skill.\n---\n"
    if not valid:
        content = "# Missing frontmatter\n"
    (skill / "SKILL.md").write_text(content, encoding="utf-8", newline="\n")
    output = tmp_path / "dist"
    if entrypoint == "script":
        command = [str(SKILL_CREATOR / "scripts/package_skill.py")]
        cwd = tmp_path
    else:
        command = ["-m", "scripts.package_skill"]
        cwd = SKILL_CREATOR
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    env.pop("PYTHONPATH", None)

    result = subprocess.run(
        [sys.executable, "-B", *command, str(skill), str(output)],
        cwd=cwd,
        env=env,
        capture_output=True,
        encoding="utf-8",
        timeout=15,
    )

    assert result.returncode == (0 if valid else 1), result.stdout + result.stderr
    assert "Traceback" not in result.stderr
    archive = output / "example-skill.skill"
    if valid:
        with zipfile.ZipFile(archive) as package:
            assert package.read("example-skill/SKILL.md").decode("utf-8") == content
    else:
        assert "No YAML frontmatter found" in result.stdout
        assert not archive.exists()
