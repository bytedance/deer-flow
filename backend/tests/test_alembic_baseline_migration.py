"""Tests for KB usability sprint Alembic baseline migration (revision 003)."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


@pytest.fixture
def alembic_cfg(tmp_path: Path) -> tuple[Config, str]:
    """Build an Alembic Config pointed at a throwaway SQLite DB.

    Mimics a 002-era deployment: tables created via ``create_all`` from the
    current model, but the rev-003 columns dropped so the upgrade can
    add them. The DB is then stamped at ``002`` so the rev-003 migration
    is the only outstanding step.
    """
    db_path = tmp_path / "kb_baseline.db"
    async_url = f"sqlite+aiosqlite:///{db_path}"
    sync_url = f"sqlite:///{db_path}"

    import deerflow.persistence.models  # noqa: F401  — register all tables
    from deerflow.persistence.base import Base

    sync_engine = create_engine(sync_url, future=True)
    try:
        Base.metadata.create_all(sync_engine)

        # Strip the rev-003 columns to simulate the pre-baseline schema.
        with sync_engine.begin() as conn:
            for col in ("embedding_model", "embedding_dim", "vector_metric_stale"):
                conn.exec_driver_sql(f"ALTER TABLE knowledge_bases DROP COLUMN {col}")
            conn.exec_driver_sql(
                "ALTER TABLE knowledge_base_documents DROP COLUMN index_queued_at"
            )
    finally:
        sync_engine.dispose()

    here = (
        Path(__file__).resolve().parents[1]
        / "packages"
        / "harness"
        / "deerflow"
        / "persistence"
        / "migrations"
    )
    cfg = Config(str(here / "alembic.ini"))
    cfg.set_main_option("script_location", str(here))
    cfg.set_main_option("sqlalchemy.url", async_url)

    command.stamp(cfg, "002")
    return cfg, sync_url


def _columns(sync_url: str, table: str) -> set[str]:
    engine = create_engine(sync_url, future=True)
    try:
        return {c["name"] for c in inspect(engine).get_columns(table)}
    finally:
        engine.dispose()


def test_upgrade_head_adds_kb_usability_columns(alembic_cfg) -> None:
    cfg, url = alembic_cfg

    pre_kb_cols = _columns(url, "knowledge_bases")
    assert "embedding_model" not in pre_kb_cols  # dropped by fixture

    command.upgrade(cfg, "head")

    kb_cols = _columns(url, "knowledge_bases")
    assert "embedding_model" in kb_cols
    assert "embedding_dim" in kb_cols
    assert "vector_metric_stale" in kb_cols

    doc_cols = _columns(url, "knowledge_base_documents")
    assert "index_queued_at" in doc_cols


def test_downgrade_then_upgrade_is_idempotent(alembic_cfg) -> None:
    cfg, url = alembic_cfg

    command.upgrade(cfg, "head")
    kb_cols_before = _columns(url, "knowledge_bases")

    command.downgrade(cfg, "-1")
    kb_cols_after_down = _columns(url, "knowledge_bases")
    assert "embedding_model" not in kb_cols_after_down
    assert "embedding_dim" not in kb_cols_after_down
    assert "vector_metric_stale" not in kb_cols_after_down

    doc_cols_after_down = _columns(url, "knowledge_base_documents")
    assert "index_queued_at" not in doc_cols_after_down

    command.upgrade(cfg, "head")
    kb_cols_after_up = _columns(url, "knowledge_bases")
    assert kb_cols_after_up == kb_cols_before


def test_upgrade_is_idempotent_when_run_twice(alembic_cfg) -> None:
    cfg, url = alembic_cfg
    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")
    kb_cols = _columns(url, "knowledge_bases")
    assert "embedding_model" in kb_cols
