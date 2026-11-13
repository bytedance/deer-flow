"""A PowerShell sandbox command must not leave the shared console in UTF-8.

``LocalSandbox.execute_command`` runs PowerShell with a preamble that sets
``[Console]::InputEncoding`` / ``[Console]::OutputEncoding`` to UTF-8 (#5440)
so PowerShell's own output is decodable. Those setters write the **console
the process is attached to**, and on Windows a child without
``CREATE_NO_WINDOW`` / ``DETACHED_PROCESS`` attaches to the *parent's* console.
The preamble therefore reconfigures a shared resource: after one sandbox
PowerShell command, ``cmd /c chcp`` reports 65001 for the rest of the process
lifetime (936 on a zh-CN host before).

That breaks every later ``cmd.exe`` batch read in the same process: ``cmd``
decodes ``.cmd``/``.bat`` files with the console code page, while the Windows
ecosystem writes shims in the ANSI code page (``encoding="mbcs"`` — the repo's
own lark-cli test fixture does exactly this). A shim whose interpreter path
contains non-ASCII characters (a CJK user directory) then fails to start with
"the system cannot find the path specified" — the visible failure behind the
lark-cli probe tests going red only when a PowerShell-sandbox test ran first
(order-dependent, invisible to the ubuntu-only CI).

The fix is to give the PowerShell child its own (invisible) console via
``CREATE_NO_WINDOW``: the preamble still pins that child's own output to
UTF-8, and the parent's console keeps its original code page. Timeout teardown
is unaffected — it uses ``taskkill /T /F``, not console control events.
"""

import os
import shutil
import subprocess

import pytest

from deerflow.sandbox.local.local_sandbox import LocalSandbox, PathMapping


def _console_code_page() -> str:
    result = subprocess.run(
        ["cmd", "/c", "chcp"],
        capture_output=True,
        text=True,
        encoding="mbcs",
        errors="replace",
        check=False,
    )
    return (result.stdout or "").strip().rsplit(":", 1)[-1].strip()


@pytest.fixture
def powershell_sandbox(monkeypatch, tmp_path):
    if os.name != "nt":
        pytest.skip("console code page is a Windows concept")
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if shell is None:
        pytest.skip("PowerShell is not installed")
    monkeypatch.setattr(LocalSandbox, "_get_shell", staticmethod(lambda: shell))
    root = tmp_path / "host directory with spaces"
    root.mkdir()
    (root / "marker.txt").write_text("needle", encoding="utf-8")
    return LocalSandbox("local", [PathMapping("/mnt/data", str(root))])


def test_powershell_command_keeps_console_code_page(powershell_sandbox):
    """The preamble must pin only the child's console, not the shared one."""
    before = _console_code_page()
    if before == "65001":
        # A host with "Use Unicode UTF-8 for worldwide language support" enabled
        # already reports 65001, so ``before == after`` holds whether or not the
        # child leaked into the shared console. Skipping turns that into a
        # visible gap instead of a green test that proves nothing.
        pytest.skip("console is already 65001; leaked and clean runs look identical")
    output = powershell_sandbox.execute_command("Write-Output sentinel")
    assert "sentinel" in output
    assert _console_code_page() == before
