"""Migrate memory.json files to LangGraph Store (PostgreSQL).

Reads memory from FileMemoryStorage JSON files and writes them to the
LangGraph Store using the same namespace scheme as StoreMemoryStorage:
    namespace = ("memory", tenant_id, user_id, agent_name)
    key       = "data"

Usage:
    python scripts/migrate_memory_to_store.py \\
        --postgres-url postgresql://user:pass@host:5432/db
"""

import argparse
import json
import logging
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

LEGACY_USER_DIR = "users"


def load_memory_file(file_path: Path) -> dict[str, Any] | None:
    """Load memory data from a JSON file."""
    try:
        with open(file_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error("Failed to load %s: %s", file_path, e)
        return None


def find_memory_files(base_dir: Path) -> list[tuple[Path, str, str | None]]:
    """Scan for memory.json files under base_dir.

    Returns list of (file_path, user_id, agent_name | None).

    Recognised layouts:
        {base_dir}/memory.json                          -> ("default", None)
        {base_dir}/agents/{name}/memory.json            -> ("default", name)
        {base_dir}/users/{uid}/memory.json              -> (uid, None)
        {base_dir}/users/{uid}/agents/{name}/memory.json -> (uid, name)
    """
    results: list[tuple[Path, str, str | None]] = []

    # Tenant-level (single-tenant layout)
    tenant_mem = base_dir / "memory.json"
    if tenant_mem.exists():
        results.append((tenant_mem, "default", None))

    # Tenant-level agents
    agents_dir = base_dir / "agents"
    if agents_dir.is_dir():
        for agent_dir in sorted(agents_dir.iterdir()):
            mf = agent_dir / "memory.json"
            if agent_dir.is_dir() and mf.exists():
                results.append((mf, "default", agent_dir.name))

    # Per-user layout
    users_dir = base_dir / LEGACY_USER_DIR
    if users_dir.is_dir():
        for user_dir in sorted(users_dir.iterdir()):
            if not user_dir.is_dir():
                continue
            user_id = user_dir.name

            user_mem = user_dir / "memory.json"
            if user_mem.exists():
                results.append((user_mem, user_id, None))

            user_agents = user_dir / "agents"
            if user_agents.is_dir():
                for agent_dir in sorted(user_agents.iterdir()):
                    mf = agent_dir / "memory.json"
                    if agent_dir.is_dir() and mf.exists():
                        results.append((mf, user_id, agent_dir.name))

    return results


def migrate_memory_to_store(
    postgres_url: str,
    *,
    base_dir: Path | None = None,
    tenant_id: str = "default",
    dry_run: bool = False,
) -> bool:
    """Migrate all memory.json files to LangGraph PostgresStore.

    Returns True if every file was migrated (or skipped as existing), False otherwise.
    """
    from deerflow.config.paths import Paths

    try:
        from langgraph.store.postgres import PostgresStore
    except ImportError as exc:
        raise ImportError(
            "langgraph-checkpoint-postgres is required. "
            "Install with: uv add langgraph-checkpoint-postgres psycopg[binary]"
        ) from exc

    scan_dir = base_dir if base_dir is not None else Paths().base_dir

    memory_files = find_memory_files(scan_dir)
    logger.info("Found %d memory files to migrate", len(memory_files))

    if not memory_files:
        logger.info("No memory files found")
        return True

    if dry_run:
        logger.info("Dry run mode - no changes will be made")
        for file_path, user_id, agent_name in memory_files:
            logger.info(
                "  Would migrate: user=%s, agent=%s",
                user_id,
                agent_name or "default",
            )
        return True

    migrated_count = 0
    failed_count = 0

    with PostgresStore.from_conn_string(postgres_url) as store:
        store.setup()

        for file_path, user_id, agent_name in memory_files:
            memory_data = load_memory_file(file_path)
            if memory_data is None:
                failed_count += 1
                continue

            ns = ("memory", tenant_id, user_id, agent_name or "default")

            existing = store.get(ns, "data")
            if existing is not None and existing.value is not None:
                logger.info(
                    "Skipping existing: user=%s, agent=%s",
                    user_id,
                    agent_name or "default",
                )
                migrated_count += 1
                continue

            store.put(ns, "data", memory_data)
            logger.info(
                "Migrated: user=%s, agent=%s",
                user_id,
                agent_name or "default",
            )
            migrated_count += 1

    logger.info(
        "Migration complete: %d migrated, %d failed",
        migrated_count,
        failed_count,
    )
    return failed_count == 0


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Migrate memory.json files to LangGraph PostgresStore",
    )
    parser.add_argument(
        "--postgres-url",
        required=True,
        help="PostgreSQL connection URL",
    )
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=None,
        help="Base directory to scan (defaults to DeerFlow base_dir)",
    )
    parser.add_argument(
        "--tenant-id",
        default="default",
        help="Tenant ID for Store namespace (default: 'default')",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be migrated without making changes",
    )

    args = parser.parse_args()

    success = migrate_memory_to_store(
        postgres_url=args.postgres_url,
        base_dir=args.base_dir,
        tenant_id=args.tenant_id,
        dry_run=args.dry_run,
    )
    exit(0 if success else 1)


if __name__ == "__main__":
    main()
