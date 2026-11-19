"""Offline regressions for the find-skills host-checkout installer."""

import os
import subprocess
from pathlib import Path

import pytest

INSTALLER = (
    Path(__file__).resolve().parents[2]
    / "skills/public/find-skills/scripts/install-skill.sh"
)
SKILL_REFERENCE = "example/repo@example-skill"

pytestmark = pytest.mark.skipif(
    os.name == "nt", reason="The installer and npx test doubles require Bash"
)


def _install_fake_npx(tmp_path: Path, body: str) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    executable = bin_dir / "npx"
    executable.write_text(f"#!/bin/bash\n{body}\n", encoding="utf-8", newline="\n")
    executable.chmod(0o755)
    return bin_dir


def _run_installer(
    cwd: Path, home: Path, bin_dir: Path, log: Path
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "NPX_TEST_LOG": str(log),
    }
    return subprocess.run(
        ["bash", str(INSTALLER), SKILL_REFERENCE],
        check=False,
        cwd=cwd,
        env=env,
        capture_output=True,
        encoding="utf-8",
        timeout=15,
    )


def test_missing_checkout_reports_actionable_error_without_calling_npx(
    tmp_path: Path,
) -> None:
    if any(
        (parent / "deer-flow.code-workspace").is_file()
        for parent in (tmp_path, *tmp_path.parents)
    ):
        pytest.skip(
            "This regression requires a temporary directory outside a DeerFlow checkout"
        )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    bin_dir = _install_fake_npx(tmp_path, 'printf called > "$NPX_TEST_LOG"\nexit 99')
    log = tmp_path / "npx-called"

    result = _run_installer(tmp_path / "workspace", tmp_path / "home", bin_dir, log)

    assert result.returncode == 1
    assert result.stdout == ""
    assert "Could not find a DeerFlow checkout" in result.stderr
    assert "skills/custom" in result.stderr
    assert "Install .skill" in result.stderr
    assert not log.exists()


def test_npx_failure_preserves_status_and_output(tmp_path: Path) -> None:
    (tmp_path / "deer-flow.code-workspace").touch()
    bin_dir = _install_fake_npx(
        tmp_path,
        'printf "registry unavailable\\n"\nprintf "upstream timed out\\n" >&2\nexit 23',
    )

    result = _run_installer(
        tmp_path, tmp_path / "home", bin_dir, tmp_path / "npx-called"
    )

    assert result.stdout == ""
    assert result.stderr.splitlines() == [
        f"Error: npx skills add failed for {SKILL_REFERENCE} (exit 23).",
        "registry unavailable",
        "upstream timed out",
    ]
    assert not (tmp_path / "skills/custom/example-skill").exists()


def test_successful_install_links_skill_into_checkout(tmp_path: Path) -> None:
    (tmp_path / "deer-flow.code-workspace").touch()
    bin_dir = _install_fake_npx(
        tmp_path,
        'printf "%s\\n" "$@" > "$NPX_TEST_LOG"\nmkdir -p "$HOME/.agents/skills/example-skill"',
    )
    home = tmp_path / "home"
    log = tmp_path / "npx-args"

    result = _run_installer(tmp_path, home, bin_dir, log)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "Skill 'example-skill' installed successfully"
    assert log.read_text(encoding="utf-8").splitlines() == [
        "skills",
        "add",
        SKILL_REFERENCE,
        "-g",
        "-y",
    ]
    link = tmp_path / "skills/custom/example-skill"
    assert link.is_symlink()
    assert link.resolve() == (home / ".agents/skills/example-skill").resolve()
