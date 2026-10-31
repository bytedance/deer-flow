"""Exercise scripts/sync_labels.py through real, strictly encoded stdout streams.

The label sync runs from CI and from developer shells. On a legacy console code
page the status glyphs used to raise UnicodeEncodeError and abort the run part
way through, leaving a half-synced label set. These tests pin the guard that
scripts/doctor.py and scripts/setup_wizard.py already ship: the report survives
any host encoding, and only utf-8 preserves the glyphs.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ENCODINGS = ["ascii", "cp1252", "cp936", "utf-8"]

LABELS = """\
labels:
  - name: good first issue
    color: "7057ff"
    description: Good for newcomers
  - name: bug
    color: "d73a4a"
    description: Something isn't working
"""


@pytest.fixture
def labels_checkout(tmp_path: Path) -> Path:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copyfile(REPO_ROOT / "scripts" / "sync_labels.py", scripts / "sync_labels.py")
    github = tmp_path / ".github"
    github.mkdir()
    (github / "labels.yml").write_text(LABELS, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("encoding", ENCODINGS)
def test_dry_run_survives_restricted_stdout(labels_checkout: Path, encoding: str):
    result = subprocess.run(
        [sys.executable, "-c", "import sys, sync_labels; sys.exit(sync_labels.main())", "--dry-run"],
        cwd=labels_checkout,
        env={
            **os.environ,
            "PYTHONPATH": str(labels_checkout / "scripts"),
            "PYTHONIOENCODING": f"{encoding}:strict",
        },
        capture_output=True,
        text=True,
        encoding=encoding,
        check=False,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "labels in sync" in result.stdout
    assert "[dry-run] gh label create good first issue" in result.stdout
    if encoding == "utf-8":
        assert "\u2014" in result.stdout  # em dash survives only on utf-8
        assert "Done \u2014 2 labels in sync." in result.stdout
