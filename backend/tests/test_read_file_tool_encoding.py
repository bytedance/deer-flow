"""``read_file`` text-decoding contract.

``LocalSandbox.read_file`` decoded with a bare ``utf-8`` codec, so two kinds of
ordinary text file reached the model wrong: a UTF-8 file saved with a BOM kept a
stray ``\\ufeff`` at offset 0, and a BOM-marked UTF-16 file raised
``UnicodeDecodeError`` and was reported as "binary" — steering the model to
``view_image``/pandas for what is plain text.

The workspace change scanner already decoded both correctly (#3966). These tests
pin the shared rule that both readers now use, so the two cannot drift apart
again, and keep the genuinely-binary and legacy-encoding paths distinguishable.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from deerflow.sandbox.local.local_sandbox import LocalSandbox, PathMapping
from deerflow.sandbox.tools import grep_tool, read_file_tool
from deerflow.utils.text_decoding import decode_text_bytes, detect_text_encoding

WORKSPACE_VIRTUAL = "/mnt/user-data/workspace"


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


def _read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, filename: str, raw: bytes, **kwargs) -> str:
    runtime = _local_runtime(tmp_path)
    (tmp_path / "workspace" / filename).write_bytes(raw)
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox("t1"))
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)
    return read_file_tool.func(runtime=runtime, description="read fixture", path=f"{WORKSPACE_VIRTUAL}/{filename}", **kwargs)


# ---------------------------------------------------------------------------
# The shared decoding rule
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("prefix", "expected"),
    [
        (b"", "utf-8-sig"),
        (b"pl", "utf-8-sig"),
        (b"\xef\xbb\xbf", "utf-8-sig"),  # UTF-8 BOM: utf-8-sig strips it, so no special case
        (b"\xff\xfe", "utf-16"),
        (b"\xfe\xff", "utf-16"),
    ],
)
def test_detect_text_encoding_reads_only_the_bom(prefix: bytes, expected: str) -> None:
    assert detect_text_encoding(prefix) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b"plain", "plain"),
        ("bom".encode("utf-8-sig"), "bom"),
        ("wide".encode("utf-16"), "wide"),
        ("한글".encode("cp949"), None),  # legacy encodings are never guessed
        (b"PK\x03\x04\x14\x00\x00\x00\x08\x00\x82\x6a\xb1\x55", None),
    ],
)
def test_decode_text_bytes_accepts_only_utf8_and_bom_marked_utf16(raw: bytes, expected: str | None) -> None:
    assert decode_text_bytes(raw) == expected


def test_bomless_utf16_is_not_recognized_as_utf16() -> None:
    """Pins a limit of the rule that predates it and is deliberately kept.

    Without a BOM there is nothing to distinguish UTF-16 from bytes that merely
    look like it, and ASCII-range UTF-16-LE *is* valid UTF-8 — the NUL padding
    decodes to U+0000 rather than raising. So the content comes back NUL-riddled
    instead of either decoding correctly or being rejected. The workspace scanner
    never reaches this case because ``_looks_binary`` rejects embedded NULs first;
    the read path has no such pre-check, and adding one would reject files that
    read (badly) today.
    """
    assert decode_text_bytes("wide".encode("utf-16-le")) == "w\x00i\x00d\x00e\x00"


# ---------------------------------------------------------------------------
# UTF-8 BOM
# ---------------------------------------------------------------------------


def test_utf8_bom_is_stripped_from_full_read(tmp_path, monkeypatch) -> None:
    result = _read(tmp_path, monkeypatch, "bom.md", "# Title\nbody\n".encode("utf-8-sig"))

    assert not result.startswith("﻿"), repr(result)
    assert result == "# Title\nbody\n"


def test_utf8_bom_is_stripped_from_ranged_read(tmp_path, monkeypatch) -> None:
    # The BOM sits on line 1, so a range starting there is what would leak it.
    result = _read(tmp_path, monkeypatch, "bom.md", "# Title\nbody\ntail\n".encode("utf-8-sig"), start_line=1, end_line=2)

    assert "﻿" not in result, repr(result)
    assert result == "# Title\nbody"


# ---------------------------------------------------------------------------
# BOM-marked UTF-16
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-le", "utf-16-be"])
def test_bom_marked_utf16_reads_as_text(tmp_path, monkeypatch, encoding: str) -> None:
    raw = "# Title\nbody\n".encode(encoding)
    if encoding != "utf-16":
        # utf-16-le / utf-16-be do not emit a BOM; prepend the matching one so the
        # file declares its byte order the way a real editor would.
        raw = (b"\xff\xfe" if encoding.endswith("le") else b"\xfe\xff") + raw

    result = _read(tmp_path, monkeypatch, "wide.md", raw)

    assert "binary" not in result.lower(), result
    assert result == "# Title\nbody\n"


def test_bom_marked_utf16_supports_ranged_read(tmp_path, monkeypatch) -> None:
    result = _read(tmp_path, monkeypatch, "wide.md", "one\ntwo\nthree\n".encode("utf-16"), start_line=2, end_line=3)

    assert result == "two\nthree"


# ---------------------------------------------------------------------------
# Unchanged paths
# ---------------------------------------------------------------------------


def test_plain_utf8_is_unaffected(tmp_path, monkeypatch) -> None:
    result = _read(tmp_path, monkeypatch, "notes.txt", "hello 你好 안녕\nsecond line\n".encode())

    assert result == "hello 你好 안녕\nsecond line\n"


def test_binary_file_still_reports_binary(tmp_path, monkeypatch) -> None:
    # .xlsx is a zip container: PK header plus a byte no UTF-8 decoder accepts.
    result = _read(tmp_path, monkeypatch, "data.xlsx", b"PK\x03\x04\x14\x00\x00\x00\x08\x00\x82\x6a\xb1\x55")

    assert "Unexpected error" not in result, result
    assert "binary" in result.lower(), result
    assert "bash" in result.lower(), result


def test_legacy_encoding_error_names_the_encoding_cause(tmp_path, monkeypatch) -> None:
    # CP949 text is not binary, but it cannot be decoded under this rule either.
    # The error must say so, or the model retries as if the file were a spreadsheet.
    result = _read(tmp_path, monkeypatch, "legacy.txt", "안녕하세요\n한글 파일\n".encode("cp949"))

    assert "encoding" in result.lower(), result
    assert "cp949" in result.lower(), result


# ---------------------------------------------------------------------------
# Drift guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        b"plain\n",
        "bom\n".encode("utf-8-sig"),
        "wide\n".encode("utf-16"),
        "한글\n".encode("cp949"),
        b"PK\x03\x04\x14\x00\x00\x00\x08\x00\x82\x6a\xb1\x55",
    ],
)
def test_streaming_read_matches_the_buffered_rule(tmp_path, monkeypatch, raw: bytes) -> None:
    """The tool streams through ``open(encoding=...)``; the rule decodes a buffer.

    Those are separate code paths, and the workspace change panel reads through the
    buffered one. If they ever disagree, a file the panel renders is reported to the
    agent as unreadable — the drift #3966 fixed on the scanner side alone.
    """
    tool_result = _read(tmp_path, monkeypatch, "sample.md", raw)
    tool_says_text = "as text" not in tool_result

    assert tool_says_text is (decode_text_bytes(raw) is not None), tool_result


# ---------------------------------------------------------------------------
# Round-trip: what read_file can now open, the write path must not corrupt
# ---------------------------------------------------------------------------


def test_append_preserves_utf16_so_the_file_stays_readable(tmp_path) -> None:
    """Appending UTF-8 onto UTF-16 would leave a file no decoder can read back.

    Reachable only because read_file accepts BOM-marked UTF-16: before that, the
    agent could not read such a file and had no reason to append to it.
    """
    workspace = tmp_path / "data"
    workspace.mkdir()
    target = workspace / "wide.md"
    target.write_bytes("first\n".encode("utf-16"))

    sandbox = LocalSandbox("t1", [PathMapping(container_path="/mnt/data", local_path=str(workspace))])
    sandbox.write_file("/mnt/data/wide.md", "second\n", append=True)

    assert sandbox.read_file("/mnt/data/wide.md") == "first\nsecond\n"
    # Exactly one BOM: the utf-16 codec would have emitted a second one mid-file.
    assert target.read_bytes().count(b"\xff\xfe") == 1


def test_append_preserves_utf8_bom(tmp_path) -> None:
    workspace = tmp_path / "data"
    workspace.mkdir()
    target = workspace / "bom.md"
    target.write_bytes("first\n".encode("utf-8-sig"))

    sandbox = LocalSandbox("t1", [PathMapping(container_path="/mnt/data", local_path=str(workspace))])
    sandbox.write_file("/mnt/data/bom.md", "second\n", append=True)

    assert sandbox.read_file("/mnt/data/bom.md") == "first\nsecond\n"
    assert target.read_bytes().startswith(b"\xef\xbb\xbf")


def test_append_to_a_new_file_is_utf8(tmp_path) -> None:
    workspace = tmp_path / "data"
    workspace.mkdir()

    sandbox = LocalSandbox("t1", [PathMapping(container_path="/mnt/data", local_path=str(workspace))])
    sandbox.write_file("/mnt/data/fresh.md", "안녕\n", append=True)

    assert (workspace / "fresh.md").read_bytes() == "안녕\n".encode()


def test_overwrite_still_writes_utf8(tmp_path) -> None:
    """A full rewrite replaces the content, so agent-authored UTF-8 is the contract."""
    workspace = tmp_path / "data"
    workspace.mkdir()
    (workspace / "wide.md").write_bytes("first\n".encode("utf-16"))

    sandbox = LocalSandbox("t1", [PathMapping(container_path="/mnt/data", local_path=str(workspace))])
    sandbox.write_file("/mnt/data/wide.md", "replaced\n")

    assert (workspace / "wide.md").read_bytes() == b"replaced\n"


# ---------------------------------------------------------------------------
# grep: the third reader of the same rule
# ---------------------------------------------------------------------------


def test_grep_finds_matches_in_bom_marked_utf16(tmp_path, monkeypatch) -> None:
    """UTF-16 is half NUL bytes, so the plain NUL test used to skip it silently.

    A file read_file opens happily returning "no matches" is the same drift as the
    binary misreport, only shaped like an empty result instead of an error.
    """
    runtime = _local_runtime(tmp_path)
    (tmp_path / "workspace" / "wide.md").write_bytes("needle here\nsecond\n".encode("utf-16"))
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox("t1"))
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)

    result = grep_tool.func(runtime=runtime, description="find needle", pattern="needle", path=WORKSPACE_VIRTUAL)

    assert "wide.md" in result, result
    assert "needle here" in result, result


def test_grep_still_skips_real_binary(tmp_path, monkeypatch) -> None:
    runtime = _local_runtime(tmp_path)
    (tmp_path / "workspace" / "blob.bin").write_bytes(b"needle\x00\x00\x01\x02binary")
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox("t1"))
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)

    result = grep_tool.func(runtime=runtime, description="find needle", pattern="needle", path=WORKSPACE_VIRTUAL)

    assert "blob.bin" not in result, result
