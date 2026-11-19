"""Every nginx launcher must survive a host with IPv6 disabled.

``docker/nginx/nginx.conf`` listens on both ``2026`` and ``[::]:2026``. On a
host booted with ``ipv6.disable=1`` (or a kernel without IPv6) nginx refuses to
start — ``socket() [::]:2026 failed (97: Address family not supported by
protocol)`` — and a ``restart: unless-stopped`` container loops until the
``--wait`` readiness check gives up. #2027 added a launcher guard that strips
the IPv6 ``listen`` when ``/proc/net/if_inet6`` is absent, but only to the dev
compose file; the Helm chart mirrors it; the production compose file used by
``make up`` / ``scripts/deploy.sh`` did not. These tests pin the guard in every
launcher, keep the three copies identical, and check the pattern really
removes the IPv6 line from the config it is applied to.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATHS = {
    "prod": REPO_ROOT / "docker" / "docker-compose.yaml",
    "dev": REPO_ROOT / "docker" / "docker-compose-dev.yaml",
}
HELM_NGINX_DEPLOYMENT = REPO_ROOT / "deploy" / "helm" / "deer-flow" / "templates" / "nginx-deployment.yaml"
NGINX_CONFS = {
    "compose": REPO_ROOT / "docker" / "nginx" / "nginx.conf",
    "helm": REPO_ROOT / "deploy" / "helm" / "deer-flow" / "templates" / "configmap-nginx.yaml",
}

GUARD_RE = re.compile(r"test -e /proc/net/if_inet6 \|\| sed -i '(?P<pattern>[^']+)' (?P<target>\S+)")


def _compose_nginx_script(compose_path: Path) -> str:
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    command = compose["services"]["nginx"]["command"]
    if isinstance(command, list):
        assert command[:2] == ["sh", "-c"], f"{compose_path.name}: nginx command must be `sh -c <script>`; got {command[:2]!r}"
        return command[2]
    return str(command)


def _helm_nginx_script() -> str:
    # The template carries Helm expressions elsewhere; the nginx container's
    # ``args`` block is plain YAML, so pull the folded scalar out textually.
    text = HELM_NGINX_DEPLOYMENT.read_text(encoding="utf-8")
    match = re.search(r"args:\n\s+- >-\n((?:\s{14}.*\n)+)", text)
    assert match, "could not find the nginx args block in the Helm deployment"
    return " ".join(line.strip() for line in match.group(1).splitlines())


LAUNCHERS = {
    "prod": lambda: _compose_nginx_script(COMPOSE_PATHS["prod"]),
    "dev": lambda: _compose_nginx_script(COMPOSE_PATHS["dev"]),
    "helm": _helm_nginx_script,
}


def _guard(script: str) -> re.Match[str]:
    match = GUARD_RE.search(script)
    assert match, f"nginx launcher has no `test -e /proc/net/if_inet6 || sed -i ...` guard:\n{script}"
    return match


@pytest.mark.parametrize("launcher", sorted(LAUNCHERS))
def test_every_nginx_launcher_strips_the_ipv6_listen_when_ipv6_is_unavailable(launcher: str):
    script = LAUNCHERS[launcher]()

    guard = _guard(script)
    # The guard must run on the copied config, between the copy and the start.
    assert script.index("cp /etc/nginx/nginx.conf.template") < guard.start() < script.index("nginx -")
    start = script[guard.end() :]
    explicit = re.search(r"nginx (?:.*\s)?-c (\S+)", start)
    loaded = explicit.group(1) if explicit else "/etc/nginx/nginx.conf"  # nginx's compiled-in default
    assert guard.group("target") == loaded, f"the guard edits {guard.group('target')} but nginx loads {loaded}"


def test_all_nginx_launchers_use_one_identical_guard_pattern():
    """Three copies of one rule: pin them to the same sed expression so they cannot drift."""
    patterns = {launcher: _guard(script())["pattern"] for launcher, script in LAUNCHERS.items()}

    assert len(set(patterns.values())) == 1, f"nginx launchers disagree on the IPv6 guard pattern: {patterns}"


@pytest.mark.parametrize("variant", sorted(COMPOSE_PATHS))
def test_compose_nginx_execs_nginx_as_pid_1(variant: str):
    """`exec` hands PID 1 to nginx so `docker stop` delivers SIGTERM/SIGQUIT to it, not to `sh`."""
    script = _compose_nginx_script(COMPOSE_PATHS[variant])

    assert re.search(r"(^|\n|&&\s*)exec nginx -g 'daemon off;'", script), f"{variant} compose must start nginx with `exec`:\n{script}"
    assert "set -e" in script, f"{variant} compose must fail the container when the copy or the guard fails:\n{script}"


def _apply_sed_delete(bre_pattern: str, text: str) -> str:
    """Apply `sed -i '/<pattern>/d'` with Python's regex engine (BusyBox BRE → Python re)."""
    assert bre_pattern.startswith("/") and bre_pattern.endswith("/d"), bre_pattern
    body = bre_pattern[1:-2].replace("[[:space:]]", r"\s").replace(r"\+", "+")
    return "".join(line for line in text.splitlines(keepends=True) if not re.search(body, line))


@pytest.mark.parametrize("conf", sorted(NGINX_CONFS))
def test_guard_pattern_removes_only_the_ipv6_listen_from_the_shipped_config(conf: str):
    """The pattern is only useful if it matches the exact `listen [::]:2026 ...;` line we ship."""
    pattern = _guard(LAUNCHERS["dev"]())["pattern"]
    original = NGINX_CONFS[conf].read_text(encoding="utf-8")
    assert re.search(r"^\s*listen \[::\]:2026 default_server;\s*$", original, re.M), f"{conf} nginx config no longer has the IPv6 listen this guard targets"

    stripped = _apply_sed_delete(pattern, original)

    assert not re.search(r"^\s*listen\s+\[::\]", stripped, re.M), f"{conf}: IPv6 listen survived the guard"
    assert re.search(r"^\s*listen 2026 default_server;\s*$", stripped, re.M), f"{conf}: the IPv4 listen must survive"
    assert len(original.splitlines()) - len(stripped.splitlines()) == 1
