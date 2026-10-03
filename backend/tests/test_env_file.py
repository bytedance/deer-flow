"""Exercise startup in fresh processes without reading checkout dotenv files."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
ENTRYPOINTS = {
    "config": "import deerflow.config.app_config",
    "auth": "from app.gateway.auth.config import get_auth_config; get_auth_config(); import deerflow.config.app_config",
    "debug": f"import runpy; runpy.run_path({str(BACKEND / 'debug.py')!r}); import deerflow.config.app_config",
}


def run_startup(tmp_path, entrypoint="config", selector=None, extra_env=None, prelude=""):
    # Only propagate interpreter necessities, never ambient credentials/config.
    env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT") if key in os.environ}
    env.update(PYTHONPATH=os.pathsep.join((str(BACKEND), str(BACKEND / "packages/harness"))), AUTH_JWT_SECRET="test-only")
    if selector is not None:
        env["DEER_FLOW_ENV_FILE"] = str(selector)
    env.update(extra_env or {})
    default = tmp_path / ".env"
    default.write_text("ENV_FILE_TEST_VALUE=default\nENV_FILE_TEST_DEFAULT_ONLY=unselected\n", encoding="utf-8")
    cwd = tmp_path / "unrelated"
    cwd.mkdir(exist_ok=True)
    # Control discovery only; parsing, precedence and startup imports are real.
    # This prevents default discovery from reading any developer secrets.
    script = f"""
import json, os
import dotenv.main
dotenv.main.find_dotenv = lambda *args, **kwargs: {str(default)!r}
{prelude}
{ENTRYPOINTS[entrypoint]}
print(json.dumps([os.getenv('ENV_FILE_TEST_VALUE'), os.getenv('ENV_FILE_TEST_DEFAULT_ONLY')]))
"""
    return subprocess.run([sys.executable, "-c", script], cwd=cwd, env=env, capture_output=True, text=True, timeout=30)


@pytest.mark.parametrize("entrypoint", ENTRYPOINTS)
@pytest.mark.parametrize("relative", [False, True])
def test_explicit_selection_from_unrelated_cwd(tmp_path, entrypoint, relative):
    selected = tmp_path / "stage.env"
    selected.write_text("ENV_FILE_TEST_VALUE=selected\n", encoding="utf-8")
    result = run_startup(tmp_path, entrypoint, "../stage.env" if relative else selected)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == ["selected", None]


@pytest.mark.parametrize("value", ["exported", ""])
def test_process_environment_wins(tmp_path, value):
    selected = tmp_path / "stage.env"
    selected.write_text("ENV_FILE_TEST_VALUE=selected\n", encoding="utf-8")
    result = run_startup(tmp_path, selector=selected, extra_env={"ENV_FILE_TEST_VALUE": value})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [value, None]


@pytest.mark.parametrize("entrypoint", ENTRYPOINTS)
def test_unset_preserves_default_loading(tmp_path, entrypoint):
    result = run_startup(tmp_path, entrypoint)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == ["default", "unselected"]


@pytest.mark.parametrize("entrypoint", ENTRYPOINTS)
@pytest.mark.parametrize("kind", ["missing", "directory", "empty", "unreadable", "invalid_encoding"])
def test_invalid_explicit_file_fails_without_fallback(tmp_path, entrypoint, kind):
    selected = tmp_path / "invalid.env"
    prelude = ""
    if kind == "directory":
        selected.mkdir()
    elif kind == "unreadable":
        selected.write_text("ENV_FILE_TEST_VALUE=do-not-print-this\n", encoding="utf-8")
        # Deterministic even under root and on Windows: emulate OS denial on open.
        prelude = f"""
import sys
def deny_open(event, args):
    if event == 'open' and str(args[0]) == {str(selected)!r}:
        raise PermissionError('do-not-print-this')
sys.addaudithook(deny_open)
"""
    elif kind == "invalid_encoding":
        selected.write_bytes(b"ENV_FILE_TEST_VALUE=do-not-print-this\xff")
    result = run_startup(tmp_path, entrypoint, "" if kind == "empty" else selected, prelude=prelude)
    assert result.returncode != 0
    assert "DEER_FLOW_ENV_FILE" in result.stderr
    assert "readable UTF-8 regular file" in result.stderr
    assert "do-not-print-this" not in result.stderr
    assert "unselected" not in result.stdout


def test_empty_selected_file_does_not_load_defaults(tmp_path):
    selected = tmp_path / "empty.env"
    selected.touch()
    result = run_startup(tmp_path, selector=selected)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [None, None]
