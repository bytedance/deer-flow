"""Optional real PostgreSQL coverage for JSON escape normalization in GC."""

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.schema import CreateSchema, DropSchema


def test_postgres_retains_unicode_escaped_references_in_every_carrier():
    uri = os.environ.get("TEST_POSTGRES_URI")
    if not uri:
        pytest.skip("requires TEST_POSTGRES_URI for real PostgreSQL GC coverage")
    pytest.importorskip("psycopg")
    import deerflow.persistence.models  # noqa: F401
    from deerflow.config.app_config import AppConfig
    from deerflow.persistence.base import Base
    from deerflow.persistence.run.model import RunRow
    from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow
    from deerflow.persistence.subagent_batches.model import SubagentBatchRow
    from deerflow.persistence.tracing_profiles.gc import cleanup_tracing_records
    from deerflow.persistence.tracing_profiles.model import RunTracingSnapshotRow

    schema = f"tracing_gc_{uuid4().hex}"
    config = AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}, "database": {"backend": "postgres", "postgres_url": uri, "postgres_schema": schema}})
    engine = create_engine(config.database.app_sync_sqlalchemy_url)
    identifiers = [letter * 32 for letter in "abcde"]

    def payload(letter):
        return '{"deerflow_tracing_snapshot_id":"' + f"\\u{ord(letter):04x}" * 32 + '"}'

    try:
        with engine.begin() as connection:
            connection.execute(CreateSchema(schema))
            Base.metadata.create_all(connection)
            connection.execute(
                text(
                    "CREATE TABLE checkpoints (thread_id TEXT NOT NULL, checkpoint_ns TEXT NOT NULL DEFAULT '', checkpoint_id TEXT NOT NULL, "
                    "parent_checkpoint_id TEXT, type TEXT, checkpoint JSONB NOT NULL, metadata JSONB NOT NULL DEFAULT '{}', "
                    "PRIMARY KEY(thread_id,checkpoint_ns,checkpoint_id))"
                )
            )
            for identifier in identifiers:
                connection.execute(
                    RunTracingSnapshotRow.__table__.insert().values(
                        snapshot_id=identifier,
                        owner_user_id="alice",
                        agent_name="lead_agent",
                        agent_incarnation="builtin:lead_agent",
                        mode="inherit",
                        binding_revision=0,
                        payload_ciphertext="opaque",
                        retention_state="published",
                        created_at=datetime.now(UTC) - timedelta(days=30),
                    )
                )
            connection.execute(RunRow.__table__.insert().values(run_id="history", thread_id="thread", status="success"))
            connection.execute(ScheduledTaskRunRow.__table__.insert().values(id="queue", task_id="task", thread_id="thread", scheduled_for=datetime.now(UTC), trigger="manual", status="interrupted"))
            connection.execute(
                SubagentBatchRow.__table__.insert().values(
                    id="batch",
                    user_id="alice",
                    thread_id="thread",
                    run_id="history",
                    tool_call_id="call",
                    submission_key="key",
                    title="Paused",
                    subagent_type="test",
                    status="paused",
                    total_items=1,
                    max_live_items=1,
                    max_running_items=1,
                    max_attempts=1,
                    execution_spec={},
                )
            )
            for table, column, letter in (("runs", "metadata_json", "a"), ("runs", "kwargs_json", "b"), ("scheduled_task_runs", "tracing_snapshot_refs", "c"), ("subagent_batches", "execution_spec", "d")):
                connection.execute(text(f"UPDATE {table} SET {column}=CAST(:metadata AS JSON)"), {"metadata": payload(letter)})
            connection.execute(text("INSERT INTO checkpoints (thread_id,checkpoint_ns,checkpoint_id,checkpoint,metadata) VALUES ('checkpoint-only','tools:child','history','{}',CAST(:metadata AS JSONB))"), {"metadata": payload("e")})
            assert "\\u0061" in connection.scalar(text("SELECT CAST(metadata_json AS TEXT) FROM runs"))
        result = cleanup_tracing_records(config, apply=True)
        assert result["snapshot_skip_reason"] is None
        assert result["snapshots_deleted"] == 0
        with engine.connect() as connection:
            assert set(connection.execute(text("SELECT snapshot_id FROM run_tracing_snapshots")).scalars()) == set(identifiers)
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True, if_exists=True))
        engine.dispose()
