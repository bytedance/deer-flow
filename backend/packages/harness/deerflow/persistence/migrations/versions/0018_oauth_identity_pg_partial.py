"""partial postgres predicate for idx_users_oauth_identity.

Revision ID: 0018_oauth_identity_pg_partial
Revises: 0017_personal_access_tokens
Create Date: 2026-08-29

alembic_version.version_num is VARCHAR(32); revision ids in this chain must
stay at or under that length or stamping/upgrading a database fails outright.

Numbering note: originally generated as 0017 against the then-current main
head (0016), same as 0017_personal_access_tokens (#5041). That one merged
first and kept the slot per this package's own renumber-on-rebase
convention, so this revision moved to 0018 and re-parented onto it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_oauth_identity_pg_partial"
down_revision: str | Sequence[str] | None = "0017_personal_access_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX_NAME = "idx_users_oauth_identity"
_WHERE = sa.text("oauth_provider IS NOT NULL AND oauth_id IS NOT NULL")

# 0001_baseline's create_index call for this index passed sqlite_where but
# not postgresql_where, so every deployment provisioned via
# `alembic upgrade head` (the only path production actually runs, per this
# package's own AGENTS.md) has idx_users_oauth_identity as a FULL
# (non-partial) unique index on Postgres, even after UserRow.__table_args__
# gained postgresql_where -- ORM metadata only affects fresh create_all
# databases, never an already-versioned one. Not a correctness bug (NULL is
# never equal to NULL in a unique index on either backend, so real
# duplicates are already rejected and unlimited NULL/NULL rows already
# coexist) -- see UserRow.__table_args__'s own comment -- but the index
# stays full-table-sized instead of covering only the OAuth-linked rows.


def _pg_index_missing_predicate(bind) -> bool:
    """True only if the index exists on Postgres as a full (non-partial)
    index. False if it doesn't exist yet (a fresh create_all-provisioned DB
    already built the partial form from ORM metadata -- nothing to do) or
    already has a predicate (this revision already ran, or a legacy DB was
    stamped past it)."""
    row = bind.execute(sa.text(f"SELECT indpred FROM pg_index WHERE indexrelid = to_regclass('{_INDEX_NAME}')")).first()
    return row is not None and row[0] is None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # SQLite already got sqlite_where from 0001_baseline; nothing for this revision to do there.
    if not _pg_index_missing_predicate(bind):
        return
    op.drop_index(_INDEX_NAME, table_name="users")
    op.create_index(_INDEX_NAME, "users", ["oauth_provider", "oauth_id"], unique=True, postgresql_where=_WHERE)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    row = bind.execute(sa.text(f"SELECT indpred FROM pg_index WHERE indexrelid = to_regclass('{_INDEX_NAME}')")).first()
    if row is None or row[0] is None:
        return  # doesn't exist, or already the pre-migration full form -- nothing to revert
    op.drop_index(_INDEX_NAME, table_name="users")
    op.create_index(_INDEX_NAME, "users", ["oauth_provider", "oauth_id"], unique=True)
