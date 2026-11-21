"""Browser CI supplies matching browsers and verifies them before tests."""

from pathlib import Path

import pytest
import yaml


@pytest.mark.parametrize(("workflow", "job"), [("e2e-tests.yml", "e2e-tests"), ("replay-e2e.yml", "fullstack-replay-render")])
def test_browser_ci_image_matches_locked_playwright(workflow, job):
    root = Path(__file__).resolve().parents[2]
    config = yaml.safe_load((root / ".github/workflows" / workflow).read_text(encoding="utf-8"))
    lock = yaml.safe_load((root / "frontend/pnpm-lock.yaml").read_text(encoding="utf-8"))
    version = lock["importers"]["."]["devDependencies"]["@playwright/test"]["version"]
    image = config["jobs"][job].get("container", {}).get("image", "")
    assert image.startswith(f"mcr.microsoft.com/playwright:v{version}-"), "The preinstalled browsers must match the locked Playwright runtime"


@pytest.mark.parametrize(("workflow", "job"), [("e2e-tests.yml", "e2e-tests"), ("replay-e2e.yml", "fullstack-replay-render")])
def test_browser_ci_verifies_chromium_before_running_tests(workflow, job):
    root = Path(__file__).resolve().parents[2]
    config = yaml.safe_load((root / ".github/workflows" / workflow).read_text(encoding="utf-8"))
    browser_job = config["jobs"][job]
    steps = browser_job["steps"]
    probes = [index for index, step in enumerate(steps) if "await chromium.launch()" in step.get("run", "") and "await browser.close()" in step.get("run", "")]
    tests = [index for index, step in enumerate(steps) if "pnpm exec playwright test" in step.get("run", "")]
    assert probes, "Launch the image's Chromium before executing browser tests"
    assert tests, "The browser job must execute tests"
    assert max(probes) < min(tests), "Verify Chromium before running browser tests"


def test_auth_recovery_requires_a_working_browser():
    root = Path(__file__).resolve().parents[2]
    config = yaml.safe_load((root / ".github/workflows/e2e-tests.yml").read_text(encoding="utf-8"))
    steps = config["jobs"]["e2e-tests"]["steps"]
    probe = next(step for step in steps if "await chromium.launch()" in step.get("run", ""))
    auth = next(step for step in steps if "playwright.auth.config.ts" in step.get("run", ""))
    assert f"steps.{probe['id']}.outcome == 'success'" in auth["if"]


@pytest.mark.parametrize(("workflow", "job"), [("e2e-tests.yml", "e2e-tests"), ("replay-e2e.yml", "fullstack-replay-render")])
def test_browser_ci_uses_container_compatible_python(workflow, job):
    root = Path(__file__).resolve().parents[2]
    config = yaml.safe_load((root / ".github/workflows" / workflow).read_text(encoding="utf-8"))
    browser_job = config["jobs"][job]
    assert browser_job.get("env", {}).get("UV_PYTHON_PREFERENCE") == "only-managed"
    steps = browser_job["steps"]
    assert not any(step.get("uses", "").startswith("actions/setup-python@") for step in steps)
    install = next(index for index, step in enumerate(steps) if "uv python install 3.12" in step.get("run", ""))
    sync = next(index for index, step in enumerate(steps) if "uv sync" in step.get("run", ""))
    assert install < sync
    assert any("import ssl, sqlite3" in step.get("run", "") for step in steps)
