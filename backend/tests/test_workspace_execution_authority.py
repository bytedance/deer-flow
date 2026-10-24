"""Receiver preflight uses native SQL authority, never token-selected membership."""

from dataclasses import asdict, replace

import pytest
import sqlalchemy as sa
from test_workspace_executor_migration import executor_engine, native_engine  # noqa: F401
from test_workspace_mcp import _in_workspace_case


def test_native_execution_receiver_resolves_original_run(native_engine):  # noqa: F811
    from ecs_executor import scope

    from deerflow.authz.workspace import get_current_workspace, set_current_workspace
    from deerflow.persistence.thread_meta import ThreadMetaRepository
    from deerflow.runtime import RunStatus

    assert hasattr(scope, "verify_native_execution_scope"), "native SQL execution receiver is missing"

    async def scenario(case):
        parent = await ThreadMetaRepository(case.sf).create("receiver-main", user_id="owner")
        run = await case.runs.create_or_reject(parent["thread_id"], user_id="owner")
        await case.runs.try_start(run.run_id)
        arguments = {"request_key": "report", "profile": "python", "argv": ["python", "report.py"]}
        secret = b"synthetic-native-receiver-secret-32-bytes"

        def signed(context=case.original, **changes):
            return scope.mint_execution_scope(
                secret=secret,
                audience="B",
                user_id="owner",
                thread_id=changes.get("thread_id", run.thread_id),
                incarnation=changes.get("incarnation", run.thread_incarnation),
                run_id=run.run_id,
                operation="submit",
                arguments=arguments,
                workspace_context=context,
            )

        def verify(token):
            return scope.verify_native_execution_scope(token, engine=native_engine, secret=secret, authenticated_user_id="owner", arguments=arguments, expected_audience="B", expected_operation="submit")

        token = signed()
        statements = []

        def observe(connection, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        sa.event.listen(native_engine, "before_cursor_execute", observe)
        try:
            for bad_token, overrides in (
                (token + "x", {}),
                (token, {"authenticated_user_id": "intruder"}),
                (token, {"arguments": {"request_key": "changed"}}),
                (
                    scope.mint_execution_scope(
                        secret=secret, audience="B", user_id="owner", thread_id=run.thread_id, incarnation=run.thread_incarnation, run_id=run.run_id, operation="submit", arguments=arguments, workspace_context=case.original, now=1
                    ),
                    {},
                ),
            ):
                kwargs = dict(engine=native_engine, secret=secret, authenticated_user_id="owner", arguments=arguments, expected_audience="B", expected_operation="submit")
                with pytest.raises(ValueError):
                    scope.verify_native_execution_scope(bad_token, **(kwargs | overrides))
            assert not statements, "Unverified intent reached native SQL"
        finally:
            sa.event.remove(native_engine, "before_cursor_execute", observe)
        set_current_workspace(case.other)
        claims = verify(token)
        assert claims["workspace_context"] == asdict(case.original)
        assert get_current_workspace() == case.other
        for invalid in (signed(case.other), signed(None), signed(incarnation="replaced"), signed(thread_id="foreign"), signed(replace(case.original, policy_version=case.original.policy_version + 1))):
            with pytest.raises((ValueError, PermissionError)):
                verify(invalid)
        await case.runs.set_status_if_not_cancelled(run.run_id, RunStatus.success)
        with pytest.raises(PermissionError):
            verify(token)

    _in_workspace_case(native_engine, scenario)


def test_native_execution_receiver_rechecks_live_authority(native_engine):  # noqa: F811
    from datetime import UTC, datetime, timedelta

    from ecs_executor import scope

    from deerflow.persistence.run.model import RunRow
    from deerflow.persistence.thread_meta import ThreadMetaRepository
    from deerflow.persistence.thread_meta.model import ThreadMetaRow
    from deerflow.persistence.user.model import UserRow
    from deerflow.persistence.workspaces.model import WorkspaceMembershipRow, WorkspaceRow

    assert hasattr(scope, "verify_native_execution_scope"), "native SQL execution receiver is missing"

    async def scenario(case):
        parent = await ThreadMetaRepository(case.sf).create("receiver-boundary", user_id="owner")
        run = await case.runs.create_or_reject(parent["thread_id"], user_id="owner")
        await case.runs.try_start(run.run_id)
        secret = b"synthetic-native-receiver-secret-32-bytes"
        token = scope.mint_execution_scope(secret=secret, audience="B", user_id="owner", thread_id=run.thread_id, incarnation=run.thread_incarnation, run_id=run.run_id, operation="submit", arguments={}, workspace_context=case.original)
        mutations = [
            sa.update(WorkspaceMembershipRow).where(WorkspaceMembershipRow.workspace_id == case.original.workspace_id).values(status="removed"),
            sa.update(WorkspaceMembershipRow).where(WorkspaceMembershipRow.workspace_id == case.original.workspace_id).values(version=2),
            sa.update(WorkspaceRow).where(WorkspaceRow.id == case.original.workspace_id).values(policy_version=2),
            sa.update(WorkspaceRow).where(WorkspaceRow.id == case.original.workspace_id).values(status="suspended"),
            sa.update(UserRow).where(UserRow.id == "owner").values(account_status="suspended"),
            sa.update(UserRow).where(UserRow.id == "owner").values(email_verified_at=None),
            sa.update(ThreadMetaRow).where(ThreadMetaRow.thread_id == run.thread_id).values(user_id=None),
            sa.update(ThreadMetaRow).where(ThreadMetaRow.thread_id == run.thread_id).values(status="deleting"),
            sa.update(ThreadMetaRow).where(ThreadMetaRow.thread_id == run.thread_id).values(incarnation="replaced"),
            sa.update(RunRow).where(RunRow.run_id == run.run_id).values(workspace_context_json=None),
            sa.update(RunRow).where(RunRow.run_id == run.run_id).values(cancel_action="interrupt"),
            sa.update(RunRow).where(RunRow.run_id == run.run_id).values(owner_worker_id=None),
            sa.update(RunRow).where(RunRow.run_id == run.run_id).values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=30)),
        ]
        for mutation in mutations:
            with native_engine.connect() as connection:
                transaction = connection.begin()
                try:
                    connection.execute(mutation)
                    # Same real SQL transaction; no permission-success stubs.
                    with pytest.raises(PermissionError):
                        scope.verify_native_execution_scope(token, engine=connection, secret=secret, authenticated_user_id="owner", arguments={}, expected_audience="B", expected_operation="submit")
                finally:
                    transaction.rollback()

    _in_workspace_case(native_engine, scenario)
