"""Bounded, read-only startup checks shared by doctor and support bundles.

Only structured conclusions leave this module: Docker endpoints, command stderr,
process command lines and environment values are never included in reports.
"""

from __future__ import annotations

import argparse
import csv
import errno
import ipaddress
import json
import os
import platform
import re
import shutil
import socket
import subprocess


def _finding(code: str, status: str, label: str, detail: str = "", fix: str = "") -> dict:
    return {
        "code": code,
        "status": status,
        "label": label,
        "detail": detail,
        "fix": fix,
    }


def _command(args: list[str]) -> tuple[bool, str, str]:
    """Capture privately; callers only expose allowlisted fields or fixed messages."""
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
        return result.returncode == 0, result.stdout.strip(), "command failed"
    except subprocess.TimeoutExpired:
        return False, "", "timed out after 5s"
    except OSError:
        return False, "", "command unavailable"


def _local_docker_endpoint(docker: str) -> bool | None:
    # An explicit context takes precedence over DOCKER_HOST in the Docker CLI.
    if os.environ.get("DOCKER_HOST") and not os.environ.get("DOCKER_CONTEXT"):
        endpoint = os.environ["DOCKER_HOST"]
    else:
        ok, output, _ = _command(
            [
                docker,
                "context",
                "inspect",
                "--format",
                "{{json .Endpoints.docker.Host}}",
            ]
        )
        if not ok:
            return None
        try:
            endpoint = json.loads(output)
        except ValueError:
            return None
    if not isinstance(endpoint, str):
        return None
    if endpoint.startswith("npipe://"):
        # A named pipe may point at another Windows host, not the local Desktop.
        return endpoint.replace("\\", "/").startswith("npipe:////./pipe/")
    if endpoint.startswith("unix:///"):
        return True
    # TCP (even localhost), SSH and unknown contexts may forward to another host.
    return False


def _desktop_running() -> bool | None:
    tasklist = shutil.which("tasklist.exe")
    if tasklist is None:
        return None
    ok, output, _ = _command([tasklist, "/FI", "IMAGENAME eq Docker Desktop.exe", "/FO", "CSV", "/NH"])
    if not ok:
        return None
    return any(row and row[0].casefold() == "docker desktop.exe" for row in csv.reader(output.splitlines()))


def check_docker() -> tuple[list[dict], bool | None]:
    """Return Docker findings and whether its endpoint is known to be local."""
    docker = shutil.which("docker")
    if docker is None:
        return [
            _finding(
                "docker_cli_missing",
                "fail",
                "Docker CLI",
                "not found on PATH",
                "Install Docker Desktop (Windows/macOS) or Docker Engine (Linux), then reopen the terminal so docker is on PATH.",
            )
        ], None

    local = _local_docker_endpoint(docker)
    ok, output, failure = _command([docker, "info", "--format", "{{json .OSType}}"])
    if not ok:
        code = "docker_engine_unavailable"
        detail = f"CLI found, engine probe {failure}"
        fix = "Check docker context ls and DOCKER_HOST/DOCKER_CONTEXT; verify the selected engine is reachable and your user has access."
        if platform.system() == "Windows" and local:
            desktop = _desktop_running()
            if desktop is False:
                code = "docker_desktop_not_running"
                detail += "; Docker Desktop process not detected"
                fix = "If using Docker Desktop, open it and wait for the Linux engine to be ready, then retry. For a standalone engine, check its service and context instead."
            else:
                fix += " If using Docker Desktop, check its Troubleshoot panel and WSL 2 status (wsl --status); Desktop being open does not mean its engine is ready."
        elif local:
            fix += " Start Docker Desktop or the Docker service appropriate to your installation."
        return [_finding(code, "fail", "Docker engine", detail, fix)], local

    linux = output == '"linux"'
    windows = output == '"windows"'
    results = [
        _finding(
            "docker_engine",
            "ok" if linux else "fail" if windows else "warn",
            "Docker engine",
            "Linux engine reachable" if linux else "engine responded; Linux container mode not confirmed",
            "" if linux else "DeerFlow images require a Linux engine; in Docker Desktop select Linux containers.",
        )
    ]
    ok, output, _ = _command([docker, "compose", "version", "--short"])
    version = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:[-+][\w.-]+)?", output)
    supported = ok and version is not None and tuple(map(int, version.groups())) >= (2, 24, 0)
    results.append(
        _finding(
            "docker_compose",
            "ok" if supported else "fail",
            "Docker Compose",
            "Compose 2.24+ available" if supported else "Compose 2.24+ not confirmed",
            "" if supported else "Install/update Docker Compose v2 (2.24+) or Docker Desktop; verify docker compose version.",
        )
    )
    return results, local


def listener_pids(host: str, port: int) -> list[int]:
    """Best-effort Windows listener attribution; never return raw netstat output."""
    netstat = shutil.which("netstat.exe")
    if platform.system() != "Windows" or netstat is None:
        return []
    ok, output, _ = _command([netstat, "-ano"])
    if not ok:
        return []
    requested = ipaddress.ip_address(host)
    pids = set()
    for line in output.splitlines():
        fields = line.split()
        if len(fields) != 5 or fields[0] != "TCP" or fields[3] != "LISTENING" or not fields[4].isascii() or not fields[4].isdigit():
            continue
        address, _, raw_port = fields[1].rpartition(":")
        if raw_port != str(port):
            continue
        try:
            bound = ipaddress.ip_address(address.strip("[]"))
        except ValueError:
            continue
        # netstat does not reveal IPV6_V6ONLY; never assume IPv6 wildcard is dual-stack.
        if bound.version == requested.version and (bound == requested or bound.is_unspecified or requested.is_unspecified):
            pids.add(int(fields[4]))
    return sorted(pids)


def check_port(host: str, port: int) -> dict:
    address = ipaddress.ip_address(host)
    label = f"TCP bind {host}:{port}"
    try:
        with socket.socket(
            socket.AF_INET6 if address.version == 6 else socket.AF_INET,
            socket.SOCK_STREAM,
        ) as probe:
            # Windows otherwise allows a second bind to a listener that enabled reuse.
            if platform.system() == "Windows" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind((host, port))
    except OSError as exc:
        in_use = exc.errno == errno.EADDRINUSE or getattr(exc, "winerror", None) == 10048
        denied = exc.errno == errno.EACCES or getattr(exc, "winerror", None) == 10013
        # Winsock exclusive listeners can also cause WSAEACCES (10013).
        pids = listener_pids(host, port) if in_use or (denied and platform.system() == "Windows") else []
        if in_use or pids:
            detail = "already in use; it may be an existing DeerFlow service"
            if pids:
                detail += "; listener PID(s): " + ", ".join(map(str, pids))
            return _finding(
                "port_in_use",
                "warn",
                label,
                detail,
                "Inspect the listener before stopping anything. Reuse a healthy DeerFlow instance, or free the port before starting another. For Docker, you can change the published PORT.",
            )
        if denied:
            fix = "Check binding permissions and host policy."
            if platform.system() == "Windows":
                fix += " In PowerShell inspect netsh interface ipv4 show excludedportrange protocol=tcp (use ipv6 for an IPv6 bind); a reserved port is not proof of a running process."
            return _finding("port_access_denied", "fail", label, "bind access denied; an exclusive listener, reserved port, or host policy may be responsible", fix)
        return _finding(
            "port_unavailable",
            "warn",
            label,
            "could not bind this address",
            "Verify this IP belongs to the host and that its address family is enabled; retry the diagnostic on the deployment host.",
        )
    return _finding("port_available", "ok", label, "available at probe time (not reserved)")


def collect_startup_diagnostics(mode: str, *, host: str = "127.0.0.1", port: int = 2026) -> dict:
    """Probe explicit targets only; do not guess Compose dotenv precedence."""
    if mode not in {"local", "docker"}:
        raise ValueError("startup mode must be local or docker")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("startup port must be between 1 and 65535")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        raise ValueError("startup host must be a numeric IPv4 or IPv6 address") from None
    if mode == "local" and port != 2026:
        raise ValueError("local nginx uses port 2026; --startup-port applies to Docker only")

    checks = []
    if mode == "docker":
        checks, local = check_docker()
        if local is not True:
            checks.append(
                _finding(
                    "port_check_skipped",
                    "skip",
                    "Published Docker port",
                    "Docker endpoint is remote or could not be determined",
                    "Run port diagnostics on the Docker host; this machine's port availability does not describe a remote engine.",
                )
            )
        else:
            checks.append(check_port(host, port))
    else:
        checks = [
            check_port(host, 2026),
            check_port("127.0.0.1", 3000),
            check_port("127.0.0.1", 8001),
        ]
    return {
        "schema_version": 1,
        "mode": mode,
        "host": host,
        "port": port,
        "checks": checks,
    }


def add_startup_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--startup-mode",
        choices=("local", "docker"),
        default=None,
        help="Opt in to startup probes for local services or Docker",
    )
    parser.add_argument(
        "--startup-host",
        default="127.0.0.1",
        help="Numeric bind IP to probe (default: 127.0.0.1; not inferred from .env)",
    )
    parser.add_argument(
        "--startup-port",
        type=int,
        default=2026,
        help="Docker published port to probe (default: 2026; not inferred from .env)",
    )
