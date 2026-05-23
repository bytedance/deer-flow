"""Docker Compose lifecycle management for the Start-Cloud stack."""

import os
import subprocess

from langchain_core.tools import tool

COMPOSE_DIR = os.environ.get("STARTCLOUD_COMPOSE_DIR", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", "..")))


def _run_compose(args: list[str], timeout: int = 120) -> str:
    """Run a docker compose command and return output."""
    cmd = ["docker", "compose", "-f", f"{COMPOSE_DIR}/docker-compose.yml"] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=COMPOSE_DIR,
        )
        output = result.stdout
        if result.returncode != 0:
            output += f"\n[STDERR]: {result.stderr}"
        return output.strip()
    except subprocess.TimeoutExpired:
        return f"ERROR: Command timed out after {timeout}s: {' '.join(cmd)}"
    except Exception as e:
        return f"ERROR: {e}"


@tool
def stack_deploy(action: str, service: str = "all") -> str:
    """Deploy, restart, or stop the Start-Cloud service stack.

    Args:
        action: One of 'up', 'down', 'restart', 'logs', 'pull'
        service: 'all' for entire stack, or specific service name
                 (postgres, keycloak, vaultwarden, nocodb, twenty-server, twenty-worker, redis)
    """
    valid_actions = {"up", "down", "restart", "logs", "pull"}
    if action not in valid_actions:
        return f"Invalid action '{action}'. Must be one of: {', '.join(valid_actions)}"

    service_args = [] if service == "all" else [service]

    if action == "up":
        args = ["up", "-d", "--remove-orphans"] + service_args
        result = _run_compose(args, timeout=300)
        status = _run_compose(["ps", "--format", "json"])
        return f"Stack deploy result:\n{result}\n\nCurrent status:\n{status}"

    elif action == "down":
        args = ["down"] + service_args
        return _run_compose(args)

    elif action == "restart":
        args = ["restart"] + service_args
        result = _run_compose(args)
        status = _run_compose(["ps", "--format", "json"])
        return f"Restart result:\n{result}\n\nCurrent status:\n{status}"

    elif action == "logs":
        args = ["logs", "--tail", "50"] + service_args
        return _run_compose(args)

    elif action == "pull":
        args = ["pull"] + service_args
        return _run_compose(args, timeout=600)

    return "Unknown action"
