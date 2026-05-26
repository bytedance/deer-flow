"""Audit and archive token_usage.json files after PostgreSQL migration.

Compares token usage data from JSON files with RunRow and AgentUsageRow ORM data.
Archives JSON files to backups/ when data matches within 1% tolerance.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import create_engine, select

logger = logging.getLogger(__name__)


@dataclass
class AuditResult:
    """Result of auditing a single token_usage.json file."""

    json_path: Path
    json_records: int
    orm_total_tokens: int
    json_total_tokens: int
    tolerance_pct: float
    matches: bool
    archived: bool
    error: str | None = None


@dataclass
class CleanupReport:
    """Overall cleanup report."""

    results: list[AuditResult]
    total_files: int
    files_matched: int
    files_mismatched: int
    files_archived: int
    files_not_found: int

    def print_report(self) -> None:
        """Print human-readable cleanup report."""
        print("\n" + "=" * 70)
        print("TOKEN USAGE JSON CLEANUP REPORT")
        print("=" * 70)
        print(f"  Total JSON files scanned:     {self.total_files}")
        print(f"  Files not found (skipped):    {self.files_not_found}")
        print(f"  Files with matching data:     {self.files_matched}")
        print(f"  Files with mismatch:          {self.files_mismatched}")
        print(f"  Files archived:               {self.files_archived}")
        print("-" * 70)

        if self.results:
            for r in self.results:
                if r.error:
                    status = "✗ ERROR"
                elif r.archived:
                    status = "✓ ARCHIVED"
                elif r.matches:
                    status = "✓ MATCH"
                else:
                    status = "✗ MISMATCH"

                print(f"\n  {status}: {r.json_path}")
                print(f"    JSON records: {r.json_records}")
                print(f"    JSON tokens:  {r.json_total_tokens}")
                print(f"    ORM tokens:   {r.orm_total_tokens}")
                print(f"    Tolerance:    {r.tolerance_pct:.1f}%")
                if r.error:
                    print(f"    Error: {r.error}")

        print("\n" + "=" * 70 + "\n")


def load_json_usage(json_path: Path) -> list[dict]:
    """Load token usage records from JSON file."""
    if not json_path.exists():
        return []
    try:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.error("Failed to read %s: %s", json_path, e)
        return []


def sum_json_tokens(records: list[dict]) -> int:
    """Sum total tokens from JSON records."""
    return sum(r.get("total_tokens", 0) for r in records)


def sum_orm_tokens(engine, tenant_id: str) -> int:
    """Sum total tokens from RunRow and AgentUsageRow for a tenant."""
    from deerflow.persistence.agent.usage_model import AgentUsageRow
    from deerflow.persistence.run.model import RunRow

    total = 0

    with engine.begin() as conn:
        # Sum from RunRow
        stmt = select(RunRow).where(RunRow.tenant_id == tenant_id)
        runs = conn.execute(stmt).scalars().all()
        for run in runs:
            total += run.total_tokens or 0

        # Sum from AgentUsageRow
        stmt = select(AgentUsageRow).where(AgentUsageRow.tenant_id == tenant_id)
        usages = conn.execute(stmt).scalars().all()
        for usage in usages:
            total += (usage.token_input or 0) + (usage.token_output or 0)

    return total


def within_tolerance(json_tokens: int, orm_tokens: int, tolerance_pct: float) -> bool:
    """Check if two token counts are within tolerance (default 1%)."""
    if json_tokens == 0 and orm_tokens == 0:
        return True
    if json_tokens == 0 or orm_tokens == 0:
        return False
    diff = abs(json_tokens - orm_tokens)
    max_val = max(json_tokens, orm_tokens)
    return (diff / max_val) <= (tolerance_pct / 100.0)


def archive_json_file(json_path: Path, backup_dir: Path) -> bool:
    """Move JSON file to backup directory with .bak extension."""
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"{json_path.name}.bak"
        shutil.move(str(json_path), str(backup_path))
        logger.info("Archived %s to %s", json_path, backup_path)
        return True
    except Exception as e:
        logger.error("Failed to archive %s: %s", json_path, e)
        return False


def audit_token_usage(
    db_url: str,
    base_dir: Path,
    *,
    tolerance_pct: float = 1.0,
    archive: bool = True,
) -> CleanupReport:
    """Audit and optionally archive token_usage.json files.

    Args:
        db_url: SQLAlchemy database URL (PostgreSQL or SQLite).
        base_dir: Base directory containing tenant folders with token_usage.json.
        tolerance_pct: Allowed difference percentage (default 1%).
        archive: If True, archive matching files to backups/.

    Returns:
        CleanupReport with audit results.
    """
    engine = create_engine(db_url)
    results: list[AuditResult] = []

    # Scan for token_usage.json files
    json_files = list(base_dir.rglob("token_usage.json"))

    if not json_files:
        logger.info("No token_usage.json files found in %s", base_dir)
        return CleanupReport(
            results=[],
            total_files=0,
            files_matched=0,
            files_mismatched=0,
            files_archived=0,
            files_not_found=0,
        )

    logger.info("Found %d token_usage.json files", len(json_files))

    for json_path in json_files:
        # Extract tenant_id from path (e.g., /tenants/tenant-123/token_usage.json)
        parts = json_path.parts
        tenant_id = "default"
        if "tenants" in parts:
            idx = parts.index("tenants")
            if idx + 1 < len(parts):
                tenant_id = parts[idx + 1]

        logger.info("Auditing %s (tenant: %s)", json_path, tenant_id)

        # Load JSON data
        json_records = load_json_usage(json_path)
        json_tokens = sum_json_tokens(json_records)

        if not json_records:
            logger.warning("Empty or invalid JSON file: %s", json_path)
            results.append(AuditResult(
                json_path=json_path,
                json_records=0,
                orm_total_tokens=0,
                json_total_tokens=0,
                tolerance_pct=tolerance_pct,
                matches=False,
                archived=False,
                error="Empty or invalid JSON file",
            ))
            continue

        # Load ORM data
        try:
            orm_tokens = sum_orm_tokens(engine, tenant_id)
        except Exception as e:
            logger.error("Failed to query ORM data for tenant %s: %s", tenant_id, e)
            results.append(AuditResult(
                json_path=json_path,
                json_records=len(json_records),
                orm_total_tokens=0,
                json_total_tokens=json_tokens,
                tolerance_pct=tolerance_pct,
                matches=False,
                archived=False,
                error=f"ORM query failed: {e}",
            ))
            continue

        # Compare
        matches = within_tolerance(json_tokens, orm_tokens, tolerance_pct)
        archived = False

        if matches:
            logger.info(
                "✓ Match: JSON=%d, ORM=%d (tolerance %.1f%%)",
                json_tokens, orm_tokens, tolerance_pct,
            )
            if archive:
                backup_dir = base_dir / "backups"
                archived = archive_json_file(json_path, backup_dir)
        else:
            diff_pct = abs(json_tokens - orm_tokens) / max(json_tokens, orm_tokens) * 100
            logger.warning(
                "✗ Mismatch: JSON=%d, ORM=%d (diff %.1f%%, tolerance %.1f%%)",
                json_tokens, orm_tokens, diff_pct, tolerance_pct,
            )
            logger.warning("Skipping archival for %s — manual review required", json_path)

        results.append(AuditResult(
            json_path=json_path,
            json_records=len(json_records),
            orm_total_tokens=orm_tokens,
            json_total_tokens=json_tokens,
            tolerance_pct=tolerance_pct,
            matches=matches,
            archived=archived,
        ))

    # Summary
    files_matched = sum(1 for r in results if r.matches)
    files_mismatched = sum(1 for r in results if not r.matches and not r.error)
    files_archived = sum(1 for r in results if r.archived)
    files_not_found = len(json_files) - len(results)

    report = CleanupReport(
        results=results,
        total_files=len(json_files),
        files_matched=files_matched,
        files_mismatched=files_mismatched,
        files_archived=files_archived,
        files_not_found=files_not_found,
    )

    engine.dispose()
    return report


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Audit and archive token_usage.json files after PostgreSQL migration",
    )
    parser.add_argument(
        "--db-url",
        required=True,
        help="SQLAlchemy database URL (e.g., postgresql://user:pass@host/db)",
    )
    parser.add_argument(
        "--base-dir",
        required=True,
        type=Path,
        help="Base directory containing tenant folders",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=1.0,
        help="Allowed difference percentage (default: 1.0)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Audit only, do not archive files",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    report = audit_token_usage(
        db_url=args.db_url,
        base_dir=args.base_dir,
        tolerance_pct=args.tolerance,
        archive=not args.dry_run,
    )

    report.print_report()

    # Exit code: 0 if all matched or no files, 1 if any mismatched
    exit_code = 0 if report.files_mismatched == 0 else 1
    return exit_code


if __name__ == "__main__":
    import sys

    sys.exit(main())
