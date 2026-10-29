"""Every capture of ``lark-cli`` / npm output decodes as UTF-8, not the locale.

``lark-cli`` is a native binary shipped through the ``@larksuite/cli`` npm
package (``bin`` is the Node wrapper ``scripts/run.js``, which ``execFileSync``es
the downloaded binary), and npm writes its own output as UTF-8. Both therefore
put UTF-8 bytes on the pipe regardless of the host's ANSI code page. Decoding
those bytes with ``locale.getencoding()`` -- cp936 on a Chinese Windows host,
cp1252 on a Western one -- silently corrupts every non-ASCII field the CLI
returns (a CJK ``userName`` from ``auth status --json``, a document title) and
can kill the pipe reader thread, which surfaces as ``stdout is None`` rather
than as an exception.

The tests drive the real functions with a stand-in CLI that emits non-ASCII
UTF-8, and force the locale decoding path without depending on the host code
page: the module's ``subprocess.run`` reference is wrapped so a text-mode call
that names no codec is decoded with one that mangles UTF-8, while a call that
pins its own ``encoding`` is passed through untouched. That reproduces the
behaviour of the pre-fix call sites on a cp936/cp1252 host even when the test
host itself is UTF-8.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from deerflow.config import paths as paths_module
from deerflow.config.paths import Paths
from deerflow.integrations import lark_cli

# A code page that cannot represent the payload below and is not UTF-8.
MANGLING_CODEPAGE = "cp1252"

EXPECTED_USER = "\u5f20\u4f1f"  # 张伟
EXPECTED_TITLE = "\u5b63\u5ea6\u590d\u76d8"  # 季度复盘
EXPECTED_VERSION = "lark-cli v1.0.65 \u5f20\u4f1f"  # the CLI's --version payload

_FAKE_CLI_BODY = f"""\
import json
import os
import sys

if "--version" in sys.argv[1:]:
    os.write(1, {EXPECTED_VERSION!r}.encode("utf-8"))
    raise SystemExit(0)

payload = {{
    "userName": {EXPECTED_USER!r},
    "title": {EXPECTED_TITLE!r},
    "verification_url": "https://open.feishu.cn/verify",
}}
os.write(1, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
"""


@pytest.fixture
def fake_cli(tmp_path: Path) -> tuple[list[str], str]:
    """A stand-in CLI emitting UTF-8 non-ASCII JSON, as argv and as a path.

    The interpreter path can contain non-ASCII characters (a checkout under a
    CJK directory), so the Windows shim is written in the ANSI code page that
    ``cmd.exe`` itself uses to read a ``.cmd`` file; otherwise the shim cannot
    find its own interpreter. The Python body is always UTF-8.
    """
    body = textwrap.dedent(_FAKE_CLI_BODY)
    script = tmp_path / "fake_lark_cli.py"
    script.write_text(body, encoding="utf-8")
    argv = [sys.executable, str(script)]

    if os.name != "nt":
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        launcher = tmp_path / "lark-cli"
        launcher.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
        launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC)
        return argv, str(launcher)

    launcher = tmp_path / "lark-cli.cmd"
    launcher.write_text(f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n', encoding="mbcs")
    return argv, str(launcher)


@pytest.fixture
def locale_decoding(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``lark_cli`` capture text the way a non-UTF-8 host code page would.

    A call that names its own codec is passed through untouched, so a pinned
    ``encoding="utf-8"`` still wins; a text-mode call that names none is decoded
    with a code page that cannot represent non-ASCII -- exactly what happens on
    cp936/cp1252 when the locale supplies the codec. Emulating it here keeps
    these tests meaningful on a host (or CI runner) whose own locale is UTF-8,
    where the unpatched flip would otherwise pass on the pre-fix code too.

    ``locale.getencoding`` is deliberately not patched: ``lark_cli`` never calls
    it, so pinning it would document a redirection that does not happen.
    """
    real_run = subprocess.run

    def locale_run(*args, **kwargs):
        if (kwargs.get("text") or kwargs.get("universal_newlines")) and "encoding" not in kwargs:
            kwargs["encoding"] = MANGLING_CODEPAGE
            kwargs["errors"] = "replace"
        return real_run(*args, **kwargs)

    monkeypatch.setattr(lark_cli.subprocess, "run", locale_run)


@pytest.fixture(autouse=True)
def isolated_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep the suite off the live runtime home.

    ``_run_lark_cli_json`` and ``probe_lark_auth`` reach
    ``ensure_lark_cli_credential_tree`` through the global ``get_paths()``
    singleton, so without this every run would create and harden a real
    ``<cwd>/.deer-flow/users/alice/integrations/lark-cli/{config,data}`` tree --
    the same directory a live deployment keeps real per-user Lark credentials
    in -- in whatever directory pytest runs from. The sibling
    ``test_lark_cli_integration.py`` isolates it the same way.
    """
    monkeypatch.setattr(paths_module, "_paths", Paths(base_dir=tmp_path / "home"))


def test_run_lark_cli_json_decodes_utf8_output_regardless_of_locale(fake_cli, locale_decoding: None) -> None:
    """``_run_lark_cli_json`` must return the CLI's non-ASCII fields intact."""
    argv, _launcher = fake_cli

    data = lark_cli._run_lark_cli_json([*argv, "auth", "status", "--json"], user_id="alice", timeout=20)

    assert data["userName"] == EXPECTED_USER
    assert data["title"] == EXPECTED_TITLE


def test_probe_lark_auth_decodes_utf8_user_name(fake_cli, locale_decoding: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """The frequently-polled status probe reports the real CJK account name."""
    _argv, launcher = fake_cli
    monkeypatch.setattr(lark_cli, "_resolve_lark_cli_path", lambda: launcher)
    monkeypatch.setattr(lark_cli, "read_lark_app_config", lambda _user_id: {"configured": True})

    probe = lark_cli.probe_lark_auth("alice")

    assert probe.status == "authenticated"
    assert probe.user == EXPECTED_USER


def test_probe_lark_cli_at_path_decodes_utf8_version_output(fake_cli, locale_decoding: None) -> None:
    """The probe's reported version keeps a non-ASCII byte intact.

    Asserting only ``available``/``error`` would not guard the pin: the probe
    returns ``available=True, version=output or None`` for any non-empty output
    with a zero exit code, so a mojibake version string still passes. Naming the
    expected text is what fails on the unpinned call site.
    """
    _argv, launcher = fake_cli

    probe = lark_cli._probe_lark_cli_at_path(launcher)

    assert probe.available is True
    assert probe.error is None
    assert probe.version == EXPECTED_VERSION


def test_unpinned_capture_corrupts_the_same_output(fake_cli) -> None:
    """Control: without the pin, the locale decode corrupts the payload.

    Asserted directly so the failure mode stays documented on hosts whose own
    locale happens to be UTF-8 (where this records that the pin is what keeps
    the decode correct elsewhere rather than re-testing the corruption).
    """
    argv, _launcher = fake_cli

    unpinned = subprocess.run(argv, check=False, capture_output=True, text=True)
    raw = unpinned.stdout or ""
    if raw.strip() and json.loads(raw)["userName"] == EXPECTED_USER:
        # A UTF-8 host locale: the locale decode happens to be correct here.
        return
    assert EXPECTED_USER not in raw
