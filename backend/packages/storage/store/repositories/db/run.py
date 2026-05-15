from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, update
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
            error=data.error,
            follow_up_to_run_id=data.follow_up_to_run_id,
            meta=dict(data.metadata),
            kwargs=dict(data.kwargs),
        )
        if data.created_time is not None:
            model.created_time = data.created_time
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return _to_run(model)

    async def get_run(self, run_id: str) -> Run | None:
        result = await self._session.execute(select(RunModel).where(RunModel.run_id == run_id))
        model = result.scalar_one_or_none()
        return _to_run(model) if model else None

    async def list_runs_by_thread(
        self,
        thread_id: str,
        *,
        user_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Run]:
        stmt = select(RunModel).where(RunModel.thread_id == thread_id)
        if user_id is not None:
            stmt = stmt.where(RunModel.user_id == user_id)
        stmt = stmt.order_by(RunModel.created_time.desc()).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return [_to_run(m) for m in result.scalars().all()]

    async def update_run_status(self, run_id: str, status: str, *, error: str | None = None) -> None:
        values: dict = {"status": status}
        if error is not None:
            values["error"] = error
        await self._session.execute(update(RunModel).where(RunModel.run_id == run_id).values(**values))

    async def delete_run(self, run_id: str) -> None:
        await self._session.execute(delete(RunModel).where(RunModel.run_id == run_id))

    async def list_pending(self, *, before: datetime | str | None = None) -> list[Run]:
        if before is None:
            before_dt = datetime.now().astimezone()
        elif isinstance(before, datetime):
            before_dt = before
        else:
            before_dt = datetime.fromisoformat(before)

        result = await self._session.execute(select(RunModel).where(RunModel.status == "pending", RunModel.created_time <= before_dt).order_by(RunModel.created_time.asc()))
        return [_to_run(m) for m in result.scalars().all()]

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
        }
        if first_human_message is not None:
            values["first_human_message"] = first_human_message[:2000]
        if last_ai_message is not None:
            values["last_ai_message"] = last_ai_message[:2000]
        if error is not None:
            values["error"] = error
        await self._session.execute(update(RunModel).where(RunModel.run_id == run_id).values(**values))

    async def aggregate_tokens_by_thread(self, thread_id: str) -> dict[str, Any]:
        completed = RunModel.status.in_(("success", "error"))
        model_expr = func.coalesce(RunModel.model_name, "unknown")
        stmt = (
            select(
                model_expr.label("model"),
                func.count().label("runs"),
                func.coalesce(func.sum(RunModel.total_tokens), 0).label("total_tokens"),
                func.coalesce(func.sum(RunModel.total_input_tokens), 0).label("total_input_tokens"),
                func.coalesce(func.sum(RunModel.total_output_tokens), 0).label("total_output_tokens"),
                func.coalesce(func.sum(RunModel.lead_agent_tokens), 0).label("lead_agent"),
                func.coalesce(func.sum(RunModel.subagent_tokens), 0).label("subagent"),
                func.coalesce(func.sum(RunModel.middleware_tokens), 0).label("middleware"),
            )
            .where(RunModel.thread_id == thread_id, completed)
            .group_by(model_expr)
        )

        rows = (await self._session.execute(stmt)).all()
        total_tokens = total_input = total_output = total_runs = 0
        lead_agent = subagent = middleware = 0
        by_model: dict[str, dict] = {}
        for row in rows:
            by_model[row.model] = {"tokens": row.total_tokens, "runs": row.runs}
            total_tokens += row.total_tokens
            total_input += row.total_input_tokens
            total_output += row.total_output_tokens
            total_runs += row.runs
            lead_agent += row.lead_agent
            subagent += row.subagent
            middleware += row.middleware

        return {
            "total_tokens": total_tokens,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_runs": total_runs,
            "by_model": by_model,
            "by_caller": {
                "lead_agent": lead_agent,
                "subagent": subagent,
                "middleware": middleware,
            },
        }
