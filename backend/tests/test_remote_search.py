"""Remote grep/glob command wrapper and stdout contract, including a real POSIX sh pipeline (#5376)."""

from __future__ import annotations

import os
import shlex
import shutil
import stat
import subprocess

import pytest

from deerflow.sandbox.remote_search import parse_remote_search_output, remote_search_command

_POSIX_SH = pytest.mark.skipif(
    os.name == "nt" or shutil.which("sh") is None or shutil.which("head") is None,
    reason="POSIX sh pipeline required",
)
_REAL_GREP = pytest.mark.skipif(shutil.which("grep") is None, reason="system grep required")
_REAL_FIND = pytest.mark.skipif(shutil.which("find") is None, reason="system find required")


def _grep(root: str, pattern: str = "needle") -> str:
    return f"grep -r -H -n -I -E -e {shlex.quote(pattern)} {shlex.quote(root)} 2>/dev/null"


def _find(root: str) -> str:
    return f"find -H {shlex.quote(root)} \\( -type f \\) -print 2>/dev/null"


def _run(command: str, *, env: dict[str, str] | None = None) -> str:
    # Providers invoke ``sh -lc``; tests use ``sh -c`` so an injected fake
    # binary on PATH is not overwritten by a login profile.
    proc = subprocess.run(["sh", "-c", command], capture_output=True, text=True, env=env, check=False)
    # The wrapper always exits 0 so SDKs that raise on a non-zero exit still
    # return the status marker.
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def _env_with_fake(tmp_path, name: str, script: str) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake = bin_dir / name
    fake.write_text(script, encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    env = os.environ.copy()
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
    return env


# ── parser ────────────────────────────────────────────────────────────────


def test_parse_missing_root_marker_is_file_not_found() -> None:
    with pytest.raises(FileNotFoundError):
        parse_remote_search_output("__DF_SEARCH_STATUS__:missing\n", "/dir", tool="grep")


@pytest.mark.parametrize("stdout", ["", "/dir/a.py:1:needle\n"])
def test_parse_without_marker_is_a_failure_not_a_result(stdout: str) -> None:
    with pytest.raises(OSError, match="status marker missing"):
        parse_remote_search_output(stdout, "/dir", tool="grep")


@pytest.mark.parametrize(("tool", "status"), [("grep", 0), ("grep", 141), ("find", 0), ("find", 141)])
def test_parse_success_keeps_output_and_trailing_space(tool: str, status: int) -> None:
    stdout = f"/dir/notes.txt \n\n__DF_SEARCH_STATUS__:{status}\n"
    assert parse_remote_search_output(stdout, "/dir", tool=tool) == "/dir/notes.txt "


def test_parse_genuine_no_match_is_empty() -> None:
    assert parse_remote_search_output("\n__DF_SEARCH_STATUS__:1\n", "/dir", tool="grep") == ""
    assert parse_remote_search_output("\n__DF_SEARCH_STATUS__:0\n", "/dir", tool="find") == ""


@pytest.mark.parametrize(("tool", "status"), [("grep", 2), ("grep", 126), ("grep", 127), ("find", 1), ("find", 127)])
def test_parse_failure_without_output_raises(tool: str, status: int) -> None:
    with pytest.raises(OSError, match=f"exited with code {status}"):
        parse_remote_search_output(f"\n__DF_SEARCH_STATUS__:{status}\n", "/dir", tool=tool)


@pytest.mark.parametrize(("tool", "status"), [("grep", 2), ("find", 1)])
def test_parse_partial_error_keeps_what_was_read(tool: str, status: int) -> None:
    # One unreadable file or subdirectory: the rest of the tree was still searched.
    assert parse_remote_search_output(f"/dir/a.py\n\n__DF_SEARCH_STATUS__:{status}\n", "/dir", tool=tool) == "/dir/a.py"


def test_parse_unparseable_status_is_a_failure() -> None:
    with pytest.raises(OSError, match="status unavailable"):
        parse_remote_search_output("\n__DF_SEARCH_STATUS__:\n", "/dir", tool="find")


def test_command_checks_root_first_and_records_status_after_head() -> None:
    command = remote_search_command(_grep("/mnt/data dir"), "/mnt/data dir", limit=450)
    assert command.startswith("set +e; ")
    assert "[ ! -e '/mnt/data dir' ]" in command
    assert command.index("[ ! -e ") < command.index("grep ") < command.index("head -n 450")
    assert command.index("head -n 450") < command.rindex("__DF_SEARCH_STATUS__:")
    assert command.endswith("exit 0")


# ── real POSIX sh ─────────────────────────────────────────────────────────


@_POSIX_SH
@_REAL_GREP
def test_naive_grep_head_pipeline_hides_a_missing_root(tmp_path) -> None:
    """Reproduction of #5376: without the wrapper, head's 0 wins and stdout is empty."""
    proc = subprocess.run(["sh", "-c", _grep(str(tmp_path / "missing")) + " | head -450"], capture_output=True, text=True, check=False)
    assert (proc.returncode, proc.stdout) == (0, "")


@_POSIX_SH
@_REAL_GREP
def test_grep_distinguishes_match_no_match_and_missing_root(tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def needle():\n    return 1\n", encoding="utf-8")
    root = str(tmp_path)

    found = parse_remote_search_output(_run(remote_search_command(_grep(root), root, limit=450)), root, tool="grep")
    assert found == f"{tmp_path / 'src' / 'app.py'}:1:def needle():"
    none = parse_remote_search_output(_run(remote_search_command(_grep(root, "zzz_nothing"), root, limit=450)), root, tool="grep")
    assert none == ""

    missing = str(tmp_path / "missing")
    with pytest.raises(FileNotFoundError):
        parse_remote_search_output(_run(remote_search_command(_grep(missing), missing, limit=450)), missing, tool="grep")


@_POSIX_SH
@pytest.mark.parametrize("binary", ["grep", "find"])
def test_missing_search_binary_is_a_failure_not_a_no_match(tmp_path, binary: str) -> None:
    env = _env_with_fake(tmp_path, binary, "#!/bin/sh\nexit 127\n")
    root = str(tmp_path)
    search, tool = (_grep(root), "grep") if binary == "grep" else (_find(root), "find")
    with pytest.raises(OSError, match="exited with code 127"):
        parse_remote_search_output(_run(remote_search_command(search, root, limit=450), env=env), root, tool=tool)


@_POSIX_SH
@_REAL_FIND
def test_find_follows_a_symlinked_root_and_reports_an_empty_tree(tmp_path) -> None:
    real = tmp_path / "real"
    (real / "sub").mkdir(parents=True)
    (real / "sub" / "a.txt").write_text("x", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    out = parse_remote_search_output(_run(remote_search_command(_find(str(link)), str(link), limit=850)), str(link), tool="find")
    assert out == f"{link}/sub/a.txt"

    empty = tmp_path / "empty"
    empty.mkdir()
    assert parse_remote_search_output(_run(remote_search_command(_find(str(empty)), str(empty), limit=850)), str(empty), tool="find") == ""


@_POSIX_SH
@_REAL_GREP
@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root can read an unreadable directory")
def test_unreadable_root_is_a_failure_not_a_no_match(tmp_path) -> None:
    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / "a.txt").write_text("needle\n", encoding="utf-8")
    locked.chmod(0)
    try:
        with pytest.raises(OSError, match="exited with code 2"):
            parse_remote_search_output(_run(remote_search_command(_grep(str(locked)), str(locked), limit=450)), str(locked), tool="grep")
    finally:
        locked.chmod(0o700)


@_POSIX_SH
def test_head_truncation_is_not_a_failure(tmp_path) -> None:
    env = _env_with_fake(tmp_path, "grep", '#!/bin/sh\ni=1\nwhile [ "$i" -le 5000 ]; do\n  echo "/dir/f$i:1:needle"\n  i=$((i+1))\ndone\nexit 0\n')
    out = parse_remote_search_output(_run(remote_search_command(_grep("/"), "/", limit=450), env=env), "/", tool="grep")
    lines = out.split("\n")
    assert len(lines) == 450
    assert lines[0] == "/dir/f1:1:needle"
