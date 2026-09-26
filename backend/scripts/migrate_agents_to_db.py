#!/usr/bin/env python
"""One-shot importer: copy file-backed agent definitions into ``db`` stores.

For operators switching ``agent_storage.backend`` from ``file`` to ``db``. Reads
every Custom Agent from the on-disk layout (both the per-user
``{base_dir}/users/{user_id}/agents/`` and the legacy shared
``{base_dir}/agents/``, with the same shadowing rule the file store uses) and
writes each as a row in the shared ``agents`` table. It also copies every
deployment-level definition from ``{base_dir}/managed-subagents/`` into the
shared ``managed_subagents`` table.

Design (mirrors ``scripts/migrate_user_isolation.py``):
- Explicit, operator-run. Nothing auto-imports on boot.
- Idempotent: a definition already present in the db is skipped, so re-running is safe.
- Non-destructive: the on-disk files are left untouched, so unsetting
  ``agent_storage.backend`` (back to ``file``) is a clean rollback.

Usage::

    python scripts/migrate_agents_to_db.py [--dry-run]

Requires ``database.backend`` to be ``sqlite`` or ``postgres`` in config.yaml.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from deerflow.config.app_config import get_app_config
from deerflow.persistence.agents.base import AgentExistsError
from deerflow.persistence.agents.file import FileAgentStore
from deerflow.persistence.agents.sql import SqlAgentStore
from deerflow.persistence.managed_subagents.base import ManagedSubagentExistsError
from deerflow.persistence.managed_subagents.file import FileManagedSubagentStore
from deerflow.persistence.managed_subagents.sql import SqlManagedSubagentStore

logger = logging.getLogger("migrate_agents_to_db")


def main() -> int:
    parser = argparse.ArgumentParser(description="Import file-backed Custom Agents and managed subagents into db stores.")
    parser.add_argument("--dry-run", action="store_true", help="List what would be imported without writing to the database.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    config = get_app_config()
    db_backend = getattr(config.database, "backend", None)
    if db_backend not in ("sqlite", "postgres"):
        logger.error(
            "database.backend is %r; this importer needs 'sqlite' or 'postgres'. Set it in config.yaml (the same database the gateway uses).",
            db_backend,
        )
        return 1

    agent_source = FileAgentStore()
    agents = agent_source.list_all()
    managed_source = FileManagedSubagentStore()
    managed_definitions = managed_source.list()
    if not agents and not managed_definitions:
        logger.info("No file-backed Custom Agents or managed subagents found — nothing to import.")
        return 0

    if args.dry_run:
        for user_id, cfg in agents:
            logger.info("[dry-run] would import Custom Agent %s/%s", user_id, cfg.name)
        for definition in managed_definitions:
            logger.info("[dry-run] would import managed subagent %s", definition.name)
        logger.info(
            "[dry-run] %d Custom Agent(s) and %d managed subagent(s) would be imported. Source files are left in place.",
            len(agents),
            len(managed_definitions),
        )
        return 0

    # Ensure the schema exists (creates both definition tables via the same
    # Alembic bootstrap the gateway runs) before the sync stores write rows.
    from deerflow.persistence.engine import init_engine_from_config

    asyncio.run(init_engine_from_config(config.database))

    agent_dest = SqlAgentStore(config.database.app_sync_sqlalchemy_url)
    managed_dest = SqlManagedSubagentStore(config.database.app_sync_sqlalchemy_url)
    imported_agents = 0
    skipped_agents = 0
    for user_id, cfg in agents:
        soul = agent_source.get_soul(cfg.name, user_id=user_id) or ""
        # exclude_unset keeps the stored document as sparse as the source file
        # (only the keys the operator actually wrote), matching the file layout.
        document = cfg.model_dump(exclude_unset=True)
        try:
            agent_dest.create(cfg.name, document, soul, user_id=user_id)
            imported_agents += 1
            logger.info("imported Custom Agent %s/%s", user_id, cfg.name)
        except AgentExistsError:
            skipped_agents += 1
            logger.info("skip Custom Agent %s/%s: already present in db", user_id, cfg.name)

    imported_managed = 0
    skipped_managed = 0
    for definition in managed_definitions:
        try:
            managed_dest.create(definition)
            imported_managed += 1
            logger.info("imported managed subagent %s", definition.name)
        except ManagedSubagentExistsError:
            skipped_managed += 1
            logger.info("skip managed subagent %s: already present in db", definition.name)

    logger.info(
        "Done: Custom Agents: %d imported, %d already present; managed subagents: %d imported, %d already present. Source files left in place (rollback: revert agent_storage.backend to 'file').",
        imported_agents,
        skipped_agents,
        imported_managed,
        skipped_managed,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
