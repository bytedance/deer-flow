"""Generate a new alembic revision against an ephemeral SQLite DB.

Used by ``make migrate-rev MSG="..."``. Avoids two pitfalls:

1. ``alembic.ini``'s default ``sqlalchemy.url`` (``sqlite:///./data/deerflow.db``)
   points at a path that doesn't exist in a clean checkout, so a bare
   ``alembic revision --autogenerate`` fails with ``unable to open database file``.
2. A persistent DB might be at an unknown revision (or at no revision at all),
   producing a noisy autogenerate diff that mixes "real" changes with
   accidentally-detected drift.

This script builds a *fresh* temp SQLite, runs the existing alembic chain to
``head`` against it, then runs ``alembic revision --autogenerate`` against
that. The temp DB must be built from migration history -- not from
``Base.metadata.create_all`` -- so newly edited ORM fields that do not yet have
a revision remain visible to autogenerate as a real diff.

The generated file lands in
``packages/harness/deerflow/persistence/migrations/versions/`` -- exactly
where alembic puts it by default -- and the temp directory is left for the OS
to GC. Review the generated revision and switch raw ``op.add_column`` /
``op.drop_column`` calls to the idempotent helpers in ``migrations/_helpers.py``
before committing.

Run from the ``backend/`` directory:
    PYTHONPATH=. uv run python scripts/_autogen_revision.py "MESSAGE"
or via Makefile:
    make migrate-rev MSG="..."
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from alembic import command
from alembic.config import Config

import deerflow.persistence.models  # noqa: F401  -- registers ORM models with Base.metadata
from deerflow.persistence.bootstrap import _escape_url_for_alembic

BACKEND_DIR = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = BACKEND_DIR / "packages/harness/deerflow/persistence/migrations"


def _alembic_config(url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    # Shared with ``bootstrap._alembic_safe_url`` so the ConfigParser ``%``
    # interpolation rule lives in one place.
    cfg.set_main_option("sqlalchemy.url", _escape_url_for_alembic(url))
    return cfg


def _build_temp_db_at_head() -> str:
    tmpdir = tempfile.mkdtemp(prefix="deerflow-autogen-")
    db_path = os.path.join(tmpdir, "autogen.db").replace(os.sep, "/")
    url = f"sqlite+aiosqlite:///{db_path}"
    command.upgrade(_alembic_config(url), "head")
    return url


def main() -> None:
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print('usage: python scripts/_autogen_revision.py "describe the change"', file=sys.stderr)
        sys.exit(2)
    message = sys.argv[1]

    url = _build_temp_db_at_head()
    print(f"autogen: built temp DB at head: {url}", file=sys.stderr)

    command.revision(_alembic_config(url), message=message, autogenerate=True)


if __name__ == "__main__":
    main()
