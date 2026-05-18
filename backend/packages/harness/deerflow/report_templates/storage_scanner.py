"""Periodic snapshot scanner for report-template storage (Phase 7).

Captures two charter metrics (§4.4 + §4.5):

  - storage_bytes per (user / tenant)
  - version_count per template

Designed to be invoked from a cron job, admin API, or a test fixture — never
runs automatically inside request handlers because the scan is O(n_files).
"""

from __future__ import annotations

import logging
from pathlib import Path

from deerflow.report_templates.telemetry import get_telemetry

logger = logging.getLogger(__name__)


def _dir_size_bytes(path: Path) -> int:
    """Sum size of every regular file under ``path``. Silently skips OS errors."""
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            continue
    return total


def scan_storage(runtime_root: Path) -> dict[str, int]:
    """Scan ``{runtime_root}/{users,tenants}/*/`` and record byte counts.

    Returns the same payload it emits, keyed by ``"{owner_type}/{owner_id}"``,
    so callers (admin route, test) can assert on it.
    """
    runtime_root = Path(runtime_root)
    tele = get_telemetry()
    out: dict[str, int] = {}
    for owner_type in ("users", "tenants"):
        scope_root = runtime_root / owner_type
        if not scope_root.exists():
            continue
        for owner_dir in scope_root.iterdir():
            if not owner_dir.is_dir():
                continue
            size = _dir_size_bytes(owner_dir)
            out[f"{owner_type}/{owner_dir.name}"] = size
            tele.record_storage_snapshot(
                owner_type=owner_type,
                owner_id=owner_dir.name,
                bytes_used=size,
            )
    return out


def scan_version_counts(runtime_root: Path) -> dict[str, int]:
    """Count published versions under each template's ``versions/`` dir.

    Returns ``{template_id: count}``. Templates with no ``versions/`` dir
    (pure draft) are reported with count 0.
    """
    runtime_root = Path(runtime_root)
    tele = get_telemetry()
    out: dict[str, int] = {}
    for owner_type in ("users", "tenants"):
        scope_root = runtime_root / owner_type
        if not scope_root.exists():
            continue
        for owner_dir in scope_root.iterdir():
            if not owner_dir.is_dir():
                continue
            for tpl_dir in owner_dir.iterdir():
                if not tpl_dir.is_dir():
                    continue
                versions_dir = tpl_dir / "versions"
                if versions_dir.is_dir():
                    count = sum(
                        1 for p in versions_dir.iterdir() if p.is_file() and p.suffix == ".json"
                    )
                else:
                    count = 0
                out[tpl_dir.name] = count
                tele.record_version_count(template_id=tpl_dir.name, version_count=count)
    return out
