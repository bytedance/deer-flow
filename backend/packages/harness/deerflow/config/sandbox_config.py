from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SandboxOwnershipType = Literal["memory", "redis"]
SandboxOverflowPolicy = Literal["wait", "reject", "burst"]


class SandboxOwnershipConfig(BaseModel):
    """Configuration for cross-instance sandbox container ownership (#4206).

    Gateway instances share sandbox containers but each keeps its own in-memory
    warm pool. Without shared ownership state, one instance's reconciliation
    adopts another's live container and later idle-destroys it. This selects
    where that ownership state lives.
    """

    type: SandboxOwnershipType = Field(
        default="memory",
        description=(
            "Sandbox ownership store backend. 'memory' keeps ownership in-process (single-instance deployments only, where cross-instance adoption cannot occur). "
            "'redis' shares ownership across gateway instances and is required for load-balanced / multi-worker deployments that share a container backend."
        ),
    )
    redis_url: str | None = Field(
        default=None,
        description="Redis URL for the redis ownership type. If omitted, DEER_FLOW_SANDBOX_OWNERSHIP_REDIS_URL, DEER_FLOW_STREAM_BRIDGE_REDIS_URL, REDIS_URL, or redis://localhost:6379/0 is used.",
    )
    renewal_interval_seconds: float = Field(
        default=30.0,
        gt=0,
        allow_inf_nan=False,
        description=(
            "How often an owning instance refreshes its leases. The lease TTL is derived from this (interval x ttl_multiplier), so ownership liveness is independent of sandbox.idle_timeout: "
            "renewal keeps running even when idle cleanup is disabled (idle_timeout: 0)."
        ),
    )
    ttl_multiplier: float = Field(
        default=4.0,
        ge=2,
        allow_inf_nan=False,
        description="Lease TTL as a multiple of renewal_interval_seconds. At least 2, so a single missed renewal (slow host, brief Redis blip) cannot expire a live owner's lease. Default 4 tolerates three consecutive misses.",
    )
    key_prefix: str = Field(
        default="deerflow:sandbox:owner",
        description="Redis key prefix for ownership leases. Only applies to the redis ownership type.",
    )


class VolumeMountConfig(BaseModel):
    """Configuration for a volume mount."""

    host_path: str = Field(
        ...,
        description=(
            "Source path for the mount. Resolution depends on the active provider: "
            "``LocalSandboxProvider`` checks this path from the gateway process — in "
            "``make dev`` that is the host machine, but in Docker deployments "
            "(``make up`` / docker-compose) it is the path *inside* the "
            "``deer-flow-gateway`` container, so the host directory must also be "
            "bind-mounted into the gateway service for the mount to take effect. "
            "``AioSandboxProvider`` (DooD) passes this value straight to ``docker -v`` "
            "for the sandbox container, where it is resolved by the host Docker daemon "
            "from the host machine's perspective."
        ),
    )
    container_path: str = Field(..., description="Path inside the container")
    read_only: bool = Field(default=False, description="Whether the mount is read-only")


class SandboxConfig(BaseModel):
    """Config section for a sandbox.

    Common options:
        use: Class path of the sandbox provider (required)
        allow_host_bash: Enable host-side bash execution for LocalSandboxProvider.
            Dangerous and intended only for fully trusted local workflows.

    AioSandboxProvider, BoxliteProvider, E2BSandboxProvider, and OpenSandboxProvider shared options:
        image: Sandbox image to use (Docker/AIO, BoxLite OCI, or OpenSandbox image)
        replicas: Positive provider capacity. E2B shares it across Gateway
            workers when ownership uses Redis; other modes/providers keep
            process-local accounting.
        idle_timeout: Idle timeout in seconds before released warm sandboxes/VMs are stopped (default: 600 = 10 minutes). Set to 0 to disable.
        environment: Environment variables to inject into the sandbox (values starting with $ are resolved from host env)

    BoxliteProvider specific options:
        health_check_skip_seconds: Optional reclaim-time skip window in seconds for recently released warm VMs. Default behavior is 0.0 = always validate before reuse.

    AioSandboxProvider specific options:
        port: Base port for sandbox containers (default: 8080)
        container_prefix: Prefix for container names (default: deer-flow-sandbox)
        mounts: List of volume mounts to share directories with the container
        thread_data_mounts: Override whether thread data is already visible to
            the sandbox through shared mounts. Omit to auto-detect from the backend.

    AioSandboxProvider and E2BSandboxProvider shared options:
        ownership: Cross-instance sandbox ownership store (memory | redis). Multi-instance
            deployments sharing a sandbox backend need redis; see SandboxOwnershipConfig.

    OpenSandboxProvider specific options:
        api_key, domain, protocol, request_timeout, use_server_proxy: OpenSandbox
            management and execd connection settings.
        ready_timeout: Create/readiness deadline in seconds (default: 30).
        sandbox_timeout: Remote lifetime in seconds (default: 14400); 0 requires
            explicit provider cleanup.
    """

    use: str = Field(
        ...,
        description="Class path of the sandbox provider (e.g. deerflow.sandbox.local:LocalSandboxProvider)",
    )
    allow_host_bash: bool = Field(
        default=False,
        description="Allow the bash tool to execute directly on the host when using LocalSandboxProvider. Dangerous; intended only for fully trusted local environments.",
    )
    image: str | None = Field(
        default=None,
        description="Sandbox image to use (Docker/AIO, BoxLite OCI, or OpenSandbox image)",
    )
    port: int | None = Field(
        default=None,
        description="Base port for sandbox containers",
    )
    replicas: int | None = Field(
        default=None,
        gt=0,
        description=("Positive provider capacity. E2B enforces it deployment-wide when sandbox ownership uses Redis; otherwise accounting is per Gateway process. Each provider defines which lifecycle states count."),
    )
    overflow_policy: SandboxOverflowPolicy = Field(
        default="wait",
        description="E2B capacity policy. Use wait, reject, or burst.",
    )
    acquire_timeout: int = Field(
        default=30,
        gt=0,
        description="Seconds that E2B wait policy waits for capacity.",
    )
    burst_limit: int = Field(
        default=0,
        ge=0,
        description="Extra E2B capacity slots when overflow_policy is burst.",
    )
    container_prefix: str | None = Field(
        default=None,
        description="Prefix for container names",
    )
    idle_timeout: int | None = Field(
        default=None,
        description="Idle timeout in seconds before released warm sandboxes/VMs are stopped (default: 600 = 10 minutes). Set to 0 to disable.",
    )
    health_check_skip_seconds: float | None = Field(
        default=None,
        ge=0,
        description="BoxLite-only reclaim skip window in seconds for boxes recently released by this provider instance. Set to 0 to always validate before warm reuse.",
    )
    ownership: SandboxOwnershipConfig | None = Field(
        default=None,
        description=(
            "AioSandboxProvider/E2BSandboxProvider: where cross-instance sandbox ownership is tracked (#4206, #4341). Omitted = memory (single-instance). "
            "Multi-worker / load-balanced gateways sharing one sandbox backend must set type: redis, or peers can adopt and destroy each other's live sandboxes."
        ),
    )
    mounts: list[VolumeMountConfig] = Field(
        default_factory=list,
        description="List of volume mounts to share directories between host and container",
    )
    thread_data_mounts: bool | None = Field(
        default=None,
        description=("AioSandboxProvider: override whether /mnt/user-data is already visible through shared mounts. Omitted uses backend auto-detection; true skips explicit upload synchronization; false forces it."),
    )
    environment: dict[str, str] = Field(
        default_factory=dict,
        description="Environment variables to inject into the sandbox container. Values starting with $ will be resolved from host environment variables.",
    )

    bash_output_max_chars: int = Field(
        default=20000,
        ge=0,
        description="Maximum characters to keep from bash tool output. Output exceeding this limit is middle-truncated (head + tail), preserving the first and last half. Set to 0 to disable truncation.",
    )
    read_file_output_max_chars: int = Field(
        default=50000,
        ge=0,
        description="Maximum characters to keep from read_file tool output. Output exceeding this limit is head-truncated. Set to 0 to disable truncation.",
    )
    ls_output_max_chars: int = Field(
        default=20000,
        ge=0,
        description="Maximum characters to keep from ls tool output. Output exceeding this limit is head-truncated. Set to 0 to disable truncation.",
    )
    bash_command_timeout: int = Field(
        default=600,
        gt=0,
        description=(
            "Maximum wall-clock seconds a bash command may run before it is terminated. LocalSandboxProvider applies it to the host process group; "
            "OpenSandboxProvider forwards it to the remote exec service when a call has no explicit timeout. Keeps a blocking foreground command "
            "(e.g. an un-backgrounded server) from hanging the turn; background `&` processes return immediately."
        ),
    )

    provisioner_api_key: str | None = Field(
        default=None,
        description=(
            "API key sent as X-API-Key header to the provisioner service. "
            "Must match PROVISIONER_API_KEY on the provisioner container. "
            "Both sides must be set to the same value; "
            "the provisioner rejects all /api/* requests when the key is unset or mismatched."
        ),
    )

    model_config = ConfigDict(extra="allow")
