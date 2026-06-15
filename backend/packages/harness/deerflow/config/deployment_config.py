"""Deployment mode configuration — single-worker vs multi-worker orchestration."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class DeploymentConfig(BaseModel):
    """Configuration for deployment mode.

    In ``single_worker`` mode (default), all stateful components use
    process-local backends (in-memory, file, SQLite, ChromaDB).

    In ``multi_worker`` mode, components automatically switch to shared
    backends (PostgreSQL + Redis) so multiple worker processes can
    share state.
    """

    mode: Literal["single_worker", "multi_worker"] = Field(
        default="single_worker",
        description="Deployment mode: 'single_worker' (process-local backends) or 'multi_worker' (shared PostgreSQL + Redis backends)",
    )


_deployment_config: DeploymentConfig | None = None


def get_deployment_config() -> DeploymentConfig:
    """Get the current deployment config singleton."""
    global _deployment_config
    if _deployment_config is None:
        _deployment_config = DeploymentConfig()
    return _deployment_config


def load_deployment_config_from_dict(data: dict) -> DeploymentConfig:
    """Load deployment config from a dictionary."""
    global _deployment_config
    _deployment_config = DeploymentConfig.model_validate(data)
    return _deployment_config


def reset_deployment_config() -> None:
    """Reset the deployment config singleton."""
    global _deployment_config
    _deployment_config = None
