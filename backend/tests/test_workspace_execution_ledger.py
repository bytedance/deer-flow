"""Physical intent retains original scope; attribution alone is not permission."""

from copy import deepcopy

import pytest
import sqlalchemy as sa
from test_workspace_executor_migration import executor_engine  # noqa: F401


def test_physical_ledger_keeps_immutable_original_identity(executor_engine):  # noqa: F811
    from ecs_executor.job_store import JobStore
    from ecs_executor.schema import upgrade_schema

    upgrade_schema(executor_engine)
    store = JobStore(executor_engine.url.render_as_string(hide_password=False))
    scope = {"workspace_id": "22222222-2222-2222-2222-222222222222", "actor_user_id": "owner", "membership_version": 1, "policy_version": 1}
    record = dict(workspace_id=scope["workspace_id"], workspace_context=scope, user_id="owner", thread_id="thread", incarnation="generation", run_id="run", kind="B")
    try:
        job = store.create(namespace="intent", request_key="report", spec_digest="digest", record=deepcopy(record))
        with executor_engine.connect() as connection:
            columns = {column["name"] for column in sa.inspect(connection).get_columns("ecs_execution_jobs")}
            assert "execution_identity" in columns, "physical identity has no independent immutable column"
            captured = connection.execute(sa.text("SELECT execution_identity FROM ecs_execution_jobs WHERE id=:id"), {"id": job["id"]}).scalar_one()
            assert captured is not None
        same = store.create(namespace="intent", request_key="report", spec_digest="digest", record=deepcopy(record))
        assert same["id"] == job["id"]
        for key, changed in (
            ("user_id", "peer"),
            ("thread_id", "different"),
            ("incarnation", "replaced"),
            ("run_id", "other-run"),
            ("kind", "C"),
            ("workspace_context", scope | {"membership_version": 2}),
            ("spec", {"argv": ["different"]}),
            ("profile", {"image": "other"}),
            ("max_input_bytes", 1),
        ):
            with pytest.raises(ValueError, match="identity"):
                store.mutate(job["id"], lambda row: row.update({key: changed}))
            with pytest.raises(ValueError, match="identity"):
                store.create(namespace="intent", request_key="report", spec_digest="digest", record=deepcopy(record) | {key: changed})
            assert store.get(job["id"]) == job
        store.mutate(job["id"], lambda row: row.update(state="queued"))
        assert store.claim_queued() is None, "unintegrated worker claimed scoped work"
        assert store.get(job["id"])["state"] == "queued"
    finally:
        store.engine.dispose()


def test_ledger_upgrade_preserves_metadata_without_fabricating_authority(executor_engine):  # noqa: F811
    from ecs_executor.job_store import JobStore
    from ecs_executor.schema import SchemaCompatibilityError, require_schema, upgrade_schema

    upgrade_schema(executor_engine)
    assert require_schema(executor_engine) == "e0003_execution_identity", "old workers are not fenced from scoped execution identity"
    store = JobStore(executor_engine.url.render_as_string(hide_password=False))
    try:
        with executor_engine.connect() as connection:
            unknown = connection.execute(sa.text("SELECT state,record,execution_identity FROM ecs_execution_jobs WHERE id='unknown'")).one()
            assert unknown.state == "uncertain" and unknown.execution_identity is None
        historical = store.create(namespace="attributed", request_key="old", spec_digest="old", record={"workspace_id": "22222222-2222-2222-2222-222222222222", "kind": "B"})
        store.mutate(historical["id"], lambda row: row.update(state="queued"))
        assert store.claim_queued() is None
        with executor_engine.begin() as connection:
            connection.execute(sa.text("UPDATE ecs_executor_alembic_version SET version_num='e0002_workspace_scope'"))
        with pytest.raises(SchemaCompatibilityError):
            require_schema(executor_engine)
        upgrade_schema(executor_engine)
        assert require_schema(executor_engine) == "e0003_execution_identity"
        assert store.get(historical["id"])["state"] == "queued"
    finally:
        store.engine.dispose()


def test_pool_claim_filters_unintegrated_scope_before_limit(executor_engine):  # noqa: F811
    from ecs_executor.job_store import JobStore
    from ecs_executor.nodes import Node
    from ecs_executor.scheduling import Scheduling
    from ecs_executor.schema import upgrade_schema

    upgrade_schema(executor_engine)
    store = JobStore(executor_engine.url.render_as_string(hide_password=False))
    try:
        base = {"kind": "B", "spec": {"profile": "small"}, "profile": {"cpu_millis": 500, "memory_mib": 128}}
        scoped = store.create(namespace="pool-scope", request_key="blocked", spec_digest="scoped", record=base | {"workspace_id": "22222222-2222-2222-2222-222222222222"})
        legacy = store.create(namespace="pool-scope", request_key="legacy", spec_digest="legacy", record=base)
        for job in (scoped, legacy):
            store.mutate(job["id"], lambda row: row.update(state="queued"))
        node = Node(cpu_millis=2000, memory_mib=4096, resident_cpu_millis=1500, resident_memory_mib=2048, max_concurrency=1, profiles={"small"}, kinds={"B", "C"})
        pool = Scheduling(store, nodes={"one": node})
        claimed = pool.claim("one", "worker")
        assert claimed["id"] == legacy["id"], "pool bypassed unintegrated scope fence"
        assert store.get(scoped["id"])["state"] == "queued"
        store.mutate(legacy["id"], lambda row: row.update(state="uncertain", lease_until=0))
        assert pool.claim("one", "worker") is None
        assert pool.node_status("one")["unreleased"] == 1
    finally:
        store.engine.dispose()
