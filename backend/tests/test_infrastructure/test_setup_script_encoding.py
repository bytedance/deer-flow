"""Exercise setup command output through real, strictly encoded stdout streams."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ENCODINGS = ["ascii", "cp1252", "cp936", "utf-8"]


@pytest.fixture
def setup_checkout(tmp_path: Path) -> Path:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in ("doctor.py", "setup_wizard.py"):
        shutil.copyfile(REPO_ROOT / "scripts" / name, scripts / name)
    shutil.copytree(REPO_ROOT / "scripts" / "wizard", scripts / "wizard")
    (tmp_path / ".env.example").write_text("# test environment\n", encoding="utf-8")
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / ".env.example").write_text("# frontend environment\n", encoding="utf-8")
    return tmp_path


def run_setup_script(checkout: Path, encoding: str, code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        cwd=checkout,
        env={**os.environ, "PYTHONPATH": str(checkout / "scripts"), "PYTHONIOENCODING": f"{encoding}:strict"},
        capture_output=True,
        text=True,
        encoding=encoding,
        check=False,
        timeout=30,
    )


@pytest.mark.parametrize("encoding", ENCODINGS)
@pytest.mark.parametrize("is_tty", [False, True], ids=["pipe", "tty"])
@pytest.mark.parametrize("has_failure", [False, True], ids=["ready", "failed"])
def test_doctor_report_survives_restricted_stdout(setup_checkout: Path, encoding: str, is_tty: bool, has_failure: bool):
    result = run_setup_script(
        setup_checkout,
        encoding,
        f"""
        import sys
        from unittest.mock import patch
        import doctor

        sys.stdout.isatty = lambda: {is_tty!r}
        checks = {{}}
        for name in vars(doctor):
            if name.startswith("check_"):
                value = doctor.CheckResult("Example check", "ok", "Unicode detail: 检查")
                if name in ("check_llm_api_key", "check_llm_auth", "check_llm_package", "check_sandbox"):
                    value = [value]
                checks[name] = lambda *args, value=value: value
        checks["check_node"] = lambda: doctor.CheckResult("Warning check", "warn")
        checks["check_pnpm"] = lambda: doctor.CheckResult("Skipped check", "skip")
        checks["check_nginx"] = lambda: doctor.CheckResult(
            "Required check", "fail" if {has_failure!r} else "ok", fix="Run make setup"
        )
        with patch.multiple(doctor, **checks), patch.object(doctor, "resolve_config_path", return_value=(None, None)):
            sys.exit(doctor.main())
        """,
    )

    assert result.returncode == int(has_failure), result.stderr
    assert result.stderr == ""
    assert "DeerFlow Health Check" in result.stdout
    assert "Skipped check" in result.stdout
    assert "Run make setup" in result.stdout
    assert "Status: " in result.stdout
    assert ("error(s)" if has_failure else "Ready") in result.stdout
    if encoding == "utf-8":
        assert "✓" in result.stdout
        assert "检查" in result.stdout


@pytest.mark.parametrize("encoding", ENCODINGS)
def test_interactive_setup_completes_with_restricted_stdout(setup_checkout: Path, encoding: str):
    result = run_setup_script(
        setup_checkout,
        encoding,
        """
        import builtins
        import getpass
        import sys
        import setup_wizard
        from wizard.providers import LLM_PROVIDERS, SEARCH_PROVIDERS, WEB_FETCH_PROVIDERS

        # Model a legacy-locale terminal while keeping this test portable.
        sys.stdin.isatty = lambda: True
        sys.stdout.isatty = lambda: True
        choices = iter([
            str(next(i for i, provider in enumerate(LLM_PROVIDERS, 1) if provider.name == "openai")),
            "",  # default model
            str(len(SEARCH_PROVIDERS) + 1),  # skip web search
            str(len(WEB_FETCH_PROVIDERS) + 1),  # skip web fetch
            "",  # local sandbox
            "",  # bash disabled
            "",  # file writes enabled
            "",  # no IM channels
        ])
        builtins.input = lambda prompt: next(choices)
        getpass.getpass = lambda prompt: "test-api-key"
        sys.exit(setup_wizard.main())
        """,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "Writing configuration" in result.stdout
    assert "Setup complete!" in result.stdout
    assert "make doctor" in result.stdout
    assert (setup_checkout / "config.yaml").is_file()
    assert "OPENAI_API_KEY=test-api-key" in (setup_checkout / ".env").read_text(encoding="utf-8")
    assert (setup_checkout / "frontend" / ".env").read_bytes() == (setup_checkout / "frontend" / ".env.example").read_bytes()
    if encoding == "utf-8":
        assert "✓" in result.stdout
        assert "· Writing configuration" in result.stdout


@pytest.mark.parametrize("encoding", ENCODINGS)
def test_setup_still_requires_an_interactive_terminal(setup_checkout: Path, encoding: str):
    result = run_setup_script(
        setup_checkout,
        encoding,
        """
        import sys
        import setup_wizard
        sys.exit(setup_wizard.main())
        """,
    )

    assert result.returncode == 1
    assert result.stderr == ""
    assert "Non-interactive environment detected" in result.stdout
    assert not (setup_checkout / "config.yaml").exists()
    assert not (setup_checkout / ".env").exists()
