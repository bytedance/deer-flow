"""Run the existing checklist for a durable item without a parent tool runtime."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from deerflow.config.app_config import AppConfig
from deerflow.subagents.acceptance_checks import AcceptanceVerdict, check_acceptance_criteria, parse_file_criterion
from deerflow.subagents.report_contract import normalize_acceptance_criteria


def _thread_data(thread_id: str, user_id: str) -> dict[str, str]:
    from deerflow.config.paths import get_paths

    paths = get_paths()
    return {
        "workspace_path": str(paths.sandbox_work_dir(thread_id, user_id=user_id)),
        "uploads_path": str(paths.sandbox_uploads_dir(thread_id, user_id=user_id)),
        "outputs_path": str(paths.sandbox_outputs_dir(thread_id, user_id=user_id)),
    }


async def check_batch_acceptance(
    criteria: list[str],
    *,
    batch: dict[str, Any],
    app_config: AppConfig,
    bash_executions: list[dict[str, Any]] | None,
) -> AcceptanceVerdict | None:
    from deerflow.authz.sandbox_authz import authorize_sandbox_execution_async
    from deerflow.sandbox.lease import SANDBOX_LEASE_OWNER_CONTEXT_KEY, acquire_sandbox_client_lease, run_sync_lifecycle_operation
    from deerflow.sandbox.sandbox_provider import get_sandbox_provider

    criteria = await run_sync_lifecycle_operation(normalize_acceptance_criteria, criteria)
    if not criteria:
        return None
    thread_id, user_id = batch["thread_id"], batch["user_id"]
    spec = batch["execution_spec"]
    context = {key: spec.get(key) for key in ("user_role", "oauth_provider", "oauth_id", "channel_user_id", "is_internal", "authz_attributes")}
    context.update(thread_id=thread_id, user_id=user_id)
    thread_data = await run_sync_lifecycle_operation(_thread_data, thread_id, user_id)
    runtime = SimpleNamespace(state={"thread_data": thread_data}, context=context, config={"configurable": {"thread_id": thread_id}})
    lease = None
    try:
        # Evidence-only / unsupported conditions need no sandbox. File checks
        # use an authorized, owner-scoped holder of the shared thread sandbox.
        if any(parse_file_criterion(criterion) is not None for criterion in criteria):
            await authorize_sandbox_execution_async(context=context, app_config=app_config)
            provider = await run_sync_lifecycle_operation(get_sandbox_provider)
            lease = await acquire_sandbox_client_lease(provider, thread_id, user_id=user_id, owner_prefix="batch-acceptance")
            runtime.state["sandbox"] = {"sandbox_id": lease.sandbox_id}
            context[SANDBOX_LEASE_OWNER_CONTEXT_KEY] = lease.owner_id
        # Drain blocking reads before releasing the holder, including shutdown.
        return await run_sync_lifecycle_operation(check_acceptance_criteria, criteria, runtime=runtime, thread_data=thread_data, bash_executions=bash_executions)
    finally:
        if lease is not None:
            await lease.release()
