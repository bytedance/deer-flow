"""Exercise the public skill creation and packaging commands."""

import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

SKILL_CREATOR = Path(__file__).resolve().parents[2] / "skills/public/skill-creator"


def run_cli(script, *args, cwd, entrypoint="script"):
    command = [str(SKILL_CREATOR / "scripts" / f"{script}.py")]
    if entrypoint == "module":
        command = ["-m", f"scripts.{script}"]
        cwd = SKILL_CREATOR
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    env.pop("PYTHONPATH", None)
    return subprocess.run(
        [sys.executable, "-B", *command, *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        encoding="utf-8",
        timeout=15,
    )


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
    result = run_cli(
        "package_skill", skill, output, cwd=tmp_path, entrypoint=entrypoint
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


def test_init_creates_skill_under_requested_root(tmp_path):
    name = "example-" + "2" * 32
    root = tmp_path / "skills"
    result = run_cli("init_skill", name, "--path", root, cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    skill = root / name
    assert (skill / "scripts" / "example.py").is_file()
    assert (skill / "references" / "api_reference.md").is_file()
    assert (skill / "assets" / "example_asset.txt").is_file()
    manifest = skill / "SKILL.md"
    assert name in manifest.read_text(encoding="utf-8")

    manifest.write_text("Edited by the author.\n", encoding="utf-8")
    result = run_cli("init_skill", name, "--path", root, cwd=tmp_path)
    assert result.returncode == 1
    assert manifest.read_text(encoding="utf-8") == "Edited by the author.\n"


@pytest.mark.parametrize(
    "name",
    [
        "",
        "../sibling",
        "nested/child",
        r"nested\child",
        "Bad Name",
        "foo--bar",
        "-prefix",
        "suffix-",
        "x" * 41,
        pytest.param(None, id="absolute-path"),
    ],
)
def test_init_rejects_invalid_name_before_creating_directories(tmp_path, name):
    if name is None:
        name = str(tmp_path / "absolute-name")
    result = run_cli("init_skill", name, "--path", tmp_path / "skills", cwd=tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert not list(tmp_path.iterdir())


def test_init_rejects_existing_directory_link(tmp_path):
    root = tmp_path / "skills"
    root.mkdir()
    target = tmp_path / "existing"
    target.mkdir()
    (root / "my-skill").symlink_to(target, target_is_directory=True)
    result = run_cli("init_skill", "my-skill", "--path", root, cwd=tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert not list(target.iterdir())


def test_package_includes_regular_files_and_skips_symbolic_links(tmp_path):
    # Existing skills may use names up to the validator's 64-character limit.
    name = "s" * 64
    skill = tmp_path / name
    assets = skill / "assets"
    assets.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Example skill.\n---\n", encoding="utf-8"
    )
    (assets / "example.txt").write_text("Example asset.\n", encoding="utf-8")
    (assets / "cached.pyc").touch()
    (skill / "evals").mkdir()
    (skill / "evals" / "fixture.json").touch()
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "sample.txt").write_text("Sample fixture.\n", encoding="utf-8")
    (assets / "file-link").symlink_to(fixtures / "sample.txt")
    (assets / "dir-link").symlink_to(fixtures, target_is_directory=True)
    (assets / "internal-link").symlink_to("example.txt")
    (assets / "broken-link").symlink_to("missing")

    # The default output can be the source directory, including on a repeat run.
    for _ in range(2):
        result = run_cli("package_skill", skill, cwd=skill)
        assert result.returncode == 0, result.stdout + result.stderr
        with zipfile.ZipFile(skill / f"{name}.skill") as package:
            assert set(package.namelist()) == {
                f"{name}/SKILL.md",
                f"{name}/assets/example.txt",
            }
            assert package.read(f"{name}/assets/example.txt") == b"Example asset.\n"


def test_package_requires_regular_manifest(tmp_path):
    skill = tmp_path / "example-skill"
    skill.mkdir()
    template = tmp_path / "template.md"
    template.write_text(
        "---\nname: example-skill\ndescription: Example skill.\n---\n", encoding="utf-8"
    )
    (skill / "SKILL.md").symlink_to(template)
    output = tmp_path / "dist"
    result = run_cli("package_skill", skill, output, cwd=tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert not (output / "example-skill.skill").exists()


def test_package_rejects_output_file_link(tmp_path):
    skill = tmp_path / "example-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: example-skill\ndescription: Example skill.\n---\n", encoding="utf-8"
    )
    target = tmp_path / "sample.txt"
    target.write_bytes(b"Example fixture.")
    archive = tmp_path / "example-skill.skill"
    archive.symlink_to(target)
    result = run_cli("package_skill", skill, cwd=tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert archive.is_symlink()
    assert target.read_bytes() == b"Example fixture."
