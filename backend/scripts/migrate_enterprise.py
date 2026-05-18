"""One-time migration: map legacy ``system_role='admin'`` users into RBAC.

Usage::

    cd backend
    PYTHONPATH=. python -m scripts.migrate_enterprise [--dry-run] [--config PATH]

The script is **idempotent**: candidates are users whose ``system_role``
is ``"admin"`` AND whose ``roles`` is empty. Users who have been
hand-edited to have additional roles (e.g. ``["admin", "auditor"]``) are
NEVER overwritten — preserving operator intent is the whole point.

Exits 0 on success including zero candidates; non-zero only on unhandled
exceptions. Designed to be safe to wire into post-deploy automation.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Any

from app.gateway.auth.repositories.base import UserRepository

logger = logging.getLogger(__name__)


async def migrate_admins(
    repo: UserRepository,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Walk every user, promote legacy admins, return a structured report.

    Args:
        repo: A ``UserRepository`` already bound to the target database.
        dry_run: When ``True`` no writes are issued; the report still
            lists the candidates so operators can preview.

    Returns:
        A report dict:
        ``{"candidates": [{"id", "email"}], "upgraded": int, "skipped": int}``
        where ``skipped`` counts admins whose ``roles`` already contains a
        value (left untouched on purpose).
    """
    users = await repo.list_all_users()
    candidates: list[dict[str, str]] = []
    skipped = 0
    for u in users:
        if u.system_role != "admin":
            continue
        if u.roles:
            # Operator already curated this row; do not clobber.
            skipped += 1
            continue
        candidates.append({"id": str(u.id), "email": u.email})

    upgraded = 0
    if not dry_run:
        for u in users:
            if u.system_role != "admin" or u.roles:
                continue
            u.roles = ["admin"]
            await repo.update_user(u)
            upgraded += 1

    return {"candidates": candidates, "upgraded": upgraded, "skipped": skipped}


async def _amain(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="List candidates without modifying")
    parser.add_argument("--config", default=None, help="Optional config.yaml path override")
    args = parser.parse_args(argv)

    # Resolve repo lazily so unit tests can bypass the whole engine setup.
    repo = await _build_repo_from_config(args.config)

    report = await migrate_admins(repo, dry_run=args.dry_run)

    mode = "dry-run" if args.dry_run else "applied"
    logger.info(
        "migrate_enterprise (%s): %d candidate(s), %d upgraded, %d skipped (already roled)",
        mode,
        len(report["candidates"]),
        report["upgraded"],
        report["skipped"],
    )
    for c in report["candidates"]:
        logger.info("  candidate: %s (%s)", c["email"], c["id"])
    return 0


async def _build_repo_from_config(config_path: str | None) -> UserRepository:
    """Build the production ``SQLiteUserRepository`` from app config.

    Kept in a separate function so unit tests can monkeypatch / bypass it
    cleanly. Production callers go: ``get_app_config()`` ->
    ``init_engine_from_config()`` -> ``SQLiteUserRepository(sf)``.
    """
    from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
    from deerflow.config import get_app_config
    from deerflow.persistence.engine import get_session_factory, init_engine_from_config

    cfg = get_app_config(config_path=config_path) if config_path else get_app_config()
    if not cfg.enterprise or not cfg.enterprise.enabled or not cfg.enterprise.rbac.enabled:
        logger.info("enterprise.rbac not enabled; nothing to migrate.")
        # Raise to short-circuit; _main below catches and returns 0.
        raise _NoOpExit()
    await init_engine_from_config(cfg)
    return SQLiteUserRepository(get_session_factory())


class _NoOpExit(Exception):
    """Internal sentinel signalling 'nothing to do, exit 0'."""


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        return asyncio.run(_amain(list(argv) if argv is not None else sys.argv[1:]))
    except _NoOpExit:
        return 0


if __name__ == "__main__":
    sys.exit(main())
