#!/usr/bin/env python3
"""Load the Memory Settings review sample into a local DeerFlow runtime."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path


def default_source(repo_root: Path) -> Path:
    return repo_root / "backend" / "docs" / "memory-settings-sample.json"


def default_target(repo_root: Path) -> Path:
    return repo_root / "backend" / ".deer-flow" / "memory.json"


def parse_args(repo_root: Path) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Copy the Memory Settings sample data into the local runtime memory file.",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=default_source(repo_root),
        help="Path to the sample JSON file.",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=default_target(repo_root),
        help="Path to the runtime memory.json file.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Overwrite the target without writing a backup copy first.",
    )
    return parser.parse_args()


def validate_json_file(path: Path) -> None:
    with path.open(encoding="utf-8") as handle:
        json.load(handle)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    args = parse_args(repo_root)

    source = args.source.resolve()
    target = args.target.resolve()

    if not source.exists():
        raise SystemExit(f"Sample file not found: {source}")

    validate_json_file(source)
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
