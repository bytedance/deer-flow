"""Remote list_dir command/parser contract, including a real POSIX sh pipeline."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess

import pytest

from deerflow.sandbox.remote_list_dir import parse_remote_list_dir_output, remote_list_dir_command

_POSIX_SH = pytest.mark.skipif(
    os.name == "nt" or shutil.which("sh") is None or shutil.which("head") is None,
    reason="POSIX sh pipeline required",
)


def test_parse_marker_127_is_command_failure_not_missing_path() -> None:
    stdout = "\n__DF_FIND_STATUS__:127\n"
    with pytest.raises(OSError, match="exited with code 127"):
        parse_remote_list_dir_output(stdout, "/dir", pipeline_exit_code=0)


def test_parse_marker_1_empty_is_missing_path() -> None:
    stdout = "\n__DF_FIND_STATUS__:1\n"
    with pytest.raises(FileNotFoundError):
        parse_remote_list_dir_output(stdout, "/dir", pipeline_exit_code=0)


def test_parse_marker_0_returns_listing_and_keeps_trailing_space() -> None:
    stdout = "/dir/notes.txt \n/dir/sub\n\n__DF_FIND_STATUS__:0\n"
    assert parse_remote_list_dir_output(stdout, "/dir", pipeline_exit_code=0) == [
        "/dir/notes.txt ",
        "/dir/sub",
    ]


def test_parse_sigpipe_truncated_listing_is_success() -> None:
    lines = "\n".join(f"/dir/f{i}" for i in range(500))
    stdout = f"{lines}\n\n__DF_FIND_STATUS__:141\n"
    entries = parse_remote_list_dir_output(stdout, "/dir", pipeline_exit_code=0)
    assert len(entries) == 500
    assert entries[0] == "/dir/f0"
    assert entries[-1] == "/dir/f499"


def test_parse_falls_back_to_pipeline_exit_without_marker() -> None:
    with pytest.raises(OSError, match="exited with code 127"):
        parse_remote_list_dir_output("", "/dir", pipeline_exit_code=127)
    with pytest.raises(OSError, match="marker missing"):
        parse_remote_list_dir_output("", "/dir", pipeline_exit_code=0)
    with pytest.raises(OSError, match="marker missing"):
        parse_remote_list_dir_output("/dir\n", "/dir", pipeline_exit_code=0)


@_POSIX_SH
def test_parse_without_marker_real_subprocess_status_is_not_always_ok() -> None:
    """``rm -f`` exits 0/1, both in _FIND_OK. A real process status with no marker must not become FileNotFoundError."""
    for script in ("exit 0", "exit 1"):
        proc = subprocess.run(["sh", "-c", script], capture_output=True, text=True, check=False)
        with pytest.raises(OSError, match="marker missing"):
            parse_remote_list_dir_output(
                proc.stdout,
                "/dir",
                pipeline_exit_code=proc.returncode,
            )


def test_command_records_find_status_after_head() -> None:
    command = remote_list_dir_command("/mnt/acp-workspace", 2)
    assert command.startswith("set +e; ")
    assert "find -H " in command
    assert "\\( -type f -o -type d \\)" in command
    assert "head -n 500" in command
    assert "__DF_FIND_STATUS__:" in command
    assert command.index("find -H ") < command.index("head -n")
    assert command.index("head -n") < command.index("__DF_FIND_STATUS__:")
    assert 'exit "${st:-126}"' in command


def _run_list_dir_script(command: str, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    # Providers invoke ``sh -lc``; tests use ``sh -c`` so an injected fake
    # ``find`` on PATH is not overwritten by a login profile.
    return subprocess.run(
        ["sh", "-c", command],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _env_with_bin(bin_dir: str) -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
    return env


@_POSIX_SH
def test_naive_find_head_pipeline_hides_find_127(tmp_path) -> None:
    """Reproduction: without capturing find's status, head's 0 wins."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_find = fake_bin / "find"
    fake_find.write_text("#!/bin/sh\nexit 127\n", encoding="utf-8")
    fake_find.chmod(fake_find.stat().st_mode | stat.S_IEXEC)

    naive = "find -H /dir -maxdepth 2 \\( -type f -o -type d \\) 2>/dev/null | head -n 500"
    proc = _run_list_dir_script(naive, env=_env_with_bin(str(fake_bin)))
    assert proc.returncode == 0
    assert proc.stdout == ""


def _write_fake_find(tmp_path, script: str):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_find = fake_bin / "find"
    fake_find.write_text(script, encoding="utf-8")
    fake_find.chmod(fake_find.stat().st_mode | stat.S_IEXEC)
    return fake_bin


@_POSIX_SH
def test_list_dir_command_surfaces_find_127_not_head_0(tmp_path) -> None:
    fake_bin = _write_fake_find(tmp_path, "#!/bin/sh\nexit 127\n")
    proc = _run_list_dir_script(
        remote_list_dir_command("/dir", 2),
        env=_env_with_bin(str(fake_bin)),
    )
    assert proc.returncode == 127
    with pytest.raises(OSError, match="exited with code 127"):
        parse_remote_list_dir_output(proc.stdout, "/dir", pipeline_exit_code=proc.returncode)


@_POSIX_SH
def test_list_dir_command_records_find_127_under_set_e(tmp_path) -> None:
    fake_bin = _write_fake_find(tmp_path, "#!/bin/sh\nexit 127\n")
    proc = _run_list_dir_script(
        "set -e; " + remote_list_dir_command("/dir", 2),
        env=_env_with_bin(str(fake_bin)),
    )
    assert proc.returncode == 127
    with pytest.raises(OSError, match="exited with code 127"):
        parse_remote_list_dir_output(proc.stdout, "/dir", pipeline_exit_code=proc.returncode)


@_POSIX_SH
@pytest.mark.skipif(shutil.which("find") is None, reason="system find required")
def test_list_dir_command_missing_path_is_file_not_found(tmp_path) -> None:
    missing = tmp_path / "no-such-dir"
    proc = _run_list_dir_script(remote_list_dir_command(str(missing), 2))
    with pytest.raises(FileNotFoundError):
        parse_remote_list_dir_output(proc.stdout, str(missing), pipeline_exit_code=proc.returncode)


@_POSIX_SH
@pytest.mark.skipif(shutil.which("find") is None, reason="system find required")
def test_list_dir_command_empty_dir_lists_the_start_point(tmp_path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    proc = _run_list_dir_script(remote_list_dir_command(str(empty), 2))
    entries = parse_remote_list_dir_output(proc.stdout, str(empty), pipeline_exit_code=proc.returncode)
    assert str(empty) in entries


@_POSIX_SH
def test_list_dir_command_head_truncation_is_not_an_error(tmp_path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_find = fake_bin / "find"
    fake_find.write_text(
        '#!/bin/sh\ni=1\nwhile [ "$i" -le 5000 ]; do\n  echo "/dir/f$i"\n  i=$((i+1))\ndone\nexit 0\n',
        encoding="utf-8",
    )
    fake_find.chmod(fake_find.stat().st_mode | stat.S_IEXEC)

    proc = _run_list_dir_script(
        remote_list_dir_command("/dir", 2),
        env=_env_with_bin(str(fake_bin)),
    )
    entries = parse_remote_list_dir_output(proc.stdout, "/dir", pipeline_exit_code=proc.returncode)
    assert len(entries) == 500
    assert entries[0] == "/dir/f1"
    assert entries[-1] == "/dir/f500"
