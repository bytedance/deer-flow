from pydantic import BaseModel, ConfigDict, Field


class VolumeMountConfig(BaseModel):
    """Configuration for a volume mount."""

    host_path: str = Field(..., description="Path on the host machine")
    container_path: str = Field(..., description="Path inside the container")
    read_only: bool = Field(default=False, description="Whether the mount is read-only")


class SandboxConfig(BaseModel):
    """配置 section for a sandbox.

    Common options:
        use: Class 路径 of the sandbox provider (required)

    AioSandboxProvider specific options:
        image: Docker image to use (默认: enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:最新)
        port: Base port for sandbox containers (默认: 8080)
        replicas: Maximum 数字 of 并发 sandbox containers (默认: 3). When the limit is reached the least-recently-used sandbox is evicted to make room.
        container_prefix: Prefix for container names (默认: deer-flow-sandbox)
        idle_timeout: Idle timeout in seconds before sandbox is released (默认: 600 = 10 minutes). Set to 0 to disable.
        mounts: List of volume mounts to share directories with the container
        环境: Environment variables to inject into the container (values starting with $ are resolved from host env)
    """

    use: str = Field(
        ...,
        description="Class path of the sandbox provider (e.g. deerflow.sandbox.local:LocalSandboxProvider)",
    )
    image: str | None = Field(
        default=None,
        description="Docker image to use for the sandbox container",
    )
    port: int | None = Field(
        default=None,
        description="Base port for sandbox containers",
    )
    replicas: int | None = Field(
        default=None,
        description="Maximum number of concurrent sandbox containers (default: 3). When the limit is reached the least-recently-used sandbox is evicted to make room.",
    )
    container_prefix: str | None = Field(
        default=None,
        description="Prefix for container names",
    )
    idle_timeout: int | None = Field(
        default=None,
        description="Idle timeout in seconds before sandbox is released (default: 600 = 10 minutes). Set to 0 to disable.",
    )
    mounts: list[VolumeMountConfig] = Field(
        default_factory=list,
        description="List of volume mounts to share directories between host and container",
    )
    environment: dict[str, str] = Field(
        default_factory=dict,
        description="Environment variables to inject into the sandbox container. Values starting with $ will be resolved from host environment variables.",
    )

    model_config = ConfigDict(extra="allow")
