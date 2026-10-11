"""Ranged read_file numbers lines the same way on every sandbox provider.

``LocalSandbox.read_file``, ``count_file_lines`` and read_file's truncation
marker end lines only at ``"\\n"``. The remote providers slice the content they
fetched themselves, so they must use the same rule: ``str.splitlines()`` would
also end lines at a bare ``"\\r"``, ``\\f``, ``\\x85`` or ``\\u2028``, and a
continuation such as ``start_line=3`` would then return an earlier part of the
file than the one the marker pointed at.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from deerflow.sandbox.local.local_sandbox import LocalSandbox
from deerflow.sandbox.read_file_contract import READ_FILE_TRUNCATION_PREFIX, count_file_lines
from deerflow.sandbox.tools import _truncate_read_file_output

# Four lines by the "\n"-only rule; splitlines() sees eight.
_CONTENT = "progress 10%\rprogress 100%\npage one\fpage two\nhead\u2028tail\r\nnext\x85line\n"
_RANGES = [(None, None), (2, 3), (3, None), (None, 2), (4, 4), (5, None)]
REMOTE_PROVIDERS = ("e2b", "boxlite", "tenki", "opensandbox")
_CONTINUE = re.compile(r"Continue with start_line=(\d+)")


def _remote_sandbox(name: str, monkeypatch: pytest.MonkeyPatch, remote_files: dict[str, Path]):
    """Map POSIX sandbox paths to native host files in the fake transport."""

    def read_text(path: str) -> str:
        return remote_files[path].read_bytes().decode("utf-8")

    if name == "e2b":
        from deerflow.community.e2b_sandbox.e2b_sandbox import E2BSandbox

        return E2BSandbox("line-contract", SimpleNamespace(files=SimpleNamespace(read=lambda path, **_kwargs: read_text(path))))
    if name == "boxlite":
        from deerflow.community.boxlite.box import BoxliteBox

        sandbox = BoxliteBox("line-contract", SimpleNamespace(), run=None)
        monkeypatch.setattr(sandbox, "_exec", lambda *argv: SimpleNamespace(exit_code=0, stdout=read_text(argv[-1]), stderr=""))
        return sandbox
    if name == "tenki":
        from deerflow.community.tenki.sandbox import TenkiSandbox

        sandbox = TenkiSandbox("line-contract", SimpleNamespace())
        monkeypatch.setattr(sandbox, "_fs_op", lambda op: op(SimpleNamespace(read_text=read_text)))
        return sandbox
    if name == "opensandbox":
        from deerflow.community.opensandbox.sandbox import OpenSandboxSandbox

        sandbox = OpenSandboxSandbox("line-contract", SimpleNamespace(), run_command_opts_cls=SimpleNamespace)
        monkeypatch.setattr(sandbox, "_file_op", lambda operation: operation(SimpleNamespace(read_file=lambda path, **_kwargs: read_text(path))))
        return sandbox
    raise AssertionError(f"Unregistered provider: {name}")


@pytest.mark.parametrize("provider", REMOTE_PROVIDERS)
def test_remote_ranged_read_matches_local_sandbox_line_numbers(provider, tmp_path, monkeypatch):
    path = tmp_path / "mixed-separators.log"
    path.write_bytes(_CONTENT.encode("utf-8"))
    local = LocalSandbox("line-contract")
    remote_path = f"/workspace/{path.name}"
    remote = _remote_sandbox(provider, monkeypatch, {remote_path: path})

    for start_line, end_line in _RANGES:
        expected = local.read_file(str(path), start_line=start_line, end_line=end_line)
        assert remote.read_file(remote_path, start_line=start_line, end_line=end_line) == expected, (start_line, end_line)

    # The line read_file's truncation marker would name after line 2.
    assert remote.read_file(remote_path, start_line=3, end_line=3) == "head\u2028tail"


@pytest.mark.parametrize("provider", REMOTE_PROVIDERS)
def test_remote_read_continues_at_the_line_a_truncation_marker_names(provider, tmp_path, monkeypatch):
    """A saved progress log: every line carries a bare carriage return."""
    path = tmp_path / "progress.log"
    content = "".join(f"step {i:03d} 0%\rstep {i:03d} 100%\n" for i in range(1, 201))
    path.write_bytes(content.encode("utf-8"))
    remote_path = f"/workspace/{path.name}"
    remote = _remote_sandbox(provider, monkeypatch, {remote_path: path})

    truncated = _truncate_read_file_output(remote.read_file(remote_path), 1000)
    kept = truncated[: truncated.index(READ_FILE_TRUNCATION_PREFIX)]
    start_line = int(_CONTINUE.search(truncated).group(1))
    first_unread = content[len(kept) :].split("\n", 1)[0]

    assert remote.read_file(remote_path, start_line=start_line, end_line=start_line) == first_unread


@pytest.mark.parametrize(
    "content",
    ["", "\n", "one", "one\n", "one\n\n", "a\rb\n", "a\r\nb", "a\fb\vc\x1cd\x85e\u2028f\u2029g\n", "trailing cr\r"],
)
def test_split_file_lines_agrees_with_count_file_lines(content):
    from deerflow.sandbox.read_file_contract import split_file_lines

    assert len(split_file_lines(content)) == count_file_lines(content)
