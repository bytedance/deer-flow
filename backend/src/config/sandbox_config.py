from pydantic import BaseModel, ConfigDict, Field


class VolumeMountConfig(BaseModel):
    """Configuration for a volume mount."""

    host_path: str = Field(..., description="Path on the host machine")
    container_path: str = Field(..., description="Path inside the container")
    read_only: bool = Field(default=False, description="Whether the mount is read-only")


class SandboxConfig(BaseModel):
    """Config section for a sandbox.

    Common options:
        use: Class path of the sandbox provider (required)

    AioSandboxProvider specific options:
        image: Docker image to use (default: enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest)
        port: Base port for sandbox containers (default: 8080)
        base_url: If set, uses existing sandbox instead of starting new container
        auto_start: Whether to automatically start Docker container (default: true)
        container_prefix: Prefix for container names (default: deer-flow-sandbox)
        idle_timeout: Idle timeout in seconds before sandbox is released (default: 900 = 15 minutes). Set to 0 to disable.
        max_sandboxes_per_user: Maximum concurrent sandboxes per user (default: 3). Set to 0 to disable quota.
        mounts: List of volume mounts to share directories with the container
        environment: Environment variables to inject into the container (values starting with $ are resolved from host env)
    """

    use: str = Field(
        ...,
        description="Class path of the sandbox provider (e.g. src.sandbox.local:LocalSandboxProvider)",
    )
    image: str | None = Field(
        default=None,
        description="Docker image to use for the sandbox container",
    )
    port: int | None = Field(
        default=None,
        description="Base port for sandbox containers",
    )
    base_url: str | None = Field(
        default=None,
        description="If set, uses existing sandbox at this URL instead of starting new container",
    )
    auto_start: bool | None = Field(
        default=None,
        description="Whether to automatically start Docker container",
    )
    container_prefix: str | None = Field(
        default=None,
        description="Prefix for container names",
    )
    idle_timeout: int | None = Field(
        default=None,
        description="Idle timeout in seconds before sandbox is released (default: 900 = 15 minutes). Set to 0 to disable.",
    )
    max_sandboxes_per_user: int = Field(
        default=3,
        description="Maximum number of concurrent sandboxes per user (default: 3). Set to 0 to disable quota.",
    )
    mounts: list[VolumeMountConfig] = Field(
        default_factory=list,
        description="List of volume mounts to share directories between host and container",
    )
    environment: dict[str, str] = Field(
        default_factory=dict,
        description="Environment variables to inject into the sandbox container. Values starting with $ will be resolved from host environment variables.",
    )
    ptc_enabled: bool = Field(
        default=False,
        description="Enable Programmatic Tool Calling (PTC). When true, execute_python can call MCP tools as Python functions via a host-side proxy.",
    )

    model_config = ConfigDict(extra="allow")
