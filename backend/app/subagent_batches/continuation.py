"""Native batch follow-ups through the existing revocable AgentRuns host."""

import copy
import json
import logging

from deerflow_extension_api.agent_runs import AgentRunError, ExecutionFence

from deerflow.agents.human_input import extract_unanswered_human_input_request
from deerflow.mcp_scope import THREAD_INCARNATION_CONTEXT_KEY
from deerflow.runtime.goal import goal_waits_for_external_result, read_thread_goal
from deerflow.runtime.runs.schemas import GOAL_RUN_HARD_STOP_REASONS

logger = logging.getLogger(__name__)
_TRUSTED = object()


class BatchContinuations:
    def __init__(self, app):
        self.app = app

    async def prepare(self, request):
        from app.gateway.services import _CONTEXT_CONFIGURABLE_KEYS, _MODEL_SELECTION_CONTEXT_KEYS

        host = self.app.state.agent_runs_host
        grant = host.capture_batch_authority(request.continuation_authority, user_id=request.user_id)
        source = await request.continuation_authority.get(thread_id=request.thread_id, run_id=request.run_id)
        if source.status not in ("pending", "running"):
            raise AgentRunError(409, "The originating Run has already stopped")
        record = await self.app.state.run_manager.get(request.run_id, user_id=request.user_id)
        if record is None or record.user_id != request.user_id or record.thread_id != request.thread_id:
            raise AgentRunError(403, "Batch follow-up must belong to its originating Run")
        captured = request.continuation_context or {}
        if (record.metadata or {}).get("deerflow_origin", {}).get("kind") == "subagent_batch" and (captured.get("goal") or {}).get("status") != "active":
            raise AgentRunError(409, "A batch follow-up cannot register another automatic follow-up")
        context = {key: value for key, value in captured.get("context", {}).items() if key in _CONTEXT_CONFIGURABLE_KEYS | _MODEL_SELECTION_CONTEXT_KEYS and key not in ("agent_name", "is_bootstrap")}
        if isinstance(captured.get("context", {}).get("locale"), str):
            context["locale"] = captured["context"]["locale"]
        scope = request.execution_spec.get("knowledge_scope")
        return {
            "prompt": request.continuation,
            "grant": grant,
            "thread_incarnation": request.execution_spec.get(THREAD_INCARNATION_CONTEXT_KEY),
            "goal": copy.deepcopy(captured.get("goal")),
            "context": copy.deepcopy(context),
            "config": copy.deepcopy(captured.get("config", {})),
            "knowledge_scope": copy.deepcopy(scope),
        }

    async def dispatch(self, batch):
        continuation = batch["continuation"]
        try:
            runs = await self.app.state.agent_runs_host.restore_batch_authority(user_id=batch["user_id"], grant=continuation["grant"])
            existing_id = await self.app.state.subagent_batch_repo.continuation_run_id(batch["id"], user_id=batch["user_id"])
            if existing_id is not None:
                existing = await runs.get(thread_id=batch["thread_id"], run_id=existing_id)
                return {"status": "dispatched", "run_id": existing.run_id}
            source = await runs.get(thread_id=batch["thread_id"], run_id=batch["run_id"])
            if source.status in ("pending", "running"):
                return None
            if source.status != "success" or source.stop_reason in GOAL_RUN_HARD_STOP_REASONS:
                return {"status": "suppressed"}
            thread = await self.app.state.thread_store.get(batch["thread_id"], user_id=batch["user_id"])
            if thread is None or thread.get("incarnation") != continuation.get("thread_incarnation"):
                return {"status": "suppressed"}
            state = await runs.get_state(thread_id=batch["thread_id"])
            values = state.get("values", {})
            if extract_unanswered_human_input_request(values.get("messages")) is not None:
                return {"status": "waiting"}
            goal = values.get("goal")
            goal_identity = {key: goal.get(key) for key in ("created_at", "status", "objective")} if isinstance(goal, dict) else None
            expected_goal = continuation.get("goal")
            if goal_identity != expected_goal:
                return {"status": "suppressed"}
            goal_wakeup = None
            if expected_goal is not None:
                latest = await self.app.state.subagent_batch_repo.latest_run_state(batch["thread_id"], user_id=batch["user_id"])
                if latest and latest["status"] in ("pending", "running"):
                    return None
                if latest and (latest["status"] != "success" or latest.get("stop_reason") in GOAL_RUN_HARD_STOP_REASONS):
                    return {"status": "suppressed"}
                if not goal_waits_for_external_result(goal, expected_goal):
                    return None if not (goal.get("last_evaluation") or {}).get("stand_down_reason") else {"status": "suppressed"}
                goal_wakeup = expected_goal
            public = await self.app.state.subagent_batch_repo.get_batch(batch["id"], user_id=batch["user_id"])
            if public is None or public.get("continuation_status") == "cancelled" or public["status"] == "cancelled":
                return {"status": "suppressed"}
            if public["status"] not in ("completed", "failed"):
                return None
            # Stable input is essential after an unknown admission outcome.
            # Counts/results stay in the existing owner-scoped result reader.
            content = "The requested background batch has finished. Continue the agreed follow-up using its stored results; preserve any failures or missing information.\n" + json.dumps(
                {"batch_id": batch["id"], "follow_up": continuation["prompt"]}, ensure_ascii=False
            )
            from deerflow.knowledge_scope import KNOWLEDGE_SCOPE_KEY

            metadata = {"hide_from_ui": True, "untrusted_input": True}
            if continuation.get("knowledge_scope") is not None:
                metadata[KNOWLEDGE_SCOPE_KEY] = continuation["knowledge_scope"]
            result = await runs.start_batch_followup(
                thread_id=batch["thread_id"],
                batch_id=batch["id"],
                input={"messages": [{"role": "user", "content": content, "additional_kwargs": metadata}]},
                context=continuation.get("context"),
                config=continuation.get("config"),
                execution_fence=ExecutionFence(**batch["execution_fence"]),
                goal_wakeup=goal_wakeup,
            )
            return {"status": "dispatched", "run_id": result.run_id}
        except AgentRunError as exc:
            if exc.status_code == 409:
                return None
            if exc.status_code in (400, 401, 403, 404, 422):
                return {"status": "suppressed"}
            raise

    async def cancel(self, batch_id, user_id, *, thread_id=None, authority=_TRUSTED, authorize_only=False):
        if authority is not _TRUSTED:
            self.app.state.agent_runs_host.capture_batch_authority(authority, user_id=user_id)
            async with authority._request("runs:cancel", thread_id):
                if authorize_only:
                    return
        elif authorize_only:
            return
        run_id = await self.app.state.subagent_batch_repo.continuation_run_id(batch_id, user_id=user_id)
        if run_id is None:
            return
        record = await self.app.state.run_manager.get(run_id, user_id=user_id)
        if record is not None:
            await self.app.state.run_manager.cancel(run_id)

    async def source_finished(self, record):
        if record.stop_reason == "goal_wakeup_superseded":
            return
        if record.status == "success" and record.stop_reason not in GOAL_RUN_HARD_STOP_REASONS:
            return
        for batch in await self.app.state.subagent_batch_repo.list_continuation_batches_for_run(record.run_id):
            try:
                await self.app.state.subagent_batch_service.cancel_batch(batch_id=batch["id"], user_id=batch["user_id"])
            except Exception:
                logger.warning("Batch %s cancellation failed for run %s (non-fatal)", batch["id"], record.run_id, exc_info=True)
        goal = await read_thread_goal(self.app.state.checkpointer, record.thread_id)
        if goal and goal.get("status") == "active" and goal.get("created_at"):
            await self.app.state.subagent_batch_repo.suppress_thread_continuations(record.thread_id, goal_created_at=goal["created_at"])
