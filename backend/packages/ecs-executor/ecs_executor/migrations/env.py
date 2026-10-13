"""Private executor migration environment; no native ORM ownership."""

from alembic import context

connection = context.config.attributes["connection"]
context.configure(connection=connection, version_table="ecs_executor_alembic_version")
with context.begin_transaction():
    context.run_migrations()
