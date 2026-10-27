import hashlib
import ipaddress
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from deerflow.config.sandbox_config import SandboxNetworkConfig


def test_pool_configuration_rejects_public_and_invalid_ranges():
    for value in ("8.8.0.0/16", "0.0.0.0/0", "127.0.0.0/8", "10.240.0.1/16", "::/64"):
        with pytest.raises(ValidationError):
            SandboxNetworkConfig(address_pool=value, subnet_prefix=28)
    with pytest.raises(ValidationError):
        SandboxNetworkConfig(address_pool="10.240.0.0/28", subnet_prefix=24)


def test_pool_skips_existing_networks_and_allocates_small_subnet(monkeypatch):
    from deerflow.community.aio_sandbox import subnet_pool

    commands = []

    def run(command, **kwargs):
        assert kwargs.get("encoding") == "utf-8", "Docker emits UTF-8 even on Windows GBK hosts"
        commands.append(command)
        if command[:3] == ["docker", "network", "ls"]:
            return SimpleNamespace(returncode=0, stdout="one\n", stderr="")
        if command[:3] == ["docker", "network", "inspect"]:
            return SimpleNamespace(returncode=0, stdout='[{"IPAM":{"Config":[{"Subnet":"10.240.0.0/28"}]}}]', stderr="")
        return SimpleNamespace(returncode=0, stdout="created", stderr="")

    monkeypatch.setattr(subnet_pool.subprocess, "run", run)
    result = subnet_pool.create_network(["docker", "network", "create", "--internal", "example"], {"address_pool": "10.240.0.0/27", "subnet_prefix": 28})
    assert result.returncode == 0
    created = commands[-1]
    assert created[created.index("--subnet") + 1] == "10.240.0.16/28"
    assert "--internal" in created


def test_pool_retries_docker_overlap_race(monkeypatch):
    from deerflow.community.aio_sandbox import subnet_pool

    attempts = []

    def run(command, **kwargs):
        if command[:3] == ["docker", "network", "ls"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        attempts.append(command[command.index("--subnet") + 1])
        return SimpleNamespace(returncode=1 if len(attempts) == 1 else 0, stdout="", stderr="Pool overlaps with other one on this address space")

    monkeypatch.setattr(subnet_pool.subprocess, "run", run)
    result = subnet_pool.create_network(["docker", "network", "create", "example"], {"address_pool": "10.240.0.0/24", "subnet_prefix": 28})
    assert result.returncode == 0
    assert len(set(attempts)) == 2
    assert all(ipaddress.ip_network(value).prefixlen == 28 for value in attempts)


def test_pool_does_not_retry_other_docker_failures(monkeypatch):
    from deerflow.community.aio_sandbox import subnet_pool

    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0 if "ls" in command else 1, stdout="", stderr="permission denied")

    monkeypatch.setattr(subnet_pool.subprocess, "run", run)
    assert subnet_pool.create_network(["docker", "network", "create", "example"], {"address_pool": "10.240.0.0/24", "subnet_prefix": 28}).returncode == 1
    assert len(calls) == 2


@pytest.mark.parametrize("protected", ["stopped-reference", "proxy-exists", "recent", "foreign-prefix", "none"])
def test_orphan_cleanup_preserves_references_and_only_reaps_our_old_networks(monkeypatch, protected):
    from deerflow.community.aio_sandbox import subnet_pool

    prefix = "other-prefix" if protected == "foreign-prefix" else "pool"
    digest = hashlib.sha256(f"{prefix}:sandbox".encode()).hexdigest()[:16]
    name = f"deer-flow-sandbox-net-{digest}"
    created = datetime.now(UTC) - timedelta(seconds=20 if protected == "recent" else 1200)
    network = {"Id": "network-id", "Name": name, "Created": created.isoformat(), "Containers": {}, "Labels": {"deerflow.role": "network", "deerflow.sandbox_id": "sandbox"}}
    containers = []
    if protected == "stopped-reference":
        containers = [{"Name": "/stopped", "NetworkSettings": {"Networks": {name: {}}}}]
    elif protected == "proxy-exists":
        containers = [{"Name": f"/deer-flow-netproxy-{digest}", "NetworkSettings": {"Networks": {}}}]
    removed = []

    def run(command, **kwargs):
        assert kwargs.get("encoding") == "utf-8", "Container metadata may include Chinese text"
        if command[:3] == ["docker", "network", "ls"]:
            output = "network-id"
        elif command[:3] == ["docker", "network", "inspect"]:
            output = json.dumps([network])
        elif command[:2] == ["docker", "ps"]:
            output = "container-id" if containers else ""
        elif command[:2] == ["docker", "inspect"]:
            output = json.dumps(containers)
        else:
            removed.append(command)
            output = "removed"
        return SimpleNamespace(returncode=0, stdout=output, stderr="")

    monkeypatch.setattr(subnet_pool.subprocess, "run", run)
    result = subnet_pool.cleanup_orphan_networks("pool")
    assert result == ([name] if protected == "none" else [])
    assert len(removed) == (1 if protected == "none" else 0)
