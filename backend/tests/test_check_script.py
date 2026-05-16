from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK_SCRIPT_PATH = REPO_ROOT / "scripts" / "check.py"


spec = importlib.util.spec_from_file_location("deerflow_check_script", CHECK_SCRIPT_PATH)
assert spec is not None
assert spec.loader is not None
check_script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_script)


def test_find_pnpm_command_prefers_resolved_executable(monkeypatch):
    def fake_which(name: str) -> str | None:
        if name == "pnpm":
            return r"C:\Users\tester\AppData\Roaming\npm\pnpm.CMD"
        if name == "pnpm.cmd":
            return r"C:\Users\tester\AppData\Roaming\npm\pnpm.cmd"
        return None

    monkeypatch.setattr(check_script.shutil, "which", fake_which)

    assert check_script.find_pnpm_command() == [r"C:\Users\tester\AppData\Roaming\npm\pnpm.CMD"]


def test_find_pnpm_command_falls_back_to_corepack(monkeypatch):
    def fake_which(name: str) -> str | None:
        if name == "corepack":
            return r"C:\Program Files\nodejs\corepack.exe"
        return None

    monkeypatch.setattr(check_script.shutil, "which", fake_which)

    assert check_script.find_pnpm_command() == [
        r"C:\Program Files\nodejs\corepack.exe",
        "pnpm",
    ]


def test_find_pnpm_command_falls_back_to_corepack_cmd(monkeypatch):
    def fake_which(name: str) -> str | None:
        if name == "corepack":
            return None
        if name == "corepack.cmd":
            return r"C:\Program Files\nodejs\corepack.cmd"
        return None

    monkeypatch.setattr(check_script.shutil, "which", fake_which)

    assert check_script.find_pnpm_command() == [
        r"C:\Program Files\nodejs\corepack.cmd",
        "pnpm",
    ]
