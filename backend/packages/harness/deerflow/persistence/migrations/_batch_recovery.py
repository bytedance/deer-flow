"""Protect recovery metadata before a merge downgrade changes the database."""

from alembic import op


def check_recovery_downgrade(current_revision: str) -> None:
    # SQLite commits each revision separately. Refuse a destructive downgrade
    # before splitting the version stamp or removing tables on another branch.
    context = op.get_context()
    for step in context.script.iterate_revisions(current_revision, context.opts["destination_rev"], select_for_downgrade=True):
        if step.revision == "0053_batch_recovery":
            step.module.check_downgrade()
            break
