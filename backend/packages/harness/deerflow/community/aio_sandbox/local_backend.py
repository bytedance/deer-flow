"""Local container backend for sandbox provisioning.

Manages sandbox containers using Docker or Apple Container on the local machine.
Handles container lifecycle, port allocation, and cross-process container discovery.
"""

from __future__ import annotations

import csv
import ipaddress
import json
import logging
import os
import posixpath
import shlex
import socket
import subprocess
from datetime import datetime

from deerflow.utils.network import get_free_port, release_port

from .backend import SandboxBackend, wait_for_sandbox_ready
from .sandbox_info import SandboxInfo

logger = logging.getLogger(__name__)


def _parse_docker_timestamp(raw: str) -> float:
    """Parse Docker's ISO 8601 timestamp into a Unix epoch float.

    Docker returns timestamps with nanosecond precision and a trailing ``Z``
    (e.g. ``2026-04-08T01:22:50.123456789Z``).  Python's ``fromisoformat``
    accepts at most microseconds and (pre-3.11) does not accept ``Z``, so the
    string is normalized before parsing.  Returns ``0.0`` on empty input or
    parse failure so callers can use ``0.0`` as a sentinel for "unknown age".
    """
    if not raw:
        return 0.0
    try:
        s = raw.strip()
        if "." in s:
            dot_pos = s.index(".")
            tz_start = dot_pos + 1
            while tz_start < len(s) and s[tz_start].isdigit():
                tz_start += 1
            frac = s[dot_pos + 1 : tz_start][:6]  # truncate to microseconds
            tz_suffix = s[tz_start:]
            s = s[: dot_pos + 1] + frac + tz_suffix
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s).timestamp()
    except (ValueError, TypeError) as e:
        logger.debug(f"Could not parse docker timestamp {raw!r}: {e}")
        return 0.0


def _extract_host_port(inspect_entry: dict, container_port: int) -> int | None:
    """Extract the host port mapped to ``container_port/tcp`` from a docker inspect entry.

    Returns None if the container has no port mapping for that port.
    """
    try:
        ports = (inspect_entry.get("NetworkSettings") or {}).get("Ports") or {}
        bindings = ports.get(f"{container_port}/tcp") or []
        if bindings:
            host_port = bindings[0].get("HostPort")
            if host_port:
                return int(host_port)
    except (ValueError, TypeError, AttributeError):
        pass
    return None


def _format_container_mount(runtime: str, host_path: str, container_path: str, read_only: bool) -> list[str]:
    """Format a bind-mount argument for the selected runtime.

    Docker's ``-v host:container`` syntax is ambiguous for Windows drive-letter
    paths like ``D:/...`` because ``:`` is both the drive separator and the
    volume separator. Use ``--mount type=bind,...`` for Docker to avoid that
    parsing ambiguity. Apple Container keeps using ``-v``.
    """
    if runtime == "docker":
        mount_spec = f"type=bind,src={host_path},dst={container_path}"
        if read_only:
            mount_spec += ",readonly"
        return ["--mount", mount_spec]

    mount_spec = f"{host_path}:{container_path}"
    if read_only:
        mount_spec += ":ro"
    return ["-v", mount_spec]


def _redact_container_command_for_log(cmd: list[str]) -> list[str]:
    """Return a Docker/Container command with environment values redacted."""
    redacted: list[str] = []
    redact_next_env = False

    for arg in cmd:
        if redact_next_env:
            if "=" in arg:
                key = arg.split("=", 1)[0]
                redacted.append(f"{key}=<redacted>" if key else "<redacted>")
            else:
                redacted.append(arg)
            redact_next_env = False
            continue

        if arg in {"-e", "--env"}:
            redacted.append(arg)
            redact_next_env = True
            continue

        if arg.startswith("--env="):
            value = arg.removeprefix("--env=")
            if "=" in value:
                key = value.split("=", 1)[0]
                redacted.append(f"--env={key}=<redacted>" if key else "--env=<redacted>")
            else:
                redacted.append(arg)
            continue

        redacted.append(arg)

    return redacted


def _format_container_command_for_log(cmd: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(cmd)
    return shlex.join(cmd)


def _normalize_sandbox_host(host: str) -> str:
    return host.strip().lower()


def _is_ipv6_loopback_sandbox_host(host: str) -> bool:
    return _normalize_sandbox_host(host) in {"::1", "[::1]"}


def _is_loopback_sandbox_host(host: str) -> bool:
    return _normalize_sandbox_host(host) in {"", "localhost", "127.0.0.1", "::1", "[::1]"}


def _is_ip_bind_spec(value: str) -> bool:
    """Return True when ``value`` (bare or bracketed) is an IP literal."""
    inner = value.strip()
    if inner.startswith("[") and inner.endswith("]"):
        inner = inner[1:-1]
    try:
        ipaddress.ip_address(inner)
        return True
    except ValueError:
        return False


def _normalize_docker_bind_spec(value: str) -> str:
    """Bracket bare IPv6 literals for Docker's ``-p`` publish syntax.

    Docker requires the host part of a publish spec to be a bracketed IPv6
    literal (``[fd00::1]:port:8080``), but operators writing the bind override
    naturally give the bare address. Raw and already-bracketed IPv6 forms are
    normalized; IPv4 addresses and hostnames pass through unchanged.
    """
    candidate = value.strip()
    inner = candidate
    if candidate.startswith("[") and candidate.endswith("]"):
        inner = candidate[1:-1]
    try:
        if ipaddress.ip_address(inner).version == 6:
            return f"[{inner}]"
    except ValueError:
        pass
    return candidate


# Fallback gateway of Docker's default bridge network (docker0). Used when the
# daemon cannot be queried (see _docker_bridge_gateway_ip) so non-loopback
# sandbox deployments still get a host-only bind instead of 0.0.0.0.
_DOCKER_BRIDGE_GATEWAY_FALLBACK = "172.17.0.1"

# Hardening defaults for sandbox containers. The sandbox executes untrusted,
# model-authored code, so containers get bounded resources by default; every
# value can be tuned or disabled through the corresponding DEER_FLOW_SANDBOX_*
# environment variable (see _start_container).
_DEFAULT_SANDBOX_MEMORY = "2g"
_DEFAULT_SANDBOX_CPUS = "2"
_DEFAULT_SANDBOX_PIDS_LIMIT = "512"


def _docker_bridge_gateway_ip() -> str | None:
    """Return the gateway IPv4 of Docker's default bridge network, or None.

    The gateway is discovered from the daemon (``docker network inspect
    bridge``) because the address is deployment-specific: daemons with a
    custom ``bip`` or rootless/multi-network setups do not use 172.17.0.1.
    Any failure (docker missing, daemon down, unparsable or non-IPv4 output)
    returns None so the caller can fall back to the well-known default.
    """
    try:
        result = subprocess.run(
            [
                "docker",
                "network",
                "inspect",
                "bridge",
                "--format",
                "{{(index .IPAM.Config 0).Gateway}}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.debug(f"Could not query Docker bridge gateway: {e}")
        return None
    if result.returncode != 0:
        logger.debug(f"docker network inspect bridge failed: {(result.stderr or '').strip()}")
        return None
    candidate = (result.stdout or "").strip()
    try:
        if ipaddress.ip_address(candidate).version != 4:
            return None
    except ValueError:
        return None
    return candidate


def _resolve_docker_bind_host(sandbox_host: str | None = None, bind_host: str | None = None) -> str:
    """Choose the host interface for legacy Docker ``-p`` sandbox publishing.

    Bare-metal/local runs talk to sandboxes through localhost and bind to
    127.0.0.1, so the sandbox HTTP API (which has no authentication — anyone
    who can reach it gets arbitrary shell execution) is never exposed on
    other host interfaces.

    Non-loopback sandbox hosts (typically Docker-outside-of-Docker via
    ``host.docker.internal``) used to bind 0.0.0.0, which published the
    unauthenticated exec API on every interface of the host. They now bind
    the address the sandbox host itself resolves to: ``host.docker.internal``
    follows the daemon's ``host-gateway-ip`` mapping (customizable, possibly
    IPv6), so resolving it yields exactly where the gateway will connect —
    the published port and the advertised sandbox URL always match. Only
    when resolution fails does the default bridge gateway serve as a
    best-effort fallback (with a warning). Operators that genuinely need the
    old broad bind (e.g. remote clients connecting to the sandbox API
    directly) can restore it with ``DEER_FLOW_SANDBOX_BIND_HOST=0.0.0.0`` —
    that re-exposes an unauthenticated shell endpoint and should be paired
    with an external firewall. When operators choose an IPv6 loopback
    sandbox host, bind Docker to IPv6 loopback as well so the advertised
    sandbox URL and published socket use the same address family.
    """
    explicit_bind = bind_host if bind_host is not None else os.environ.get("DEER_FLOW_SANDBOX_BIND_HOST", "").strip()
    if explicit_bind:
        explicit_bind = _normalize_docker_bind_spec(explicit_bind)
        if explicit_bind and not _is_ip_bind_spec(explicit_bind):
            # -p requires an IP literal as the host part; Docker rejects a
            # hostname there, which would prevent every sandbox from
            # starting. Resolve hostname overrides to the address the daemon
            # actually maps (e.g. host.docker.internal -> host-gateway-ip).
            resolved = _resolve_sandbox_host_address(explicit_bind)
            if resolved is None:
                raise RuntimeError(
                    f"DEER_FLOW_SANDBOX_BIND_HOST={explicit_bind!r} is not an IP literal and could not be resolved; "
                    "Docker publish specs require an IP address as the host part. "
                    "Set an IPv4/IPv6 literal (bare or bracketed) or a resolvable hostname."
                )
            explicit_bind = resolved
        if explicit_bind:
            logger.debug("Docker sandbox bind: %s (explicit bind host override)", explicit_bind)
            return explicit_bind

    host = sandbox_host if sandbox_host is not None else os.environ.get("DEER_FLOW_SANDBOX_HOST", "localhost")
    if _is_ipv6_loopback_sandbox_host(host):
        logger.debug("Docker sandbox bind: [::1] (IPv6 loopback sandbox host)")
        return "[::1]"
    if _is_loopback_sandbox_host(host):
        logger.debug("Docker sandbox bind: 127.0.0.1 (loopback default)")
        return "127.0.0.1"

    resolved = _resolve_sandbox_host_address(host)
    if resolved:
        logger.debug(
            "Docker sandbox bind: %s (resolved from sandbox host %r, follows the daemon host-gateway mapping)",
            resolved,
            host,
        )
        return resolved

    # Resolution failed (unusual — e.g. a custom hostname with no DNS entry
    # yet). Fall back to the default bridge gateway so non-loopback setups
    # still get a host-only bind, and tell the operator to set the explicit
    # override when their host-gateway-ip is customized or IPv6.
    gateway = _docker_bridge_gateway_ip() or _DOCKER_BRIDGE_GATEWAY_FALLBACK
    logger.warning(
        "Could not resolve sandbox host %r for the Docker bind; falling back to the default bridge gateway %s. If the daemon's host-gateway-ip is customized or IPv6, set DEER_FLOW_SANDBOX_BIND_HOST to that address explicitly.",
        host,
        gateway,
    )
    return gateway


def _env_flag_enabled(name: str) -> bool:
    """Return True when environment variable ``name`` holds an affirmative value."""
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _env_flag_disabled(name: str) -> bool:
    """Return True when ``name`` is explicitly set to a negative value.

    For flags whose behavior defaults to ON, only an explicit opt-out
    (``0``/``false``/``no``/``off``) counts as disabled; any other value,
    including unset, keeps the default.
    """
    return os.environ.get(name, "").strip().lower() in {"0", "false", "no", "off"}


def _strip_ipv6_brackets(value: str) -> str:
    """Return ``value`` without IPv6 URL-style brackets, if any."""
    inner = value.strip()
    if inner.startswith("[") and inner.endswith("]"):
        return inner[1:-1]
    return inner


def _normalize_sandbox_host_for_url(host: str) -> str:
    """Bracket IPv6 literals exactly once for a URL authority (``host:port``).

    ``http://fd00::1:8080`` is malformed — the URL authority form requires
    brackets around IPv6 (``http://[fd00::1]:8080``), while operators (and
    DEER_FLOW_SANDBOX_HOST) may carry the address in either bare or
    bracketed form. Strip first, re-bracket once, so both inputs produce the
    same URL; IPv4 addresses and hostnames pass through unchanged.
    """
    inner = _strip_ipv6_brackets(host)
    try:
        if ipaddress.ip_address(inner).version == 6:
            return f"[{inner}]"
    except ValueError:
        pass
    return inner


def _resolve_sandbox_host_address(host: str) -> str | None:
    """Resolve ``host`` to the bind spec Docker should publish sandboxes on.

    ``host.docker.internal`` resolves to whatever the daemon's
    ``host-gateway-ip`` maps it to (customizable and possibly IPv6), so the
    address the gateway will actually *connect* to is exactly this
    resolution — binding it keeps the published port and the advertised
    sandbox URL on the same address instead of guessing the default bridge
    IPv4. IPv6 results are bracketed for Docker's ``-p`` syntax. Returns
    None when the name cannot be resolved.
    """
    # getaddrinfo takes the bare form; a bracketed IPv6 literal (legal in
    # DEER_FLOW_SANDBOX_HOST) would fail to resolve and silently fall back
    # to the IPv4 bridge gateway, splitting the bind from the URL address.
    lookup = _strip_ipv6_brackets(host)
    try:
        infos = socket.getaddrinfo(lookup, None)
    except OSError as e:
        logger.debug(f"Could not resolve sandbox host {host!r}: {e}")
        return None
    for family, _, _, _, sockaddr in infos:
        ip = sockaddr[0]
        if family == socket.AF_INET6:
            # Drop any zone id (%eth0) — Docker bind specs do not accept it.
            ip = ip.split("%", 1)[0]
            if ip in ("::",):
                continue
            return f"[{ip}]"
        if family == socket.AF_INET and ip not in ("0.0.0.0",):
            return ip
    return None


def _effective_docker_network_target(raw: str) -> str:
    r"""Return the network Docker will actually attach to for ``--network raw``.

    Mirrors Docker CLI's parser (opts/network.go): a value without ``=`` is
    the short syntax — the whole value is a network name or ID. A value with
    ``=`` is the long syntax — a CSV of ``key=value`` fields in any order
    (``name=``, ``alias=``, ``ip=``, ``ip6=``, ``mac-address=``,
    ``link-local-ip=``, ``driver-opt=``, ``gw-priority=``) — and the network
    is the value of the ``name=`` field, with the last occurrence winning
    and fields lowercased, exactly as Docker does it.

    Validation must run on this effective value: neither ``name=host`` nor
    ``gw-priority=0,name=host`` reads as the bare word ``host``, but both
    attach the host network namespace all the same, silently voiding the
    port publish. A long-syntax value with no ``name=`` field cannot name a
    network at all (Docker rejects it as well), so the raw value is returned
    and falls through the checks harmlessly.
    """
    value = raw.strip()
    if "=" not in value:
        return value.lower()
    target = ""
    for field in next(csv.reader([value])):
        key, _, val = field.partition("=")
        key = key.strip().lower()
        val = val.strip().lower()  # Docker lowercases the whole field as well
        if key == "name":
            target = val  # last name= wins, mirroring the loop in network.go
    return target or value.lower()


def _docker_resource_limit(env_name: str, default: str) -> str | None:
    """Resolve a Docker resource limit from the environment with a safe default.

    Unset/empty keeps the secure default; ``0`` or ``none`` disables the limit
    entirely (escape hatch for hosts where the default breaks a workload);
    any other value is passed through verbatim so operators can tune it.
    """
    raw = os.environ.get(env_name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip()
    if value.lower() in {"0", "none"}:
        return None
    return value


def _is_no_such_container_error(stderr: str, container_name: str) -> bool:
    """Return True only when stderr definitively says the container does not exist.

    Docker reports "No such object" / "No such container". Apple Container
    reports a generic "not found", so that phrase is only trusted when the
    message also names the inspected container (or refers to a
    container/object); transient failures whose text happens to contain
    "not found" (e.g. "command not found", "context not found") must stay on
    the raise path instead of being misread as a dead container.
    """
    message = stderr.lower()
    if "no such object" in message or "no such container" in message:
        return True
    if "not found" not in message:
        return False
    return container_name.lower() in message or "container" in message or "object" in message


class LocalContainerBackend(SandboxBackend):
    """Backend that manages sandbox containers locally using Docker or Apple Container.

    On macOS, automatically prefers Apple Container if available, otherwise falls back to Docker.
    On other platforms, uses Docker.

    Features:
    - Deterministic container naming for cross-process discovery
    - Port allocation with thread-safe utilities
    - Container lifecycle management (start/stop with --rm)
    - Support for volume mounts and environment variables
    """

    # Wall clock for a single `stop`. Comfortably above the runtime's own default
    # SIGKILL escalation (10s for docker/podman), so this only fires when the
    # daemon itself is wedged rather than truncating a slow-but-progressing stop.
    _STOP_TIMEOUT_SECONDS = 120.0

    def __init__(
        self,
        *,
        image: str,
        base_port: int,
        container_prefix: str,
        config_mounts: list,
        environment: dict[str, str],
    ):
        """Initialize the local container backend.

        Args:
            image: Container image to use.
            base_port: Base port number to start searching for free ports.
            container_prefix: Prefix for container names (e.g., "deer-flow-sandbox").
            config_mounts: Volume mount configurations from config (list of VolumeMountConfig).
            environment: Environment variables to inject into containers.
        """
        self._image = image
        self._base_port = base_port
        self._container_prefix = container_prefix
        self._config_mounts = config_mounts
        self._environment = environment
        self._runtime = self._detect_runtime()

    @property
    def runtime(self) -> str:
        """The detected container runtime ("docker" or "container")."""
        return self._runtime

    def _detect_runtime(self) -> str:
        """Detect which container runtime to use.

        On macOS, prefer Apple Container if available, otherwise fall back to Docker.
        On other platforms, use Docker.

        Returns:
            "container" for Apple Container, "docker" for Docker.
        """
        import platform

        if platform.system() == "Darwin":
            try:
                result = subprocess.run(
                    ["container", "--version"],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=5,
                )
                logger.info(f"Detected Apple Container: {result.stdout.strip()}")
                return "container"
            except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
                logger.info("Apple Container not available, falling back to Docker")

        return "docker"

    # ── SandboxBackend interface ──────────────────────────────────────────

    def create(
        self,
        thread_id: str | None,
        sandbox_id: str,
        extra_mounts: list[tuple[str, str, bool]] | None = None,
        *,
        config_mount_exclusion_root: str | None = None,
        user_id: str | None = None,
        provision_lark_cli_runtime: bool = False,
        provision_lark_cli_broker: bool = False,
    ) -> SandboxInfo:
        """Start a new container and return its connection info.

        Args:
            thread_id: Thread ID for which the sandbox is being created. Useful for backends that want to organize sandboxes by thread.
            sandbox_id: Deterministic sandbox identifier (used in container name).
            extra_mounts: Additional volume mounts as (host_path, container_path, read_only) tuples.
            config_mount_exclusion_root: Exclude config-level mounts at or
                below this container path. Policy-scoped skill projections use
                this to prevent a nested operator mount from overlaying an
                excluded skill back into the restricted view.
            user_id: User bucket already reflected in extra_mounts. Accepted for
                interface compatibility with remote backends.
            provision_lark_cli_runtime: Ignored — the local backend provisions the
                lark-cli runtime via the Gateway-download bind mount in extra_mounts.
            provision_lark_cli_broker: Ignored — the local backend has no sandbox
                boundary to protect, so it keeps the credential-mount overlay.

        Returns:
            SandboxInfo with container details.

        Raises:
            RuntimeError: If the container fails to start.
        """
        del user_id, provision_lark_cli_runtime, provision_lark_cli_broker
        container_name = f"{self._container_prefix}-{sandbox_id}"

        # Retry loop: if Docker rejects the port (e.g. a stale container still
        # holds the binding after a process restart), skip that port and try the
        # next one.  The socket-bind check in get_free_port mirrors Docker's
        # 0.0.0.0 bind, but Docker's port-release can be slightly asynchronous,
        # so a reactive fallback here ensures we always make progress.
        _next_start = self._base_port
        container_id: str | None = None
        port: int = 0
        for _attempt in range(10):
            port = get_free_port(start_port=_next_start)
            try:
                container_id = self._start_container(
                    container_name,
                    port,
                    extra_mounts,
                    config_mount_exclusion_root=config_mount_exclusion_root,
                )
                break
            except RuntimeError as exc:
                release_port(port)
                err = str(exc)
                err_lower = err.lower()
                # Port already bound: skip this port and retry with the next one.
                if "port is already allocated" in err or "address already in use" in err_lower:
                    logger.warning(f"Port {port} rejected by Docker (already allocated), retrying with next port")
                    _next_start = port + 1
                    continue
                # Container-name conflict: another process may have already started
                # the deterministic sandbox container for this sandbox_id. Try to
                # discover and adopt the existing container instead of failing.
                if "is already in use by container" in err_lower or "conflict. the container name" in err_lower:
                    logger.warning(f"Container name {container_name} already in use, attempting to discover existing sandbox instance")
                    existing = self.discover(sandbox_id)
                    if existing is not None:
                        return existing
                raise
        else:
            raise RuntimeError("Could not start sandbox container: all candidate ports are already allocated by Docker")

        # When running inside Docker (DooD), sandbox containers are reachable via
        # host.docker.internal rather than localhost (they run on the host daemon).
        sandbox_host = _normalize_sandbox_host_for_url(os.environ.get("DEER_FLOW_SANDBOX_HOST", "localhost"))
        return SandboxInfo(
            sandbox_id=sandbox_id,
            sandbox_url=f"http://{sandbox_host}:{port}",
            container_name=container_name,
            container_id=container_id,
        )

    def destroy(self, info: SandboxInfo) -> None:
        """Stop the container and release its port."""
        # Prefer container_id, fall back to container_name (both accepted by docker stop).
        # This ensures containers discovered via list_running() (which only has the name)
        # can also be stopped.
        stop_target = info.container_id or info.container_name
        if stop_target:
            self._stop_container(stop_target)
        # Extract port from sandbox_url for release
        try:
            from urllib.parse import urlparse

            port = urlparse(info.sandbox_url).port
            if port:
                release_port(port)
        except Exception:
            pass

    def is_alive(self, info: SandboxInfo) -> bool:
        """Check if the container is still running (lightweight, no HTTP)."""
        if info.container_name:
            return self._is_container_running(info.container_name)
        return False

    def discover(self, sandbox_id: str) -> SandboxInfo | None:
        """Discover an existing container by its deterministic name.

        Checks if a container with the expected name is running, retrieves its
        port, and verifies it responds to health checks.

        Args:
            sandbox_id: The deterministic sandbox ID (determines container name).

        Returns:
            SandboxInfo if container found and healthy, None otherwise. A
            failed runtime check (e.g. transient daemon error) also returns
            None — discovery must not adopt a container it cannot verify, and
            falling through to create keeps acquire recoverable instead of
            hard-failing on a hiccup.
        """
        container_name = f"{self._container_prefix}-{sandbox_id}"

        try:
            running = self._is_container_running(container_name)
        except RuntimeError as e:
            logger.warning(f"Could not verify container {container_name} during discovery; not adopting it: {e}")
            return None

        if not running:
            return None

        port = self._get_container_port(container_name)
        if port is None:
            return None

        sandbox_host = _normalize_sandbox_host_for_url(os.environ.get("DEER_FLOW_SANDBOX_HOST", "localhost"))
        sandbox_url = f"http://{sandbox_host}:{port}"
        if not wait_for_sandbox_ready(sandbox_url, timeout=5):
            return None

        return SandboxInfo(
            sandbox_id=sandbox_id,
            sandbox_url=sandbox_url,
            container_name=container_name,
        )

    def list_running(self) -> list[SandboxInfo]:
        """Enumerate all running containers matching the configured prefix.

        Uses a single ``docker ps`` call to list container names, then a
        single batched ``docker inspect`` call to retrieve creation timestamp
        and port mapping for all containers at once.  Total subprocess calls:
        2 (down from 2N+1 in the naive per-container approach).

        Note: Docker's ``--filter name=`` performs *substring* matching,
        so a secondary ``startswith`` check is applied to ensure only
        containers with the exact prefix are included.

        Containers without port mappings are still included (with empty
        sandbox_url) so that startup reconciliation can adopt orphans
        regardless of their port state.
        """
        # Step 1: enumerate container names via docker ps
        try:
            result = subprocess.run(
                [
                    self._runtime,
                    "ps",
                    "--filter",
                    f"name={self._container_prefix}-",
                    "--format",
                    "{{.Names}}",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                stderr = (result.stderr or "").strip()
                logger.warning(
                    "Failed to list running containers with %s ps (returncode=%s, stderr=%s)",
                    self._runtime,
                    result.returncode,
                    stderr or "<empty>",
                )
                return []
            if not result.stdout.strip():
                return []
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            logger.warning(f"Failed to list running containers: {e}")
            return []

        # Filter to names matching our exact prefix (docker filter is substring-based)
        container_names = [name.strip() for name in result.stdout.strip().splitlines() if name.strip().startswith(self._container_prefix + "-")]
        if not container_names:
            return []

        # Step 2: batched docker inspect — single subprocess call for all containers
        inspections = self._batch_inspect(container_names)

        infos: list[SandboxInfo] = []
        sandbox_host = _normalize_sandbox_host_for_url(os.environ.get("DEER_FLOW_SANDBOX_HOST", "localhost"))
        for container_name in container_names:
            data = inspections.get(container_name)
            if data is None:
                # Container disappeared between ps and inspect, or inspect failed
                continue
            created_at, host_port = data
            sandbox_id = container_name[len(self._container_prefix) + 1 :]
            sandbox_url = f"http://{sandbox_host}:{host_port}" if host_port else ""

            infos.append(
                SandboxInfo(
                    sandbox_id=sandbox_id,
                    sandbox_url=sandbox_url,
                    container_name=container_name,
                    created_at=created_at,
                )
            )

        logger.info(f"Found {len(infos)} running sandbox container(s)")
        return infos

    def _batch_inspect(self, container_names: list[str]) -> dict[str, tuple[float, int | None]]:
        """Batch-inspect containers in a single subprocess call.

        Returns a mapping of ``container_name -> (created_at, host_port)``.
        Missing containers or parse failures are silently dropped from the result.
        """
        if not container_names:
            return {}
        try:
            result = subprocess.run(
                [self._runtime, "inspect", *container_names],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            logger.warning(f"Failed to batch-inspect containers: {e}")
            return {}

        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            logger.warning(
                "Failed to batch-inspect containers with %s inspect (returncode=%s, stderr=%s)",
                self._runtime,
                result.returncode,
                stderr or "<empty>",
            )
            return {}

        try:
            payload = json.loads(result.stdout or "[]")
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse docker inspect output as JSON: {e}")
            return {}

        out: dict[str, tuple[float, int | None]] = {}
        for entry in payload:
            # ``Name`` is prefixed with ``/`` in the docker inspect response
            name = (entry.get("Name") or "").lstrip("/")
            if not name:
                continue
            created_at = _parse_docker_timestamp(entry.get("Created", ""))
            host_port = _extract_host_port(entry, 8080)
            out[name] = (created_at, host_port)
        return out

    # ── Container operations ─────────────────────────────────────────────

    def _start_container(
        self,
        container_name: str,
        port: int,
        extra_mounts: list[tuple[str, str, bool]] | None = None,
        *,
        config_mount_exclusion_root: str | None = None,
    ) -> str:
        """Start a new container.

        Args:
            container_name: Name for the container.
            port: Host port to map to container port 8080.
            extra_mounts: Additional volume mounts.
            config_mount_exclusion_root: Config-level mounts at or below this
                container root are omitted for this container only.

        Returns:
            The container ID.

        Raises:
            RuntimeError: If container fails to start.
        """
        cmd = [self._runtime, "run"]

        # Docker-only security hardening. The sandbox container executes
        # untrusted, model-authored code, so it must not run with the
        # daemon's permissive defaults: all Linux capabilities are dropped
        # except the minimum the shipped image's entrypoint needs to
        # initialize itself, privilege escalation (setuid/sudo) is blocked,
        # and CPU/memory/PID footprints are bounded so one runaway sandbox
        # cannot exhaust the host or fork-bomb it. Each knob has an env
        # escape hatch documented in backend/docs/CONFIGURATION.md. Apple
        # Container's CLI does not support these flags, so they are
        # Docker-only.
        if self._runtime == "docker":
            # The default image (/opt/gem/run.sh) starts as root, creates the
            # gem account at runtime, chown -R's /opt/jupyter, and drops to
            # that user via su before starting the services. That needs
            # CHOWN/SETUID/SETGID; additionally the root nginx master writes
            # logs under /var/log/nginx that belong to the gem user, which
            # requires DAC_OVERRIDE — without it nginx dies with
            # "open() .../access.log failed (13: Permission denied)" on every
            # start (a runtime need, not just startup: access.log is written
            # per request). Dropping ALL of them makes the image fail before
            # the readiness endpoint exists.
            # no-new-privileges stays: it only blocks *gaining* privileges
            # through exec, it does not revoke the capabilities added here,
            # and su from the already-root entrypoint does not need to gain
            # anything. Everything else (NET_RAW, SYS_PTRACE, ...) stays
            # dropped, which is the bulk of the attack-surface reduction.
            # For a pre-initialized non-root image nothing ever runs as
            # root, so the handoff capabilities are not needed — and leaving
            # them available for the container's lifetime would let
            # sandboxed code chown bind-mounted paths or impersonate
            # mounted-file UIDs/GIDs. Such images opt out with
            # DEER_FLOW_SANDBOX_IMAGE_STARTUP_CAPS=0 (see CONFIGURATION.md),
            # which drops every capability including these three.
            if _env_flag_disabled("DEER_FLOW_SANDBOX_IMAGE_STARTUP_CAPS"):
                cmd.extend(["--cap-drop=ALL", "--security-opt", "no-new-privileges"])
            else:
                cmd.extend(
                    [
                        "--cap-drop=ALL",
                        "--cap-add=CHOWN",
                        "--cap-add=SETUID",
                        "--cap-add=SETGID",
                        "--cap-add=DAC_OVERRIDE",
                        "--security-opt",
                        "no-new-privileges",
                    ]
                )

            # The shipped AIO image runs a Chromium-based browser that does
            # not start under Docker's default seccomp profile — its upstream
            # quick-start always passes seccomp=unconfined and the upstream
            # FAQ documents the browser failing under the default profile
            # (Chromium needs namespace-related syscalls). Keep that option
            # as the default so the shipped image keeps working. Two ways to
            # tighten it for a known image:
            #   DEER_FLOW_SANDBOX_SECCOMP_PROFILE=/path/to/profile.json
            #       → use a restricted, Chromium-compatible profile instead
            #         (Docker's default profile plus the needed syscalls);
            #   DEER_FLOW_SANDBOX_SECCOMP_UNCONFINED=0
            #       → fall back to Docker's default profile, only for images
            #         verified to start and pass their browser checks with it.
            seccomp_profile = os.environ.get("DEER_FLOW_SANDBOX_SECCOMP_PROFILE", "").strip()
            if seccomp_profile:
                cmd.extend(["--security-opt", f"seccomp={seccomp_profile}"])
            elif not _env_flag_disabled("DEER_FLOW_SANDBOX_SECCOMP_UNCONFINED"):
                cmd.extend(["--security-opt", "seccomp=unconfined"])
            else:
                # The documented opt-out must actually enable Docker's
                # built-in filtering: merely omitting the option would
                # inherit the daemon's configured default, which can itself
                # be unconfined or a custom profile.
                # https://docs.docker.com/reference/cli/docker/container/run/#optional-security-options---security-opt
                cmd.extend(["--security-opt", "seccomp=builtin"])

            if memory := _docker_resource_limit("DEER_FLOW_SANDBOX_MEMORY", _DEFAULT_SANDBOX_MEMORY):
                cmd.extend(["--memory", memory])
            if cpus := _docker_resource_limit("DEER_FLOW_SANDBOX_CPUS", _DEFAULT_SANDBOX_CPUS):
                cmd.extend(["--cpus", cpus])
            if pids_limit := _docker_resource_limit("DEER_FLOW_SANDBOX_PIDS_LIMIT", _DEFAULT_SANDBOX_PIDS_LIMIT):
                cmd.extend(["--pids-limit", pids_limit])

            # No --user is forced by default: the default AIO sandbox image
            # is upstream-built and its runtime user is not pinned here, and
            # a wrong user would break the sandbox server's home-directory
            # assumptions. Deployments that know their image's user (and the
            # UID/GID ownership of its mounts) can pass it through.
            if container_user := os.environ.get("DEER_FLOW_SANDBOX_CONTAINER_USER", "").strip():
                cmd.extend(["--user", container_user])

            # Default: the daemon's default network (unchanged behavior).
            # Point this at a dedicated, egress-controlled Docker network so
            # sandbox traffic can be filtered by that network's policy —
            # otherwise sandbox code can reach internal networks and cloud
            # metadata endpoints directly, bypassing the gateway's SSRF
            # protections.
            if network := os.environ.get("DEER_FLOW_SANDBOX_NETWORK", "").strip():
                # Validate the *effective* target: Docker accepts the extended
                # "name=<network>" long syntax in addition to plain names and
                # network IDs, and "name=host" / "name=none" attach exactly
                # like the bare words while dodging a raw-string check.
                target = _effective_docker_network_target(network)
                if target == "host" or target.startswith("container:"):
                    # Docker discards -p/--publish in host mode and
                    # container:<name> shares another container's network
                    # namespace, so either one voids the hardened bind below
                    # and re-exposes the unauthenticated sandbox exec API on
                    # the host's interfaces. Refuse instead of silently
                    # losing the bind.
                    # https://docs.docker.com/engine/network/drivers/host/
                    raise RuntimeError(
                        f"DEER_FLOW_SANDBOX_NETWORK={network!r} resolves to the {target.split(':', 1)[0]!r} network, "
                        "which would void the sandbox port bind (Docker drops -p/--publish in host mode and shares "
                        "the network namespace for container:<name>). Use a dedicated egress-controlled bridge "
                        "network instead."
                    )
                if target == "none":
                    # The none driver gives the container only a loopback
                    # interface, so the published sandbox HTTP API cannot
                    # receive traffic: readiness would time out (60s), the
                    # container would be destroyed, and every acquisition
                    # would fail. Refuse at start-up with a clear message
                    # instead of failing opaquely on first use.
                    # https://docs.docker.com/engine/network/drivers/none/
                    raise RuntimeError(
                        f"DEER_FLOW_SANDBOX_NETWORK={network!r} resolves to the 'none' network, which leaves the "
                        "container loopback-only, so the published sandbox API port cannot receive traffic (readiness "
                        "would time out and every acquisition would fail). Use a dedicated egress-controlled bridge "
                        "network instead."
                    )
                # Pass the raw value through: custom names, network IDs, and
                # the legit name=<custom-net> long form all keep working.
                cmd.extend(["--network", network])

        if self._runtime == "docker":
            port_mapping = f"{_resolve_docker_bind_host()}:{port}:8080"
        else:
            port_mapping = f"{port}:8080"

        cmd.extend(
            [
                "--rm",
                "-d",
                "-p",
                port_mapping,
                "--name",
                container_name,
            ]
        )

        # Environment variables
        for key, value in self._environment.items():
            cmd.extend(["-e", f"{key}={value}"])

        # Config-level volume mounts. A policy-scoped skills view owns its
        # complete container subtree; keeping a more-specific config mount
        # would let Docker overlay an excluded skill inside that view.
        exclusion_root = None
        if config_mount_exclusion_root is not None:
            exclusion_root = posixpath.normpath(config_mount_exclusion_root.rstrip("/") or "/")

        for mount in self._config_mounts:
            mount_path = posixpath.normpath(str(mount.container_path).rstrip("/") or "/")
            if exclusion_root is not None and (mount_path == exclusion_root or mount_path.startswith(exclusion_root.rstrip("/") + "/")):
                logger.info(
                    "Skipping config mount inside policy-scoped skills root: %s",
                    mount.container_path,
                )
                continue
            cmd.extend(
                _format_container_mount(
                    self._runtime,
                    mount.host_path,
                    mount.container_path,
                    mount.read_only,
                )
            )

        # Extra mounts (thread-specific, skills, etc.)
        if extra_mounts:
            for host_path, container_path, read_only in extra_mounts:
                cmd.extend(
                    _format_container_mount(
                        self._runtime,
                        host_path,
                        container_path,
                        read_only,
                    )
                )

        cmd.append(self._image)

        log_cmd = _format_container_command_for_log(_redact_container_command_for_log(cmd))
        logger.info(f"Starting container using {self._runtime}: {log_cmd}")

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            container_id = result.stdout.strip()
            logger.info(f"Started container {container_name} (ID: {container_id}) using {self._runtime}")
            return container_id
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to start container using {self._runtime}: {e.stderr}")
            raise RuntimeError(f"Failed to start sandbox container: {e.stderr}")

    def _stop_container(self, container_id: str) -> None:
        """Stop a container (--rm ensures automatic removal).

        The timeout bounds the worst case independently of the ownership layer.
        The teardown lease keeps a peer from re-acquiring the container while
        this runs, but that exclusion is a lease and can lapse (a store outage
        longer than the TTL); an unbounded ``docker stop`` against a wedged
        daemon could then outlive it and land on a peer's live container — #4206.
        Bounding the stop caps how long that exposure can last even when the
        store is perfectly healthy.
        """
        try:
            subprocess.run(
                [self._runtime, "stop", container_id],
                capture_output=True,
                text=True,
                check=True,
                timeout=self._STOP_TIMEOUT_SECONDS,
            )
            logger.info(f"Stopped container {container_id} using {self._runtime}")
        except subprocess.TimeoutExpired:
            # Deliberately not swallowed like a CalledProcessError: the container
            # may still be running, so the caller must not report a clean stop.
            logger.error(f"Timed out after {self._STOP_TIMEOUT_SECONDS}s stopping container {container_id} using {self._runtime}")
            raise
        except subprocess.CalledProcessError as e:
            logger.warning(f"Failed to stop container {container_id}: {e.stderr}")

    def _is_container_running(self, container_name: str) -> bool:
        """Check if a named container is currently running.

        This enables cross-process container discovery — any process can detect
        containers started by another process via the deterministic container name.

        Raises:
            RuntimeError: If the container runtime cannot answer the inspect
                query. A failed check is intentionally distinct from a
                definitive "container does not exist" result so callers do not
                destroy healthy containers during transient Docker/Container
                daemon failures.
        """
        try:
            result = subprocess.run(
                [self._runtime, "inspect", "-f", "{{.State.Running}}", container_name],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Timed out checking container {container_name}") from exc

        if result.returncode == 0:
            return result.stdout.strip().lower() == "true"
        if _is_no_such_container_error(result.stderr, container_name):
            return False
        raise RuntimeError(f"Failed to inspect container {container_name}: {result.stderr.strip()}")

    def _get_container_port(self, container_name: str) -> int | None:
        """Get the host port of a running container.

        Args:
            container_name: The container name to inspect.

        Returns:
            The host port mapped to container port 8080, or None if not found.
        """
        try:
            result = subprocess.run(
                [self._runtime, "port", container_name, "8080"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                # Output format: "0.0.0.0:PORT" or ":::PORT"
                port_str = result.stdout.strip().split(":")[-1]
                return int(port_str)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError):
            pass
        return None
