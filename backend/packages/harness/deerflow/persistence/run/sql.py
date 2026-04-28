"""SQLAlchemy-backed RunStore implementation.

Each method acquires and releases its own short-lived session.
Run status updates happen from background workers that may live
minutes -- we don't hold connections across long execution.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.run.model import RunRow
from deerflow.runtime.runs.store.base import RunStore
from deerflow.runtime.user_context import AUTO, _AutoSentinel, resolve_user_id


class RunRepository(RunStore):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _safe_json(obj: Any) -> Any:
        """Ensure obj is JSON-serializable. Falls back to model_dump() or str()."""
        if obj is None:
            return None
        if isinstance(obj, (str, int, float, bool)):
            return obj
        if isinstance(obj, dict):
            return {k: RunRepository._safe_json(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [RunRepository._safe_json(v) for v in obj]
        if hasattr(obj, "model_dump"):
            try:
                return obj.model_dump()
            except Exception:
                pass
        if hasattr(obj, "dict"):
            try:
                return obj.dict()
            except Exception:
                pass
        try:
            json.dumps(obj)
            return obj
        except (TypeError, ValueError):
            return str(obj)

    @staticmethod
    def _row_to_dict(row: RunRow) -> dict[str, Any]:
        d = row.to_dict()
        # Remap JSON columns to match RunStore interface
        d["metadata"] = d.pop("metadata_json", {})
        d["kwargs"] = d.pop("kwargs_json", {})
        # Convert datetime to ISO string for consistency with MemoryRunStore
        for key in ("created_at", "updated_at"):
            val = d.get(key)
            if isinstance(val, datetime):
                d[key] = val.isoformat()
        return d

    async def put(
        self,
        run_id,
        *,
        thread_id,
        assistant_id=None,
        user_id: str | None | _AutoSentinel = AUTO,
        status="pending",
        multitask_strategy="reject",
        metadata=None,
        kwargs=None,
        error=None,
        created_at=None,
        follow_up_to_run_id=None,
    ):
        resolved_user_id = resolve_user_id(user_id, method_name="RunRepository.put")
        now = datetime.now(UTC)
        row = RunRow(
            run_id=run_id,
            thread_id=thread_id,
            assistant_id=assistant_id,
            user_id=resolved_user_id,
            status=status,
            multitask_strategy=multitask_strategy,
            metadata_json=self._safe_json(metadata) or {},
            kwargs_json=self._safe_json(kwargs) or {},
            error=error,
            follow_up_to_run_id=follow_up_to_run_id,
            created_at=datetime.fromisoformat(created_at) if created_at else now,
            updated_at=now,
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()

    async def get(
        self,
        run_id,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ):
        resolved_user_id = resolve_user_id(user_id, method_name="RunRepository.get")
        async with self._sf() as session:
            row = await session.get(RunRow, run_id)
            if row is None:
                return None
            if resolved_user_id is not None and row.user_id != resolved_user_id:
                return None
            return self._row_to_dict(row)

    async def list_by_thread(
        self,
        thread_id,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
        limit=100,
    ):
        resolved_user_id = resolve_user_id(user_id, method_name="RunRepository.list_by_thread")
        stmt = select(RunRow).where(RunRow.thread_id == thread_id)
        if resolved_user_id is not None:
            stmt = stmt.where(RunRow.user_id == resolved_user_id)
        stmt = stmt.order_by(RunRow.created_at.desc()).limit(limit)
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

    async def update_status(self, run_id, status, *, error=None):
        values: dict[str, Any] = {"status": status, "updated_at": datetime.now(UTC)}
        if error is not None:
            values["error"] = error
        async with self._sf() as session:
            await session.execute(update(RunRow).where(RunRow.run_id == run_id).values(**values))
            await session.commit()

    async def delete(
        self,
        run_id,
        *,
        user_id: str | None | _AutoSentinel = AUTO,
    ):
        resolved_user_id = resolve_user_id(user_id, method_name="RunRepository.delete")
        async with self._sf() as session:
            row = await session.get(RunRow, run_id)
            if row is None:
                return
            if resolved_user_id is not None and row.user_id != resolved_user_id:
                return
            await session.delete(row)
            await session.commit()

    async def list_pending(self, *, before=None):
        if before is None:
            before_dt = datetime.now(UTC)
        elif isinstance(before, datetime):
            before_dt = before
        else:
            before_dt = datetime.fromisoformat(before)
        stmt = select(RunRow).where(RunRow.status == "pending", RunRow.created_at <= before_dt).order_by(RunRow.created_at.asc())
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]

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
        last_ai_message: str | None = None,
        first_human_message: str | None = None,
        error: str | None = None,
    ) -> None:
        """Update status + token usage + convenience fields on run completion."""
        values: dict[str, Any] = {
            "status": status,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "total_tokens": total_tokens,
            "llm_call_count": llm_call_count,
            "lead_agent_tokens": lead_agent_tokens,
            "subagent_tokens": subagent_tokens,
            "middleware_tokens": middleware_tokens,
            "message_count": message_count,
            "updated_at": datetime.now(UTC),
        }
        if last_ai_message is not None:
            values["last_ai_message"] = last_ai_message[:2000]
        if first_human_message is not None:
            values["first_human_message"] = first_human_message[:2000]
        if error is not None:
            values["error"] = error
        async with self._sf() as session:
            await session.execute(update(RunRow).where(RunRow.run_id == run_id).values(**values))
            await session.commit()

    async def aggregate_tokens_by_thread(self, thread_id: str) -> dict[str, Any]:
        """Aggregate token usage via a single SQL GROUP BY query."""
        _completed = RunRow.status.in_(("success", "error"))
        _thread = RunRow.thread_id == thread_id

        stmt = (
            select(
                func.coalesce(RunRow.model_name, "unknown").label("model"),
                func.count().label("runs"),
                func.coalesce(func.sum(RunRow.total_tokens), 0).label("total_tokens"),
                func.coalesce(func.sum(RunRow.total_input_tokens), 0).label("total_input_tokens"),
                func.coalesce(func.sum(RunRow.total_output_tokens), 0).label("total_output_tokens"),
                func.coalesce(func.sum(RunRow.lead_agent_tokens), 0).label("lead_agent"),
                func.coalesce(func.sum(RunRow.subagent_tokens), 0).label("subagent"),
                func.coalesce(func.sum(RunRow.middleware_tokens), 0).label("middleware"),
            )
            .where(_thread, _completed)
            .group_by(func.coalesce(RunRow.model_name, "unknown"))
        )

        async with self._sf() as session:
            rows = (await session.execute(stmt)).all()

        total_tokens = total_input = total_output = total_runs = 0
        lead_agent = subagent = middleware = 0
        by_model: dict[str, dict] = {}
        for r in rows:
            by_model[r.model] = {"tokens": r.total_tokens, "runs": r.runs}
            total_tokens += r.total_tokens
            total_input += r.total_input_tokens
            total_output += r.total_output_tokens
            total_runs += r.runs
            lead_agent += r.lead_agent
            subagent += r.subagent
            middleware += r.middleware

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
