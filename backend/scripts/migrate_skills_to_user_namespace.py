"""Migrate flat custom-skill layout to per-user namespace.

Moves every skill directory directly under ``skills/custom/<name>/`` into
``skills/custom/default/<name>/``, where ``"default"`` is the fallback user ID
used by unauthenticated single-user deployments.

Before:
    skills/custom/<name>/SKILL.md
    skills/custom/.history/<name>.jsonl

After:
    skills/custom/default/<name>/SKILL.md
    skills/custom/default/.history/<name>.jsonl

The script is idempotent: if the target path already exists it is skipped.
Run with ``--dry-run`` to preview actions without modifying the filesystem.

Usage::

    python scripts/migrate_skills_to_user_namespace.py [--skills-root PATH] [--dry-run]
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


def _is_flat_skill_dir(path: Path) -> bool:
    """Return True if *path* looks like a flat-layout skill directory."""
    return path.is_dir() and not path.name.startswith(".") and (path / "SKILL.md").exists()


def migrate(skills_root: Path, *, dry_run: bool) -> int:
    """Migrate flat layout under *skills_root* to the per-user namespace.

    Returns the number of items migrated (skills + history files).
    """
    custom_dir = skills_root / "custom"
    if not custom_dir.exists():
        print(f"No custom skills directory found at {custom_dir}. Nothing to migrate.")
        return 0

    target_user_dir = custom_dir / "default"
    target_history_dir = target_user_dir / ".history"

    migrated = 0

    # --- Migrate skill directories ---
    for entry in sorted(custom_dir.iterdir()):
        if not _is_flat_skill_dir(entry):
            continue

        target = target_user_dir / entry.name
        if target.exists():
            print(f"  SKIP  {entry.name}/ (target already exists at {target})")
            continue

        print(f"  MOVE  custom/{entry.name}/ -> custom/default/{entry.name}/")
        if not dry_run:
            target_user_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(entry), str(target))
        migrated += 1

    # --- Migrate history files ---
    old_history_dir = custom_dir / ".history"
    if old_history_dir.exists() and old_history_dir.is_dir():
        for history_file in sorted(old_history_dir.iterdir()):
            if not history_file.is_file():
                continue
            target_file = target_history_dir / history_file.name
            if target_file.exists():
                print(f"  SKIP  .history/{history_file.name} (target already exists)")
                continue
            print(f"  MOVE  custom/.history/{history_file.name} -> custom/default/.history/{history_file.name}")
            if not dry_run:
                target_history_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(history_file), str(target_file))
            migrated += 1

        # Remove old .history dir only when empty and not dry-run
        if not dry_run and old_history_dir.exists() and not any(old_history_dir.iterdir()):
            old_history_dir.rmdir()
            print(f"  RMDIR custom/.history/ (now empty)")

    return migrated


def _resolve_skills_root(override: str | None) -> Path:
    if override:
        return Path(override)
    try:
        import os
        import sys

        backend_dir = Path(__file__).resolve().parent.parent
        sys.path.insert(0, str(backend_dir / "packages" / "harness"))
        os.chdir(backend_dir)
        from deerflow.config import get_app_config

        return get_app_config().skills.get_skills_path()
    except Exception as exc:
        print(f"Could not auto-detect skills root from config ({exc}).", file=sys.stderr)
        print("Pass --skills-root explicitly.", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skills-root", metavar="PATH", help="Path to the skills root directory (auto-detected from config.yaml if omitted)")
    parser.add_argument("--dry-run", action="store_true", help="Preview actions without modifying the filesystem")
    args = parser.parse_args()

    skills_root = _resolve_skills_root(args.skills_root)
    print(f"Skills root: {skills_root}")
    if args.dry_run:
        print("DRY RUN — no files will be moved.\n")

    count = migrate(skills_root, dry_run=args.dry_run)

    if count == 0:
        print("Nothing to migrate.")
    elif args.dry_run:
        print(f"\nDry run complete. {count} item(s) would be migrated.")
    else:
        print(f"\nMigration complete. {count} item(s) moved.")


if __name__ == "__main__":
    main()
