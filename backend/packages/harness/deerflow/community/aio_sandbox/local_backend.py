"""Local container backend for sandbox provisioning.

Manages sandbox containers using Docker or Apple Container on the local machine.
Handles container lifecycle, port allocation, and cross-process container discovery.
"""

from __future__ import annotations

import csv
import hashlib
import ipaddress
import json
import logging
import os
import platform
import posixpath
import secrets
import shlex
import socket
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from deerflow.utils.network import get_free_port, release_port

from .backend import SandboxBackend, wait_for_sandbox_ready
from .network_proxy import RELAY_AUTH_HEADER, RELAY_TOKEN_ENV
from .sandbox_info import SandboxInfo

logger = logging.getLogger(__name__)


class _ExistingRestrictedSandbox(RuntimeError):
    def __init__(self, info: SandboxInfo):
        super().__init__(f"restricted sandbox {info.sandbox_id} already exists")
        self.info = info


@dataclass(frozen=True)
class _ContainerInspection:
    created_at: float
    host_port: int | None
    labels: dict[str, str]
    image: str
    networks: frozenset[str]
    relay_token: str | None = None


@dataclass(frozen=True)
class _NetworkInspection:
    driver: str
    internal: bool
    labels: dict[str, str]
    options: dict[str, str]


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


def _extract_container_environment(config: dict, name: str) -> str | None:
    """Read one exact environment value from Docker inspect data."""
    prefix = f"{name}="
    for item in config.get("Env") or []:
        if isinstance(item, str) and item.startswith(prefix):
            value = item[len(prefix) :]
            return value or None
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
_NETWORK_PROXY_CONTAINER_SCRIPT = "/tmp/deerflow-network-proxy.py"
_NETWORK_POLICY_DIGEST_LABEL = "deerflow.network_policy_digest"
_NETWORK_GATEWAY_MODE_IPV4 = "com.docker.network.bridge.gateway_mode_ipv4"
_NETWORK_GATEWAY_MODE_IPV6 = "com.docker.network.bridge.gateway_mode_ipv6"
_NETWORK_ENABLE_ICC = "com.docker.network.bridge.enable_icc"


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
        network_config: dict[str, object] | None = None,
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
        self._network_config = network_config or {"mode": "open"}
        self._network_mode = str(self._network_config.get("mode", "open"))
        self._allow_synthetic_dns = False
        self._runtime = self._detect_runtime()

        if self._network_mode != "open":
            if self._runtime != "docker":
                raise RuntimeError("sandbox.network restricted modes require Docker; Apple Container is not supported")
            self._require_restricted_network_support()
            self._allow_synthetic_dns = self._docker_server_is_desktop()

    @property
    def runtime(self) -> str:
        """The detected container runtime ("docker" or "container")."""
        return self._runtime

    @property
    def network_mode(self) -> str:
        return self._network_mode

    def _resource_names(self, sandbox_id: str) -> tuple[str, str]:
        digest = hashlib.sha256(f"{self._container_prefix}:{sandbox_id}".encode()).hexdigest()[:16]
        return f"deer-flow-netproxy-{digest}", f"deer-flow-sandbox-net-{digest}"

    def _egress_network_name(self, sandbox_id: str) -> str:
        digest = hashlib.sha256(f"{self._container_prefix}:{sandbox_id}".encode()).hexdigest()[:16]
        return f"deer-flow-sandbox-egress-{digest}"

    def _proxy_image(self) -> str:
        return str(
            self._network_config.get(
                "proxy_image",
                "ghcr.io/bytedance/deer-flow-sandbox-network-proxy:latest",
            )
        )

    def _sandbox_labels(self, sandbox_id: str) -> dict[str, str]:
        """Return the stable identity shared by every Docker sandbox mode."""
        return {
            "deerflow.sandbox_id": sandbox_id,
            "deerflow.role": "sandbox",
            "deerflow.network_mode": self._network_mode,
        }

    def _network_policy_digest(self) -> str:
        allow_domains = self._network_config.get("allow_domains", [])
        canonical_domains = sorted({value for value in allow_domains if isinstance(value, str)}) if isinstance(allow_domains, list) else []
        proxy_source = Path(__file__).with_name("network_proxy.py").read_bytes()
        material = {
            "schema": 1,
            "mode": self._network_mode,
            "allow_domains": canonical_domains,
            "approval": self._network_config.get("approval", "prompt"),
            "temporary_grant_ttl": self._network_config.get("temporary_grant_ttl", 300),
            "proxy_image": self._proxy_image(),
            "proxy_source_sha256": hashlib.sha256(proxy_source).hexdigest(),
            "allow_synthetic_dns": self._allow_synthetic_dns,
            "network": {
                "driver": "bridge",
                "internal": True,
                "gateway_mode_ipv4": "isolated",
                "gateway_mode_ipv6": "isolated",
            },
            "egress_network": {
                "driver": "bridge",
                "internal": False,
                "enable_icc": False,
            },
        }
        encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def _restricted_labels(self, sandbox_id: str, role: str) -> dict[str, str]:
        return {
            "deerflow.sandbox_id": sandbox_id,
            "deerflow.role": role,
            "deerflow.network_mode": self._network_mode,
            _NETWORK_POLICY_DIGEST_LABEL: self._network_policy_digest(),
        }

    def _persisted_sandbox_mode(self, sandbox: _ContainerInspection, sandbox_id: str) -> str | None:
        """Classify an inspected container without claiming or mutating it.

        Matching DeerFlow identity labels are authoritative. Unlabelled
        containers can only be legacy ``open`` sandboxes: open mode preserves
        the historical name-based discovery contract, while a restricted
        process accepts the narrower legacy shape of the configured image with
        a published API port. Any partial/mismatched DeerFlow identity is left
        unmanaged so a configurable prefix cannot turn a sidecar or unrelated
        labelled container into a sandbox.
        """
        labels = sandbox.labels
        role = labels.get("deerflow.role")
        labelled_id = labels.get("deerflow.sandbox_id")
        labelled_mode = labels.get("deerflow.network_mode")
        identity_keys_present = any(key in labels for key in ("deerflow.role", "deerflow.sandbox_id", "deerflow.network_mode"))

        if role == "sandbox" and labelled_id == sandbox_id:
            # A missing/unknown value still proves DeerFlow ownership, but it
            # cannot be adopted under any current policy. Returning a sentinel
            # routes it through the fenced replacement path.
            return labelled_mode or "unknown"
        if identity_keys_present:
            return None

        if self._network_mode == "open":
            return "open"
        if sandbox.host_port is not None and sandbox.image == self._image:
            return "open"
        return None

    @staticmethod
    def _labels_match(actual: dict[str, str], expected: dict[str, str]) -> bool:
        return all(actual.get(key) == value for key, value in expected.items())

    def _inspect_network(self, network_name: str) -> _NetworkInspection | None:
        try:
            result = subprocess.run(
                ["docker", "network", "inspect", network_name],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            raise RuntimeError(f"Failed to inspect restricted sandbox network {network_name}") from exc
        if result.returncode != 0:
            stderr = (result.stderr or "").lower()
            if "not found" in stderr and (network_name.lower() in stderr or "network" in stderr):
                return None
            raise RuntimeError(f"Failed to inspect restricted sandbox network {network_name}: {(result.stderr or '').strip()}")
        try:
            payload = json.loads(result.stdout or "[]")
            entry = payload[0]
            return _NetworkInspection(
                driver=str(entry.get("Driver") or ""),
                internal=entry.get("Internal") is True,
                labels={str(key): str(value) for key, value in (entry.get("Labels") or {}).items()},
                options={str(key): str(value) for key, value in (entry.get("Options") or {}).items()},
            )
        except (IndexError, TypeError, AttributeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Docker returned invalid inspection data for restricted sandbox network {network_name}") from exc

    def _network_matches_policy(self, network: _NetworkInspection, sandbox_id: str) -> bool:
        return (
            network.driver == "bridge"
            and network.internal
            and network.options.get(_NETWORK_GATEWAY_MODE_IPV4) == "isolated"
            and network.options.get(_NETWORK_GATEWAY_MODE_IPV6) == "isolated"
            and self._labels_match(network.labels, self._restricted_labels(sandbox_id, "network"))
        )

    def _egress_network_matches_policy(self, network: _NetworkInspection, sandbox_id: str) -> bool:
        return network.driver == "bridge" and not network.internal and network.options.get(_NETWORK_ENABLE_ICC) == "false" and self._labels_match(network.labels, self._restricted_labels(sandbox_id, "egress-network"))

    def _restricted_resources_status(
        self,
        sandbox_id: str,
        *,
        inspections: dict[str, _ContainerInspection] | None = None,
    ) -> str:
        """Return missing, compatible, or mismatch for one restricted sandbox set."""
        container_name = f"{self._container_prefix}-{sandbox_id}"
        proxy_name, network_name = self._resource_names(sandbox_id)
        egress_network_name = self._egress_network_name(sandbox_id)
        if inspections is None:
            inspections = self._batch_inspect([container_name, proxy_name], strict=True)
        sandbox = inspections.get(container_name)
        proxy = inspections.get(proxy_name)
        network = self._inspect_network(network_name)
        egress_network = self._inspect_network(egress_network_name)
        if sandbox is None and proxy is None and network is None and egress_network is None:
            return "missing"
        if sandbox is None or proxy is None or network is None or egress_network is None:
            return "mismatch"
        sandbox_matches = sandbox.host_port is None and sandbox.networks == frozenset({network_name}) and self._labels_match(sandbox.labels, self._restricted_labels(sandbox_id, "sandbox"))
        proxy_matches = (
            proxy.host_port is not None
            and proxy.image == self._proxy_image()
            and proxy.networks == frozenset({egress_network_name, network_name})
            and isinstance(proxy.relay_token, str)
            and len(proxy.relay_token) >= 32
            and self._labels_match(proxy.labels, self._restricted_labels(sandbox_id, "network-proxy"))
        )
        return "compatible" if sandbox_matches and proxy_matches and self._network_matches_policy(network, sandbox_id) and self._egress_network_matches_policy(egress_network, sandbox_id) else "mismatch"

    def _require_restricted_network_support(self) -> None:
        try:
            result = subprocess.run(
                ["docker", "version", "--format", "{{.Server.Version}}"],
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            )
            major = int(result.stdout.strip().split(".", 1)[0])
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError) as exc:
            raise RuntimeError("sandbox.network restricted modes require a reachable Docker Engine 28 or newer") from exc
        if major < 28:
            raise RuntimeError("sandbox.network restricted modes require Docker Engine 28 or newer so both internal bridge gateway families can use isolated mode")

    def _docker_server_is_desktop(self) -> bool:
        """Detect Desktop from the daemon, including a Linux DooD Gateway."""
        try:
            result = subprocess.run(
                ["docker", "info", "--format", "{{json .OperatingSystem}}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            logger.warning("Could not identify the Docker server platform; Desktop synthetic DNS answers remain disabled: %s", exc)
            return False
        if result.returncode != 0:
            logger.warning("Could not identify the Docker server platform; Desktop synthetic DNS answers remain disabled: %s", (result.stderr or "").strip())
            return False
        raw = (result.stdout or "").strip()
        try:
            operating_system = json.loads(raw)
        except json.JSONDecodeError:
            operating_system = raw
        return isinstance(operating_system, str) and "docker desktop" in operating_system.lower()

    def _docker_has_managed_sandboxes(self) -> bool:
        """Keep using Docker while this prefix still has managed sandboxes.

        Restricted networking is Docker-only. On macOS, switching its config
        back to ``open`` must not make Apple Container hide the Docker
        resources that startup reconciliation needs to replace. The role
        label excludes fixed-name proxy sidecars even when a custom sandbox
        prefix overlaps their names.
        """
        try:
            result = subprocess.run(
                [
                    "docker",
                    "ps",
                    "--filter",
                    f"name={self._container_prefix}-",
                    "--filter",
                    "label=deerflow.role=sandbox",
                    "--format",
                    "{{.Names}}",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return False
        if result.returncode != 0:
            return False
        prefix = self._container_prefix + "-"
        return any(name.strip().startswith(prefix) for name in result.stdout.splitlines())

    def _detect_runtime(self) -> str:
        """Detect which container runtime to use.

        On macOS, prefer Apple Container if available, otherwise fall back to Docker.
        On other platforms, use Docker.

        Returns:
            "container" for Apple Container, "docker" for Docker.
        """
        if platform.system() == "Darwin" and self._network_mode == "open":
            try:
                result = subprocess.run(
                    ["container", "--version"],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=5,
                )
                logger.info(f"Detected Apple Container: {result.stdout.strip()}")
                if self._docker_has_managed_sandboxes():
                    logger.info("Keeping Docker runtime so managed sandboxes remain visible to startup reconciliation")
                    return "docker"
                return "container"
            except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
                logger.info("Apple Container not available, falling back to Docker")

        if platform.system() == "Darwin" and self._network_mode != "open":
            logger.info("sandbox.network mode %s requires Docker; skipping Apple Container detection", self._network_mode)

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
        relay_token: str | None = None
        port: int = 0
        for _attempt in range(10):
            port = get_free_port(start_port=_next_start)
            try:
                if self._network_mode == "open":
                    container_id = self._start_container(
                        container_name,
                        port,
                        extra_mounts,
                        config_mount_exclusion_root=config_mount_exclusion_root,
                        labels=self._sandbox_labels(sandbox_id),
                    )
                else:
                    relay_token = secrets.token_urlsafe(32)
                    container_id = self._start_restricted_sandbox(
                        sandbox_id,
                        container_name,
                        port,
                        extra_mounts,
                        config_mount_exclusion_root=config_mount_exclusion_root,
                        relay_token=relay_token,
                    )
                break
            except _ExistingRestrictedSandbox as exc:
                release_port(port)
                return exc.info
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
                    if existing is not None and not existing.requires_replacement:
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
            request_headers={RELAY_AUTH_HEADER: relay_token} if relay_token is not None else {},
        )

    def _start_restricted_sandbox(
        self,
        sandbox_id: str,
        container_name: str,
        port: int,
        extra_mounts: list[tuple[str, str, bool]] | None,
        *,
        config_mount_exclusion_root: str | None,
        relay_token: str,
    ) -> str:
        proxy_name, network_name = self._resource_names(sandbox_id)
        egress_network_name = self._egress_network_name(sandbox_id)
        resource_status = self._restricted_resources_status(sandbox_id)
        if resource_status == "mismatch":
            # Enumeration/provisioning is deliberately non-destructive. A
            # mismatched set can still belong to a live Gateway from an older
            # rolling-deployment revision, so only the provider may replace it
            # after acquiring both teardown fences.
            raise RuntimeError(f"Restricted sandbox {sandbox_id} requires ownership-fenced replacement")
        if resource_status == "compatible":
            existing = self.discover(sandbox_id)
            if existing is not None and not existing.requires_replacement:
                raise _ExistingRestrictedSandbox(existing)
            raise RuntimeError(f"Restricted sandbox {sandbox_id} already exists but is not ready for adoption")

        try:
            self._create_internal_network(network_name, sandbox_id)
            self._create_egress_network(egress_network_name, sandbox_id)
            self._start_network_proxy(proxy_name, network_name, egress_network_name, container_name, port, sandbox_id, relay_token)
            proxy_url = f"http://{proxy_name}:3128"
            return self._start_container(
                container_name,
                port,
                extra_mounts,
                config_mount_exclusion_root=config_mount_exclusion_root,
                network_override=network_name,
                publish_port=False,
                extra_environment={
                    "HTTP_PROXY": proxy_url,
                    "HTTPS_PROXY": proxy_url,
                    "ALL_PROXY": proxy_url,
                    "http_proxy": proxy_url,
                    "https_proxy": proxy_url,
                    "all_proxy": proxy_url,
                    "NO_PROXY": "localhost,127.0.0.1,::1",
                    "no_proxy": "localhost,127.0.0.1,::1",
                    # The upstream AIO image uses these to configure Chromium;
                    # Chromium does not consistently consume shell proxy vars.
                    "PROXY_SERVER": f"{proxy_name}:3128",
                    "PROXY_EXCLUDE": "localhost,127.0.0.1,::1",
                },
                labels=self._restricted_labels(sandbox_id, "sandbox"),
            )
        except BaseException as exc:
            message = str(exc).lower()
            if "is already in use by container" in message or "conflict. the container name" in message:
                existing = self.discover(sandbox_id)
                if existing is not None and not existing.requires_replacement:
                    raise _ExistingRestrictedSandbox(existing) from exc
                # A peer may still be provisioning the deterministic resource
                # set. Never roll it back just because its readiness check has
                # not completed yet.
                if self._restricted_resources_status(sandbox_id) != "missing":
                    raise
            self._cleanup_restricted_resources(sandbox_id)
            raise

    def _create_internal_network(self, network_name: str, sandbox_id: str) -> None:
        existing = self._inspect_network(network_name)
        if existing is not None:
            if self._network_matches_policy(existing, sandbox_id):
                return
            raise RuntimeError(f"Restricted sandbox network {network_name} exists with incompatible policy or isolation settings")
        labels = self._restricted_labels(sandbox_id, "network")
        result = subprocess.run(
            [
                "docker",
                "network",
                "create",
                "--driver",
                "bridge",
                "--internal",
                "--opt",
                f"{_NETWORK_GATEWAY_MODE_IPV4}=isolated",
                "--opt",
                f"{_NETWORK_GATEWAY_MODE_IPV6}=isolated",
                *(item for key, value in labels.items() for item in ("--label", f"{key}={value}")),
                network_name,
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to create restricted sandbox network: {result.stderr.strip()}")

    def _create_egress_network(self, network_name: str, sandbox_id: str) -> None:
        existing = self._inspect_network(network_name)
        if existing is not None:
            if self._egress_network_matches_policy(existing, sandbox_id):
                return
            raise RuntimeError(f"Restricted sandbox egress network {network_name} exists with incompatible policy or isolation settings")
        labels = self._restricted_labels(sandbox_id, "egress-network")
        result = subprocess.run(
            [
                "docker",
                "network",
                "create",
                "--driver",
                "bridge",
                "--opt",
                f"{_NETWORK_ENABLE_ICC}=false",
                *(item for key, value in labels.items() for item in ("--label", f"{key}={value}")),
                network_name,
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to create restricted sandbox egress network: {result.stderr.strip()}")

    def _start_network_proxy(
        self,
        proxy_name: str,
        network_name: str,
        egress_network_name: str,
        container_name: str,
        port: int,
        sandbox_id: str,
        relay_token: str,
    ) -> None:
        allow_domains = self._network_config.get("allow_domains", [])
        proxy_image = self._proxy_image()
        labels = self._restricted_labels(sandbox_id, "network-proxy")
        port_mapping = f"{_resolve_docker_bind_host()}:{port}:8080"
        cmd = [
            "docker",
            "create",
            "--rm",
            "--cap-drop=ALL",
            "--security-opt",
            "no-new-privileges",
            "--memory",
            "256m",
            "--cpus",
            "1",
            "--pids-limit",
            "128",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=16m",
            "--user",
            "65532:65532",
            "-p",
            port_mapping,
            "--network",
            egress_network_name,
            "--name",
            proxy_name,
            *(item for key, value in labels.items() for item in ("--label", f"{key}={value}")),
            "-e",
            f"DEERFLOW_NETWORK_MODE={self._network_mode}",
            "-e",
            f"DEERFLOW_ALLOW_DOMAINS_JSON={json.dumps(allow_domains, separators=(',', ':'))}",
            "-e",
            f"DEERFLOW_SANDBOX_TARGET={container_name}:8080",
            "-e",
            f"DEERFLOW_ALLOW_SYNTHETIC_DNS={'1' if self._allow_synthetic_dns else '0'}",
            "-e",
            f"DEERFLOW_RECORD_DENIALS={'1' if self._network_mode == 'allowlist' and self._network_config.get('approval', 'prompt') == 'prompt' else '0'}",
            "-e",
            f"{RELAY_TOKEN_ENV}={relay_token}",
            proxy_image,
            "sh",
            "-c",
            f"while [ ! -f {_NETWORK_PROXY_CONTAINER_SCRIPT} ]; do sleep 0.05; done; exec python {_NETWORK_PROXY_CONTAINER_SCRIPT} serve",
        ]
        # First use may pull the sidecar image. Match the sandbox create path's
        # tolerance for an image download instead of killing Docker mid-pull.
        created = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if created.returncode != 0:
            raise RuntimeError(f"Failed to create sandbox network proxy: {created.stderr.strip()}")
        connected = subprocess.run(
            ["docker", "network", "connect", network_name, proxy_name],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if connected.returncode != 0:
            raise RuntimeError(f"Failed to connect sandbox network proxy: {connected.stderr.strip()}")
        started = subprocess.run(["docker", "start", proxy_name], capture_output=True, text=True, timeout=15)
        if started.returncode != 0:
            raise RuntimeError(f"Failed to start sandbox network proxy: {started.stderr.strip()}")
        source = Path(__file__).with_name("network_proxy.py")
        copied = subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                proxy_name,
                "python",
                "-c",
                (f"import pathlib,sys; p=pathlib.Path({_NETWORK_PROXY_CONTAINER_SCRIPT!r}); tmp=p.with_suffix('.tmp'); tmp.write_bytes(sys.stdin.buffer.read()); tmp.replace(p)"),
            ],
            input=source.read_bytes(),
            capture_output=True,
            timeout=15,
        )
        if copied.returncode != 0:
            raise RuntimeError(f"Failed to install sandbox network proxy: {(copied.stderr or b'').decode(errors='replace').strip()}")

    def destroy(self, info: SandboxInfo) -> None:
        """Stop the container and release its port."""
        # Prefer container_id, fall back to container_name (both accepted by docker stop).
        # This ensures containers discovered via list_running() (which only has the name)
        # can also be stopped.
        stop_target = info.container_id or info.container_name
        if stop_target:
            self._stop_container(stop_target)
        # An incompatible sandbox discovered while the new process is in open
        # mode may have been provisioned by a previous restricted-mode process.
        # Remove its deterministic sidecar/networks from this provider-owned,
        # fenced destroy path as well (never from discovery itself).
        if self._runtime == "docker" and (self._network_mode != "open" or info.requires_replacement):
            self._cleanup_restricted_resources(info.sandbox_id, stop_sandbox=False)
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
            if not self._is_container_running(info.container_name):
                return False
            if self._network_mode != "open":
                proxy_name, _ = self._resource_names(info.sandbox_id)
                return self._is_container_running(proxy_name) and self._restricted_resources_status(info.sandbox_id) == "compatible"
            return True
        return False

    def discover(self, sandbox_id: str) -> SandboxInfo | None:
        """Discover an existing container by its deterministic name.

        Checks if a container with the expected name is running, retrieves its
        port, and verifies it responds to health checks.

        Args:
            sandbox_id: The deterministic sandbox ID (determines container name).

        Returns:
            SandboxInfo if a container is found and healthy, or a non-adoptable
            SandboxInfo with ``requires_replacement=True`` when its persisted
            restricted-network policy is incompatible. A failed runtime check
            (e.g. transient daemon error) returns None — discovery must not
            adopt a container it cannot verify, and falling through to create
            keeps acquire recoverable instead of hard-failing on a hiccup.
        """
        container_name = f"{self._container_prefix}-{sandbox_id}"

        try:
            running = self._is_container_running(container_name)
        except RuntimeError as e:
            logger.warning(f"Could not verify container {container_name} during discovery; not adopting it: {e}")
            return None

        if not running:
            return None

        request_headers: dict[str, str] = {}
        restricted_port: int | None = None
        created_at = time.time()
        inspections: dict[str, _ContainerInspection] = {}
        sandbox_inspection: _ContainerInspection | None = None
        if self._runtime == "docker":
            try:
                inspections = self._batch_inspect([container_name], strict=True)
            except RuntimeError as e:
                logger.warning("Could not inspect persisted sandbox %s: %s", sandbox_id, e)
                return None
            sandbox_inspection = inspections.get(container_name)
            if sandbox_inspection is None:
                return None
            persisted_mode = self._persisted_sandbox_mode(sandbox_inspection, sandbox_id)
            if persisted_mode is None:
                logger.warning(
                    "Container %s uses the sandbox name but lacks a compatible DeerFlow identity; leaving it unmanaged",
                    container_name,
                )
                return None
            created_at = sandbox_inspection.created_at
            if persisted_mode != self._network_mode:
                return SandboxInfo(
                    sandbox_id=sandbox_id,
                    sandbox_url="",
                    container_name=container_name,
                    created_at=created_at,
                    requires_replacement=True,
                )

        if self._network_mode != "open":
            proxy_name, _ = self._resource_names(sandbox_id)
            try:
                inspections.update(self._batch_inspect([proxy_name], strict=True))
                resource_status = self._restricted_resources_status(sandbox_id, inspections=inspections)
            except RuntimeError as e:
                logger.warning("Could not verify persisted network policy for sandbox %s: %s", sandbox_id, e)
                return None
            if resource_status != "compatible":
                return SandboxInfo(
                    sandbox_id=sandbox_id,
                    sandbox_url="",
                    container_name=container_name,
                    created_at=created_at,
                    requires_replacement=True,
                )
            proxy_inspection = inspections.get(proxy_name)
            if proxy_inspection is None or proxy_inspection.host_port is None or proxy_inspection.relay_token is None:
                return None
            restricted_port = proxy_inspection.host_port
            request_headers = {RELAY_AUTH_HEADER: proxy_inspection.relay_token}

        if restricted_port is not None:
            port = restricted_port
        elif sandbox_inspection is not None:
            port = sandbox_inspection.host_port
        else:
            # Apple Container is supported only in open mode and does not use
            # Docker labels, so retain its native port-discovery path.
            port = self._get_container_port(container_name)
        if port is None:
            return SandboxInfo(
                sandbox_id=sandbox_id,
                sandbox_url="",
                container_name=container_name,
                created_at=created_at,
                requires_replacement=True,
            )

        sandbox_host = _normalize_sandbox_host_for_url(os.environ.get("DEER_FLOW_SANDBOX_HOST", "localhost"))
        sandbox_url = f"http://{sandbox_host}:{port}"
        readiness_kwargs = {"headers": request_headers} if request_headers else {}
        if not wait_for_sandbox_ready(sandbox_url, timeout=5, **readiness_kwargs):
            return None

        return SandboxInfo(
            sandbox_id=sandbox_id,
            sandbox_url=sandbox_url,
            container_name=container_name,
            created_at=created_at,
            request_headers=request_headers,
        )

    def list_running(self) -> list[SandboxInfo]:
        """Enumerate all running containers matching the configured prefix.

        Uses a single ``docker ps`` call to list container names, then a
        batched ``docker inspect`` calls to retrieve creation timestamp, mode,
        and port mapping. Restricted mode uses a second inspect only for the
        proxies paired with already-identified restricted sandboxes, avoiding
        fabricated resource names for sidecars caught by an overlapping custom
        prefix. Total subprocess calls: 2 in open mode and at most 3 in a
        restricted mode (down from 2N+1 in the naive per-container approach).

        Note: Docker's ``--filter name=`` performs *substring* matching,
        so a secondary ``startswith`` check is applied to ensure only
        containers with the exact prefix are included.

        Containers without a usable port mapping are still included with an
        empty sandbox URL and ``requires_replacement=True`` so startup
        reconciliation can remove them only after ownership fencing.
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

        # Step 2: inspect candidate containers before deriving any paired
        # resource names. A custom prefix can overlap the fixed sidecar prefix,
        # and only the inspected role label distinguishes that sidecar from a
        # real sandbox.
        try:
            inspections = self._batch_inspect(container_names, strict=True)
        except RuntimeError as e:
            logger.warning("Failed to inspect running sandbox resources: %s", e)
            return []

        persisted_modes: dict[str, str | None] = {}
        for container_name in container_names:
            data = inspections.get(container_name)
            if data is None:
                continue
            sandbox_id = container_name[len(self._container_prefix) + 1 :]
            persisted_modes[container_name] = self._persisted_sandbox_mode(data, sandbox_id) if self._runtime == "docker" else "open"

        if self._network_mode != "open":
            proxy_names = [self._resource_names(name[len(self._container_prefix) + 1 :])[0] for name, persisted_mode in persisted_modes.items() if persisted_mode == self._network_mode]
            if proxy_names:
                try:
                    inspections.update(self._batch_inspect(proxy_names, strict=True))
                except RuntimeError as e:
                    logger.warning("Failed to inspect running sandbox proxy resources: %s", e)
                    return []

        infos: list[SandboxInfo] = []
        sandbox_host = _normalize_sandbox_host_for_url(os.environ.get("DEER_FLOW_SANDBOX_HOST", "localhost"))
        for container_name in container_names:
            data = inspections.get(container_name)
            if data is None:
                # Container disappeared between ps and inspect, or inspect failed
                continue
            sandbox_id = container_name[len(self._container_prefix) + 1 :]
            persisted_mode = persisted_modes.get(container_name)
            if persisted_mode is None:
                # A custom prefix such as ``deer-flow`` also matches the fixed
                # ``deer-flow-netproxy-*`` sidecar names. Inspecting the stable
                # role/id identity excludes them while still allowing legacy
                # open sandboxes to be reported for a fenced mode transition.
                continue
            created_at, host_port = data.created_at, data.host_port
            request_headers: dict[str, str] = {}
            requires_replacement = persisted_mode != self._network_mode
            if not requires_replacement and self._network_mode != "open":
                proxy_name, _ = self._resource_names(sandbox_id)
                proxy_data = inspections.get(proxy_name)
                try:
                    resource_status = self._restricted_resources_status(sandbox_id, inspections=inspections)
                except RuntimeError as e:
                    logger.warning("Could not verify persisted network policy for sandbox %s during reconciliation: %s", sandbox_id, e)
                    continue
                if resource_status != "compatible":
                    requires_replacement = True
                    host_port = None
                else:
                    host_port = proxy_data.host_port if proxy_data is not None else None
                    if proxy_data is not None and proxy_data.relay_token is not None:
                        request_headers = {RELAY_AUTH_HEADER: proxy_data.relay_token}
            elif not requires_replacement and host_port is None:
                # An open-mode container without its published API port cannot
                # be adopted. Report it instead of placing an unusable empty URL
                # in the warm pool.
                requires_replacement = True
            if requires_replacement:
                host_port = None
            sandbox_url = f"http://{sandbox_host}:{host_port}" if host_port else ""

            infos.append(
                SandboxInfo(
                    sandbox_id=sandbox_id,
                    sandbox_url=sandbox_url,
                    container_name=container_name,
                    created_at=created_at,
                    request_headers=request_headers,
                    requires_replacement=requires_replacement,
                )
            )

        logger.info(f"Found {len(infos)} running sandbox container(s)")
        return infos

    def _cleanup_restricted_resources(self, sandbox_id: str, *, stop_sandbox: bool = True) -> None:
        proxy_name, network_name = self._resource_names(sandbox_id)
        egress_network_name = self._egress_network_name(sandbox_id)
        if stop_sandbox:
            self._stop_container(f"{self._container_prefix}-{sandbox_id}")
        self._stop_container(proxy_name)
        # ``--rm`` removes a container after it has run and then stopped, but
        # not one left in Docker's Created state by a failure before start.
        # An explicit remove closes that lifecycle gap and is harmless after a
        # normal stop (Docker reports the already-removed name as not found).
        removed = subprocess.run(
            ["docker", "rm", "-f", proxy_name],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if removed.returncode != 0 and "no such container" not in (removed.stderr or "").lower():
            logger.warning("Failed to remove sandbox network proxy %s: %s", proxy_name, removed.stderr.strip())
        for current_network_name in (network_name, egress_network_name):
            result = subprocess.run(
                ["docker", "network", "rm", current_network_name],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode != 0 and "not found" not in (result.stderr or "").lower():
                logger.warning("Failed to remove sandbox network %s: %s", current_network_name, result.stderr.strip())

    def consume_network_policy_events(self, sandbox_id: str) -> list[dict[str, object]]:
        if self._network_mode != "allowlist" or self._network_config.get("approval", "prompt") != "prompt":
            return []
        proxy_name, _ = self._resource_names(sandbox_id)
        result = subprocess.run(
            ["docker", "exec", proxy_name, "python", _NETWORK_PROXY_CONTAINER_SCRIPT, "pending"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            logger.warning("Failed to read sandbox network policy events for %s: %s", sandbox_id, result.stderr.strip())
            return []
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            logger.warning("Sandbox network proxy returned invalid policy events for %s", sandbox_id)
            return []
        return [event for event in payload if isinstance(event, dict)] if isinstance(payload, list) else []

    def deny_pending_network_policy_events(self, sandbox_id: str) -> bool:
        """Atomically deny every unsurfaced proxy event for one sandbox."""
        if self._network_mode != "allowlist" or self._network_config.get("approval", "prompt") != "prompt":
            return True
        proxy_name, _ = self._resource_names(sandbox_id)
        result = subprocess.run(
            ["docker", "exec", proxy_name, "python", _NETWORK_PROXY_CONTAINER_SCRIPT, "deny-pending"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            logger.warning("Failed to deny pending sandbox network policy events for %s: %s", sandbox_id, result.stderr.strip())
            return False
        return True

    def decide_network_policy_request(self, sandbox_id: str, request_id: str, decision: str) -> bool:
        if self._network_mode != "allowlist" or decision not in {"deny", "allow_temporary", "allow_sandbox"}:
            return False
        proxy_name, _ = self._resource_names(sandbox_id)
        ttl = int(self._network_config.get("temporary_grant_ttl", 300))
        result = subprocess.run(
            [
                "docker",
                "exec",
                proxy_name,
                "python",
                _NETWORK_PROXY_CONTAINER_SCRIPT,
                "decide",
                request_id,
                decision,
                "--ttl",
                str(ttl),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0

    def _batch_inspect(self, container_names: list[str], *, strict: bool = False) -> dict[str, _ContainerInspection]:
        """Batch-inspect containers in a single subprocess call.

        Returns creation/port plus policy-relevant labels, image, and networks.
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
            if strict:
                raise RuntimeError("Failed to batch-inspect containers") from e
            logger.warning(f"Failed to batch-inspect containers: {e}")
            return {}

        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            missing = "no such object" in stderr.lower() or "no such container" in stderr.lower()
            if not missing:
                if strict:
                    raise RuntimeError(f"Failed to batch-inspect containers with {self._runtime} inspect: {stderr or '<empty>'}")
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
            if strict:
                raise RuntimeError("Failed to parse container inspection data") from e
            logger.warning(f"Failed to parse docker inspect output as JSON: {e}")
            return {}

        out: dict[str, _ContainerInspection] = {}
        for entry in payload:
            # ``Name`` is prefixed with ``/`` in the docker inspect response
            name = (entry.get("Name") or "").lstrip("/")
            if not name:
                continue
            created_at = _parse_docker_timestamp(entry.get("Created", ""))
            host_port = _extract_host_port(entry, 8080)
            config = entry.get("Config") or {}
            network_settings = entry.get("NetworkSettings") or {}
            out[name] = _ContainerInspection(
                created_at=created_at,
                host_port=host_port,
                labels={str(key): str(value) for key, value in (config.get("Labels") or {}).items()},
                image=str(config.get("Image") or ""),
                networks=frozenset(str(value) for value in (network_settings.get("Networks") or {})),
                relay_token=_extract_container_environment(config, RELAY_TOKEN_ENV),
            )
        return out

    # ── Container operations ─────────────────────────────────────────────

    def _start_container(
        self,
        container_name: str,
        port: int,
        extra_mounts: list[tuple[str, str, bool]] | None = None,
        *,
        config_mount_exclusion_root: str | None = None,
        network_override: str | None = None,
        publish_port: bool = True,
        extra_environment: dict[str, str] | None = None,
        labels: dict[str, str] | None = None,
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
        # except a small compatibility set needed across supported AIO image
        # startup/runtime paths, privilege escalation (setuid/sudo) is blocked,
        # and CPU/memory/PID footprints are bounded so one runaway sandbox
        # cannot exhaust the host or fork-bomb it. Each knob has an env
        # escape hatch documented in backend/docs/CONFIGURATION.md. Apple
        # Container's CLI does not support these flags, so they are
        # Docker-only.
        if self._runtime == "docker":
            # Supported shipped/recommended AIO images start as root, create
            # the gem account at runtime, chown -R /opt/jupyter, and drop to
            # that user via su. CHOWN/SETUID/SETGID cover that ownership
            # handoff. FOWNER is specifically required by the newer 1.11.x
            # startup path (regression-tested against 1.11.0), which chmods
            # /run/user/1000 after capabilities are dropped. Images that do
            # not perform that chmod do not need FOWNER; DeerFlow deliberately
            # keeps this compatibility allowlist version-agnostic instead of
            # guessing from mutable tags/digests or arbitrary custom images.
            # The root nginx master also writes gem-owned logs under
            # /var/log/nginx, which requires DAC_OVERRIDE — without it nginx
            # dies with "open() .../access.log failed (13: Permission denied)"
            # on every start (a runtime need, not just startup). Dropping ALL
            # of these can make root-initialized images fail before readiness.
            # no-new-privileges stays: it only blocks *gaining* privileges
            # through exec, it does not revoke the capabilities added here,
            # and su from the already-root entrypoint does not need to gain
            # anything. Everything else (NET_RAW, SYS_PTRACE, ...) stays
            # dropped, which is the bulk of the attack-surface reduction.
            # A pre-initialized non-root image that needs none of these
            # compatibility capabilities should opt out with
            # DEER_FLOW_SANDBOX_IMAGE_STARTUP_CAPS=0 (see CONFIGURATION.md).
            # That switch drops the whole set; it is intentionally not used
            # to infer or trim individual capabilities for older/custom root-
            # initialized images that may still need the remaining entries.
            if _env_flag_disabled("DEER_FLOW_SANDBOX_IMAGE_STARTUP_CAPS"):
                cmd.extend(["--cap-drop=ALL", "--security-opt", "no-new-privileges"])
            else:
                cmd.extend(
                    [
                        "--cap-drop=ALL",
                        "--cap-add=CHOWN",
                        "--cap-add=FOWNER",
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
            network = network_override
            if network is None:
                network = os.environ.get("DEER_FLOW_SANDBOX_NETWORK", "").strip()
            if network:
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

        cmd.extend(["--rm", "-d"])
        if publish_port:
            if self._runtime == "docker":
                port_mapping = f"{_resolve_docker_bind_host()}:{port}:8080"
            else:
                port_mapping = f"{port}:8080"
            cmd.extend(["-p", port_mapping])
        cmd.extend(["--name", container_name])

        if labels and self._runtime == "docker":
            for key, value in labels.items():
                cmd.extend(["--label", f"{key}={value}"])

        # Environment variables
        for key, value in self._environment.items():
            cmd.extend(["-e", f"{key}={value}"])
        for key, value in (extra_environment or {}).items():
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
