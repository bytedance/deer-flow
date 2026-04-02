"""Shared test helpers for title configuration."""

from deerflow.config.title_config import TitleConfig


def clone_title_config(config: TitleConfig) -> TitleConfig:
    """Return a detached copy of the global title config for test isolation."""
    return TitleConfig(**config.model_dump())
