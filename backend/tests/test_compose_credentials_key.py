"""Both compose stacks pass ``DEER_FLOW_CREDENTIALS_KEY`` through to the Gateway.

``scripts/deploy.sh`` resolves the key (shell, ``.env``, the persisted
``$DEER_FLOW_HOME/.credentials_key``, or a freshly generated one) and Compose
interpolates it into the gateway service. ``:-`` keeps a stack started without
the deploy script quiet: an empty value makes the Gateway fall back to the same
``.credentials_key`` file under its runtime home, which is the host's
``DEER_FLOW_HOME`` bind mount.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATHS = {
    "prod": REPO_ROOT / "docker" / "docker-compose.yaml",
    "dev": REPO_ROOT / "docker" / "docker-compose-dev.yaml",
}
EXPECTED_ENTRY = "DEER_FLOW_CREDENTIALS_KEY=${DEER_FLOW_CREDENTIALS_KEY:-}"


@pytest.mark.parametrize("variant", sorted(COMPOSE_PATHS))
def test_gateway_receives_the_credentials_key(variant: str) -> None:
    services = yaml.safe_load(COMPOSE_PATHS[variant].read_text(encoding="utf-8"))["services"]

    assert EXPECTED_ENTRY in services["gateway"]["environment"]
    assert "DEER_FLOW_HOME=/app/backend/.deer-flow" in services["gateway"]["environment"], "the fallback key file lives in the runtime home"


@pytest.mark.parametrize("variant", sorted(COMPOSE_PATHS))
def test_only_the_gateway_receives_the_credentials_key(variant: str) -> None:
    services = yaml.safe_load(COMPOSE_PATHS[variant].read_text(encoding="utf-8"))["services"]
    for name, service in services.items():
        if name == "gateway":
            continue
        environment = service.get("environment") or []
        entries = environment if isinstance(environment, list) else [f"{key}={value}" for key, value in environment.items()]
        assert not any(str(entry).startswith("DEER_FLOW_CREDENTIALS_KEY") for entry in entries), name
