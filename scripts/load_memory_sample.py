#!/usr/bin/env python3
"""Load the Memory Settings review sample into a local DeerFlow runtime."""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import shutil
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any


def default_source(repo_root: Path) -> Path:
    return repo_root / "backend" / "docs" / "memory-settings-sample.json"


def parse_args(repo_root: Path, argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load Memory Settings sample data into DeerFlow runtime memory.",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=default_source(repo_root),
        help="Path to the sample JSON file.",
    )
    target_group = parser.add_mutually_exclusive_group(required=True)
    target_group.add_argument(
        "--target",
        type=Path,
        help="Path to one runtime memory.json file.",
    )
    target_group.add_argument(
        "--all-users",
        action="store_true",
        help="Replace memory for every registered database user.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Overwrite memory without writing backup copies first.",
    )
    return parser.parse_args(argv)


def load_json_file(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise SystemExit(f"Memory sample must be a JSON object: {path}")
    return data


def require_persistent_database(backend: str) -> None:
    if backend == "memory":
        raise SystemExit("--all-users requires database.backend sqlite or postgres")


def load_sample_for_users(
    sample: dict[str, Any],
    user_ids: list[str],
    *,
    backup_root: Path | None,
    no_backup: bool,
    load_memory: Callable[..., dict[str, Any]],
    import_memory: Callable[..., dict[str, Any]],
) -> int:
    if not user_ids:
        return 0

    if not no_backup:
        if backup_root is None:
            raise ValueError("backup_root is required when backups are enabled")
        existing = {user_id: load_memory(user_id=user_id) for user_id in user_ids}
        backup_root.mkdir(parents=True, exist_ok=True)
        for user_id, memory in existing.items():
            (backup_root / f"{user_id}.json").write_text(
                json.dumps(memory, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

    for user_id in user_ids:
        try:
            import_memory(copy.deepcopy(sample), user_id=user_id)
        except OSError as exc:
            raise OSError(f"Failed to import memory for user {user_id}: {exc}") from exc

    return len(user_ids)


async def load_sample_for_all_users(
    repo_root: Path,
    sample: dict[str, Any],
    *,
    no_backup: bool,
) -> tuple[int, Path | None]:
    backend_dir = repo_root / "backend"
    sys.path.insert(0, str(backend_dir))
    sys.path.insert(0, str(backend_dir / "packages" / "harness"))

    from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
    from deerflow.agents.memory.updater import get_memory_data, import_memory_data
    from deerflow.config.app_config import AppConfig
    from deerflow.config.paths import get_paths
    from deerflow.persistence.engine import (
        close_engine,
        get_session_factory,
        init_engine_from_config,
    )

    config = await asyncio.to_thread(AppConfig.from_file, str(repo_root / "config.yaml"))
    require_persistent_database(config.database.backend)

    await init_engine_from_config(config.database)
    try:
        session_factory = get_session_factory()
        if session_factory is None:
            raise SystemExit("Registered-user persistence is unavailable")

        user_ids = await SQLiteUserRepository(session_factory).list_user_ids()
        backup_root = None
        if user_ids and not no_backup:
            backup_root = get_paths().base_dir / "memory-sample-backups" / datetime.now().strftime("%Y%m%d-%H%M%S")

        count = await asyncio.to_thread(
            load_sample_for_users,
            sample,
            user_ids,
            backup_root=backup_root,
            no_backup=no_backup,
            load_memory=get_memory_data,
            import_memory=import_memory_data,
        )
        return count, backup_root
    finally:
        await close_engine()


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    args = parse_args(repo_root, argv)

    source = args.source.resolve()
    if not source.exists():
        raise SystemExit(f"Sample file not found: {source}")

    sample = load_json_file(source)

    if args.all_users:
        count, backup_root = asyncio.run(
            load_sample_for_all_users(repo_root, sample, no_backup=args.no_backup),
        )
        print(f"Loaded sample memory for {count} registered user(s).")
        if backup_root is not None:
            print(f"Backups created under: {backup_root}")
        else:
            print("No backups created.")
        return 0

    assert args.target is not None
    target = args.target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    backup_path: Path | None = None
    if target.exists() and not args.no_backup:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = target.with_name(f"{target.name}.bak-{timestamp}")
        shutil.copy2(target, backup_path)

    shutil.copy2(source, target)

    print(f"Loaded sample memory into: {target}")
    if backup_path is not None:
        print(f"Backup created at: {backup_path}")
    else:
        print("No backup created.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
