"""Gateway-local scheduler for conversation-created one-time runs."""

from __future__ import annotations

import asyncio
import copy
import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from langchain_core.messages import AIMessage, BaseMessage

from app.channels.message_bus import OutboundMessage
from deerflow.config.app_config import AppConfig
from deerflow.persistence.engine import get_session_factory
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository
from deerflow.runtime import ConflictError, DisconnectMode, RunContext, RunStatus, run_agent
from deerflow.runtime.user_context import reset_current_user, set_current_user

logger = logging.getLogger(__name__)


class ScheduledRunService:
    def __init__(self, app: FastAPI, config: AppConfig, repository: ScheduledTaskRepository) -> None:
        self._app = app
        self._config = config
        self._repo = repository
        self._running = False
        self._loop_task: asyncio.Task | None = None
        self._semaphore = asyncio.Semaphore(config.scheduler.max_concurrent_runs)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._loop_task = asyncio.create_task(self._poll_loop())
        logger.info("ScheduledRunService started")

    async def stop(self) -> None:
        self._running = False
        if self._loop_task is not None:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None
        logger.info("ScheduledRunService stopped")

    async def _poll_loop(self) -> None:
        interval = self._config.scheduler.poll_interval_seconds
        while self._running:
            try:
                await self._dispatch_due_tasks()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Scheduled task polling failed")
            await asyncio.sleep(interval)

    async def _dispatch_due_tasks(self) -> None:
        now = datetime.now(UTC)
        due = await self._repo.list_due(now=now, limit=self._config.scheduler.max_concurrent_runs * 4)
        for task in due:
            asyncio.create_task(self._execute_if_claimed(task["id"]))

    async def _execute_if_claimed(self, task_id: str) -> None:
        async with self._semaphore:
            now = datetime.now(UTC)
            task = await self._repo.claim_due(task_id, now=now, lease_seconds=self._config.scheduler.claim_ttl_seconds)
            if task is None:
                return
            grace = self._config.scheduler.misfire_grace_time_seconds
            run_at = datetime.fromisoformat(str(task["run_at"]))
            if run_at.tzinfo is None:
                run_at = run_at.replace(tzinfo=UTC)
            if grace >= 0 and (now - run_at.astimezone(UTC)).total_seconds() > grace:
                await self._repo.mark_missed(task_id, error="Scheduled task missed its grace window.")
                await self._notify_thread_event(
                    task,
                    "scheduled_run_missed",
                    status="missed",
                    error="Scheduled task missed its grace window.",
                )
                return
            await self._execute_task(task)

    async def _execute_task(self, task: dict[str, Any]) -> None:
        run_id: str | None = None
        try:
            record = await self._start_agent_run(task)
            run_id = record.run_id
            if record.task is not None:
                await record.task
            if record.status == RunStatus.success:
                await self._repo.mark_completed(task["id"], run_id=run_id)
                await self._notify_thread_event(task, "scheduled_run_completed", status="completed", run_id=run_id)
                await self._notify_channel(task, await self._extract_latest_response_async(task["thread_id"]))
            else:
                error = record.error or f"Scheduled run finished with status {record.status.value}"
                await self._repo.mark_failed(task["id"], error=error, run_id=run_id)
                await self._notify_thread_event(task, "scheduled_run_failed", status="failed", run_id=run_id, error=error)
                await self._notify_channel(task, f"Scheduled task failed: {error}")
        except ConflictError as exc:
            error = f"Thread is busy: {exc}"
            await self._repo.mark_failed(task["id"], error=error, run_id=run_id)
            await self._notify_thread_event(task, "scheduled_run_failed", status="failed", run_id=run_id, error=error)
            await self._notify_channel(task, f"Scheduled task could not start because the thread is busy: {exc}")
        except Exception as exc:
            logger.exception("Scheduled task %s failed", task.get("id"))
            await self._repo.mark_failed(task["id"], error=str(exc), run_id=run_id)
            await self._notify_thread_event(task, "scheduled_run_failed", status="failed", run_id=run_id, error=str(exc))
            await self._notify_channel(task, f"Scheduled task failed: {exc}")

    async def _start_agent_run(self, task: dict[str, Any]):
        from app.gateway.services import build_run_config, merge_run_context_overrides, normalize_input, resolve_agent_factory

        thread_id = str(task["thread_id"])
        assistant_id = str(task.get("assistant_id") or "lead_agent")
        owner_user_id = str(task["owner_user_id"])
        prompt = self._build_scheduled_prompt(task)
        body_input = {
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "additional_kwargs": {"hide_from_ui": True},
                }
            ]
        }
        metadata = {"scheduled_task_id": task["id"], "source": "scheduled_task"}
        config = build_run_config(thread_id, None, metadata, assistant_id=assistant_id)
        context: dict[str, Any] = {"user_id": owner_user_id}
        if task.get("agent_name"):
            context["agent_name"] = task["agent_name"]
        merge_run_context_overrides(config, context)

        run_mgr = self._app.state.run_manager
        record = await run_mgr.create_or_reject(
            thread_id,
            assistant_id,
            on_disconnect=DisconnectMode.continue_,
            metadata=metadata,
            kwargs={"input": body_input, "config": copy.deepcopy(config)},
            multitask_strategy="reject",
            user_id=owner_user_id,
        )

        token = set_current_user(SimpleNamespace(id=owner_user_id))
        try:
            run_ctx = RunContext(
                checkpointer=self._app.state.checkpointer,
                store=getattr(self._app.state, "store", None),
                event_store=getattr(self._app.state, "run_event_store", None),
                run_events_config=getattr(self._app.state, "run_events_config", None),
                thread_store=getattr(self._app.state, "thread_store", None),
                app_config=self._config,
            )
            record.task = asyncio.create_task(
                run_agent(
                    self._app.state.stream_bridge,
                    run_mgr,
                    record,
                    ctx=run_ctx,
                    agent_factory=resolve_agent_factory(assistant_id),
                    graph_input=normalize_input(body_input),
                    config=config,
                    stream_modes=["values"],
                )
            )
            return record
        finally:
            reset_current_user(token)

    @staticmethod
    def _build_scheduled_prompt(task: dict[str, Any]) -> str:
        title = task.get("title")
        prefix = f"Scheduled task '{title}' is due." if title else "Scheduled task is due."
        return f"{prefix}\n\n{task['prompt']}"

    async def _extract_latest_response_async(self, thread_id: str) -> str:
        checkpoint_tuple = await self._app.state.checkpointer.aget_tuple({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}})
        if checkpoint_tuple is None:
            return "Scheduled task completed."
        channel_values = getattr(checkpoint_tuple, "checkpoint", {}).get("channel_values", {})
        messages = channel_values.get("messages", [])
        for message in reversed(messages):
            if isinstance(message, AIMessage):
                return _message_content_to_text(message.content) or "Scheduled task completed."
            if isinstance(message, BaseMessage) and getattr(message, "type", "") == "ai":
                return _message_content_to_text(message.content) or "Scheduled task completed."
        return "Scheduled task completed."

    async def _notify_channel(self, task: dict[str, Any], text: str | None) -> None:
        channel_name = task.get("channel_name")
        chat_id = task.get("chat_id")
        if not channel_name or not chat_id:
            return
        from app.channels.service import get_channel_service

        service = get_channel_service()
        channel = service.get_channel(str(channel_name)) if service else None
        if channel is None:
            logger.info("Scheduled task %s completed without active channel %s", task.get("id"), channel_name)
            return
        await channel.send(
            OutboundMessage(
                channel_name=str(channel_name),
                chat_id=str(chat_id),
                thread_id=str(task["thread_id"]),
                text=text or "Scheduled task completed.",
                thread_ts=str(task["thread_ts"]) if task.get("thread_ts") else None,
                connection_id=str(task["connection_id"]) if task.get("connection_id") else None,
                owner_user_id=str(task["owner_user_id"]),
                metadata={"scheduled_task_id": task["id"]},
            )
        )

    async def _notify_thread_event(
        self,
        task: dict[str, Any],
        event: str,
        *,
        status: str,
        run_id: str | None = None,
        error: str | None = None,
    ) -> None:
        hub = getattr(self._app.state, "thread_event_hub", None)
        if hub is None:
            return
        data = {
            "type": event,
            "scheduled_task_id": task["id"],
            "thread_id": task["thread_id"],
            "status": status,
            "run_id": run_id,
        }
        if error:
            data["error"] = error
        await hub.publish(
            str(task["thread_id"]),
            event,
            data,
            user_id=str(task["owner_user_id"]) if task.get("owner_user_id") else None,
        )


def _message_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif isinstance(item, dict) and isinstance(item.get("content"), str):
                parts.append(item["content"])
        return "\n".join(part for part in parts if part).strip()
    return str(content) if content is not None else ""


_scheduler_service: ScheduledRunService | None = None


def get_scheduler_service() -> ScheduledRunService | None:
    return _scheduler_service


async def start_scheduler_service(app: FastAPI, app_config: AppConfig) -> ScheduledRunService | None:
    global _scheduler_service
    if not app_config.scheduler.enabled:
        logger.info("ScheduledRunService disabled by config")
        return None
    if _scheduler_service is not None:
        return _scheduler_service
    sf = get_session_factory()
    if sf is None:
        logger.warning("ScheduledRunService requires sqlite or postgres database backend; not starting")
        return None
    _scheduler_service = ScheduledRunService(app, app_config, ScheduledTaskRepository(sf))
    await _scheduler_service.start()
    return _scheduler_service


async def stop_scheduler_service() -> None:
    global _scheduler_service
    if _scheduler_service is not None:
        await _scheduler_service.stop()
        _scheduler_service = None
