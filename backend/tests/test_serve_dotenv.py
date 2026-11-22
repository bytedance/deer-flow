"""serve.sh reads the checkout .env as data, never as a shell script.

It used to ``source`` the file under ``set -a``: ``$$`` became the shell's PID,
backticks and ``$(...)`` ran commands, and an unquoted value with a space ran
its second word as a command (exit 127 under ``set -e``, so ``make dev`` died).
The exported values then beat the Gateway's own python-dotenv read, which never
overrides an existing variable.

These tests run serve.sh's actual ``.env`` block (and the ``_pick_python`` it
calls) in bash against a scratch checkout, then read back what it exported.
The launcher's expansion rules and precedence are pinned against
``support_bundle.py`` in ``test_support_bundle.py``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from dotenv import dotenv_values
from support.shell import require_script_bash

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"

_DUMP_ENVIRONMENT = "\"$TEST_PYTHON\" -c 'import json, os, sys; sys.stdout.write(json.dumps(dict(os.environ)))'"


def _dotenv_block() -> str:
    serve = (SCRIPTS / "serve.sh").read_text(encoding="utf-8")
    pick_python = serve[serve.index("_pick_python() {") :].split("\n}\n", 1)[0] + "\n}\n"
    block = serve.split("# ── Load .env", 1)[1].split("\n\n", 1)[1].split("# ── Argument parsing", 1)[0]
    return pick_python + block


def _run_dotenv_block(project: Path, dotenv: bytes, **environment: str) -> subprocess.CompletedProcess[str]:
    (project / "scripts").mkdir(parents=True, exist_ok=True)
    shutil.copy2(SCRIPTS / "dotenv_exports.py", project / "scripts" / "dotenv_exports.py")
    (project / ".env").write_bytes(dotenv)
    env = {key: value for key, value in os.environ.items() if key not in {"BASH_ENV", "ENV"}}
    env.update(environment, REPO_ROOT=str(project), TEST_PYTHON=Path(sys.executable).as_posix())
    return subprocess.run(
        [require_script_bash(), "-c", 'set -e\ncd "$REPO_ROOT"\n' + _dotenv_block() + _DUMP_ENVIRONMENT],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _exported(project: Path, dotenv: bytes, **environment: str) -> dict[str, str]:
    result = _run_dotenv_block(project, dotenv, **environment)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_dotenv_values_are_data_not_shell_code(tmp_path: Path) -> None:
    dotenv = 'PASSWORD=pa$$word\nQUOTED_PASSWORD="pa$$word"\nBACKTICKS=`touch backtick-ran`kept\nSUBSTITUTION=$(touch substitution-ran)\nSPACED=hello world\nCHAINED=first; touch chained-ran\nAFTER=still-loaded\n'

    exported = _exported(tmp_path, dotenv.encode("utf-8"))

    assert exported["PASSWORD"] == "pa$$word"
    assert exported["QUOTED_PASSWORD"] == "pa$$word"
    assert exported["BACKTICKS"] == "`touch backtick-ran`kept"
    assert exported["SUBSTITUTION"] == "$(touch substitution-ran)"
    assert exported["SPACED"] == "hello world"
    assert exported["CHAINED"] == "first; touch chained-ran"
    assert exported["AFTER"] == "still-loaded"
    assert sorted(path.name for path in tmp_path.glob("*-ran")) == []


def test_literal_values_match_what_the_gateway_reads(tmp_path: Path) -> None:
    """Without references or tildes, every value equals python-dotenv's reading."""
    dotenv = (
        "﻿FIRST=after-bom\r\n"
        "# a comment line\r\n"
        "export EXPORTED=prefixed\r\n"
        "INLINE=value # trailing comment\r\n"
        "HASH=no#comment\r\n"
        "SPACED_EQUALS = padded\r\n"
        "EMPTY=\r\n"
        "SINGLE='single \\'quoted\\' # not a comment'\r\n"
        'DOUBLE="tab\\there \\"quoted\\""\r\n'
        'MULTILINE="line one\r\nline two"\r\n'
        "'QUOTED_KEY'=quoted key\r\n"
        "UNICODE=café ✓\r\n"
        "BARE_NAME\r\n"
    )
    path = tmp_path / "gateway.env"
    path.write_text(dotenv, encoding="utf-8", newline="")
    gateway = {key: value for key, value in dotenv_values(path, encoding="utf-8-sig").items() if value is not None}

    exported = _exported(tmp_path, dotenv.encode("utf-8"))

    assert {key: exported.get(key) for key in gateway} == gateway
    assert "BARE_NAME" not in exported


def test_dotenv_still_overrides_inherited_variables(tmp_path: Path) -> None:
    exported = _exported(tmp_path, b"FROM_SHELL=from-dotenv\nEMPTIED=\n", FROM_SHELL="from-shell", EMPTIED="from-shell")

    assert exported["FROM_SHELL"] == "from-dotenv"
    assert exported["EMPTIED"] == ""


def test_unparseable_statements_and_names_are_skipped_without_echoing_values(tmp_path: Path) -> None:
    dotenv = b'BEFORE=kept\nNOT-A-NAME=secret-one\nBROKEN="unterminated secret-two\nAFTER=kept\n'

    result = _run_dotenv_block(tmp_path, dotenv)

    assert result.returncode == 0, result.stderr
    exported = json.loads(result.stdout)
    assert exported["BEFORE"] == "kept"
    assert exported["AFTER"] == "kept"
    assert "dotenv_exports: skipping 'NOT-A-NAME' at line 2: not a shell variable name" in result.stderr
    assert "dotenv_exports: skipping a statement that does not parse at line 3" in result.stderr
    assert "secret-one" not in result.stderr
    assert "secret-two" not in result.stderr


def test_non_utf8_dotenv_stops_the_launcher_before_exporting(tmp_path: Path) -> None:
    result = _run_dotenv_block(tmp_path, b"FIRST=kept\nLATIN1=caf\xe9\n")

    assert result.returncode != 0
    assert "is not valid UTF-8" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("source", ["`touch {marker}`", "$(touch {marker})"])
def test_parser_runs_on_the_standard_library_and_never_executes(tmp_path: Path, source: str) -> None:
    """serve.sh runs it with the host Python, before ``uv sync`` installs anything."""
    marker = tmp_path / "ran"
    dotenv = tmp_path / ".env"
    dotenv.write_text(f"VALUE={source.format(marker=marker.as_posix())}\n", encoding="utf-8")

    result = subprocess.run([sys.executable, "-S", str(SCRIPTS / "dotenv_exports.py"), str(dotenv)], capture_output=True, check=True)

    assert result.stdout.decode("utf-8") == f"export VALUE='{source.format(marker=marker.as_posix())}'\n"
    assert not marker.exists()
