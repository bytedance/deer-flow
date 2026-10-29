from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

PAYLOAD = {"summary": {"blockers": 0, "errors": 0, "warnings": 0, "infos": 1}, "completeness": {}, "notes": ["判定说明 ✗ 🎉"]}

DRIVER_SOURCE = """
import importlib
import sys
from pathlib import Path

scripts_dir, repo_root = sys.argv[1], Path(sys.argv[2])
sys.path.insert(0, scripts_dir)
module = importlib.import_module("review_changed_public_skills")
facts = module.collect_review_facts(repo_root / "skills" / "public" / "demo", repo_root, sys.executable)
expected = {notes!r}
if facts is None or facts.get("notes") != expected:
    print("MISMATCH:", facts)
    sys.exit(1)
print("OK")
""".format(notes=PAYLOAD["notes"])


@pytest.fixture
def analyzer_stub(tmp_path: Path) -> Path:
    """A repo-root stand-in whose `deerflow.skills.review.cli` prints raw UTF-8 JSON."""
    stub_root = tmp_path / "repo_root"
    package = stub_root / "deerflow" / "skills" / "review"
    package.mkdir(parents=True)
    for parent in (stub_root / "deerflow", stub_root / "deerflow" / "skills", package):
        (parent / "__init__.py").write_text("", encoding="utf-8")
    (package / "cli.py").write_text(
        "import json\nprint(json.dumps(" + repr(PAYLOAD) + ", ensure_ascii=False))\n",
        encoding="utf-8",
    )
    return stub_root


def _load_script_module():
    scripts_dir = REPO_ROOT / "scripts"
    spec = importlib.util.spec_from_file_location("review_changed_public_skills_under_test", scripts_dir / "review_changed_public_skills.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    sys.path.insert(0, str(scripts_dir))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(scripts_dir))
    return module


def test_collect_review_facts_round_trips_non_ascii_analyzer_output(analyzer_stub: Path, tmp_path: Path):
    """The analyzer emits ensure_ascii=False JSON, so both pipe directions must be UTF-8.

    The driver runs with UTF-8 mode disabled and a C locale so the ambient codec is
    a non-UTF-8 one (ASCII on Linux, the ANSI code page on Windows); the assertion
    fails before the UTF-8 pinning and passes after it, on every platform.
    """
    driver = tmp_path / "driver.py"
    driver.write_text(DRIVER_SOURCE, encoding="utf-8")

    env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "PYTHONUTF8": "0",
        "LC_ALL": "C",
        "PYTHONCOERCECLOCALE": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    result = subprocess.run(
        [sys.executable, str(driver), str(REPO_ROOT / "scripts"), str(analyzer_stub)],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=120,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


def test_review_env_pins_analyzer_stdio_to_utf8(analyzer_stub: Path, monkeypatch):
    """review_env must override any inherited PYTHONUTF8/PYTHONIOENCODING for the analyzer."""
    module = _load_script_module()
    monkeypatch.setenv("PYTHONIOENCODING", "cp1252")
    monkeypatch.setenv("PYTHONUTF8", "0")
    env = module.review_env(analyzer_stub)
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["PYTHONUTF8"] == "1"
