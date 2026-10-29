"""Browser CI installs its dependencies before executing browser tests."""

from pathlib import Path

import pytest
import yaml


@pytest.mark.parametrize(("workflow", "job"), [("e2e-tests.yml", "e2e-tests"), ("replay-e2e.yml", "fullstack-replay-render")])
def test_browser_ci_installs_chromium_before_running_tests(workflow, job):
    root = Path(__file__).resolve().parents[2]
    config = yaml.safe_load((root / ".github/workflows" / workflow).read_text(encoding="utf-8"))
    browser_job = config["jobs"][job]
    # Runner images are maintained by CI owners; do not freeze a temporary
    # OS compatibility workaround in an unrelated backend unit test.
    steps = browser_job["steps"]
    installs = [index for index, step in enumerate(steps) if "playwright install chromium --with-deps" in step.get("run", "")]
    tests = [index for index, step in enumerate(steps) if "pnpm exec playwright test" in step.get("run", "")]
    assert installs, "Browser dependencies must be installed"
    assert tests, "The browser job must execute tests"
    assert max(installs) < min(tests), "Install Chromium before running browser tests"
