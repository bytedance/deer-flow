from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

INSTALL_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "skills/public/find-skills/scripts/install-skill.sh"
)


def test_install_skill_reports_missing_project_root(tmp_path: Path) -> None:
    fake_npx = tmp_path / "npx"
    fake_npx.write_text("#!/bin/sh\nexit 77\n", encoding="utf-8")
    fake_npx.chmod(fake_npx.stat().st_mode | stat.S_IXUSR)

    env = os.environ.copy()
    env["PATH"] = os.pathsep.join((str(tmp_path), env.get("PATH", "")))

    result = subprocess.run(
        ["bash", str(INSTALL_SCRIPT), "example/repo@example-skill"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert "deer-flow.code-workspace not found" in result.stderr
