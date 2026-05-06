"""One-time migration: move legacy thread dirs and memory into per-user layout.

Usage:
    PYTHONPATH=. python scripts/migrate_user_isolation.py [--dry-run]

The script is idempotent — re-running it after a successful migration is a no-op.
"""

import argparse
import logging
import shutil

from deerflow.config.paths import Paths, get_paths

logger = logging.getLogger(__name__)


def migrate_thread_dirs(
    paths: Paths,
    thread_owner_map: dict[str, str],
    *,
    dry_run: bool = False,
) -> list[dict]:
    """Move legacy thread directories into per-user layout.

    Args:
        paths: Paths instance.
        thread_owner_map: Mapping of thread_id -> user_id from threads_meta table.
        dry_run: If True, only log what would happen.

    Returns:
        List of migration report entries.
    """
    report: list[dict] = []
    legacy_threads = paths.base_dir / "threads"
    if not legacy_threads.exists():
        logger.info("No legacy threads directory found — nothing to migrate.")
        return report

    for thread_dir in sorted(legacy_threads.iterdir()):
        if not thread_dir.is_dir():
            continue
        thread_id = thread_dir.name
        user_id = thread_owner_map.get(thread_id, "default")
        dest = paths.base_dir / "users" / user_id / "threads" / thread_id

        entry = {"thread_id": thread_id, "user_id": user_id, "action": ""}

        if dest.exists():
            conflicts_dir = paths.base_dir / "migration-conflicts" / thread_id
            entry["action"] = f"conflict -> {conflicts_dir}"
            if not dry_run:
                conflicts_dir.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(thread_dir), str(conflicts_dir))
            logger.warning("Conflict for thread %s: moved to %s", thread_id, conflicts_dir)
        else:
            entry["action"] = f"moved -> {dest}"
            if not dry_run:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(thread_dir), str(dest))
            logger.info("Migrated thread %s -> user %s", thread_id, user_id)

        report.append(entry)

    # Clean up empty legacy threads dir
    if not dry_run and legacy_threads.exists() and not any(legacy_threads.iterdir()):
        legacy_threads.rmdir()

    return report


def migrate_memory(
    paths: Paths,
    user_id: str = "default",
    *,
    dry_run: bool = False,
) -> None:
    """Move legacy global memory.json into per-user layout.

    Args:
        paths: Paths instance.
        user_id: Target user to receive the legacy memory.
        dry_run: If True, only log.
    """
    legacy_mem = paths.base_dir / "memory.json"
    if not legacy_mem.exists():
        logger.info("No legacy memory.json found — nothing to migrate.")
        return

    dest = paths.user_memory_file(user_id)
    if dest.exists():
        legacy_backup = paths.base_dir / "memory.legacy.json"
        logger.warning("Destination %s exists; renaming legacy to %s", dest, legacy_backup)
        if not dry_run:
            legacy_mem.rename(legacy_backup)
        return

    logger.info("Migrating memory.json -> %s", dest)
    if not dry_run:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(legacy_mem), str(dest))


def _build_owner_map_from_db(paths: Paths) -> dict[str, str]:
    """Query threads_meta table for thread_id -> user_id mapping.

    Uses raw sqlite3 to avoid async dependencies.
    """
    import sqlite3

    db_path = paths.base_dir / "deer-flow.db"
    if not db_path.exists():
        logger.info("No database found at %s — using empty owner map.", db_path)
        return {}

    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.execute("SELECT thread_id, user_id FROM threads_meta WHERE user_id IS NOT NULL")
        return {row[0]: row[1] for row in cursor.fetchall()}
    except sqlite3.OperationalError as e:
        logger.warning("Failed to query threads_meta: %s", e)
        return {}
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate DeerFlow data to per-user layout")
    parser.add_argument("--dry-run", action="store_true", help="Log actions without making changes")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    paths = get_paths()
    logger.info("Base directory: %s", paths.base_dir)
    logger.info("Dry run: %s", args.dry_run)

    owner_map = _build_owner_map_from_db(paths)
    logger.info("Found %d thread ownership records in DB", len(owner_map))

    report = migrate_thread_dirs(paths, owner_map, dry_run=args.dry_run)
    migrate_memory(paths, user_id="default", dry_run=args.dry_run)

    if report:
        logger.info("Migration report:")
        for entry in report:
            logger.info("  thread=%s user=%s action=%s", entry["thread_id"], entry["user_id"], entry["action"])
    else:
        logger.info("No threads to migrate.")

    unowned = [e for e in report if e["user_id"] == "default"]
    if unowned:
        logger.warning("%d thread(s) had no owner and were assigned to 'default':", len(unowned))
        for e in unowned:
            logger.warning("  %s", e["thread_id"])


if __name__ == "__main__":
    main()
