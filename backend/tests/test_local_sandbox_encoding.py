import builtins
import os
import subprocess
import sys

import pytest

import deerflow.sandbox.local.local_sandbox as local_sandbox
from deerflow.sandbox.local.local_sandbox import LocalSandbox, PathMapping, _BoundedPipeCapture


def _open(base, file, mode="r", *args, **kwargs):
    if "b" in mode:
        return base(file, mode, *args, **kwargs)
    return base(file, mode, *args, encoding=kwargs.pop("encoding", "gbk"), **kwargs)


def test_bounded_pipe_capture_decodes_non_utf8_output_with_configured_encoding():
    capture = _BoundedPipeCapture(encoding="cp1252")
    capture.append("caf\u00e9".encode("cp1252"))

    assert capture.read() == "caf\u00e9"


def test_bounded_pipe_capture_applies_text_mode_newline_normalization_when_enabled():
    capture = _BoundedPipeCapture(normalize_newlines=True)
    capture.append(b"crlf\r\nbare-cr\rlf\n")

    assert capture.read() == "crlf\nbare-cr\nlf\n"


def test_bounded_pipe_capture_preserves_posix_newlines_by_default():
    capture = _BoundedPipeCapture()
    capture.append(b"crlf\r\nbare-cr\rlf\n")

    assert capture.read() == "crlf\r\nbare-cr\rlf\n"


@pytest.mark.skipif(os.name == "nt", reason="POSIX capture semantics")
def test_posix_command_capture_preserves_newlines():
    stdout, stderr, returncode, timed_out = LocalSandbox._run_posix_command(
        [sys.executable, "-c", "import os; os.write(1, b'crlf\\r\\nbare-cr\\rlf\\n')"],
        10,
    )

    assert stdout == "crlf\r\nbare-cr\rlf\n"
    assert stderr == ""
    assert returncode == 0
    assert timed_out is False


@pytest.mark.skipif(os.name != "nt", reason="Windows text-mode newline semantics")
def test_windows_command_capture_normalizes_newlines():
    stdout, stderr, returncode, timed_out = LocalSandbox._run_windows_command(
        [sys.executable, "-c", "import os; os.write(1, b'crlf\\r\\nbare-cr\\rlf\\n')"],
        10,
    )

    assert stdout == "crlf\nbare-cr\nlf\n"
    assert stderr == ""
    assert returncode == 0
    assert timed_out is False


@pytest.mark.skipif(os.name != "nt", reason="Windows text-mode encoding semantics")
@pytest.mark.parametrize(
    ("python_args", "python_utf8"),
    [([], "0"), ([], "1"), (["-X", "utf8"], "0")],
    ids=["locale-code-page", "PYTHONUTF8", "-X-utf8"],
)
def test_windows_capture_matches_subprocess_text_mode_encoding(python_args, python_utf8):
    probe = r"""
import subprocess
import sys

from deerflow.sandbox.local.local_sandbox import LocalSandbox

reference = subprocess.Popen([sys.executable, "-c", ""], stdout=subprocess.PIPE, text=True)
encoding = reference.stdout.encoding
reference.communicate()

for expected in ("caf\u00e9", "\u4f60\u597d", "\u65e5\u672c\u8a9e", "\u041f\u0440\u0438\u0432\u0435\u0442"):
    try:
        payload = expected.encode(encoding)
    except UnicodeEncodeError:
        continue
    if any(byte >= 0x80 for byte in payload):
        break
else:
    raise AssertionError(f"no non-ASCII probe text for {encoding}")

stdout, stderr, returncode, timed_out = LocalSandbox._run_windows_command(
    [sys.executable, "-c", f"import sys; sys.stdout.buffer.write(bytes.fromhex('{payload.hex()}'))"],
    10,
)
assert stdout == expected, (encoding, stdout)
assert stderr == ""
assert returncode == 0
assert timed_out is False
"""
    env = os.environ.copy()
    env["PYTHONUTF8"] = python_utf8

    result = subprocess.run(
        [sys.executable, *python_args, "-c", probe],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_read_file_uses_utf8_on_windows_locale(tmp_path, monkeypatch):
    path = tmp_path / "utf8.txt"
    text = "\u201cutf8\u201d"
    path.write_text(text, encoding="utf-8")
    base = builtins.open

    monkeypatch.setattr(local_sandbox, "open", lambda file, mode="r", *args, **kwargs: _open(base, file, mode, *args, **kwargs), raising=False)

    assert LocalSandbox("t").read_file(str(path)) == text


def test_write_file_uses_utf8_on_windows_locale(tmp_path, monkeypatch):
    path = tmp_path / "utf8.txt"
    text = "emoji \U0001f600"
    base = builtins.open

    monkeypatch.setattr(local_sandbox, "open", lambda file, mode="r", *args, **kwargs: _open(base, file, mode, *args, **kwargs), raising=False)

    LocalSandbox("t").write_file(str(path), text)

    assert path.read_text(encoding="utf-8") == text


def test_get_shell_prefers_posix_shell_from_path_before_windows_fallback(monkeypatch):
    monkeypatch.setattr(local_sandbox.os, "name", "nt")
    monkeypatch.setattr(LocalSandbox, "_find_first_available_shell", lambda candidates: r"C:\Program Files\Git\bin\sh.exe" if candidates == ("/bin/zsh", "/bin/bash", "/bin/sh", "sh") else None)

    assert LocalSandbox._get_shell() == r"C:\Program Files\Git\bin\sh.exe"


def test_get_shell_uses_powershell_fallback_on_windows(monkeypatch):
    calls: list[tuple[str, ...]] = []

    def fake_find(candidates: tuple[str, ...]) -> str | None:
        calls.append(candidates)
        if candidates == ("/bin/zsh", "/bin/bash", "/bin/sh", "sh"):
            return None
        return r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"

    monkeypatch.setattr(local_sandbox.os, "name", "nt")
    monkeypatch.setattr(local_sandbox.os, "environ", {"SystemRoot": r"C:\Windows"})
    monkeypatch.setattr(LocalSandbox, "_find_first_available_shell", fake_find)

    assert LocalSandbox._get_shell() == r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    assert calls[1] == (
        "pwsh",
        "pwsh.exe",
        "powershell",
        "powershell.exe",
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
        "cmd.exe",
    )


def test_get_shell_uses_cmd_as_last_windows_fallback(monkeypatch):
    def fake_find(candidates: tuple[str, ...]) -> str | None:
        if candidates == ("/bin/zsh", "/bin/bash", "/bin/sh", "sh"):
            return None
        return r"C:\Windows\System32\cmd.exe"

    monkeypatch.setattr(local_sandbox.os, "name", "nt")
    monkeypatch.setattr(local_sandbox.os, "environ", {"SystemRoot": r"C:\Windows"})
    monkeypatch.setattr(LocalSandbox, "_find_first_available_shell", fake_find)

    assert LocalSandbox._get_shell() == r"C:\Windows\System32\cmd.exe"


def test_execute_command_uses_powershell_command_mode_on_windows(monkeypatch):
    calls: list[tuple[list[str], float, dict[str, str]]] = []

    def fake_run(args, timeout, env):
        calls.append((args, timeout, env))
        return "ok", "", 0, False

    monkeypatch.setattr(local_sandbox.os, "name", "nt")
    monkeypatch.setattr(local_sandbox.os, "environ", {"PATH": r"C:\Windows", "OPENAI_API_KEY": "should-not-leak"})
    monkeypatch.setattr(LocalSandbox, "_get_shell", staticmethod(lambda: r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"))
    monkeypatch.setattr(LocalSandbox, "_run_windows_command", staticmethod(fake_run))

    output = LocalSandbox("t").execute_command("Write-Output hello")

    assert output == "ok"
    # Platform secrets are scrubbed from the inherited environment even on the
    # Windows PowerShell path (#3861); benign PATH is preserved and the env is an
    # explicit scrubbed dict, no longer None.
    assert calls == [
        (
            [
                r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
                "-NoProfile",
                "-Command",
                "Write-Output hello",
            ],
            600,
            {"PATH": r"C:\Windows"},
        )
    ]


def test_execute_command_keeps_msys_path_conversion_for_host_commands_on_windows(monkeypatch):
    calls: list[tuple[list[str], float, dict[str, str]]] = []

    def fake_run(args, timeout, env):
        calls.append((args, timeout, env))
        return "ok", "", 0, False

    monkeypatch.setattr(local_sandbox.os, "name", "nt")
    monkeypatch.setattr(local_sandbox.os, "environ", {"PATH": r"C:\Program Files\Git\bin"})
    monkeypatch.setattr(LocalSandbox, "_get_shell", staticmethod(lambda: r"C:\Program Files\Git\bin\sh.exe"))
    monkeypatch.setattr(LocalSandbox, "_msys_path_conversion_exclusions", lambda self: "/mnt/user-data")
    monkeypatch.setattr(LocalSandbox, "_run_windows_command", staticmethod(fake_run))

    output = LocalSandbox("t").execute_command("echo hello")

    assert output == "ok"
    assert calls == [
        (
            [r"C:\Program Files\Git\bin\sh.exe", "-c", "echo hello"],
            600,
            {
                "PATH": r"C:\Program Files\Git\bin",
                "MSYS2_ARG_CONV_EXCL": "/mnt/user-data",
            },
        )
    ]


def test_execute_command_scopes_msys_path_conversion_exclusions_on_windows(monkeypatch):
    calls: list[tuple[list[str], float, dict[str, str]]] = []

    def fake_run(args, timeout, env):
        calls.append((args, timeout, env))
        return "ok", "", 0, False

    monkeypatch.setattr(local_sandbox.os, "name", "nt")
    monkeypatch.setattr(local_sandbox.os, "environ", {"PATH": r"C:\Program Files\Git\bin"})
    monkeypatch.setattr(LocalSandbox, "_get_shell", staticmethod(lambda: r"C:\Program Files\Git\bin\sh.exe"))
    monkeypatch.setattr(LocalSandbox, "_msys_path_conversion_exclusions", lambda self: "/mnt/user-data")
    monkeypatch.setattr(LocalSandbox, "_run_windows_command", staticmethod(fake_run))

    output = LocalSandbox("t").execute_command("cat /mnt/user-data/workspace/input.txt")

    assert output == "ok"
    assert calls[0][2] == {
        "PATH": r"C:\Program Files\Git\bin",
        "MSYS2_ARG_CONV_EXCL": "/mnt/user-data",
    }


def test_execute_command_ignores_root_msys_mapping_for_host_commands_on_windows(monkeypatch):
    calls: list[tuple[list[str], float, dict[str, str]]] = []

    def fake_run(args, timeout, env):
        calls.append((args, timeout, env))
        return "ok", "", 0, False

    monkeypatch.setattr(local_sandbox.os, "name", "nt")
    monkeypatch.setattr(local_sandbox.os, "environ", {"PATH": r"C:\Program Files\Git\bin"})
    monkeypatch.setattr(LocalSandbox, "_get_shell", staticmethod(lambda: r"C:\Program Files\Git\bin\sh.exe"))
    monkeypatch.setattr(LocalSandbox, "_msys_path_conversion_exclusions", lambda self: "")
    monkeypatch.setattr(LocalSandbox, "_run_windows_command", staticmethod(fake_run))

    output = LocalSandbox("t").execute_command("echo hello")

    assert output == "ok"
    assert calls[0][2] == {"PATH": r"C:\Program Files\Git\bin"}


def test_msys_path_conversion_exclusions_omit_blanket_patterns():
    sandbox = LocalSandbox(
        "t",
        [
            PathMapping(container_path="/", local_path="C:\\"),
            PathMapping(container_path="/mnt/data;*", local_path=r"C:\data"),
            PathMapping(container_path="/mnt/user-data/", local_path=r"C:\user-data"),
            PathMapping(container_path="/mnt/user-data", local_path=r"C:\user-data"),
        ],
    )

    assert sandbox._msys_path_conversion_exclusions() == "/mnt/user-data"


def test_execute_command_does_not_set_msys_env_for_non_msys_posix_shell_on_windows(monkeypatch):
    calls: list[tuple[list[str], float, dict[str, str]]] = []

    def fake_run(args, timeout, env):
        calls.append((args, timeout, env))
        return "ok", "", 0, False

    monkeypatch.setattr(local_sandbox.os, "name", "nt")
    monkeypatch.setattr(local_sandbox.os, "environ", {"PATH": r"C:\tools"})
    monkeypatch.setattr(LocalSandbox, "_get_shell", staticmethod(lambda: r"C:\tools\busybox\sh.exe"))
    monkeypatch.setattr(LocalSandbox, "_run_windows_command", staticmethod(fake_run))

    output = LocalSandbox("t").execute_command("echo /mnt/skills/demo")

    assert output == "ok"
    # Non-MSYS posix shell adds no MSYS_* vars; the env is the scrubbed inherited
    # environment, not None (#3861).
    assert calls[0][2] == {"PATH": r"C:\tools"}
    assert "MSYS_NO_PATHCONV" not in calls[0][2]


def test_execute_command_uses_cmd_command_mode_on_windows(monkeypatch):
    calls: list[tuple[list[str], float, dict[str, str]]] = []

    def fake_run(args, timeout, env):
        calls.append((args, timeout, env))
        return "ok", "", 0, False

    monkeypatch.setattr(local_sandbox.os, "name", "nt")
    monkeypatch.setattr(local_sandbox.os, "environ", {"PATH": r"C:\Windows", "GITHUB_TOKEN": "should-not-leak"})
    monkeypatch.setattr(LocalSandbox, "_get_shell", staticmethod(lambda: r"C:\Windows\System32\cmd.exe"))
    monkeypatch.setattr(LocalSandbox, "_run_windows_command", staticmethod(fake_run))

    output = LocalSandbox("t").execute_command("echo hello")

    assert output == "ok"
    # Platform secrets are scrubbed even on the Windows cmd path (#3861); the env
    # is an explicit scrubbed dict, no longer None.
    assert calls == [
        (
            [r"C:\Windows\System32\cmd.exe", "/c", "echo hello"],
            600,
            {"PATH": r"C:\Windows"},
        )
    ]
