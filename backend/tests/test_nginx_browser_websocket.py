"""Live Browser upgrades must reach Gateway in every maintained nginx config."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from support.nginx_conf import NGINX_CONFIGS, extract_location_block, read_config

CHART = Path(__file__).resolve().parents[2] / "deploy" / "helm" / "deer-flow"
BROWSER_PATTERN = r"^/api/threads/[^/]+/browser/stream"


def _assert_browser_websocket_config(config: str, *, helm_defaults: bool = False) -> None:
    block = extract_location_block(config, f"~ {BROWSER_PATTERN}")

    # nginx selects the first matching regex, so the generic threads location
    # must not swallow the WebSocket handshake before this location is reached.
    regex_locations = re.findall(r"^\s*location\s+~\s+([^\{]+)\{", config, re.M)
    first_match = next((pattern.strip() for pattern in regex_locations if re.match(pattern.strip(), "/api/threads/thread-42/browser/stream")), None)
    assert first_match == BROWSER_PATTERN

    assert re.search(r"^\s*proxy_pass http://\$?gateway(?:_upstream)?;\s*$", block, re.M)
    assert re.search(r"^\s*proxy_set_header X-Forwarded-Proto \$(?:forwarded_proto|scheme);\s*$", block, re.M)
    for directive in (
        "proxy_http_version 1.1;",
        "proxy_set_header Host $http_host;",
        "proxy_set_header X-Real-IP $remote_addr;",
        "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
        "proxy_set_header Upgrade $http_upgrade;",
        "proxy_set_header Connection 'upgrade';",
        "proxy_cache_bypass $http_upgrade;",
        "proxy_read_timeout 600s;",
    ):
        assert re.search(r"^\s*" + re.escape(directive) + r"\s*$", block, re.M), f"Live Browser location is missing {directive}"

    if helm_defaults:
        # Connecting to Gateway and sending the upgrade request use nginx's 60s
        # defaults; the read timeout above keeps quiet WebSockets open.
        for directive in ("proxy_connect_timeout", "proxy_send_timeout"):
            assert not re.search(r"^\s*" + directive + r"\s+", block, re.M), f"Helm Live Browser location should use the default {directive}"


@pytest.mark.parametrize("path", NGINX_CONFIGS)
def test_live_browser_websocket_config(path: str) -> None:
    _assert_browser_websocket_config(read_config(path), helm_defaults=path.startswith("deploy/helm/"))


@pytest.mark.parametrize("provisioner_enabled", [True, False])
def test_rendered_helm_live_browser_websocket_config(provisioner_enabled: bool) -> None:
    helm = shutil.which("helm")
    if helm is None:
        pytest.skip("helm is unavailable")
    command = [helm, "template", "deer-flow", str(CHART), "--show-only", "templates/configmap-nginx.yaml", "--set", f"provisioner.enabled={str(provisioner_enabled).lower()}"]
    rendered = subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8").stdout
    config_map = yaml.safe_load(rendered)
    _assert_browser_websocket_config(config_map["data"]["nginx.conf"], helm_defaults=True)
