"""Read-only historical Fleet intent inventory and activation quarantine."""

import sqlalchemy as sa


class LegacyExecutionQuarantined(RuntimeError):
    pass


def inventory(connection):
    inspector = sa.inspect(connection)
    tables = set(inspector.get_table_names())
    report = {"bindings": [], "scheduled_tasks": [], "legacy_tables": sorted(name for name in tables if name.startswith("fleet_"))}
    if "thread_execution_bindings" in tables:
        report["bindings"] = [dict(row) for row in connection.execute(sa.text("SELECT user_id, thread_id, backend FROM thread_execution_bindings ORDER BY user_id, thread_id")).mappings()]
    if "scheduled_tasks" in tables and any(column["name"] == "execution" for column in inspector.get_columns("scheduled_tasks")):
        report["scheduled_tasks"] = [dict(row) for row in connection.execute(sa.text("SELECT id, status FROM scheduled_tasks WHERE execution IS NOT NULL ORDER BY id")).mappings()]
    report["legacy_table_counts"] = {}
    for name in report["legacy_tables"]:
        table = sa.Table(name, sa.MetaData(), autoload_with=connection)
        report["legacy_table_counts"][name] = connection.execute(sa.select(sa.func.count()).select_from(table)).scalar_one()
    report["active_runs"] = []
    report["active_occurrences"] = []
    if "runs" in tables:
        report["active_runs"] = [dict(row) for row in connection.execute(sa.text("SELECT run_id, thread_id, status FROM runs WHERE status IN ('pending', 'running') ORDER BY run_id")).mappings()]
    if "scheduled_task_runs" in tables:
        report["active_occurrences"] = [dict(row) for row in connection.execute(sa.text("SELECT id, task_id, thread_id, run_id, status FROM scheduled_task_runs WHERE status IN ('queued', 'launching', 'running') ORDER BY id")).mappings()]
    return report


def require_no_legacy_execution(connection):
    report = inventory(connection)
    if report["bindings"] or report["scheduled_tasks"] or report["legacy_tables"]:
        raise LegacyExecutionQuarantined(
            "Historical Fleet execution is quarantined: native Gateway activation refused. Preserve the database, inventory and drain the old deployment; see docs/ecs-native-fork-integration.md. No intent was converted or replayed."
        )


async def require_activation(engine):
    if engine is not None:
        async with engine.connect() as connection:
            await connection.run_sync(require_no_legacy_execution)


def main():
    import argparse
    import json
    import os

    parser = argparse.ArgumentParser(description="Read-only legacy execution inventory; never connects to models or changes intent")
    parser.add_argument("--database-url-env", default="DEERFLOW_LEGACY_INVENTORY_DATABASE_URL")
    args = parser.parse_args()
    engine = None
    try:
        engine = sa.create_engine(os.environ[args.database_url_env])
        with engine.connect() as connection:
            print(json.dumps(inventory(connection), sort_keys=True))
    except Exception:
        raise SystemExit("Legacy inventory failed (database URL withheld)") from None
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    main()
