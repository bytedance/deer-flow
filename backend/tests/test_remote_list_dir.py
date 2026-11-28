"""Remote list_dir command/parser contract, including a real POSIX sh pipeline."""

from __future__ import annotations

import os
import shlex
import shutil
import stat
import subprocess

import pytest

from deerflow.sandbox.remote_list_dir import parse_remote_find_output, parse_remote_list_dir_output, remote_list_dir_command

_POSIX_SH = pytest.mark.skipif(
    os.name == "nt" or shutil.which("sh") is None or shutil.which("head") is None,
    reason="POSIX sh pipeline required",
)


def test_parse_marker_127_is_command_failure_not_missing_path() -> None:
    stdout = "\n__DF_FIND_STATUS__:127\n"
    with pytest.raises(OSError, match="exited with code 127"):
        parse_remote_list_dir_output(stdout, "/dir", pipeline_exit_code=0)


def test_parse_missing_marker_is_missing_path() -> None:
    stdout = "__DF_FIND_STATUS__:missing\n"
    with pytest.raises(FileNotFoundError):
        parse_remote_list_dir_output(stdout, "/dir", pipeline_exit_code=0)


def test_parse_marker_1_empty_is_incomplete_failure() -> None:
    with pytest.raises(OSError, match="results would be incomplete"):
        parse_remote_list_dir_output("\n__DF_FIND_STATUS__:1\n", "/dir", pipeline_exit_code=1)


def test_parse_marker_1_with_entries_is_incomplete_failure() -> None:
    stdout = "/dir/visible.txt\n\n__DF_FIND_STATUS__:1\n"
    with pytest.raises(OSError, match="results would be incomplete"):
        parse_remote_list_dir_output(stdout, "/dir", pipeline_exit_code=1)


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
    """``rm -f`` exits 0/1. A process status without a marker must not become FileNotFoundError."""
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
    assert command.index("head -n") < command.rindex("__DF_FIND_STATUS__:")
    assert 'exit "${st:-126}"' in command
    # Mirror pin (review on PR #5546): the exit must stay subshell-wrapped — a
    # bare top-level exit wedges the implicit persistent session. A silent
    # revert of the subshell wrap must fail this test.
    assert command.endswith('exit "${st:-126}" )')


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
        remote_list_dir_command(str(tmp_path), 2),
        env=_env_with_bin(str(fake_bin)),
    )
    assert proc.returncode == 127
    with pytest.raises(OSError, match="exited with code 127"):
        parse_remote_list_dir_output(proc.stdout, "/dir", pipeline_exit_code=proc.returncode)


@_POSIX_SH
def test_list_dir_command_surfaces_partial_find_failure(tmp_path) -> None:
    fake_bin = _write_fake_find(tmp_path, '#!/bin/sh\nprintf "/dir/visible.txt\\n"\nexit 1\n')
    proc = _run_list_dir_script(
        remote_list_dir_command(str(tmp_path), 2),
        env=_env_with_bin(str(fake_bin)),
    )
    assert proc.returncode == 1
    with pytest.raises(OSError, match="results would be incomplete"):
        parse_remote_list_dir_output(proc.stdout, "/dir", pipeline_exit_code=proc.returncode)


@_POSIX_SH
def test_list_dir_command_records_find_127_under_set_e(tmp_path) -> None:
    fake_bin = _write_fake_find(tmp_path, "#!/bin/sh\nexit 127\n")
    proc = _run_list_dir_script(
        "set -e; " + remote_list_dir_command(str(tmp_path), 2),
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
    assert proc.stdout.strip() == "__DF_FIND_STATUS__:missing"
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
        remote_list_dir_command(str(tmp_path), 2),
        env=_env_with_bin(str(fake_bin)),
    )
    entries = parse_remote_list_dir_output(proc.stdout, "/dir", pipeline_exit_code=proc.returncode)
    assert len(entries) == 500
    # The explicitly emitted root shares the same 500-entry output budget.
    assert entries[0] == str(tmp_path)
    assert entries[1] == "/dir/f1"
    assert entries[-1] == "/dir/f499"


@_POSIX_SH
def test_list_dir_existing_root_with_no_output_is_incomplete_failure(tmp_path) -> None:
    root = tmp_path / "unreadable 'directory"
    root.mkdir()
    fake_bin = _write_fake_find(tmp_path, "#!/bin/sh\nexit 1\n")
    proc = _run_list_dir_script(remote_list_dir_command(str(root), 2), env=_env_with_bin(str(fake_bin)))
    assert proc.returncode == 1
    with pytest.raises(OSError, match="results would be incomplete"):
        parse_remote_list_dir_output(proc.stdout, str(root), pipeline_exit_code=proc.returncode)


def test_parse_drops_entries_under_ignored_directories() -> None:
    """A remote listing must skip the same directories remote glob/grep already skip."""
    stdout = "/root\n/root/.git\n/root/.git/config\n/root/node_modules/pkg/index.js\n/root/src\n/root/src/app.py\n\n__DF_FIND_STATUS__:0\n"
    assert parse_remote_list_dir_output(stdout, "/root", pipeline_exit_code=0) == [
        "/root",
        "/root/src",
        "/root/src/app.py",
    ]


def test_parse_keeps_names_that_only_resemble_ignore_patterns() -> None:
    stdout = "/root/node_modules_backup/keep.txt\n/root/builds/keep.txt\n/root/src/environment.py\n\n__DF_FIND_STATUS__:0\n"
    assert parse_remote_list_dir_output(stdout, "/root", pipeline_exit_code=0) == [
        "/root/node_modules_backup/keep.txt",
        "/root/builds/keep.txt",
        "/root/src/environment.py",
    ]


def test_parse_all_entries_ignored_returns_empty_list_not_missing_path() -> None:
    """An existing directory whose entries are all ignored is empty, not missing."""
    stdout = "/data/node_modules\n/data/node_modules/pkg/index.js\n\n__DF_FIND_STATUS__:0\n"
    assert parse_remote_list_dir_output(stdout, "/data", pipeline_exit_code=0) == []


def test_parse_keeps_contents_of_an_explicitly_requested_ignored_root() -> None:
    """Explicitly listing a directory whose own name is ignored must not come back empty."""
    stdout = "/data/node_modules\n/data/node_modules/pkg\n/data/node_modules/pkg/index.js\n\n__DF_FIND_STATUS__:0\n"
    assert parse_remote_list_dir_output(stdout, "/data/node_modules", pipeline_exit_code=0) == [
        "/data/node_modules",
        "/data/node_modules/pkg",
        "/data/node_modules/pkg/index.js",
    ]


def test_parse_ignores_only_descendants_of_the_listing_root() -> None:
    """An ignored name *outside* the root hides nothing; an ignored name inside it still does."""
    stdout = "/tmp/build/workspace\n/tmp/build/workspace/report.txt\n/tmp/build/workspace/nested/node_modules/dep.js\n\n__DF_FIND_STATUS__:0\n"
    assert parse_remote_list_dir_output(stdout, "/tmp/build/workspace", pipeline_exit_code=0) == [
        "/tmp/build/workspace",
        "/tmp/build/workspace/report.txt",
    ]
    stdout_env = "/srv/env/project\n/srv/env/project/src/main.py\n\n__DF_FIND_STATUS__:0\n"
    assert parse_remote_list_dir_output(stdout_env, "/srv/env/project", pipeline_exit_code=0) == [
        "/srv/env/project",
        "/srv/env/project/src/main.py",
    ]


@_POSIX_SH
@pytest.mark.skipif(shutil.which("find") is None, reason="system find required")
def test_list_dir_command_drops_ignored_directories(tmp_path) -> None:
    root = tmp_path / "workspace"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("print('x')", encoding="utf-8")
    (root / "node_modules" / "pkg").mkdir(parents=True)
    (root / "node_modules" / "pkg" / "index.js").write_text("module.exports = {}", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("[core]", encoding="utf-8")
    proc = _run_list_dir_script(remote_list_dir_command(str(root), 2))
    entries = parse_remote_list_dir_output(proc.stdout, str(root), pipeline_exit_code=proc.returncode)
    assert str(root / "src" / "app.py") in entries
    assert not any("node_modules" in entry for entry in entries)
    assert not any(entry.endswith("/.git") or "/.git/" in entry for entry in entries)


@_POSIX_SH
@pytest.mark.skipif(shutil.which("find") is None, reason="system find required")
def test_list_dir_command_lists_inside_an_ignored_ancestor(tmp_path) -> None:
    """Real find: an ignored-looking ancestor of the root hides nothing."""
    root = tmp_path / "build" / "workspace"
    root.mkdir(parents=True)
    (root / "report.txt").write_text("x", encoding="utf-8")
    proc = _run_list_dir_script(remote_list_dir_command(str(root), 2))
    entries = parse_remote_list_dir_output(proc.stdout, str(root), pipeline_exit_code=proc.returncode)
    assert str(root / "report.txt") in entries


@_POSIX_SH
@pytest.mark.skipif(shutil.which("find") is None, reason="system find required")
def test_list_dir_command_lists_an_explicitly_requested_ignored_directory(tmp_path) -> None:
    """Real find: `ls logs` returns the directory and its files, not emptiness."""
    root = tmp_path / "logs"
    root.mkdir()
    (root / "notes.txt").write_text("x", encoding="utf-8")
    proc = _run_list_dir_script(remote_list_dir_command(str(root), 2))
    entries = parse_remote_list_dir_output(proc.stdout, str(root), pipeline_exit_code=proc.returncode)
    assert str(root) in entries
    assert str(root / "notes.txt") in entries


@_POSIX_SH
@pytest.mark.skipif(shutil.which("find") is None or shutil.which("sort") is None, reason="system find and sort required")
@pytest.mark.parametrize("root_name", ["workspace", "build", "project [one]'s"])
@pytest.mark.parametrize("ignored_kind", ["directory", "files"])
def test_ignored_entries_do_not_consume_listing_budget(tmp_path, root_name, ignored_kind) -> None:
    """A deterministic real-find order puts ignored entries before the useful file."""
    root = tmp_path / root_name
    root.mkdir()
    if ignored_kind == "directory":
        ignored = root / "node_modules"
        ignored.mkdir()
        for index in range(600):
            (ignored / f"dependency_{index:04}.js").touch()
    else:
        for index in range(600):
            (root / f"ignored_{index:04}.log").touch()
    visible = root / "zz_report.txt"
    visible.write_text("report", encoding="utf-8")
    # Only enumeration order is normalized. The real find still evaluates the
    # production arguments and traversal/pruning expression against real files.
    find = shlex.quote(shutil.which("find"))
    sort = shlex.quote(shutil.which("sort"))
    fake_bin = _write_fake_find(tmp_path, f'#!/bin/sh\n{find} "$@" | LC_ALL=C {sort}\n')
    proc = _run_list_dir_script(remote_list_dir_command(str(root), 2), env=_env_with_bin(str(fake_bin)))
    entries = parse_remote_list_dir_output(proc.stdout, str(root), pipeline_exit_code=proc.returncode)
    assert entries == [str(root), str(visible)]


@_POSIX_SH
@pytest.mark.skipif(shutil.which("find") is None, reason="system find required")
def test_visible_listing_still_obeys_depth_and_output_limit(tmp_path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    for index in range(8):
        (root / f"visible_{index}.txt").touch()
    (root / "nested" / "too-deep").mkdir(parents=True)
    (root / "nested" / "too-deep" / "report.txt").touch()
    proc = _run_list_dir_script(remote_list_dir_command(str(root), 1, limit=4))
    entries = parse_remote_list_dir_output(proc.stdout, str(root), pipeline_exit_code=proc.returncode)
    assert len(entries) == 4
    assert entries[0] == str(root)
    assert all("too-deep" not in entry for entry in entries)


@_POSIX_SH
@pytest.mark.skipif(shutil.which("find") is None, reason="system find required")
def test_pruning_preserves_an_ignored_symlinked_root(tmp_path) -> None:
    target = tmp_path / "actual"
    target.mkdir()
    (target / "report.txt").touch()
    (target / "node_modules").mkdir()
    (target / "node_modules" / "dependency.js").touch()
    root = tmp_path / "build"
    root.symlink_to(target, target_is_directory=True)
    proc = _run_list_dir_script(remote_list_dir_command(str(root), 2))
    entries = parse_remote_list_dir_output(proc.stdout, str(root), pipeline_exit_code=proc.returncode)
    assert entries == [str(root), str(root / "report.txt")]


@_POSIX_SH
@pytest.mark.skipif(shutil.which("find") is None, reason="system find required")
def test_pruning_uses_the_parsers_case_policy(tmp_path, monkeypatch) -> None:
    root = tmp_path / "workspace"
    (root / "BUILD").mkdir(parents=True)
    (root / "BUILD" / "ignored.txt").touch()
    (root / "report.txt").touch()
    # Exercise the policy a Windows Gateway applies to a POSIX remote sandbox.
    monkeypatch.setattr(os.path, "normcase", lambda value: value.lower())
    proc = _run_list_dir_script(remote_list_dir_command(str(root), 2))
    assert "BUILD" not in proc.stdout
    entries = parse_remote_list_dir_output(proc.stdout, str(root), pipeline_exit_code=proc.returncode)
    assert entries == [str(root), str(root / "report.txt")]


def test_command_prunes_data_names_only_outside_user_data() -> None:
    default = remote_list_dir_command("/mnt/user-data/uploads", 2)
    assert "-name '*.log'" in default or "-iname '*.log'" in default
    user_data = remote_list_dir_command("/mnt/user-data/uploads", 2, user_data=True)
    assert "*.log" not in user_data
    # shlex.quote leaves bare words unquoted, so check the prune term itself.
    assert "-name logs" not in user_data and "-iname logs" not in user_data
    # Repository machinery and in-flight uploads stay pruned in both root types.
    for command in (default, user_data):
        assert "node_modules" in command
        assert ".upload-*.part" in command


def test_parse_user_data_keeps_logs_and_hides_machinery() -> None:
    stdout = (
        "/mnt/user-data/uploads\n/mnt/user-data/uploads/app.log\n/mnt/user-data/uploads/logs\n"
        "/mnt/user-data/uploads/logs/worker.log\n/mnt/user-data/uploads/notes.txt\n"
        "/mnt/user-data/uploads/node_modules/dep.log\n/mnt/user-data/uploads/.upload-active.part\n\n__DF_FIND_STATUS__:0\n"
    )
    assert parse_remote_list_dir_output(stdout, "/mnt/user-data/uploads", pipeline_exit_code=0, user_data=True) == [
        "/mnt/user-data/uploads",
        "/mnt/user-data/uploads/app.log",
        "/mnt/user-data/uploads/logs",
        "/mnt/user-data/uploads/logs/worker.log",
        "/mnt/user-data/uploads/notes.txt",
    ]
    # Without the label the same listing keeps the repository filter.
    assert parse_remote_list_dir_output(stdout, "/mnt/user-data/uploads", pipeline_exit_code=0) == [
        "/mnt/user-data/uploads",
        "/mnt/user-data/uploads/notes.txt",
    ]


@_POSIX_SH
@pytest.mark.skipif(shutil.which("find") is None, reason="system find required")
def test_list_dir_command_user_data_keeps_uploaded_logs(tmp_path) -> None:
    root = tmp_path / "uploads"
    (root / "logs").mkdir(parents=True)
    (root / "app.log").write_text("FATAL app\n", encoding="utf-8")
    (root / "logs" / "worker.log").write_text("FATAL worker\n", encoding="utf-8")
    (root / "notes.txt").write_text("FATAL notes\n", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "dep.log").write_text("FATAL dep\n", encoding="utf-8")
    (root / ".upload-active.part").write_text("partial", encoding="utf-8")

    proc = _run_list_dir_script(remote_list_dir_command(str(root), 3, user_data=True))
    entries = parse_remote_list_dir_output(proc.stdout, str(root), pipeline_exit_code=proc.returncode, user_data=True)
    assert str(root / "app.log") in entries
    assert str(root / "logs" / "worker.log") in entries
    assert not any("node_modules" in entry or ".upload-active.part" in entry for entry in entries)

    # The default prune still hides the data-looking names in the same tree.
    proc = _run_list_dir_script(remote_list_dir_command(str(root), 3))
    entries = parse_remote_list_dir_output(proc.stdout, str(root), pipeline_exit_code=proc.returncode)
    assert entries == [str(root), str(root / "notes.txt")]


# --- glob mode: in-sandbox find with a basename coarse filter -----------------


def test_glob_command_prunes_before_the_basename_filter() -> None:
    # Prune runs during the walk, so a large ignored tree never reaches the
    # -name filter or the head cap. The -name coarse filter must also appear.
    command = remote_list_dir_command("/work", None, limit=10, name_glob="*.md", files_only=True, glob="*.md")
    assert "node_modules" in command
    assert "-prune" in command
    assert "-name '*.md'" in command
    assert "-type f" in command
    assert r"\( -type f -o -type d \)" not in command  # files-only walk
    assert "-maxdepth" not in command  # unbounded glob walk
    assert command.index("-prune") < command.index("-name '*.md'")


def test_glob_command_include_dirs_keeps_directories() -> None:
    command = remote_list_dir_command("/work", None, limit=10, name_glob="*", files_only=False, glob="*")
    assert r"\( -type f -o -type d \)" in command


def test_glob_command_does_not_preprint_the_root() -> None:
    # The root's rel_path is empty, so it must not consume a head budget line.
    command = remote_list_dir_command("/work", None, limit=10, name_glob="*.md", files_only=True, glob="*.md")
    assert "printf '%s\n' /work;" not in command


def test_glob_command_data_naming_glob_keeps_logs_in_a_checkout() -> None:
    # Asking for *.log makes logs content, so the walk must NOT prune them,
    # even outside a user-data root. Otherwise find would drop what the caller
    # asked for before the client matcher ever sees it.
    command = remote_list_dir_command("/work", None, limit=10, name_glob="*.log", files_only=True, glob="*.log")
    assert "-name '*.log'" in command  # the coarse filter
    # The prune list must not contain a '*.log' prune term (would hide matches).
    assert "-prune -o" in command
    prune_section = command[: command.index("-prune")]
    assert "'*.log'" not in prune_section.replace("-name '*.log'", "")


def test_glob_command_default_glob_prunes_logs_in_a_checkout() -> None:
    # A non-data glob keeps the repository prune, which hides *.log as noise.
    command = remote_list_dir_command("/work", None, limit=10, name_glob="*.py", files_only=True, glob="*.py")
    prune_section = command[: command.index("-prune")]
    assert "'*.log'" in prune_section


@_POSIX_SH
@pytest.mark.skipif(shutil.which("find") is None, reason="system find required")
def test_glob_find_finds_a_match_behind_a_large_ignored_tree(tmp_path) -> None:
    # Reproduce the maintainer's scenario: a README beside a node_modules tree
    # that overflows the listing cap. find prunes node_modules, so the README
    # is the only candidate and the search is complete.
    root = tmp_path / "work"
    (root / "node_modules").mkdir(parents=True)
    (root / "README.md").write_text("# readme\n", encoding="utf-8")
    for i in range(50):
        (root / "node_modules" / f"f{i}.js").write_text("x\n", encoding="utf-8")

    proc = _run_list_dir_script(remote_list_dir_command(str(root), None, limit=10, name_glob="*.md", files_only=True, glob="*.md"))
    entries, truncated = parse_remote_find_output(proc.stdout, str(root), limit=10, pipeline_exit_code=proc.returncode)
    assert entries == [str(root / "README.md")]
    assert truncated is False


@_POSIX_SH
@pytest.mark.skipif(shutil.which("find") is None, reason="system find required")
def test_glob_find_reports_truncation_when_candidates_exceed_the_cap(tmp_path) -> None:
    root = tmp_path / "many"
    root.mkdir()
    for i in range(20):
        (root / f"note{i}.txt").write_text("x\n", encoding="utf-8")

    # head -n 5 cuts the 20-candidate listing; SIGPIPE marks it truncated.
    proc = _run_list_dir_script(remote_list_dir_command(str(root), None, limit=5, name_glob="*.txt", files_only=True, glob="*.txt"))
    entries, truncated = parse_remote_find_output(proc.stdout, str(root), limit=5, pipeline_exit_code=proc.returncode)
    assert truncated is True
    assert len(entries) <= 4


@_POSIX_SH
@pytest.mark.skipif(shutil.which("find") is None, reason="system find required")
def test_glob_find_exact_fit_is_not_truncated(tmp_path) -> None:
    root = tmp_path / "exact"
    root.mkdir()
    for i in range(3):
        (root / f"e{i}.txt").write_text("x\n", encoding="utf-8")

    proc = _run_list_dir_script(remote_list_dir_command(str(root), None, limit=5, name_glob="*.txt", files_only=True, glob="*.txt"))
    entries, truncated = parse_remote_find_output(proc.stdout, str(root), limit=5, pipeline_exit_code=proc.returncode)
    assert truncated is False
    assert len(entries) == 3


@_POSIX_SH
@pytest.mark.skipif(shutil.which("find") is None, reason="system find required")
def test_glob_find_keeps_a_dot_only_name(tmp_path) -> None:
    # A file named exactly ``.csv`` is a candidate for ``*.csv``: POSIX find's
    # ``*`` matches a leading dot, so the walk returns it.
    root = tmp_path / "dots"
    root.mkdir()
    (root / ".csv").write_text("x\n", encoding="utf-8")
    (root / "report.csv").write_text("x\n", encoding="utf-8")

    proc = _run_list_dir_script(remote_list_dir_command(str(root), None, limit=10, name_glob="*.csv", files_only=True, glob="*.csv"))
    entries, truncated = parse_remote_find_output(proc.stdout, str(root), limit=10, pipeline_exit_code=proc.returncode)
    assert str(root / ".csv") in entries
    assert str(root / "report.csv") in entries
    assert truncated is False


def test_parse_remote_find_output_empty_is_no_matches_not_missing() -> None:
    # An empty result is a valid "no matches", not FileNotFoundError.
    entries, truncated = parse_remote_find_output("\n__DF_FIND_STATUS__:0\n", "/work", limit=5, pipeline_exit_code=0)
    assert entries == []
    assert truncated is False


def test_parse_remote_find_output_missing_root_raises() -> None:
    with pytest.raises(FileNotFoundError):
        parse_remote_find_output("__DF_FIND_STATUS__:missing\n", "/work", limit=5, pipeline_exit_code=1)


def test_parse_remote_find_output_exact_fit_is_complete() -> None:
    # head asked for 5 lines (budget 4 + 1). find had exactly 4 candidates, so
    # head returned 4 (< 5): complete, all four kept, no false truncation.
    out = "".join(f"/work/f{i}.md\n" for i in range(4)) + "\n__DF_FIND_STATUS__:0\n"
    entries, truncated = parse_remote_find_output(out, "/work", limit=5, pipeline_exit_code=0)
    assert entries == [f"/work/f{i}.md" for i in range(4)]
    assert truncated is False


def test_parse_remote_find_output_one_past_budget_is_truncated() -> None:
    # find had 5 candidates, head filled all 5 requested lines: truncated, and
    # the probe line is dropped so the client sees a clean 4-candidate budget.
    out = "".join(f"/work/f{i}.md\n" for i in range(5)) + "\n__DF_FIND_STATUS__:0\n"
    entries, truncated = parse_remote_find_output(out, "/work", limit=5, pipeline_exit_code=0)
    assert entries == [f"/work/f{i}.md" for i in range(4)]
    assert truncated is True


def test_parse_remote_find_output_sigpipe_is_not_the_truncation_signal() -> None:
    # A small find result fits the pipe buffer, so find exits 0 even when head
    # cut it off. The raw line count, not SIGPIPE, decides truncation. Here the
    # status is 141 but head still returned fewer than the requested lines.
    out = "/work/a.md\n/work/b.md\n\n__DF_FIND_STATUS__:141\n"
    entries, truncated = parse_remote_find_output(out, "/work", limit=5, pipeline_exit_code=141)
    assert entries == ["/work/a.md", "/work/b.md"]
    assert truncated is False


def test_parse_remote_find_output_file_root_raises_not_a_directory() -> None:
    with pytest.raises(NotADirectoryError):
        parse_remote_find_output("__DF_FIND_STATUS__:notadir\n", "/work/README.md", limit=5, pipeline_exit_code=1)


def test_glob_command_file_root_marks_not_a_directory() -> None:
    # A glob whose root is a file must surface NotADirectoryError, not "no matches".
    command = remote_list_dir_command("/work/README.md", None, limit=10, name_glob="*.md", files_only=True, glob="*.md")
    assert "[ ! -d /work/README.md ]" in command
    assert "__DF_FIND_STATUS__:notadir" in command
    # list_dir (bounded depth) keeps its own behavior: no not-a-dir guard.
    list_cmd = remote_list_dir_command("/work", 2)
    assert "notadir" not in list_cmd


def test_parse_remote_find_output_truncation_equals_total_over_budget() -> None:
    """Pin the protocol: ``limit`` is the head request (budget + 1), so the
    parser sees ``min(total, limit)`` lines. That is enough to decide the only
    question that matters -- whether find had more than the budget -- without
    distinguishing "exactly budget+1" from "more": both are total > budget.
    """
    for budget in range(0, 6):
        head = budget + 1
        for total in range(0, 10):
            lines = min(total, head)
            out = "".join(f"/w/f{i}.md\n" for i in range(lines)) + "\n__DF_FIND_STATUS__:0\n"
            entries, truncated = parse_remote_find_output(out, "/w", limit=head, pipeline_exit_code=0)
            assert truncated is (total > budget), (budget, total)
            assert entries == [f"/w/f{i}.md" for i in range(min(total, budget))], (budget, total)
