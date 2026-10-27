"""Allocate small bridge subnets; Docker remains the atomic allocation authority."""

import hashlib
import ipaddress
import json
import subprocess
from datetime import UTC, datetime


def create_network(command: list[str], config: dict) -> subprocess.CompletedProcess:
    pool_value = config.get("address_pool")
    if not pool_value:
        return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=15)
    pool = ipaddress.ip_network(str(pool_value), strict=True)
    prefix = int(config.get("subnet_prefix", 28))
    listed = subprocess.run(["docker", "network", "ls", "--quiet"], capture_output=True, text=True, encoding="utf-8", timeout=15)
    if listed.returncode:
        raise RuntimeError("Cannot inspect Docker networks before allocating a sandbox subnet")
    occupied = []
    ids = listed.stdout.split()
    if ids:
        inspected = subprocess.run(["docker", "network", "inspect", *ids], capture_output=True, text=True, encoding="utf-8", timeout=15)
        if inspected.returncode:
            raise RuntimeError("Cannot inspect Docker network subnets; retry sandbox acquisition")
        for network in json.loads(inspected.stdout):
            for entry in (network.get("IPAM") or {}).get("Config") or []:
                if subnet := entry.get("Subnet"):
                    parsed = ipaddress.ip_network(subnet, strict=False)
                    if parsed.version == 4:
                        occupied.append(parsed)
    subnets = list(pool.subnets(new_prefix=prefix))
    # Stable dispersion reduces contention when several users create networks.
    start = int.from_bytes(hashlib.sha256(command[-1].encode()).digest()[:4], "big") % len(subnets)
    for index in range(len(subnets)):
        candidate = subnets[(start + index) % len(subnets)]
        if any(candidate.overlaps(existing) for existing in occupied):
            continue
        result = subprocess.run([*command[:-1], "--subnet", str(candidate), command[-1]], capture_output=True, text=True, encoding="utf-8", timeout=15)
        if result.returncode == 0 or "pool overlaps" not in result.stderr.lower():
            return result
        # Another creator won this subnet after inspection. Try a different one.
    raise RuntimeError(f"Sandbox address pool {pool} has no free /{prefix} subnets")


def cleanup_orphan_networks(container_prefix: str, *, grace_seconds: int = 600) -> list[str]:
    """Reap only our aged networks without live OR stopped container references.

    Caller must hold the user-pool creation lock and the single-Gateway lease.
    Docker itself rejects removal if an endpoint connects after inspection.
    """

    def inspect(kind):
        command = ["docker", "network", "ls", "--quiet", "--filter", "label=deerflow.sandbox_id"] if kind == "network" else ["docker", "ps", "--all", "--quiet"]
        listed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=15)
        if listed.returncode:
            raise RuntimeError("Cannot enumerate resources for sandbox network cleanup")
        ids = listed.stdout.split()
        if not ids:
            return []
        command = ["docker", "network", "inspect", *ids] if kind == "network" else ["docker", "inspect", *ids]
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=15)
        if result.returncode:
            raise RuntimeError("Cannot inspect resources for sandbox network cleanup")
        return json.loads(result.stdout)

    networks, containers = inspect("network"), inspect("container")
    container_names = {entry.get("Name", "").lstrip("/") for entry in containers}
    referenced = {name for entry in containers for name in (entry.get("NetworkSettings") or {}).get("Networks", {})}
    removed = []
    now = datetime.now(UTC)
    for network in networks:
        labels = network.get("Labels") or {}
        sandbox_id = labels.get("deerflow.sandbox_id")
        role = labels.get("deerflow.role")
        if not sandbox_id or role not in {"network", "egress-network"}:
            continue
        digest = hashlib.sha256(f"{container_prefix}:{sandbox_id}".encode()).hexdigest()[:16]
        expected = f"deer-flow-sandbox-{'net' if role == 'network' else 'egress'}-{digest}"
        if network.get("Name") != expected or network.get("Containers") or expected in referenced:
            continue
        if f"{container_prefix}-{sandbox_id}" in container_names or f"deer-flow-netproxy-{digest}" in container_names:
            continue
        try:
            created = datetime.fromisoformat(network["Created"].replace("Z", "+00:00"))
            if (now - created).total_seconds() < grace_seconds:
                continue
        except (ValueError, TypeError, KeyError):
            continue
        result = subprocess.run(["docker", "network", "rm", network["Id"]], capture_output=True, text=True, encoding="utf-8", timeout=15)
        if result.returncode == 0:
            removed.append(expected)
    return removed
