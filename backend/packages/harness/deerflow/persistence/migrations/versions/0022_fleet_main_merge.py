"""Join Fleet execution and upstream project/incarnation migration histories.

Both branches are retained so existing databases from either release can advance.
No schema DDL is needed in this merge revision.
"""

revision = "0022_fleet_main_merge"
down_revision = ("0019_scheduled_execution", "0019_thread_incarnations")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    raise RuntimeError("Fleet integration rollback requires drained execution and an approved backup")
