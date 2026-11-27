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

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from support.scaling import LINEAR_LIMIT, growth

import deerflow.sandbox.local.local_sandbox as local_sandbox
from deerflow.sandbox.local.local_sandbox import LocalSandbox
from deerflow.sandbox.read_file_contract import count_file_lines, slice_file_lines, split_file_lines
from deerflow.sandbox.tools import _replace_keeping_line_endings, read_current_file_content, str_replace_tool

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


@pytest.mark.parametrize(
    ("old_str", "new_str", "expected"),
    [
        # The n-th line break of new_str takes the ending of the n-th one in
        # the matched text, so an edit that keeps the line count keeps every
        # line's ending.
        pytest.param("b\nc\nd", "B\nC\nD", b"a\r\nB\r\nC\nD\r\ne\n", id="crlf-first"),
        pytest.param("c\nd\ne", "C\nD\nE", b"a\r\nb\r\nC\nD\r\nE\n", id="lf-first"),
        pytest.param("b\nc\n", "B\n", b"a\r\nB\r\nd\r\ne\n", id="ends-after-lf"),
        pytest.param("c\nd\n", "X\n", b"a\r\nb\r\nX\ne\n", id="ends-after-crlf"),
    ],
)
def test_str_replace_matches_a_ranged_read_across_mixed_endings(tmp_path, monkeypatch, old_str, new_str, expected) -> None:
    # A ranged read joins lines with "\n", so a span crossing CRLF and LF lines
    # matches neither the literal nor the all-CRLF spelling of old_str.
    result, after = _str_replace(tmp_path, monkeypatch, b"a\r\nb\r\nc\nd\r\ne\n", old_str=old_str, new_str=new_str)

    assert result == "OK"
    assert after == expected


def test_str_replace_across_mixed_endings_replaces_the_first_match_or_all(tmp_path, monkeypatch) -> None:
    mixed = b"x\r\ny\nx\ny\r\nx\r\ny\n"

    result, after = _str_replace(tmp_path, monkeypatch, mixed, old_str="x\ny\nx", new_str="Z\nZ")
    assert result == "OK"
    assert after == b"Z\r\nZ\ny\r\nx\r\ny\n"

    result, after = _str_replace(tmp_path, monkeypatch, mixed, old_str="x\ny\n", new_str="X\nY\n", replace_all=True)
    assert result == "OK"
    assert after == b"X\r\nY\nX\nY\r\nX\r\nY\n"


def test_str_replace_on_a_mixed_file_still_reports_a_missing_old_str(tmp_path, monkeypatch) -> None:
    mixed = b"a\r\nb\nc\r\n"

    result, after = _str_replace(tmp_path, monkeypatch, mixed, old_str="a\nc", new_str="x")

    assert result.startswith("Error: String to replace not found in file")
    assert after == mixed


@pytest.mark.parametrize(
    ("source", "old_str", "new_str", "replace_all", "expected"),
    [
        # A single-line edit inserts lines in the ending of the line it is on.
        pytest.param(b"a\r\nb\nc\r\n", "b", "b\nB", False, b"a\r\nb\nB\nc\r\n", id="inserted-lines-follow-an-lf-line"),
        pytest.param(b"a\nb\r\nc\n", "b", "b\nB", False, b"a\nb\r\nB\r\nc\n", id="inserted-lines-follow-a-crlf-line"),
        # The last line has no ending of its own and takes the one before it.
        pytest.param(b"a\nb\r\nc", "c", "c\nd", False, b"a\nb\r\nc\r\nd", id="unterminated-last-line"),
        # An old_str that starts at a line break takes the whole CRLF.
        pytest.param(b"a\r\nb\nc", "\nb", "\nB", False, b"a\r\nB\nc", id="starts-at-a-crlf"),
        # A match never ends between a "\r" and its "\n".
        pytest.param(b"a\r\nb\nc\r\n", "a\r", "x", False, None, id="never-splits-a-crlf"),
        # A bare "\r" is ordinary text, in old_str and in the file.
        pytest.param(b"one\rtwo\r\nthree\n", "one\rtwo\nthree", "1\n3", False, b"1\r\n3\n", id="bare-cr-is-text"),
        # Overlapping candidates: matches do not overlap, as with str.replace.
        pytest.param(b"a\r\na\na\r\na\n", "a\na", "b", True, b"b\nb\n", id="no-overlap"),
        # "\r\n" in old_str comes from a full read and matches only a CRLF.
        pytest.param(b"x\ny\nx\r\ny\n", "x\r\ny", "Q", False, b"x\ny\nQ\n", id="crlf-in-old-str-matches-only-crlf"),
        pytest.param(b"a\r\nb\nc\r\n", "a\r\nb\r\nc", "x", False, None, id="crlf-in-old-str-never-matches-lf"),
        # A snippet with CRLF matches as written or with every line break
        # spelled CRLF, not with its endings mixed in another way.
        pytest.param(b"a\r\nb\r\nc\r\nd\n", "a\r\nb\nc", "A\nB\nC", False, b"A\r\nB\r\nC\r\nd\n", id="lf-in-old-str-matches-crlf"),
        pytest.param(b"a\r\nb\r\nc\nd\n", "a\r\nb\nc\nd", "x", False, None, id="mixed-old-str-matches-no-other-mix"),
        pytest.param(b"a\r\nb\nc\r\nd\n", "b\nc\r\nd", "x", False, b"a\r\nx\n", id="mixed-old-str-matches-as-written"),
        # A snippet cut from a full read just after a "\r" starts with the LF of a CRLF.
        pytest.param(b"a\r\n\r\nb\r\n\n", "\n\r\nb\r\n\n", "\nX\n", False, b"a\r\nX\r\n", id="leading-lf-of-a-crlf"),
        # Each line break of new_str keeps the ending of the one it replaces.
        pytest.param(b"a\r\nb\nc\nd\n", "\nb\n", "\nB\n", False, b"a\r\nB\nc\nd\n", id="keeps-each-line-ending"),
        pytest.param(b"a\r\nb\nc\n", "a\nb\n", "a\nx\ny\nb\n", False, b"a\r\nx\ny\nb\nc\n", id="extra-lines-take-the-last-ending"),
        # Without replace_all only the first match in file order changes.
        pytest.param(b"x\ny\r\nz\nx\r\ny\r\nz\r\n", "x\ny\nz", "Q", False, b"Q\nx\r\ny\r\nz\r\n", id="first-of-two-spellings"),
    ],
)
def test_replace_keeping_line_endings_rules(source, old_str, new_str, replace_all, expected) -> None:
    result = _replace_keeping_line_endings(source.decode(), old_str, new_str, replace_all)

    assert result == (None if expected is None else expected.decode())


def test_replace_keeping_line_endings_treats_an_empty_old_str_as_a_no_op() -> None:
    # str_replace returns "OK" without writing; the syntax pre-check must see
    # the file unchanged, not new_str inserted at the start.
    assert _replace_keeping_line_endings("a\r\nb\n", "", "x", False) == "a\r\nb\n"
    assert _replace_keeping_line_endings("a\nb\n", "", "x", True) == "a\nb\n"


def test_a_line_with_several_crs_before_its_lf_matches_only_as_stored() -> None:
    # A ranged read drops every trailing "\r", so "a\r\r\nb" reads as "a\nb"
    # there. Read with CRLF as LF it is "a\r\nb": only the stored spelling
    # matches, and the ranged-read one is reported missing, not misplaced.
    content = "a\r\r\nb\r\n"

    assert _replace_keeping_line_endings(content, "a\r\r\nb", "x", False) == "x\r\n"
    assert _replace_keeping_line_endings(content, "a\nb", "x", False) is None


# The matcher against a reference model. Files and snippets are drawn from
# "a", "b" and the three line-ending pieces, so endings repeat and mix densely.
_PIECES = ("a", "b", "\r\n", "\n", "\r")


def _main_replace(content: str, old_str: str, new_str: str, replace_all: bool) -> str | None:
    """str_replace's matching before mixed-ending support, for files with one ending."""

    def to_crlf(text: str) -> str:
        return text.replace("\r\n", "\n").replace("\n", "\r\n")

    if "\r\n" in content:
        crlf_old = to_crlf(old_str)
        if content.count("\r\n") == content.count("\n") or (old_str not in content and crlf_old in content):
            old_str, new_str = crlf_old, to_crlf(new_str)
    if not content or old_str not in content:
        return None
    return content.replace(old_str, new_str) if replace_all else content.replace(old_str, new_str, 1)


def _reference_replace(content: str, old_str: str, new_str: str, replace_all: bool) -> str | None:
    """The documented rule, spelled out on units: a CRLF in the file or in old_str is one unit."""
    if not old_str:
        return content
    if "\r\n" not in content:
        return _main_replace(content, old_str, new_str, replace_all)
    units: list[str] = []
    i = 0
    while i < len(content):
        units.append("\r\n" if content.startswith("\r\n", i) else content[i])
        i += len(units[-1])
    needle: list[str] = []
    i = 0
    while i < len(old_str):
        needle.append("\r\n" if old_str.startswith("\r\n", i) else old_str[i])
        i += len(needle[-1])
    new_lines = new_str.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    i = copied = 0
    found = False

    def matches(window: list[str]) -> bool:
        if "\r\n" not in needle:
            # A snippet without CRLF: "\n" matches either ending, anything else itself.
            return all(want == unit or (want == "\n" and unit == "\r\n") for want, unit in zip(needle, window))
        # A snippet with CRLF matches as written, its first "\n" also as a
        # CRLF, or with every line break spelled CRLF.
        as_written = window[1:] == needle[1:] and (window[0] == needle[0] or needle[0] == "\n" == window[0][-1])
        return as_written or window == ["\r\n" if want == "\n" else want for want in needle]

    while i + len(needle) <= len(units):
        if not matches(units[i : i + len(needle)]):
            i += 1
            continue
        found = True
        endings = [unit for unit in units[i : i + len(needle)] if unit in ("\n", "\r\n")]
        if not endings:
            endings = [unit for unit in units[i:] if unit in ("\n", "\r\n")][:1] or [unit for unit in units[:i] if unit in ("\n", "\r\n")][-1:]
        spelled = new_lines[0] + "".join(endings[min(n, len(endings) - 1)] + line for n, line in enumerate(new_lines[1:]))
        out += units[copied:i] + [spelled]
        i = copied = i + len(needle)
        if not replace_all:
            break
    return "".join(out + units[copied:]) if found else None


@st.composite
def _replace_cases(draw, pieces=_PIECES):
    content = "".join(draw(st.lists(st.sampled_from(pieces), max_size=24)))
    lines = split_file_lines(content)
    source = draw(st.sampled_from(["ranged-read", "full-read", "typed"]))
    if source == "ranged-read" and lines:
        first = draw(st.integers(0, len(lines) - 1))
        last = draw(st.integers(first, len(lines) - 1))
        text = "\n".join(lines[first : last + 1])
    elif source == "full-read":
        text = content
    else:
        text = "".join(draw(st.lists(st.sampled_from(_PIECES), min_size=1, max_size=6)))
    start = draw(st.integers(0, len(text)))
    old_str = text[start : draw(st.integers(start, len(text)))]
    new_str = "".join(draw(st.lists(st.sampled_from(("X", "\n", "\r\n", "\r")), max_size=4)))
    return content, old_str, new_str, draw(st.booleans())


@settings(max_examples=3000, deadline=None)
@given(_replace_cases())
def test_replace_keeping_line_endings_matches_the_reference_model(case) -> None:
    content, old_str, new_str, replace_all = case

    assert _replace_keeping_line_endings(content, old_str, new_str, replace_all) == _reference_replace(content, old_str, new_str, replace_all)


@settings(max_examples=1500, deadline=None)
@given(_replace_cases())
def test_an_edit_that_keeps_the_lines_keeps_every_line_ending(case) -> None:
    # Upper-casing the matched text keeps its line count, so the file may
    # change only in case: every line ending stays as stored.
    content, old_str, _, replace_all = case
    result = _replace_keeping_line_endings(content, old_str, old_str.upper(), replace_all)

    assume(result is not None)
    assert result.lower() == content


@settings(max_examples=1500, deadline=None)
@given(_replace_cases(), st.sampled_from(["\n", "\r\n"]), st.sampled_from(["\n", "\r\n"]))
def test_replace_keeping_line_endings_is_unchanged_on_files_with_one_ending(case, ending, old_ending) -> None:
    content, old_str, new_str, replace_all = case
    content = content.replace("\r\n", "\n").replace("\r", "").replace("\n", ending)
    old_str = old_str.replace("\r\n", "\n").replace("\r", "").replace("\n", old_ending)
    # str_replace returns before matching an empty old_str.
    assume(old_str)

    assert _replace_keeping_line_endings(content, old_str, new_str, replace_all) == _main_replace(content, old_str, new_str, replace_all)


@settings(max_examples=1500, deadline=None)
@given(_replace_cases(), st.data())
def test_a_ranged_read_snippet_is_never_reported_missing(case, data) -> None:
    # Ranged reads drop every trailing "\r"; see the several-CRs case above.
    content, _, new_str, replace_all = case
    assume("\r\r\n" not in content)
    lines = split_file_lines(content)
    assume(lines)
    first = data.draw(st.integers(0, len(lines) - 1))
    last = data.draw(st.integers(first, len(lines) - 1))
    snippet = "\n".join(lines[first : last + 1])
    assume(snippet)

    assert _replace_keeping_line_endings(content, snippet, new_str, replace_all) is not None


@settings(max_examples=1500, deadline=None)
@given(_replace_cases(), st.data())
def test_a_full_read_snippet_is_found_unless_it_splits_a_crlf(case, data) -> None:
    content, _, new_str, replace_all = case
    start = data.draw(st.integers(0, len(content)))
    stop = data.draw(st.integers(start, len(content)))
    snippet = content[start:stop]
    assume(snippet and not (snippet.endswith("\r") and content.startswith("\n", stop)))

    assert _replace_keeping_line_endings(content, snippet, new_str, replace_all) is not None


@settings(max_examples=150, deadline=None)
@given(_replace_cases())
def test_str_replace_writes_what_the_reference_model_predicts(tmp_path_factory, case) -> None:
    content, old_str, new_str, replace_all = case
    assume(old_str)
    tmp_path = tmp_path_factory.mktemp("prop")
    expected = _reference_replace(content, old_str, new_str, replace_all)

    with pytest.MonkeyPatch.context() as monkeypatch:
        result, after = _str_replace(tmp_path, monkeypatch, content.encode(), old_str=old_str, new_str=new_str, replace_all=replace_all)

    if expected is None:
        assert result.startswith("Error: String to replace not found in file")
        assert after == content.encode()
    else:
        assert result == "OK"
        assert after == expected.encode()


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


@pytest.mark.parametrize(
    ("pattern", "literal", "expected"),
    [
        (r"\s$", False, [(2, "trailing ")]),
        (r"[^a-z]$", False, [(2, "trailing ")]),
        (r"\n", False, []),
        pytest.param("\n", True, [], id="literal-newline"),
    ],
)
def test_grep_does_not_match_the_line_terminator(tmp_path, pattern, literal, expected) -> None:
    # LocalSandbox excludes LF and CRLF terminators from matching, so
    # a trailing-whitespace search only matches whitespace in the line text.
    path = tmp_path / "ws.txt"
    path.write_bytes(b"clean\ntrailing \r\nalso clean\r\nlast clean")

    matches, _ = LocalSandbox("t").grep(str(path), pattern, literal=literal)

    assert [(match.line_number, match.line) for match in matches] == expected


# Each scan must stay linear on input built to defeat it. A run of "\r"
# followed by text made the old ranged-read regex retry from every "\r" of
# the run; a CRLF snippet over LF lines made the matcher check every
# overlapping candidate in full.
@pytest.mark.parametrize(
    ("make", "size"),
    [
        pytest.param(lambda n: ("a\n" + "\r" * n + "x\n", 1, 2), 2000, id="cr-run-then-text"),
        pytest.param(lambda n: ("\r" * n + "\nx\n", 1, 2), 2000, id="cr-run-then-lf"),
        pytest.param(lambda n: ("x\r\r\r" * n + "\n", 1, 1), 2000, id="cr-runs-inside-a-line"),
        pytest.param(lambda n: ("a\r\r\n" * n, 1, None), 2000, id="lines-ending-in-several-crs"),
        pytest.param(lambda n: ("a\r\n" * n, 2, None), 2000, id="crlf-lines"),
    ],
)
def test_a_ranged_read_is_linear_in_the_file(make, size) -> None:
    assert growth(lambda n: slice_file_lines(*make(n)), size) < LINEAR_LIMIT


@pytest.mark.parametrize(
    ("make", "size"),
    [
        # Both the file and the snippet grow, so a check of every overlapping
        # candidate in full grows with their product.
        pytest.param(lambda n: ("a\n" * 64 * n + "b\r\n", "a\r\n" + "a\n" * n, "x", False), 20, id="crlf-snippet-over-lf-lines"),
        pytest.param(lambda n: ("\r" + "\na\nb\r" * 50 * n + "\n", "\na\nb\r" * n, "x", False), 20, id="leading-lf-on-every-crlf"),
        pytest.param(lambda n: ("x\r\n" * 50 * n + "y\n", "x\r\n" * n + "x\r", "x", False), 20, id="trailing-cr-before-every-lf"),
        pytest.param(lambda n: ("\r" * 100 * n + "\r\nq\n", "\r" * n + "x\n", "x", False), 20, id="ranged-snippet-over-a-cr-run"),
        pytest.param(lambda n: ("a\r\nb\n" * 50 * n, "a\nb", "A\nB", True), 20, id="replace-all-across-mixed-lines"),
        pytest.param(lambda n: ("a\r\nb\n" * 50 * n, "a\r\nb\n", "A\nB\n", True), 20, id="replace-all-of-a-mixed-snippet"),
        pytest.param(lambda n: ("ab\r\n" * 50 * n + "c\n", "b", "b\nc", True), 20, id="lines-inserted-after-many-matches"),
    ],
)
def test_str_replace_matching_is_linear_in_the_file_and_the_snippet(make, size) -> None:
    assert growth(lambda n: _replace_keeping_line_endings(*make(n)), size) < LINEAR_LIMIT
