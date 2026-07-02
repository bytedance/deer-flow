"""Application-layer JobExecutor that runs scheduled jobs as Agent turns.

The executor is the **only** place where user-context manipulation
meets Agent invocation. The contract:

1. Resolve ``thread_id`` (new each run, or fixed — a fixed job with no
   pinned id generates one on its first run and writes it back so every
   later run reuses the same thread and accumulates context)
2. Insert a ``running`` row in ``scheduled_job_runs``
3. ``set_current_user(CronUser(job["user_id"]))``
4. Call ``DeerFlowClient.chat()`` via ``asyncio.to_thread`` so the
   synchronous client doesn't block the event loop
5. Reset the user context in a ``finally`` block (no leak across jobs)
6. ``mark_terminal`` on the run row with the outcome
7. Delegate delivery to ``deliver_result`` (PR #6 fills in IM push)

⚠ The executor must NEVER call ``DeerFlowClient`` without first setting
the user context — that would let one user's scheduled job read
another user's Memory / Sandbox / Uploads.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from deerflow.persistence.scheduled_job_runs import ScheduledJobRunRepository
from deerflow.persistence.scheduled_jobs import ScheduledJobRepository
from deerflow.runtime.user_context import reset_current_user, set_current_user
from deerflow.scheduler.core import ExecutionResult

logger = logging.getLogger(__name__)


class CronUser:
    """Minimal ``CurrentUser`` shim.

    ``deerflow.runtime.user_context.CurrentUser`` is a structural Protocol
    that requires only an ``id: str`` attribute. This concrete class
    satisfies it without forcing the scheduler to depend on the auth
    subsystem's full ``User`` model.
    """

    def __init__(self, user_id: str) -> None:
        self.id: str = user_id

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return f"CronUser(id={self.id!r})"


# ---------------------------------------------------------------------------
# Delivery protocol
# ---------------------------------------------------------------------------


class DeliverySink(Protocol):
    """Where execution results get delivered.

    PR #3 ships a stub that only logs. PR #6 fills in ``IMPusher`` (which
    routes through ``MessageBus.publish_outbound``) and ``InAppNotifier``
    (which writes a row to a notifications table for the Web UI bell).
    """

    async def deliver(
        self,
        *,
        job: dict[str, Any],
        thread_id: str,
        result_text: str,
        status: str,
        error_msg: str | None = None,
    ) -> None: ...


class LoggingDeliverySink:
    """Default sink: log the delivery, do nothing else.

    Used until PR #6 ships the real IM / in-app delivery. Lets the
    scheduler run end-to-end without depending on MessageBus.
    """

    async def deliver(
        self,
        *,
        job: dict[str, Any],
        thread_id: str,
        result_text: str,
        status: str,
        error_msg: str | None = None,
    ) -> None:
        preview = (result_text or "")[:80].replace("\n", " ")
        logger.info(
            "scheduled_job delivery stub: job=%s user=%s source=%s status=%s preview=%r",
            job.get("id"),
            job.get("user_id"),
            job.get("source_channel"),
            status,
            preview,
        )
        if error_msg:
            logger.warning("scheduled_job error detail: %s", error_msg)


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------


ClientFactory = Callable[..., Any]


def _default_client_factory(
    *,
    agent_name: str | None = None,
    **kwargs: Any,
) -> Any:
    """Construct a ``DeerFlowClient``. Imported lazily so the executor
    module loads even when the full client stack isn't needed (e.g.
    unit tests with a fake factory).

    ``subagent_enabled`` defaults to ``True`` so scheduled jobs can
    delegate heavy research/report work to a subagent via the ``task``
    tool. This keeps the lead agent's context clean (tool output from a
    long web-research job does not pollute the main thread state) and
    gives the job its own recursion budget — subagent ``max_turns=150``
    vs the lead graph's ``recursion_limit=100``. The lead agent still
    decides whether to delegate based on the job's ``description``, so
    simple jobs (e.g. a one-line reminder) are unaffected — they simply
    never call ``task``. An explicit ``subagent_enabled`` in ``kwargs``
    is respected (escape hatch for future per-job control).
    """
    from deerflow.client import DeerFlowClient

    kwargs.setdefault("subagent_enabled", True)
    return DeerFlowClient(agent_name=agent_name, **kwargs)


# ---------------------------------------------------------------------------
# AgentJobExecutor
# ---------------------------------------------------------------------------


class AgentJobExecutor:
    """``JobExecutor`` implementation backed by ``DeerFlowClient``.

    Construct once at Gateway lifespan startup with the shared
    repositories + delivery sink. The Scheduler calls
    ``execute(job_dict)`` per due job.
    """

    def __init__(
        self,
        jobs_repo: ScheduledJobRepository,
        runs_repo: ScheduledJobRunRepository,
        *,
        delivery: DeliverySink | None = None,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._jobs_repo = jobs_repo
        self._runs_repo = runs_repo
        self._delivery = delivery or LoggingDeliverySink()
        self._client_factory = client_factory or _default_client_factory
        # Cache DeerFlowClient by agent_name so we don't reload config
        # on every job. ``None`` means "default agent".
        self._clients: dict[str | None, Any] = {}

    # ------------------------------------------------------------------
    # Public API (called by Scheduler)
    # ------------------------------------------------------------------

    async def execute(self, job: dict[str, Any]) -> ExecutionResult:
        job_id = job["id"]
        user_id = job["user_id"]
        description = job.get("description", "")
        agent_name = job.get("agent_name")
        thread_strategy = job.get("thread_strategy", "new")
        fixed_thread_id = job.get("fixed_thread_id")

        # Resolve thread (pins fixed_thread_id on the first fixed run)
        thread_id = await self._resolve_thread_id(job_id, thread_strategy, fixed_thread_id)

        # Create run record
        started_at = datetime.now(UTC)
        run = await self._runs_repo.create_run(
            job_id=job_id,
            user_id=user_id,
            thread_id=thread_id,
            started_at=started_at,
        )

        # Set user context for the duration of this execution.
        # ``asyncio.to_thread`` copies the current context to the worker
        # thread, so ``get_effective_user_id()`` inside DeerFlowClient
        # (called by middlewares / tools) resolves correctly.
        token = set_current_user(CronUser(user_id))
        try:
            client = self._get_or_create_client(agent_name)
            # DeerFlowClient.chat is synchronous — run it in a thread.
            result_text = await asyncio.to_thread(
                client.chat,
                description,
                thread_id=thread_id,
            )
        except Exception as exc:
            await self._finish_failure(run["id"], job, thread_id, exc, started_at)
            return ExecutionResult(
                status="error",
                thread_id=thread_id,
                error_msg=str(exc),
                duration_ms=int((datetime.now(UTC) - started_at).total_seconds() * 1000),
            )
        finally:
            reset_current_user(token)

        await self._finish_success(run["id"], job, thread_id, result_text, started_at)
        return ExecutionResult(
            status="ok",
            thread_id=thread_id,
            duration_ms=int((datetime.now(UTC) - started_at).total_seconds() * 1000),
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _resolve_thread_id(
        self,
        job_id: str,
        strategy: str,
        fixed_thread_id: str | None,
    ) -> str:
        """Resolve the thread_id for this run.

        - ``fixed`` with a pinned ``fixed_thread_id`` → reuse it verbatim.
        - ``new`` (or ``fixed`` on its very first run, before any id is
          pinned) → spawn a fresh thread.

        On that first ``fixed`` run we also **write the generated id back**
        to the job's ``fixed_thread_id`` column so every subsequent run
        lands in the same thread and accumulates conversation history /
        context across executions. Without this pin, each run would get a
        brand-new thread and ``fixed`` would silently behave like ``new``.

        The write-back is best-effort: if it raises, this run proceeds
        with the fresh thread and the next run retries the pin.
        ``user_id=None`` (admin scope) because the scheduler is cross-user
        and the owning user is already captured on the job row.

        Note: the actual thread row in LangGraph's checkpointer is created
        on first ``chat()`` call with this id.
        """
        if strategy == "fixed" and fixed_thread_id:
            return fixed_thread_id

        thread_id = str(uuid.uuid4())
        if strategy == "fixed":
            try:
                await self._jobs_repo.update_job_spec(
                    job_id,
                    fixed_thread_id=thread_id,
                    user_id=None,
                )
            except Exception:
                logger.exception(
                    "failed to pin fixed_thread_id for job %s; this run uses a fresh thread and the next run will retry the pin",
                    job_id,
                )
        return thread_id

    def _get_or_create_client(self, agent_name: str | None) -> Any:
        if agent_name not in self._clients:
            self._clients[agent_name] = self._client_factory(agent_name=agent_name)
        return self._clients[agent_name]

    async def _finish_success(
        self,
        run_id: str,
        job: dict[str, Any],
        thread_id: str,
        result_text: str,
        started_at: datetime,
    ) -> None:
        duration_ms = int((datetime.now(UTC) - started_at).total_seconds() * 1000)
        await self._runs_repo.mark_terminal(
            run_id,
            status="ok",
            token_usage=0,  # TODO: extract from result (DeerFlowClient.chat doesn't return usage)
            duration_ms=duration_ms,
        )
        try:
            await self._delivery.deliver(
                job=job,
                thread_id=thread_id,
                result_text=result_text,
                status="ok",
            )
        except Exception:
            logger.exception("delivery failed for job %s", job.get("id"))

    async def _finish_failure(
        self,
        run_id: str,
        job: dict[str, Any],
        thread_id: str,
        exc: BaseException,
        started_at: datetime,
    ) -> None:
        duration_ms = int((datetime.now(UTC) - started_at).total_seconds() * 1000)
        await self._runs_repo.mark_terminal(
            run_id,
            status="error",
            error_msg=str(exc),
            duration_ms=duration_ms,
        )
        try:
            await self._delivery.deliver(
                job=job,
                thread_id=thread_id,
                result_text="",
                status="error",
                error_msg=str(exc),
            )
        except Exception:
            logger.exception("failure-delivery failed for job %s", job.get("id"))
