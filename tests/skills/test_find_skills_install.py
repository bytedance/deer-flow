"""Exercise the find-skills installer inside and outside a DeerFlow checkout."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

INSTALLER = (
    Path(__file__).resolve().parents[2]
    / "skills/public/find-skills/scripts/install-skill.sh"
)
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(BASH is None, reason="the installer is a Bash script")


def write_npx_stub(bin_dir: Path, log: Path, status: int = 0) -> Path:
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / "npx"
    stub.write_text(
        "#!/bin/sh\n"
        f'echo "npx invoked" > "{log}"\n'
        'echo "stub-npx-diagnostic" >&2\n'
        f"exit {status}\n",
        encoding="utf-8",
        newline="\n",
    )
    stub.chmod(0o755)
    return stub


def run_installer(cwd: Path, bin_dir: Path, home: Path | None = None):
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
    }
    if home is not None:
        env["HOME"] = str(home)
    return subprocess.run(
        [BASH, str(INSTALLER), "example/repo@example-skill"],
        cwd=cwd,
        env=env,
        capture_output=True,
        encoding="utf-8",
        timeout=30,
    )


def test_installer_reports_a_missing_project_root(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    bin_dir = tmp_path / "bin"
    log = tmp_path / "npx.log"
    write_npx_stub(bin_dir, log, status=77)

    result = run_installer(workspace, bin_dir)

    assert result.returncode == 1
    assert "deer-flow.code-workspace" in result.stderr
    assert "skills/custom" in result.stderr
    assert result.stdout == ""
    assert not log.exists(), "npx ran without a project root"


def test_installer_forwards_an_npx_failure(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "deer-flow.code-workspace").write_text("{}\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    log = tmp_path / "npx.log"
    write_npx_stub(bin_dir, log, status=77)

    result = run_installer(project, bin_dir)

    assert log.exists(), "npx was never reached from a project root"
    assert result.returncode == 1
    assert "npx skills add example/repo@example-skill" in result.stderr
    assert "failed" in result.stderr
    assert "stub-npx-diagnostic" in result.stderr
    assert "installed successfully" not in result.stdout


@pytest.mark.skipif(os.name == "nt", reason="symlink creation is not guaranteed on Windows")
def test_installer_links_the_skill_into_the_checkout(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "deer-flow.code-workspace").write_text("{}\n", encoding="utf-8")
    home = tmp_path / "home"
    installed = home / ".agents/skills/example-skill"
    installed.mkdir(parents=True)
    (installed / "SKILL.md").write_text("---\nname: example-skill\n---\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    log = tmp_path / "npx.log"
    write_npx_stub(bin_dir, log, status=0)

    result = run_installer(project, bin_dir, home=home)

    assert result.returncode == 0, result.stderr
    link = project / "skills/custom/example-skill"
    assert link.is_symlink()
    assert link.resolve() == installed.resolve()
    assert "installed successfully" in result.stdout
