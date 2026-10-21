"""Browser jobs must use an OS supported by the locked Playwright release."""

from pathlib import Path

import pytest
import yaml


@pytest.mark.parametrize(("workflow", "job"), [("e2e-tests.yml", "e2e-tests"), ("replay-e2e.yml", "fullstack-replay-render")])
def test_browser_ci_uses_supported_runner(workflow, job):
    root = Path(__file__).resolve().parents[2]
    config = yaml.safe_load((root / ".github/workflows" / workflow).read_text(encoding="utf-8"))
    browser_job = config["jobs"][job]
    assert browser_job["runs-on"] == "ubuntu-24.04"
    assert any("playwright install chromium --with-deps" in step.get("run", "") for step in browser_job["steps"])
