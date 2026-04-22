from __future__ import annotations

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from store.repositories.contracts.run import Run, RunCreate, RunRepositoryProtocol
from store.repositories.models.run import Run as RunModel


def _to_run(m: RunModel) -> Run:
    return Run(
        run_id=m.run_id,
        thread_id=m.thread_id,
        assistant_id=m.assistant_id,
        user_id=m.user_id,
        status=m.status,
        model_name=m.model_name,
        multitask_strategy=m.multitask_strategy,
        error=m.error,
        follow_up_to_run_id=m.follow_up_to_run_id,
        metadata=dict(m.meta or {}),
        kwargs=dict(m.kwargs or {}),
        total_input_tokens=m.total_input_tokens,
        total_output_tokens=m.total_output_tokens,
        total_tokens=m.total_tokens,
        llm_call_count=m.llm_call_count,
        lead_agent_tokens=m.lead_agent_tokens,
        subagent_tokens=m.subagent_tokens,
        middleware_tokens=m.middleware_tokens,
        message_count=m.message_count,
        first_human_message=m.first_human_message,
        last_ai_message=m.last_ai_message,
        created_time=m.created_time,
        updated_time=m.updated_time,
    )


class DbRunRepository(RunRepositoryProtocol):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_run(self, data: RunCreate) -> Run:
        model = RunModel(
            run_id=data.run_id,
            thread_id=data.thread_id,
            assistant_id=data.assistant_id,
            user_id=data.user_id,
            status=data.status,
            model_name=data.model_name,
            multitask_strategy=data.multitask_strategy,
            follow_up_to_run_id=data.follow_up_to_run_id,
            meta=dict(data.metadata),
            kwargs=dict(data.kwargs),
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return _to_run(model)

    async def get_run(self, run_id: str) -> Run | None:
        result = await self._session.execute(
            select(RunModel).where(RunModel.run_id == run_id)
        )
        model = result.scalar_one_or_none()
        return _to_run(model) if model else None

    async def list_runs_by_thread(
        self, thread_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[Run]:
        result = await self._session.execute(
            select(RunModel)
            .where(RunModel.thread_id == thread_id)
            .order_by(RunModel.created_time.desc())
            .limit(limit)
            .offset(offset)
        )
        return [_to_run(m) for m in result.scalars().all()]

    async def update_run_status(
        self, run_id: str, status: str, *, error: str | None = None
    ) -> None:
        values: dict = {"status": status}
        if error is not None:
            values["error"] = error
        await self._session.execute(
            update(RunModel).where(RunModel.run_id == run_id).values(**values)
        )

    async def delete_run(self, run_id: str) -> None:
        await self._session.execute(delete(RunModel).where(RunModel.run_id == run_id))

    async def update_run_completion(
        self,
        run_id: str,
        *,
        status: str,
        total_input_tokens: int = 0,
        total_output_tokens: int = 0,
        total_tokens: int = 0,
        llm_call_count: int = 0,
        lead_agent_tokens: int = 0,
        subagent_tokens: int = 0,
        middleware_tokens: int = 0,
        message_count: int = 0,
        first_human_message: str | None = None,
        last_ai_message: str | None = None,
        error: str | None = None,
    ) -> None:
        values = {
            "status": status,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "total_tokens": total_tokens,
            "llm_call_count": llm_call_count,
            "lead_agent_tokens": lead_agent_tokens,
            "subagent_tokens": subagent_tokens,
            "middleware_tokens": middleware_tokens,
            "message_count": message_count,
            "first_human_message": first_human_message,
            "last_ai_message": last_ai_message,
            "error": error,
        }
        await self._session.execute(
            update(RunModel).where(RunModel.run_id == run_id).values(**values)
        )
