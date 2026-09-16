from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK_SCRIPT_PATH = REPO_ROOT / "scripts" / "check.py"
PNPM_SCRIPT_PATH = REPO_ROOT / "scripts" / "pnpm.py"


def _load_script(path: Path, name: str):
    assert path.exists(), f"{path} must exist"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_find_pnpm_command_prefers_resolved_executable(monkeypatch):
    pnpm_script = _load_script(PNPM_SCRIPT_PATH, "deerflow_pnpm_script_direct")

    def fake_which(name: str) -> str | None:
        if name == "pnpm":
            return r"C:\Users\tester\AppData\Roaming\npm\pnpm.CMD"
        if name == "pnpm.cmd":
            return r"C:\Users\tester\AppData\Roaming\npm\pnpm.cmd"
        return None

    monkeypatch.setattr(pnpm_script.shutil, "which", fake_which)

    assert pnpm_script.find_pnpm_command() == [r"C:\Users\tester\AppData\Roaming\npm\pnpm.CMD"]


def test_find_pnpm_command_falls_back_to_corepack(monkeypatch):
    pnpm_script = _load_script(PNPM_SCRIPT_PATH, "deerflow_pnpm_script_corepack")

    def fake_which(name: str) -> str | None:
        if name == "corepack":
            return r"C:\Program Files\nodejs\corepack.exe"
        return None

    monkeypatch.setattr(pnpm_script.shutil, "which", fake_which)

    assert pnpm_script.find_pnpm_command() == [
        r"C:\Program Files\nodejs\corepack.exe",
        "pnpm",
    ]


def test_find_pnpm_command_falls_back_to_corepack_cmd(monkeypatch):
    pnpm_script = _load_script(PNPM_SCRIPT_PATH, "deerflow_pnpm_script_corepack_cmd")

    def fake_which(name: str) -> str | None:
        if name == "corepack":
            return None
        if name == "corepack.cmd":
            return r"C:\Program Files\nodejs\corepack.cmd"
        return None

    monkeypatch.setattr(pnpm_script.shutil, "which", fake_which)

    assert pnpm_script.find_pnpm_command() == [
        r"C:\Program Files\nodejs\corepack.cmd",
        "pnpm",
    ]


def test_check_script_uses_shared_pnpm_runner():
    check_script = CHECK_SCRIPT_PATH.read_text(encoding="utf-8")

    assert 'Path(__file__).resolve().with_name("pnpm.py")' in check_script


def test_check_script_resolves_runner_paths_independently_of_cwd(monkeypatch):
    # Reproduce invoking the entry point with a relative script path from the
    # repository root. Before the fix, `__file__` stayed relative and the
    # runner became `scripts/pnpm.py`, which later broke after cwd changed.
    monkeypatch.chdir(REPO_ROOT)
    check_script = _load_script(Path("scripts/check.py"), "deerflow_check_script_paths")

    assert check_script.PNPM_SCRIPT_PATH == PNPM_SCRIPT_PATH
    assert check_script.PNPM_SCRIPT_PATH.is_absolute()
    assert check_script.FRONTEND_DIR == REPO_ROOT / "frontend"
    assert check_script.FRONTEND_DIR.is_absolute()


def test_check_script_preserves_runner_failure_diagnostics(monkeypatch):
    check_script = _load_script(CHECK_SCRIPT_PATH, "deerflow_check_script_failure")
    call_kwargs = {}

    def fake_run(*args, **kwargs):
        call_kwargs.update(kwargs)
        return subprocess.CompletedProcess(
            args=["python", "pnpm.py", "-v"],
            returncode=42,
            stdout="partial pnpm output\n",
            stderr="Error: pnpm command failed with exit status 42.\n",
        )

    monkeypatch.setattr(check_script.subprocess, "run", fake_run)

    assert check_script.run_pnpm_version() == (
        None,
        False,
        "Error: pnpm command failed with exit status 42.\npartial pnpm output",
    )
    assert call_kwargs["cwd"] == REPO_ROOT / "frontend"


def test_check_script_preserves_corepack_resolution_hint(monkeypatch):
    check_script = _load_script(CHECK_SCRIPT_PATH, "deerflow_check_script_corepack")

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=["python", "pnpm.py", "-v"],
            returncode=0,
            stdout="10.26.2\n",
            stderr="Using pnpm via Corepack.\n",
        )

    monkeypatch.setattr(check_script.subprocess, "run", fake_run)

    assert check_script.run_pnpm_version() == ("10.26.2", True, None)


def test_check_status_labels_corepack_fallback(monkeypatch, capsys):
    check_script = _load_script(CHECK_SCRIPT_PATH, "deerflow_check_script_status")

    monkeypatch.setattr(check_script.shutil, "which", lambda name: f"/fake/{name}")
    monkeypatch.setattr(
        check_script,
        "run_command",
        lambda command: {
            "node": "v22.0.0",
            "uv": "uv 0.11.31",
            "nginx": "nginx/1.31.3",
        }[command[0]],
    )
    monkeypatch.setattr(
        check_script,
        "run_pnpm_version",
        lambda: ("10.26.2", True, None),
    )

    assert check_script.main() == 0
    assert "OK pnpm 10.26.2 (via Corepack)" in capsys.readouterr().out
