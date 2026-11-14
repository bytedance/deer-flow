"""Exercise the chart version check in an isolated checkout."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="requires bash")


def run_check(tmp_path: Path, example: str, chart: str) -> subprocess.CompletedProcess[str]:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    script = scripts / "check_config_version.sh"
    shutil.copyfile(ROOT / "scripts" / script.name, script)
    values = tmp_path / "deploy" / "helm" / "deer-flow" / "values.yaml"
    values.parent.mkdir(parents=True)
    (tmp_path / "config.example.yaml").write_text(f"config_version: {example}\n", encoding="utf-8", newline="")
    values.write_text(f"config: |\n  config_version: {chart}\n", encoding="utf-8", newline="")
    return subprocess.run([BASH, str(script)], capture_output=True, text=True, encoding="utf-8", check=False)


@pytest.mark.parametrize(("example", "chart"), [("66", "66oops"), ("66oops", "66"), ("66", "999999999999999999999999")])
def test_invalid_version_fails(tmp_path: Path, example: str, chart: str) -> None:
    result = run_check(tmp_path, example, chart)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "OK -" not in result.stdout


@pytest.mark.parametrize(("example", "chart", "expected"), [("66", "66", 0), ("66", "67", 0), ("66", "65", 1)])
def test_version_comparison(tmp_path: Path, example: str, chart: str, expected: int) -> None:
    result = run_check(tmp_path, example, chart)
    assert result.returncode == expected, result.stdout + result.stderr
