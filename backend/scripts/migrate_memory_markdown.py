"""Proactively migrate legacy global JSON facts into Markdown fact files.

Normal DeerMem reads already perform this migration lazily. This CLI lets an
operator preview or complete the same idempotent migration before serving
traffic, which is useful for multi-user upgrade audits.

Usage from ``backend/``::

    PYTHONPATH=. python scripts/migrate_memory_markdown.py --all-users --dry-run
    PYTHONPATH=. python scripts/migrate_memory_markdown.py --all-users
    PYTHONPATH=. python scripts/migrate_memory_markdown.py --user-id alice
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.paths import DEFAULT_AGENT_BUCKET, memory_file_path
from deerflow.agents.memory.backends.deermem.deermem.core.storage import DOCUMENT_VERSION, FileMemoryStorage
from deerflow.config.runtime_paths import runtime_home


def discover_user_ids(storage_path: Path) -> list[str]:
    """Return directory-safe user IDs found below one DeerMem storage root."""
    users_root = storage_path / "users"
    if not users_root.is_dir():
        return []
    return sorted(entry.name for entry in users_root.iterdir() if entry.is_dir())


def _inspect_legacy_global_json(config: DeerMemConfig, user_id: str) -> tuple[Path, bool]:
    path = memory_file_path(config, user_id=user_id)
    if not path.exists():
        return path, False
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot parse {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return path, "facts" in document or document.get("version") != DOCUMENT_VERSION


def migrate_users(
    config: DeerMemConfig,
    user_ids: list[str],
    *,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Migrate selected users independently and return an audit-friendly report."""
    storage = FileMemoryStorage(config)
    report: list[dict[str, Any]] = []
    for user_id in user_ids:
        entry: dict[str, Any] = {"user_id": user_id, "status": "current", "path": "", "error": None}
        try:
            path, needs_migration = _inspect_legacy_global_json(config, user_id)
            entry["path"] = str(path)
            if not needs_migration:
                report.append(entry)
                continue
            if dry_run:
                entry["status"] = "planned"
            else:
                result = storage.migrate(user_id=user_id, agent_name=DEFAULT_AGENT_BUCKET)
                entry["status"] = "migrated" if result.get("migrated") else "current"
                entry["from_version"] = result.get("fromVersion")
                entry["to_version"] = result.get("toVersion")
        except Exception as exc:  # noqa: BLE001 - one bad user must not hide the rest of the audit
            entry["status"] = "failed"
            entry["error"] = str(exc)
        report.append(entry)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=("Proactively migrate legacy facts from each user's memory.json into the reserved __default__ Markdown fact bucket."))
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--all-users",
        action="store_true",
        help="Migrate every directory-safe user bucket found under STORAGE_PATH/users.",
    )
    selection.add_argument(
        "--user-id",
        action="append",
        dest="user_ids",
        metavar="USER_ID",
        help="Migrate one original user ID; repeat this option for multiple users.",
    )
    parser.add_argument(
        "--storage-path",
        type=Path,
        default=None,
        help="DeerMem root directory; defaults to DeerFlow's runtime home.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report pending migrations without changing files.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    storage_path = (args.storage_path or runtime_home()).resolve()
    config = DeerMemConfig(storage_path=str(storage_path))
    user_ids = discover_user_ids(storage_path) if args.all_users else list(dict.fromkeys(args.user_ids or []))

    print(f"Storage root: {storage_path}")
    if not user_ids:
        print("No user buckets found; nothing to migrate.")
        return 0

    report = migrate_users(config, user_ids, dry_run=args.dry_run)
    for entry in report:
        status = entry["status"]
        user_id = entry["user_id"]
        if status == "planned":
            print(f"{user_id}: would migrate {entry['path']}")
        elif status == "migrated":
            print(f"{user_id}: migrated {entry['path']} ({entry.get('from_version')} -> {entry.get('to_version')})")
        elif status == "failed":
            print(f"{user_id}: FAILED: {entry['error']}")
        else:
            print(f"{user_id}: already current")

    migrated = sum(entry["status"] == "migrated" for entry in report)
    planned = sum(entry["status"] == "planned" for entry in report)
    current = sum(entry["status"] == "current" for entry in report)
    failed = sum(entry["status"] == "failed" for entry in report)
    print(f"Summary: migrated={migrated} planned={planned} current={current} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
