"""Shared project-index utilities for global/project-level config managers.

Used by metrics_manager, db_manager, and schema_manager to track which
project directories have local configuration files. Provides:

- JSON index load/save
- Project directory registration
- Active-project discovery (which projects contain cwd)
- Path containment check (Python 3.8 compatible)
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


def is_relative_to(path: Path, base: Path) -> bool:
    """Check if path is inside base directory (Python 3.8 compatible)."""
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def load_index(index_path: Path) -> list[dict]:
    """Load a JSON project index file. Returns [] if missing or corrupt."""
    if not index_path.exists():
        return []
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def save_index(index_path: Path, items: list[dict]) -> None:
    """Save project index to a JSON file (atomic write via temp file)."""
    index_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = index_path.with_suffix(index_path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(tmp_path, index_path)


def record_project(
    index_path: Path,
    project_dir: Path,
    config_path: Path,
) -> None:
    """Add or update a project record in the index."""
    project_dir = project_dir.resolve()
    config_path = config_path.resolve()
    items = load_index(index_path)
    record = {
        "project_dir": str(project_dir),
        "config_path": str(config_path),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    kept = [item for item in items if item.get("project_dir") != str(project_dir)]
    kept.append(record)
    save_index(index_path, kept)


def active_records(
    index_path: Path,
    cwd: str | os.PathLike[str] | None = None,
) -> list[dict]:
    """Return project records whose project_dir contains cwd.

    Results are sorted most-specific first (longest path first).
    """
    current = Path(cwd or os.getcwd()).resolve()
    records = []
    for item in load_index(index_path):
        project_dir = Path(item.get("project_dir", "")).expanduser()
        config_path = Path(item.get("config_path", "")).expanduser()
        if not project_dir or not config_path.exists():
            continue
        if is_relative_to(current, project_dir):
            records.append(item)
    records.sort(key=lambda item: len(Path(item.get("project_dir", "")).parts), reverse=True)
    return records
