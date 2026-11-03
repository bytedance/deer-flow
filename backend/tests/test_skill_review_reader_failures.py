import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from deerflow.skills.review.cli import main as review_cli_main


def _write_skill(root: Path) -> None:
    (root / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: Review a demo package.\n---\n\n# Demo\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize("error", [PermissionError("cannot read"), OSError("read failed")])
def test_cli_fail_on_incomplete_rejects_unreadable_package_file(tmp_path, monkeypatch, capsys, error):
    _write_skill(tmp_path)
    script = tmp_path / "scripts" / "run.py"
    script.parent.mkdir()
    script.write_text("print('demo')\n", encoding="utf-8")
    original_read = Path.read_bytes

    def read_bytes(path):
        if path == script:
            raise error
        return original_read(path)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)

    exit_code = review_cli_main([str(tmp_path), "--fail-on-incomplete"])
    facts = json.loads(capsys.readouterr().out)

    assert facts["reader_errors"][0]["code"] == "read_failed"
    assert exit_code == 1
    assert facts["completeness"]["text_content_complete"] is False
    assert facts["completeness"]["not_assessed"] == ["full_package"]


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="Named pipes require POSIX")
def test_cli_reports_fifo_without_blocking(tmp_path):
    _write_skill(tmp_path)
    os.mkfifo(tmp_path / "stream")

    result = subprocess.run(
        [sys.executable, "-m", "deerflow.skills.review.cli", str(tmp_path), "--fail-on-incomplete"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=5,
        check=False,
    )

    assert result.returncode == 1, result.stderr
    facts = json.loads(result.stdout)
    assert any(error["code"] == "unsupported_file_type" and error["path"] == "stream" for error in facts["reader_errors"])
    assert facts["completeness"]["not_assessed"] == ["full_package"]


def test_cli_fail_on_incomplete_accepts_readable_package(tmp_path, capsys):
    _write_skill(tmp_path)

    assert review_cli_main([str(tmp_path), "--fail-on-incomplete"]) == 0
    facts = json.loads(capsys.readouterr().out)
    assert facts["reader_errors"] == []
    assert facts["completeness"]["text_content_complete"] is True
    assert facts["completeness"]["not_assessed"] == []
