"""Factory for app-owned run event store backends."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.storage import AppRunEventStore
from deerflow.config import get_app_config

from .jsonl_store import JsonlRunEventStore


def build_run_event_store(session_factory: async_sessionmaker[AsyncSession]) -> AppRunEventStore | JsonlRunEventStore:
    """Build the run event store selected by app configuration."""

    config = get_app_config().run_events
    if config.backend == "db":
        return AppRunEventStore(session_factory)
    if config.backend == "jsonl":
        return JsonlRunEventStore(
            base_dir=Path(config.jsonl_base_dir),
        )
    raise ValueError(f"Unsupported run event backend: {config.backend}")
