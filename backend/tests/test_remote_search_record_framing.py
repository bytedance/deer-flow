"""Remote ``grep``/``glob`` record framing on BoxLite, OpenSandbox and Tenki.

``parse_remote_search_output`` hands callers LF-joined records and documents the
rule: split on ``"\\n"`` only, because ``str.splitlines()`` also breaks on a bare
``"\\r"``, ``\\f``, ``\\v``, ``\\x1c``-``\\x1e``, ``\\x85``, ``\\u2028`` and
``\\u2029`` -- every one of which is legal inside a Linux filename and inside
matched text. E2B was moved onto that rule in #6573; these three providers kept
the ``splitlines()`` framing, so a file such as ``notes\\x0bdraft.txt`` was
reported as two unrelated paths (one of them nonexistent) and a matched line
containing U+2028 came back truncated at that character.

The canned-output tests pin the framing directly and run on any host. The
real-shell tests build the fixture through a POSIX shell (a Windows host cannot
create ``\\x0b`` in a name at all) and are skipped where the shell tools are
missing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from deerflow.community.boxlite.box import BoxliteBox
from deerflow.community.opensandbox.sandbox import OpenSandboxSandbox
from deerflow.community.tenki.sandbox import TenkiSandbox

_ROOT = "/mnt/user-data/workspace"

# Characters that end a line for ``str.splitlines()`` but are legal in a Linux
# filename and inside grep output.
NON_LF_SEPARATORS = [
    pytest.param("\r", id="carriage-return"),
    pytest.param("\v", id="vertical-tab"),
    pytest.param("\f", id="form-feed"),
    pytest.param("\x1c", id="file-separator"),
    pytest.param("\x1d", id="group-separator"),
    pytest.param("\x1e", id="record-separator"),
    pytest.param("\x85", id="next-line"),
    pytest.param("\u2028", id="line-separator"),
    pytest.param("\u2029", id="paragraph-separator"),
]

_RS_POSIX = pytest.mark.skipif(
    os.name == "nt" or any(shutil.which(tool) is None for tool in ("sh", "head", "grep", "find")),
    reason="POSIX sh, head, grep and find required",
)


def _find_stdout(*entries: str) -> str:
    """A ``find`` result in the framing ``parse_remote_search_output`` expects."""
    return "".join(f"{entry}\n" for entry in entries) + "\n__DF_SEARCH_STATUS__:0\n"


def _grep_stdout(*records: str) -> str:
    return "".join(f"{record}\n" for record in records) + "\n__DF_SEARCH_STATUS__:0\n"


class _BoxliteTransport:
    """BoxLite's ``SimpleBox`` seam returning one canned result."""

    def __init__(self, stdout: str) -> None:
        self._stdout = stdout

    async def exec(self, *argv, env=None, timeout=None):
        return SimpleNamespace(stdout=self._stdout, stderr="", exit_code=0)


def _boxlite(stdout: str) -> BoxliteBox:
    """BoxLite with its shell seam replaced, as the provider's own tests do.

    Patching ``_sh`` (rather than injecting a fake ``SimpleBox``) keeps the
    production command string, the status marker and the record framing on the
    real path; only the transport is canned.
    """

    def sh(script: str, env=None, timeout=None):
        return SimpleNamespace(stdout=stdout, stderr="", exit_code=0)

    box = BoxliteBox("box-id", box=_BoxliteTransport(stdout), run=lambda coro, timeout=None: coro)
    box._sh = sh
    return box


class _OpenSandboxRemote:
    """OpenSandbox's remote handle; the command transport is patched below."""

    def __init__(self) -> None:
        self.id = "remote"


class _OpenSandboxEvent:
    def __init__(self, text: str) -> None:
        self.text = text


class _OpenSandboxLogs:
    def __init__(self, stdout: str) -> None:
        self.stdout = [_OpenSandboxEvent(stdout)]
        self.stderr: list[_OpenSandboxEvent] = []


class _OpenSandboxExecution:
    """The ``logs.stdout[*].text`` shape ``execution_stdout`` reads."""

    def __init__(self, stdout: str) -> None:
        self.exit_code = 0
        self.logs = _OpenSandboxLogs(stdout)
        self.result: list[_OpenSandboxEvent] = []
        self.error = None


def _opensandbox(stdout: str) -> OpenSandboxSandbox:
    box = OpenSandboxSandbox("sandbox-id", _OpenSandboxRemote(), run_command_opts_cls=lambda **kwargs: None)
    box._run = lambda command, env=None, timeout=None: _OpenSandboxExecution(stdout)
    return box


class _TenkiSandbox:
    """Tenki's live-sandbox handle; ``_sh`` is patched below."""

    def __init__(self) -> None:
        self.id = "tenki-remote"


# Tenki rewrites the DeerFlow virtual prefix into its writable home dir, so its
# search output (and the paths it reports back through ``_virtual_path``) carry
# the home-dir form rather than ``/mnt/user-data``.
_TENKI_HOME = "/home/tenki"


def _tenki(stdout: str) -> TenkiSandbox:
    box = TenkiSandbox("sb", _TenkiSandbox(), home_dir=_TENKI_HOME)

    def sh(script, env=None, timeout=None):
        return SimpleNamespace(stdout=stdout, stderr="", stdout_text=stdout, stderr_text="", exit_code=0)

    box._sh = sh
    return box


_PROVIDER_FACTORIES = [
    pytest.param(_boxlite, id="boxlite"),
    pytest.param(_opensandbox, id="opensandbox"),
    pytest.param(_tenki, id="tenki"),
]


def _search_root(factory) -> str:
    """The sandbox-side root each provider actually searches.

    Tenki rewrites the DeerFlow virtual prefix into its writable home dir, so a
    search for ``/mnt/user-data/workspace`` reaches ``/home/tenki/workspace``.
    """
    return f"{_TENKI_HOME}/workspace" if factory is _tenki else _ROOT


def _reported_path(name: str) -> str:
    """The path every provider reports back for ``name``.

    Tenki reverses its home-dir rewrite through ``_virtual_path``, and the other
    two report the DeerFlow path verbatim, so all three answer under the prefix.
    """
    return f"{_ROOT}/{name}"


@pytest.mark.parametrize("factory", _PROVIDER_FACTORIES)
@pytest.mark.parametrize("separator", NON_LF_SEPARATORS)
def test_glob_keeps_non_lf_separators_in_paths(factory, separator: str) -> None:
    """A path holding a non-LF separator must come back as one intact entry."""
    root = _search_root(factory)
    box = factory(_find_stdout(f"{root}/notes{separator}draft.txt", f"{root}/plain.txt"))

    found, truncated = box.glob(_ROOT, "**/*.txt")

    assert found == [_reported_path(f"notes{separator}draft.txt"), _reported_path("plain.txt")]
    assert truncated is False


@pytest.mark.parametrize("factory", _PROVIDER_FACTORIES)
@pytest.mark.parametrize("separator", NON_LF_SEPARATORS)
def test_grep_keeps_non_lf_separators_in_paths(factory, separator: str) -> None:
    """A matched file whose path holds a non-LF separator is reported intact."""
    root = _search_root(factory)
    box = factory(_grep_stdout(f"{root}/notes{separator}draft.txt:1:needle here"))

    matches, truncated = box.grep(_ROOT, "needle")

    expected = _reported_path(f"notes{separator}draft.txt")
    assert [(match.path, match.line_number, match.line) for match in matches] == [(expected, 1, "needle here")]
    assert truncated is False


@pytest.mark.parametrize("factory", _PROVIDER_FACTORIES)
@pytest.mark.parametrize("separator", NON_LF_SEPARATORS)
def test_grep_keeps_non_lf_separators_in_matched_text(factory, separator: str) -> None:
    """A matched line must not be cut at a separator that is legal in content."""
    line = f"needle: before{separator}after"
    box = factory(_grep_stdout(f"{_search_root(factory)}/plain.txt:2:{line}"))

    matches, _truncated = box.grep(_ROOT, "needle")

    assert len(matches) == 1
    assert matches[0].line == line


@pytest.mark.parametrize("factory", _PROVIDER_FACTORIES)
def test_glob_still_reads_plain_lf_records(factory) -> None:
    """No regression: ordinary LF-delimited records keep parsing as before."""
    root = _search_root(factory)
    box = factory(_find_stdout(f"{root}/a.txt", f"{root}/b.txt"))

    found, truncated = box.glob(_ROOT, "**/*.txt")

    assert found == [_reported_path("a.txt"), _reported_path("b.txt")]
    assert truncated is False


@pytest.mark.parametrize("factory", _PROVIDER_FACTORIES)
def test_grep_empty_result_is_reported_as_no_matches(factory) -> None:
    """No regression: an empty result set stays ``([], False)``."""
    assert factory(_grep_stdout()).grep(_ROOT, "needle") == ([], False)


def _rs_shell(env: dict[str, str]):
    def sh(script: str, env_=None, timeout=None):
        proc = subprocess.run(["sh", "-c", script], capture_output=True, text=True, env=env, check=False)
        return SimpleNamespace(stdout=proc.stdout, stderr=proc.stderr, stdout_text=proc.stdout, stderr_text=proc.stderr, exit_code=proc.returncode)

    return sh


def _rs_box() -> BoxliteBox:
    box = BoxliteBox("box-id", box=object(), run=lambda coro, timeout=None: coro)
    box._sh = _rs_shell(os.environ.copy())
    return box


@_RS_POSIX
@pytest.mark.parametrize("separator", ["\v", "\u2028"])
def test_real_shell_glob_keeps_separator_named_file(tmp_path: Path, separator: str) -> None:
    """End-to-end through a real ``find``: such a name stays one entry.

    The fixture is created by the shell because Windows cannot create a name
    containing ``\\x0b`` at all.
    """
    octal = f"\\{ord(separator):03o}" if len(separator) == 1 else f"\\u{ord(separator):04x}"
    script = f"mkdir -p {tmp_path} && printf 'x\\n' > {tmp_path}/notes$(printf '{octal}')draft.txt"
    subprocess.run(["sh", "-c", script], capture_output=True, check=True, env=os.environ.copy())
    listing = subprocess.run(["sh", "-c", f"ls {tmp_path}"], capture_output=True, text=True, env=os.environ.copy()).stdout.strip()
    target = f"{tmp_path}/{listing}"

    found, truncated = _rs_box().glob(str(tmp_path), "**/*.txt")

    assert found == [target]
    assert truncated is False


@_RS_POSIX
def test_real_shell_grep_keeps_separator_in_matched_text(tmp_path: Path) -> None:
    """End-to-end through a real ``grep``: matched text is not cut at U+2028."""
    body = 'const s = "a\\u2028b";\\n'
    subprocess.run(["sh", "-c", f"mkdir -p {tmp_path} && printf '%s' \"{body}\" > {tmp_path}/mod.js"], capture_output=True, check=True, env=os.environ.copy())

    matches, _truncated = _rs_box().grep(str(tmp_path), "const")

    assert len(matches) == 1
    assert matches[0].line == 'const s = "a\u2028b";'
