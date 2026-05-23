"""Health monitoring for the Start-Cloud service stack."""

import json
import os
import subprocess
import urllib.error
import urllib.request

from langchain_core.tools import tool

COMPOSE_DIR = os.environ.get("STARTCLOUD_COMPOSE_DIR", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", "..")))

SERVICES = {
    "keycloak": {"port": 8080, "url": "http://localhost:8080", "health": "/realms/master", "description": "Identity Provider (SSO)"},
    "vaultwarden": {"port": 8003, "url": "http://localhost:8003", "health": "/alive", "description": "Password Manager"},
    "teable": {"port": 8002, "url": "http://localhost:8002", "health": "/health", "description": "Spreadsheet / Database (Teable)"},
    "twenty-server": {"port": 3002, "url": "http://localhost:3002", "health": "/healthz", "description": "CRM (Twenty)"},
}


def _check_http(url: str, timeout: int = 5) -> tuple[bool, int]:
    """Check if an HTTP endpoint is responding."""
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, resp.status
    except urllib.error.HTTPError as e:
        return e.code < 500, e.code
    except Exception:
        return False, 0


def _get_container_status() -> dict:
    """Get Docker container statuses."""
    try:
        result = subprocess.run(
            ["docker", "compose", "-f", f"{COMPOSE_DIR}/docker-compose.yml", "ps", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=COMPOSE_DIR,
        )
        containers = {}
        for line in result.stdout.strip().split("\n"):
            if line.strip():
                try:
                    c = json.loads(line)
                    containers[c.get("Service", c.get("Name", "unknown"))] = {
                        "state": c.get("State", "unknown"),
                        "status": c.get("Status", "unknown"),
                    }
                except json.JSONDecodeError:
                    pass
        return containers
    except Exception as e:
        return {"error": str(e)}


@tool
def stack_status() -> str:
    """Check the health status of all Start-Cloud services.

    Returns a summary showing:
    - Container status (running/stopped)
    - HTTP health check results
    - Service URLs for browser access
    """
    containers = _get_container_status()

    lines = ["=== Start-Cloud Service Status ===\n"]

    for svc_name, svc_info in SERVICES.items():
        container = containers.get(svc_name, {})
        c_state = container.get("state", "not found")
        c_status = container.get("status", "")

        http_ok, http_code = _check_http(f"{svc_info['url']}{svc_info['health']}")
        health_icon = "✅" if http_ok else "❌"

        lines.append(f"{health_icon} {svc_name}")
        lines.append(f"   Description: {svc_info['description']}")
        lines.append(f"   Container:   {c_state} ({c_status})")
        lines.append(f"   HTTP:        {'OK' if http_ok else 'FAIL'} (status {http_code})")
        lines.append(f"   URL:         {svc_info['url']}")
        lines.append("")

    # Infrastructure services
    for infra in ["postgres", "redis"]:
        container = containers.get(infra, {})
        c_state = container.get("state", "not found")
        c_status = container.get("status", "")
        icon = "✅" if c_state == "running" else "❌"
        lines.append(f"{icon} {infra}")
        lines.append(f"   Container: {c_state} ({c_status})")
        lines.append("")

    return "\n".join(lines)
