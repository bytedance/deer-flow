"""Configuration for workspace backend."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class MinioConfig(BaseModel):
    """MinIO connection configuration."""

    endpoint: str = Field(default="localhost:9000", description="MinIO server endpoint")
    bucket: str = Field(default="deer-flow", description="S3 bucket name")
    access_key: str = Field(default="", description="MinIO access key")
    secret_key: str = Field(default="", description="MinIO secret key")
    secure: bool = Field(default=False, description="Use TLS/HTTPS")
    prefix: str = Field(default="workspaces", description="Object key prefix")


class WorkspaceConfig(BaseModel):
    """Configuration for agent persistent workspace storage."""

    backend: Literal["local", "minio"] = Field(
        default="local",
        description=(
            "Workspace storage backend. "
            "'local' = local filesystem under identity_workspace_dir (default). "
            "'minio' = MinIO object storage for distributed / multi-node setups."
        ),
    )
    minio: MinioConfig | None = Field(
        default=None,
        description="MinIO configuration (required when backend is 'minio').",
    )

    model_config = {"extra": "allow"}


# Global instance
_workspace_config: WorkspaceConfig = WorkspaceConfig()


def get_workspace_config() -> WorkspaceConfig:
    """Get the current workspace configuration."""
    return _workspace_config


def set_workspace_config(config: WorkspaceConfig) -> None:
    """Set the workspace configuration."""
    global _workspace_config
    _workspace_config = config


def load_workspace_config_from_dict(config_dict: dict[str, Any]) -> None:
    """Load workspace configuration from a dictionary."""
    global _workspace_config
    _workspace_config = WorkspaceConfig(**config_dict)
