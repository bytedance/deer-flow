"""Regression test for the local (non-Docker) launch bind addresses.

``README.md`` documents DeerFlow as deployed by default "in a local trusted
environment (accessible only via the 127.0.0.1 loopback interface)", and the
Docker stack publishes only its nginx entry, on ``${BIND_HOST:-127.0.0.1}``
(``test_compose_default_bind_host.py``). ``make dev`` / ``make start`` instead
started the Gateway with ``--host 0.0.0.0``, nginx with ``listen 2026`` and the
frontend on Next's ``0.0.0.0`` default, so on a LAN or VPN every one of those
ports, including ``/setup`` before the first admin exists, was reachable from
other machines.

Gateway and frontend now always bind loopback; nginx listens on loopback unless
``BIND_HOST`` opts in, the same variable the Docker stack honors.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from support.shell import require_script_bash

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVE_SH = REPO_ROOT / "scripts" / "serve.sh"
NGINX_SH = REPO_ROOT / "scripts" / "nginx.sh"
NGINX_LOCAL_CONF_SH = REPO_ROOT / "scripts" / "nginx-local-conf.sh"
NGINX_LOCAL_CONF = REPO_ROOT / "docker" / "nginx" / "nginx.local.conf"
BACKEND_MAKEFILE = REPO_ROOT / "backend" / "Makefile"


def _listen_directives(conf: str) -> list[str]:
    return re.findall(r"^\s*listen\s+([^;]+);", conf, re.M)


# ── Launch commands ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("path", [SERVE_SH, BACKEND_MAKEFILE], ids=["serve.sh", "backend-Makefile"])
def test_gateway_launch_commands_bind_loopback(path: Path):
    text = path.read_text(encoding="utf-8")
    launches = [line for line in text.splitlines() if "uvicorn app.gateway.app:app --" in line]

    assert launches, f"no Gateway launch found in {path.name}"
    for line in launches:
        assert "--host 127.0.0.1" in line, f"{path.name} must start the Gateway on loopback: {line.strip()}"


def test_frontend_launch_commands_bind_loopback():
    """Every serve.sh frontend mode must pass a loopback --hostname to Next.

    ``frontend/scripts/dev.mjs`` keeps Next's all-interfaces default off Windows
    because the Docker dev frontend container needs it, so serve.sh passes the
    hostname itself.
    """
    commands = re.findall(r"^\s*FRONTEND_CMD=(.*)$", SERVE_SH.read_text(encoding="utf-8"), re.M)

    assert len(commands) == 3, f"expected dev, start and preview frontend commands; got {commands}"
    for command in commands:
        assert "--hostname 127.0.0.1" in command, f"frontend command must bind loopback: {command}"


def test_local_nginx_config_listens_on_loopback_only():
    assert _listen_directives(NGINX_LOCAL_CONF.read_text(encoding="utf-8")) == ["127.0.0.1:2026", "[::1]:2026"]


@pytest.mark.parametrize("path", [SERVE_SH, NGINX_SH], ids=["serve.sh", "nginx.sh"])
def test_nginx_launchers_use_the_bind_host_aware_config(path: Path):
    text = path.read_text(encoding="utf-8")

    assert 'NGINX_CONF="$(bash "$REPO_ROOT/scripts/nginx-local-conf.sh")"' in text
    launches = [line for line in text.splitlines() if "daemon off;" in line]
    assert launches and all("$NGINX_CONF" in line for line in launches), launches


def test_serve_resolves_nginx_config_before_stopping_services():
    """An invalid BIND_HOST must fail before restart/start tear down a running stack."""
    serve = SERVE_SH.read_text(encoding="utf-8")

    assert serve.index("scripts/nginx-local-conf.sh") < serve.index('if [ "$ACTION" = "restart" ]; then')


# ── nginx-local-conf.sh ─────────────────────────────────────────────────────


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """A minimal checkout: the script resolves the repo root from its own location."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "docker" / "nginx").mkdir(parents=True)
    shutil.copy2(NGINX_LOCAL_CONF_SH, tmp_path / "scripts" / NGINX_LOCAL_CONF_SH.name)
    shutil.copy2(NGINX_LOCAL_CONF, tmp_path / "docker" / "nginx" / NGINX_LOCAL_CONF.name)
    return tmp_path


def _run(checkout: Path, bind_host: str | None) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if key != "BIND_HOST"}
    if bind_host is not None:
        env["BIND_HOST"] = bind_host
    return subprocess.run(
        [require_script_bash(), str(checkout / "scripts" / NGINX_LOCAL_CONF_SH.name)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("bind_host", [None, "", "127.0.0.1"], ids=["unset", "blank", "loopback"])
def test_default_bind_host_uses_the_tracked_config(checkout: Path, bind_host: str | None):
    result = _run(checkout, bind_host)

    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()) == (checkout / "docker" / "nginx" / "nginx.local.conf").resolve()
    assert not (checkout / "temp").exists()


@pytest.mark.parametrize(
    ("bind_host", "expected"),
    [
        ("0.0.0.0", ["2026", "[::]:2026"]),
        ("192.0.2.10", ["192.0.2.10:2026"]),
        ("fd00::1", ["[fd00::1]:2026"]),
        ("[fd00::1]", ["[fd00::1]:2026"]),
    ],
)
def test_bind_host_renders_a_config_listening_there(checkout: Path, bind_host: str, expected: list[str]):
    result = _run(checkout, bind_host)

    assert result.returncode == 0, result.stderr
    rendered = Path(result.stdout.strip())
    assert rendered == (checkout / "temp" / "nginx.local.conf").resolve()
    content = rendered.read_text(encoding="utf-8")
    assert _listen_directives(content) == expected

    # Only the listen directives change.
    def without_listen(text: str) -> list[str]:
        return [line for line in text.splitlines() if not line.strip().startswith("listen ")]

    assert without_listen(content) == without_listen(NGINX_LOCAL_CONF.read_text(encoding="utf-8"))


@pytest.mark.parametrize("bind_host", ["0.0.0.0; return 200", "a b", "$(id)"])
def test_bind_host_rejects_values_that_are_not_addresses(checkout: Path, bind_host: str):
    result = _run(checkout, bind_host)

    assert result.returncode != 0
    assert "BIND_HOST must be an IP address or hostname" in result.stderr
    assert not (checkout / "temp" / "nginx.local.conf").exists()


def test_render_fails_loudly_when_the_listen_directive_drifts(checkout: Path):
    conf = checkout / "docker" / "nginx" / "nginx.local.conf"
    conf.write_text(conf.read_text(encoding="utf-8").replace("listen 127.0.0.1:2026;", "listen 127.0.0.1:2027;"), encoding="utf-8")

    result = _run(checkout, "0.0.0.0")

    assert result.returncode != 0
    assert "Could not find the loopback listen directive" in result.stderr
    assert not (checkout / "temp" / "nginx.local.conf").exists()
