"""Join the batch recovery and thread sharing migration histories."""

from alembic import op

revision = "0056_merge_batch_recovery"
down_revision = ("0055_thread_shares", "0053_batch_recovery")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    # SQLite commits each revision. Check before splitting the version stamp
    # or dropping sharing tables if this downgrade also removes recovery data.
    context = op.get_context()
    for step in context.script.iterate_revisions(revision, context.opts["destination_rev"], select_for_downgrade=True):
        if step.revision == "0053_batch_recovery":
            step.module.check_downgrade()
            break
