"""Line endings survive local-sandbox reads, writes and ``str_replace``.

``LocalSandbox`` opened files in text mode with the default ``newline=None``.
Reads translated CRLF to LF, so ``str_replace`` on a CRLF file edited one line
and wrote every line back as LF, and the read-before-write gate hashed the
translated text and missed a change that only touched line endings. Writes
translated ``\\n`` to ``os.linesep``, so on Windows LF content landed as CRLF.
Reads now use ``newline="\\n"`` and writes ``newline=""``: both keep line
endings as stored, matching the remote providers, and ``str_replace`` spells
``old_str``/``new_str`` the way the file does.
"""

import builtins
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import deerflow.sandbox.local.local_sandbox as local_sandbox
from deerflow.sandbox.local.local_sandbox import LocalSandbox
from deerflow.sandbox.read_file_contract import count_file_lines
from deerflow.sandbox.tools import read_current_file_content, str_replace_tool

CRLF_SOURCE = b"first\r\nsecond\r\nthird\r\n"


def _local_runtime(tmp_path: Path) -> SimpleNamespace:
    for sub in ("workspace", "uploads", "outputs"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    thread_data = {
        "workspace_path": str(tmp_path / "workspace"),
        "uploads_path": str(tmp_path / "uploads"),
        "outputs_path": str(tmp_path / "outputs"),
    }
    return SimpleNamespace(
        state={"sandbox": {"sandbox_id": "local:t1"}, "thread_data": thread_data},
        context={"thread_id": "t1"},
    )


def _use_local_sandbox(monkeypatch) -> None:
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox("t1"))
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)


def _str_replace(tmp_path, monkeypatch, source: bytes, *, old_str: str, new_str: str, replace_all: bool = False) -> tuple[str, bytes]:
    runtime = _local_runtime(tmp_path)
    target = tmp_path / "outputs" / "file.txt"
    target.write_bytes(source)
    _use_local_sandbox(monkeypatch)
    result = str_replace_tool.func(
        runtime=runtime,
        description="replace",
        path="/mnt/user-data/outputs/file.txt",
        old_str=old_str,
        new_str=new_str,
        replace_all=replace_all,
    )
    return result, target.read_bytes()


def _emulate_windows_text_writes(monkeypatch) -> None:
    """Make text-mode writes translate ``\\n`` the way Windows does by default."""
    base = builtins.open

    def windows_open(file, mode="r", *args, **kwargs):
        if "b" not in mode and any(flag in mode for flag in "wax+"):
            kwargs.setdefault("newline", "\r\n")
        return base(file, mode, *args, **kwargs)

    monkeypatch.setattr(local_sandbox, "open", windows_open, raising=False)


def test_read_file_returns_crlf_as_stored(tmp_path) -> None:
    path = tmp_path / "crlf.txt"
    path.write_bytes(CRLF_SOURCE)

    assert LocalSandbox("t").read_file(str(path)) == "first\r\nsecond\r\nthird\r\n"


def test_ranged_read_file_still_joins_lines_with_lf(tmp_path) -> None:
    # Ranged reads join selected lines with "\n" in every provider; keep that.
    path = tmp_path / "crlf.txt"
    path.write_bytes(CRLF_SOURCE)

    assert LocalSandbox("t").read_file(str(path), start_line=2, end_line=3) == "second\nthird"


def test_ranged_read_line_numbers_agree_with_count_file_lines(tmp_path) -> None:
    # The gate's block message and read_file's truncation marker number lines
    # with count_file_lines over the full read; ranged reads must end lines at
    # the same place, so a bare CR is content, not a line break.
    path = tmp_path / "mixed.txt"
    path.write_bytes(b"a\rb\r\nc\nd")
    sandbox = LocalSandbox("t")
    full = sandbox.read_file(str(path))

    assert full == "a\rb\r\nc\nd"
    assert count_file_lines(full) == 3
    assert [sandbox.read_file(str(path), start_line=n, end_line=n) for n in (1, 2, 3, 4)] == ["a\rb", "c", "d", ""]


def test_grep_line_numbers_are_the_lines_ranged_read_file_returns(tmp_path) -> None:
    # grep ends lines where read_file does, so a hit's line_number is the
    # start_line that reads it back, even with a bare CR inside a line.
    path = tmp_path / "mixed.txt"
    path.write_bytes(b"alpha\nlineB\rbeta\ngamma\r\n")
    sandbox = LocalSandbox("t")

    matches, _ = sandbox.grep(str(path), "beta|gamma")

    assert [(match.line_number, match.line) for match in matches] == [(2, "lineB\rbeta"), (3, "gamma")]
    for match in matches:
        assert sandbox.read_file(str(path), start_line=match.line_number, end_line=match.line_number) == match.line


def test_grep_end_anchor_still_matches_a_crlf_line(tmp_path) -> None:
    path = tmp_path / "crlf.txt"
    path.write_bytes(CRLF_SOURCE)

    matches, _ = LocalSandbox("t").grep(str(path), "second$")

    assert [(match.line_number, match.line) for match in matches] == [(2, "second")]


def test_write_file_keeps_lf_under_windows_text_defaults(tmp_path, monkeypatch) -> None:
    path = tmp_path / "run.sh"
    _emulate_windows_text_writes(monkeypatch)

    LocalSandbox("t").write_file(str(path), "#!/bin/bash\necho ok\n")
    LocalSandbox("t").write_file(str(path), "echo more\n", append=True)

    assert path.read_bytes() == b"#!/bin/bash\necho ok\necho more\n"


def test_str_replace_multiline_lf_old_str_keeps_a_crlf_file_crlf(tmp_path, monkeypatch) -> None:
    result, after = _str_replace(tmp_path, monkeypatch, CRLF_SOURCE, old_str="first\nsecond\n", new_str="first\ninserted\nsecond\n")

    assert result == "OK"
    assert after == b"first\r\ninserted\r\nsecond\r\nthird\r\n"


def test_str_replace_single_line_edit_leaves_other_crlf_lines_alone(tmp_path, monkeypatch) -> None:
    result, after = _str_replace(tmp_path, monkeypatch, CRLF_SOURCE, old_str="second", new_str="SECOND")

    assert result == "OK"
    assert after == b"first\r\nSECOND\r\nthird\r\n"


def test_str_replace_lines_inserted_after_a_single_line_anchor_are_crlf(tmp_path, monkeypatch) -> None:
    # old_str has no newline to translate, so only the file decides new_str's.
    result, after = _str_replace(tmp_path, monkeypatch, CRLF_SOURCE, old_str="second", new_str="second\nextra")

    assert result == "OK"
    assert after == b"first\r\nsecond\r\nextra\r\nthird\r\n"


def test_str_replace_all_on_a_crlf_file_keeps_crlf(tmp_path, monkeypatch) -> None:
    result, after = _str_replace(tmp_path, monkeypatch, b"a\r\nb\r\na\r\nb\r\n", old_str="a\nb", new_str="c\nd", replace_all=True)

    assert result == "OK"
    assert after == b"c\r\nd\r\nc\r\nd\r\n"


def test_str_replace_on_a_mixed_file_edits_only_the_matched_lines(tmp_path, monkeypatch) -> None:
    mixed = b"lf1\nlf2\ncrlf1\r\ncrlf2\r\n"

    result, after = _str_replace(tmp_path, monkeypatch, mixed, old_str="lf1\nlf2\n", new_str="LF1\nLF2\n")
    assert result == "OK"
    assert after == b"LF1\nLF2\ncrlf1\r\ncrlf2\r\n"

    result, after = _str_replace(tmp_path, monkeypatch, mixed, old_str="crlf1\ncrlf2\n", new_str="CRLF1\nCRLF2\n")
    assert result == "OK"
    assert after == b"lf1\nlf2\nCRLF1\r\nCRLF2\r\n"


def test_str_replace_on_an_lf_file_writes_new_str_as_given(tmp_path, monkeypatch) -> None:
    result, after = _str_replace(tmp_path, monkeypatch, b"one\ntwo\n", old_str="one\n", new_str="uno\r\n")

    assert result == "OK"
    assert after == b"uno\r\ntwo\n"


def test_str_replace_on_a_crlf_file_still_reports_a_missing_old_str(tmp_path, monkeypatch) -> None:
    result, after = _str_replace(tmp_path, monkeypatch, CRLF_SOURCE, old_str="second\nfourth", new_str="x")

    assert result.startswith("Error: String to replace not found in file")
    assert after == CRLF_SOURCE


def test_str_replace_matches_crlf_from_a_provider_that_reads_raw(monkeypatch) -> None:
    # Remote providers already returned CRLF untranslated, so an LF old_str
    # spanning lines never matched there either.
    sandbox = MagicMock()
    sandbox.id = "remote"
    sandbox.read_file.return_value = "first\r\nsecond\r\n"
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: sandbox)
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)
    monkeypatch.setattr("deerflow.sandbox.tools.is_local_sandbox", lambda runtime: False)

    result = str_replace_tool.func(runtime=MagicMock(), description="d", path="/mnt/user-data/outputs/f.txt", old_str="first\nsecond", new_str="1\n2")

    assert result == "OK"
    sandbox.write_file.assert_called_once_with("/mnt/user-data/outputs/f.txt", "1\r\n2\r\n")


def test_read_before_write_content_changes_when_only_line_endings_change(tmp_path, monkeypatch) -> None:
    # The gate hashes read_current_file_content; a CRLF -> LF rewrite by
    # another process must invalidate the model's earlier read.
    runtime = _local_runtime(tmp_path)
    target = tmp_path / "outputs" / "file.txt"
    _use_local_sandbox(monkeypatch)

    target.write_bytes(CRLF_SOURCE)
    before = read_current_file_content(runtime, "/mnt/user-data/outputs/file.txt")
    target.write_bytes(CRLF_SOURCE.replace(b"\r\n", b"\n"))
    after = read_current_file_content(runtime, "/mnt/user-data/outputs/file.txt")

    assert before != after
