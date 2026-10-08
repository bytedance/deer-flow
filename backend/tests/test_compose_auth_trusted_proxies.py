"""The compose Gateway must key the login lockout by client, not by nginx.

``auth.py`` counts failed logins per client IP and honors ``X-Real-IP`` only
from a peer listed in ``AUTH_TRUSTED_PROXIES``. In the compose stack every
browser request reaches the Gateway from the ``nginx`` container, whose address
Docker assigns, so with the variable unset all logins shared nginx's address
and five wrong passwords from anyone locked out every user. Both compose files
name the bundled proxy by its service name; that trust is safe only while
nginx overwrites ``X-Real-IP`` on every route to the Gateway, pinned below for
the three maintained nginx configs.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from support.compose import DOCKER, requires_docker_compose
from support.nginx_conf import NGINX_CONFIGS, read_config

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATHS = {
    "prod": REPO_ROOT / "docker" / "docker-compose.yaml",
    "dev": REPO_ROOT / "docker" / "docker-compose-dev.yaml",
}
EXPECTED_ENTRY = "AUTH_TRUSTED_PROXIES=${AUTH_TRUSTED_PROXIES:-nginx}"


@pytest.mark.parametrize("variant", sorted(COMPOSE_PATHS))
def test_gateway_trusts_the_bundled_nginx_service_by_default(variant: str):
    compose = yaml.safe_load(COMPOSE_PATHS[variant].read_text(encoding="utf-8"))
    services = compose["services"]

    assert EXPECTED_ENTRY in services["gateway"]["environment"]
    # The default resolves only while the proxy is the service named ``nginx``
    # on a network the Gateway shares.
    assert set(services["nginx"]["networks"]) & set(services["gateway"]["networks"])


def _render(tmp_path: Path, variant: str, env_file: str | None) -> dict:
    """Render the compose file the way deploy.sh / docker.sh call it (``--env-file ../.env``)."""
    docker_dir = tmp_path / "docker"
    shutil.copytree(REPO_ROOT / "docker", docker_dir)
    (tmp_path / "frontend").mkdir(exist_ok=True)
    env = {key: value for key, value in os.environ.items() if not key.startswith(("DEER_FLOW_", "COMPOSE_", "AUTH_"))}
    env.update(
        DEER_FLOW_ROOT=str(tmp_path),
        DEER_FLOW_HOME=str(tmp_path / "home"),
        DEER_FLOW_REPO_ROOT=str(tmp_path),
        DEER_FLOW_CONFIG_PATH=str(tmp_path / "config.yaml"),
        DEER_FLOW_EXTENSIONS_CONFIG_PATH=str(tmp_path / "extensions_config.json"),
        BETTER_AUTH_SECRET="test-secret",
        DEER_FLOW_INTERNAL_AUTH_TOKEN="test-token",
    )
    command = [DOCKER, "compose"]
    if env_file is not None:
        (tmp_path / ".env").write_text(env_file, encoding="utf-8")
        command += ["--env-file", str(tmp_path / ".env")]
    command += ["-p", "deer-flow-trusted-proxies-test", "-f", str(docker_dir / COMPOSE_PATHS[variant].name), "config", "--format", "json"]
    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=120, check=False)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["services"]["gateway"]["environment"]


@requires_docker_compose
@pytest.mark.parametrize("variant", sorted(COMPOSE_PATHS))
@pytest.mark.parametrize(("env_file", "expected"), [(None, "nginx"), ("AUTH_TRUSTED_PROXIES=10.0.0.0/8,edge-proxy\n", "10.0.0.0/8,edge-proxy")], ids=["default", "operator-override"])
def test_real_compose_renders_the_default_and_keeps_an_operator_override(tmp_path, variant: str, env_file: str | None, expected: str):
    assert _render(tmp_path, variant, env_file)["AUTH_TRUSTED_PROXIES"] == expected


def _gateway_locations(content: str) -> list[tuple[str, str]]:
    """``(selector, block)`` for every location whose ``proxy_pass`` targets the Gateway."""
    locations = []
    for match in re.finditer(r"^\s*location\s+([^{#\n]+?)\s*\{", content, re.MULTILINE):
        start = match.end() - 1
        depth = 0
        for index in range(start, len(content)):
            if content[index] == "{":
                depth += 1
            elif content[index] == "}":
                depth -= 1
                if depth == 0:
                    block = content[start : index + 1]
                    break
        proxy_pass = re.search(r"proxy_pass\s+([^;]+);", block)
        if proxy_pass and "gateway" in proxy_pass.group(1):
            locations.append((match.group(1), block))
    return locations


@pytest.mark.parametrize("path", NGINX_CONFIGS)
def test_every_gateway_location_overwrites_x_real_ip(path: str):
    """A location that forwarded the client's own X-Real-IP would let anyone pick their lockout bucket."""
    locations = _gateway_locations(read_config(path))

    assert len(locations) >= 10, f"{path}: found only {len(locations)} gateway locations; did the parser break?"
    missing = [selector for selector, block in locations if not re.search(r"proxy_set_header\s+X-Real-IP\s+\$remote_addr\s*;", block)]
    assert missing == [], f"{path}: gateway locations that pass the client's X-Real-IP through: {missing}"
