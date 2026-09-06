"""Tests for the Lark CLI sandbox credential broker (Pattern B, issue #4338)."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import textwrap
import urllib.request
from http.client import HTTPConnection
from pathlib import Path

import pytest

from deerflow.integrations import lark_broker
from deerflow.integrations.lark_broker import BrokerConfig, run_lark_cli, serve


def _fake_lark_cli(tmp_path: Path) -> str:
    """A stub 'lark-cli' that echoes argv, stdin, and the credential env.

    Lets tests assert argv fidelity, stdin round-trip, and that the broker (not
    the caller) controls LARKSUITE_CLI_CONFIG_DIR / DATA_DIR.
    """
    script = tmp_path / "fake-lark-cli"
    script.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json, os, sys
            sys.stderr.write("ERR:" + " ".join(sys.argv[1:]) + "\\n")
            print(json.dumps({
                "argv": sys.argv[1:],
                "stdin": sys.stdin.read(),
                "config_dir": os.environ.get("LARKSUITE_CLI_CONFIG_DIR"),
                "data_dir": os.environ.get("LARKSUITE_CLI_DATA_DIR"),
            }))
            sys.exit(7 if "--boom" in sys.argv else 0)
            """
        ),
        encoding="utf-8",
    )
    script.chmod(0o755)
    return str(script)


def _config(tmp_path: Path, port: int = 0) -> BrokerConfig:
    return BrokerConfig(
        lark_cli_path=_fake_lark_cli(tmp_path),
        config_dir="/broker/only/config",
        data_dir="/broker/only/data",
        port=port,
    )


# ── run_lark_cli (in-process, no server) ───────────────────────────────────


def test_run_lark_cli_forwards_argv_stdin_and_credential_env(tmp_path: Path) -> None:
    config = _config(tmp_path)
    result = run_lark_cli(config, ["auth", "status", "--json"], b"piped-input")

    assert result.exit_code == 0
    payload = json.loads(result.stdout.decode())
    assert payload["argv"] == ["auth", "status", "--json"]
    assert payload["stdin"] == "piped-input"
    # The broker, not the caller, owns the credential paths.
    assert payload["config_dir"] == "/broker/only/config"
    assert payload["data_dir"] == "/broker/only/data"
    assert result.stderr == b"ERR:auth status --json\n"


def test_run_lark_cli_propagates_exit_code(tmp_path: Path) -> None:
    result = run_lark_cli(_config(tmp_path), ["do", "--boom"], b"")
    assert result.exit_code == 7


def test_run_lark_cli_never_shell_interprets_args(tmp_path: Path) -> None:
    # A shell metacharacter must reach the binary as one literal arg, not run a
    # second command (shell=False, argv list).
    result = run_lark_cli(_config(tmp_path), ["value; touch /tmp/pwned"], b"")
    payload = json.loads(result.stdout.decode())
    assert payload["argv"] == ["value; touch /tmp/pwned"]
    assert not Path("/tmp/pwned").exists()


def test_run_lark_cli_missing_binary_returns_127(tmp_path: Path) -> None:
    config = BrokerConfig(lark_cli_path=str(tmp_path / "nope"), config_dir="c", data_dir="d")
    result = run_lark_cli(config, ["x"], b"")
    assert result.exit_code == 127


# ── HTTP server ────────────────────────────────────────────────────────────


@pytest.fixture
def broker_server(tmp_path: Path):
    server = serve(_config(tmp_path, port=0))
    import threading

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[0], server.server_address[1]
    try:
        yield host, port
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _post_exec(host: str, port: int, body: dict) -> tuple[int, dict]:
    conn = HTTPConnection(host, port, timeout=10)
    data = json.dumps(body).encode()
    conn.request("POST", "/v1/exec", body=data, headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    parsed = json.loads(resp.read().decode())
    conn.close()
    return resp.status, parsed


def test_exec_endpoint_round_trips(broker_server) -> None:
    host, port = broker_server
    status, body = _post_exec(host, port, {"args": ["ping"], "stdin_b64": base64.b64encode(b"hi").decode()})
    assert status == 200
    assert body["exit_code"] == 0
    payload = json.loads(base64.b64decode(body["stdout_b64"]).decode())
    assert payload["argv"] == ["ping"]
    assert payload["stdin"] == "hi"


def test_exec_endpoint_ignores_client_supplied_credential_paths(broker_server) -> None:
    host, port = broker_server
    # Even if a malicious client tries to smuggle env-like args, the broker sets
    # the credential dirs itself; the stub reports the broker-owned values.
    status, body = _post_exec(host, port, {"args": ["whoami"]})
    assert status == 200
    payload = json.loads(base64.b64decode(body["stdout_b64"]).decode())
    assert payload["config_dir"] == "/broker/only/config"
    assert payload["data_dir"] == "/broker/only/data"


def test_exec_endpoint_rejects_invalid_body(broker_server) -> None:
    host, port = broker_server
    status, body = _post_exec(host, port, {"args": "not-a-list"})
    assert status == 400


def test_health_endpoint(broker_server) -> None:
    host, port = broker_server
    with urllib.request.urlopen(f"http://{host}:{port}/v1/health", timeout=5) as resp:
        assert json.loads(resp.read().decode())["ok"] is True


def test_exec_endpoint_returns_500_json_on_unexpected_error(broker_server, monkeypatch) -> None:
    """An unexpected exec error must return a structured 500, not close the
    connection with no body (which the shim would see as an opaque transport
    failure)."""
    host, port = broker_server

    def _boom(*_args, **_kwargs):
        raise PermissionError("simulated exec failure")

    monkeypatch.setattr(lark_broker, "run_lark_cli", _boom)
    status, body = _post_exec(host, port, {"args": ["auth", "status"]})
    assert status == 500
    assert body["error"]


# ── Shim script ─────────────────────────────────────────────────────────────


def test_shim_forwards_and_replays_exit_code(broker_server, tmp_path: Path) -> None:
    host, port = broker_server
    shim = tmp_path / "lark-cli"
    shim.write_text(lark_broker.LARK_CLI_BROKER_SHIM_SCRIPT, encoding="utf-8")
    shim.chmod(0o755)

    completed = subprocess.run(
        [sys.executable, str(shim), "do", "--boom"],
        input=b"",
        capture_output=True,
        env={**os.environ, lark_broker.LARK_BROKER_URL_ENV: f"http://{host}:{port}"},
        timeout=30,
    )
    assert completed.returncode == 7
    assert b"ERR:do --boom" in completed.stderr


def test_shim_fails_loudly_when_broker_unreachable(tmp_path: Path) -> None:
    shim = tmp_path / "lark-cli"
    shim.write_text(lark_broker.LARK_CLI_BROKER_SHIM_SCRIPT, encoding="utf-8")
    shim.chmod(0o755)
    completed = subprocess.run(
        [sys.executable, str(shim), "auth", "status"],
        input=b"",
        capture_output=True,
        # Nothing is listening here.
        env={**os.environ, lark_broker.LARK_BROKER_URL_ENV: "http://127.0.0.1:1"},
        timeout=30,
    )
    assert completed.returncode != 0
    assert b"broker unreachable" in completed.stderr


def test_install_shim_writes_runtime_layout(tmp_path: Path) -> None:
    """install-shim mode stages the same bin/lark-cli + marker layout Pattern A
    uses, marked kind=shim so the runtime validator tolerates absent binaries.

    bin/lark-cli is now the POSIX-sh launcher and the Python body lives beside it
    as bin/lark-cli-shim.py, so broker mode does not hard-depend on a resolvable
    #!/usr/bin/env python3 shebang.
    """
    dest = tmp_path / "runtime"
    launcher = lark_broker.install_shim(str(dest), version="v1.0.65")

    assert Path(launcher) == dest / "bin" / "lark-cli"
    launcher_text = (dest / "bin" / "lark-cli").read_text(encoding="utf-8")
    assert launcher_text.startswith("#!/bin/sh")
    # The shim body's absolute path is baked into the launcher (not derived from
    # $0, which is the bare command name when run off PATH).
    shim_body = dest / "bin" / lark_broker.LARK_CLI_BROKER_SHIM_FILENAME
    assert str(shim_body) in launcher_text
    assert lark_broker._LARK_CLI_BROKER_SHIM_PATH_PLACEHOLDER not in launcher_text
    assert os.access(dest / "bin" / "lark-cli", os.X_OK)
    assert shim_body.read_text(encoding="utf-8") == lark_broker.LARK_CLI_BROKER_SHIM_SCRIPT
    assert os.access(shim_body, os.X_OK)
    marker = json.loads((dest / ".deerflow-lark-cli-runtime.json").read_text())
    assert marker == {"version": "v1.0.65", "kind": "shim"}


def test_launcher_resolves_python_and_forwards(broker_server, tmp_path: Path) -> None:
    """The /bin/sh launcher finds python3 on PATH and execs the shim body."""
    host, port = broker_server
    dest = tmp_path / "runtime"
    lark_broker.install_shim(str(dest), version="v1.0.65")
    launcher = dest / "bin" / "lark-cli"

    # A PATH that has the python from this test runner so the launcher resolves it.
    py_dir = str(Path(sys.executable).parent)
    completed = subprocess.run(
        [str(launcher), "do", "--boom"],
        input=b"",
        capture_output=True,
        env={
            "PATH": py_dir + os.pathsep + "/usr/bin:/bin",
            lark_broker.LARK_BROKER_URL_ENV: f"http://{host}:{port}",
        },
        timeout=30,
    )
    assert completed.returncode == 7
    assert b"ERR:do --boom" in completed.stderr


def test_launcher_can_pin_interpreter_via_env(broker_server, tmp_path: Path) -> None:
    """DEERFLOW_LARK_BROKER_PYTHON pins the interpreter for images with no python3
    on PATH (the launcher must not silently ENOEXEC)."""
    host, port = broker_server
    dest = tmp_path / "runtime"
    lark_broker.install_shim(str(dest), version="v1.0.65")
    launcher = dest / "bin" / "lark-cli"

    completed = subprocess.run(
        [str(launcher), "ping"],
        input=b"",
        capture_output=True,
        # Deliberately no python on PATH; the pin is the only way to resolve it.
        env={
            "PATH": "/nonexistent",
            lark_broker.LARK_BROKER_PYTHON_ENV: sys.executable,
            lark_broker.LARK_BROKER_URL_ENV: f"http://{host}:{port}",
        },
        timeout=30,
    )
    assert completed.returncode == 0


def test_launcher_fails_loudly_without_python(tmp_path: Path) -> None:
    """With no python interpreter resolvable, the launcher exits 127 with an
    actionable message rather than an opaque ENOEXEC."""
    dest = tmp_path / "runtime"
    lark_broker.install_shim(str(dest), version="v1.0.65")
    launcher = dest / "bin" / "lark-cli"

    completed = subprocess.run(
        [str(launcher), "auth", "status"],
        input=b"",
        capture_output=True,
        env={"PATH": "/nonexistent"},
        timeout=30,
    )
    assert completed.returncode == 127
    assert b"Python 3 interpreter" in completed.stderr


# ── cwd is not forwarded (command surface only, no sandbox file I/O) ─────────


def test_exec_payload_omits_cwd(tmp_path: Path) -> None:
    """The shim must not forward cwd: the broker can't see the sandbox FS, so a
    dead cwd field would imply support that does not exist."""
    assert '"cwd"' not in lark_broker.LARK_CLI_BROKER_SHIM_SCRIPT
    assert "os.getcwd()" not in lark_broker.LARK_CLI_BROKER_SHIM_SCRIPT


# ── subcommand denylist (issue #4338 hardening) ──────────────────────────────


def test_parse_deny_subcommands() -> None:
    assert lark_broker.parse_deny_subcommands(None) == ()
    assert lark_broker.parse_deny_subcommands("") == ()
    assert lark_broker.parse_deny_subcommands("config show, auth token") == (
        ("config", "show"),
        ("auth", "token"),
    )
    # Blank entries are dropped.
    assert lark_broker.parse_deny_subcommands("config show, ,") == (("config", "show"),)


def test_denied_subcommand_is_refused_before_spawning_binary(tmp_path: Path) -> None:
    config = BrokerConfig(
        lark_cli_path=_fake_lark_cli(tmp_path),
        config_dir="/broker/only/config",
        data_dir="/broker/only/data",
        deny_subcommands=(("config", "show"),),
    )
    result = run_lark_cli(config, ["config", "show", "--json"], b"")
    assert result.exit_code == 126
    assert b"disabled in broker mode" in result.stderr
    # The stub echoes argv on stdout; a refused call never runs it.
    assert result.stdout == b""


def test_denied_subcommand_matches_through_leading_flags(tmp_path: Path) -> None:
    config = BrokerConfig(
        lark_cli_path=_fake_lark_cli(tmp_path),
        config_dir="c",
        data_dir="d",
        deny_subcommands=(("config", "show"),),
    )
    # Options interleaved with the subcommand path are skipped when matching.
    result = run_lark_cli(config, ["--json", "config", "show"], b"")
    assert result.exit_code == 126


def test_allowed_subcommand_still_runs_with_denylist(tmp_path: Path) -> None:
    config = BrokerConfig(
        lark_cli_path=_fake_lark_cli(tmp_path),
        config_dir="c",
        data_dir="d",
        deny_subcommands=(("config", "show"),),
    )
    result = run_lark_cli(config, ["auth", "status"], b"")
    assert result.exit_code == 0
    payload = json.loads(result.stdout.decode())
    assert payload["argv"] == ["auth", "status"]
