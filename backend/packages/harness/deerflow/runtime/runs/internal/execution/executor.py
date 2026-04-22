"""Single-run execution orchestrator and execution-local helpers."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

from langchain_core.runnables import RunnableConfig

from deerflow.runtime.serialization import serialize
from deerflow.runtime.stream_bridge import StreamBridge, StreamStatus

from ...callbacks.builder import RunCallbackArtifacts, build_run_callbacks
from ...observer import LifecycleEventType, RunObserver, RunResult
from ...store import RunEventStore
from ...types import RunStatus
from .artifacts import build_run_artifacts
from .events import RunEventEmitter
from .stream_logic import external_stream_event_name, normalize_stream_modes, should_filter_event, unpack_stream_item
from .supervisor import RunHandle

logger = logging.getLogger(__name__)


class _RunExecution:
    """Encapsulate the lifecycle of a single run."""

    def __init__(
        self,
        *,
        bridge: StreamBridge,
        run_manager: Any,
        record: Any,
        checkpointer: Any | None = None,
        store: Any | None = None,
        event_store: RunEventStore | None = None,
        ctx: Any | None = None,
        agent_factory: Any,
        graph_input: dict,
        config: dict,
        observer: RunObserver,
        stream_modes: list[str] | None,
        stream_subgraphs: bool,
        interrupt_before: list[str] | Literal["*"] | None,
        interrupt_after: list[str] | Literal["*"] | None,
        handle: RunHandle | None = None,
    ) -> None:
        if ctx is not None:
            checkpointer = getattr(ctx, "checkpointer", checkpointer)
            store = getattr(ctx, "store", store)

        self.bridge = bridge
        self.run_manager = run_manager
        self.record = record
        self.checkpointer = checkpointer
        self.store = store
        self.event_store = event_store
        self.agent_factory = agent_factory
        self.graph_input = graph_input
        self.config = config
        self.observer = observer
        self.stream_modes = stream_modes
        self.stream_subgraphs = stream_subgraphs
        self.interrupt_before = interrupt_before
        self.interrupt_after = interrupt_after
        self.handle = handle

        self.run_id = record.run_id
        self.thread_id = record.thread_id
        self._pre_run_checkpoint_id: str | None = None
        self._emitter = RunEventEmitter(
            run_id=self.run_id,
            thread_id=self.thread_id,
            observer=observer,
        )
        self.result = RunResult(
            run_id=self.run_id,
            thread_id=self.thread_id,
            status=RunStatus.pending,
        )
        self._agent: Any = None
        self._runnable_config: dict[str, Any] = {}
        self._lg_modes: list[str] = []
        self._callback_artifacts: RunCallbackArtifacts | None = None

    @property
    def _event_sequence(self) -> int:
        return self._emitter.sequence

    async def _emit(
        self,
        event_type: LifecycleEventType,
        payload: dict[str, Any] | None = None,
    ) -> None:
        await self._emitter.emit(event_type, payload)

    async def _start(self) -> None:
        await self.run_manager.set_status(self.run_id, RunStatus.running)
        await self._emit(LifecycleEventType.RUN_STARTED, {})

        human_msg = self._extract_human_message()
        if human_msg is not None:
            await self._emit(
                LifecycleEventType.HUMAN_MESSAGE,
                {"message": human_msg.model_dump()},
            )

        await self._capture_pre_run_checkpoint()
        await self.bridge.publish(
            self.run_id,
            "metadata",
            {"run_id": self.run_id, "thread_id": self.thread_id},
        )

    def _extract_human_message(self) -> Any:
        from langchain_core.messages import HumanMessage

        messages = self.graph_input.get("messages")
        if not messages:
            return None
        last = messages[-1] if isinstance(messages, list) else messages
        if isinstance(last, HumanMessage):
            return last
        if isinstance(last, str):
            return HumanMessage(content=last) if last else None
        if hasattr(last, "content"):
            return HumanMessage(content=last.content)
        if isinstance(last, dict):
            content = last.get("content", "")
            return HumanMessage(content=content) if content else None
        return None

    async def _capture_pre_run_checkpoint(self) -> None:
        try:
            config_for_check = {"configurable": {"thread_id": self.thread_id, "checkpoint_ns": ""}}
            ckpt_tuple = await self.checkpointer.aget_tuple(config_for_check)
            if ckpt_tuple is not None:
                self._pre_run_checkpoint_id = (
                    getattr(ckpt_tuple, "config", {})
                    .get("configurable", {})
                    .get("checkpoint_id")
                )
        except Exception:
            logger.debug("Could not get pre-run checkpoint_id for run %s", self.run_id)

    async def _prepare(self) -> None:
        config = dict(self.config)
        existing_callbacks = config.pop("callbacks", [])
        if existing_callbacks is None:
            existing_callbacks = []
        elif not isinstance(existing_callbacks, list):
            existing_callbacks = [existing_callbacks]

        self._callback_artifacts = build_run_callbacks(
            record=self.record,
            graph_input=self.graph_input,
            event_store=self.event_store,
            existing_callbacks=existing_callbacks,
        )

        artifacts = build_run_artifacts(
            thread_id=self.thread_id,
            run_id=self.run_id,
            checkpointer=self.checkpointer,
            store=self.store,
            agent_factory=self.agent_factory,
            config=config,
            bridge=self.bridge,
            interrupt_before=self.interrupt_before,
            interrupt_after=self.interrupt_after,
            callbacks=self._callback_artifacts.callbacks,
        )

        self._agent = artifacts.agent
        self._runnable_config = artifacts.runnable_config
        self._lg_modes = normalize_stream_modes(self.stream_modes)
        logger.info(
            "Run %s: streaming with modes %s (requested: %s)",
            self.run_id,
            self._lg_modes,
            self.stream_modes,
        )

    async def _finish_success(self) -> None:
        await self.run_manager.set_status(self.run_id, RunStatus.success)
        await self.bridge.publish_terminal(self.run_id, StreamStatus.ENDED)
        self.result.status = RunStatus.success
        completion_data = self._completion_data()
        title = self._callback_title() or await self._extract_title_from_checkpoint()
        self.result.title = title
        self.result.completion_data = completion_data
        await self._emit(
            LifecycleEventType.RUN_COMPLETED,
            {
                "title": title,
                "completion_data": completion_data,
            },
        )

    async def _finish_aborted(self, cancel_mode: str) -> None:
        payload = {
            "cancel_mode": cancel_mode,
            "pre_run_checkpoint_id": self._pre_run_checkpoint_id,
            "completion_data": self._completion_data(),
        }

        if cancel_mode == "rollback":
            await self.run_manager.set_status(
                self.run_id,
                RunStatus.error,
                error="Rolled back by user",
            )
            await self.bridge.publish_terminal(
                self.run_id,
                StreamStatus.CANCELLED,
                {"cancel_mode": "rollback", "message": "Rolled back by user"},
            )
            self.result.status = RunStatus.error
            self.result.error = "Rolled back by user"
            logger.info("Run %s rolled back", self.run_id)
        else:
            await self.run_manager.set_status(self.run_id, RunStatus.interrupted)
            await self.bridge.publish_terminal(
                self.run_id,
                StreamStatus.CANCELLED,
                {"cancel_mode": cancel_mode},
            )
            self.result.status = RunStatus.interrupted
            logger.info("Run %s cancelled (mode=%s)", self.run_id, cancel_mode)

        await self._emit(LifecycleEventType.RUN_CANCELLED, payload)

    async def _finish_failed(self, exc: Exception) -> None:
        error_msg = str(exc)
        logger.exception("Run %s failed: %s", self.run_id, error_msg)

        await self.run_manager.set_status(self.run_id, RunStatus.error, error=error_msg)
        await self.bridge.publish_terminal(
            self.run_id,
            StreamStatus.ERRORED,
            {"message": error_msg, "name": type(exc).__name__},
        )
        self.result.status = RunStatus.error
        self.result.error = error_msg

        await self._emit(
            LifecycleEventType.RUN_FAILED,
            {
                "error": error_msg,
                "error_type": type(exc).__name__,
                "completion_data": self._completion_data(),
            },
        )

    def _completion_data(self) -> dict[str, object]:
        if self._callback_artifacts is None:
            return {}
        return self._callback_artifacts.completion_data().to_dict()

    def _callback_title(self) -> str | None:
        if self._callback_artifacts is None:
            return None
        return self._callback_artifacts.title()

    async def _extract_title_from_checkpoint(self) -> str | None:
        if self.checkpointer is None:
            return None
        try:
            ckpt_config = {"configurable": {"thread_id": self.thread_id, "checkpoint_ns": ""}}
            ckpt_tuple = await self.checkpointer.aget_tuple(ckpt_config)
            if ckpt_tuple is not None:
                ckpt = getattr(ckpt_tuple, "checkpoint", {}) or {}
                return ckpt.get("channel_values", {}).get("title")
        except Exception:
            logger.debug("Failed to extract title from checkpoint for thread %s", self.thread_id)
        return None

    def _map_run_status_to_thread_status(self, status: RunStatus) -> str:
        if status == RunStatus.success:
            return "idle"
        if status == RunStatus.interrupted:
            return "interrupted"
        if status in (RunStatus.error, RunStatus.timeout):
            return "error"
        return "running"

    def _abort_requested(self) -> bool:
        if self.handle is not None:
            return self.handle.cancel_event.is_set()
        return self.record.abort_event.is_set()

    def _abort_action(self) -> str:
        if self.handle is not None:
            return self.handle.cancel_action
        return self.record.abort_action

    async def _stream(self) -> None:
        runnable_config = RunnableConfig(**self._runnable_config)

        if len(self._lg_modes) == 1 and not self.stream_subgraphs:
            single_mode = self._lg_modes[0]
            async for chunk in self._agent.astream(
                self.graph_input,
                config=runnable_config,
                stream_mode=single_mode,
            ):
                if self._abort_requested():
                    logger.info("Run %s abort requested - stopping", self.run_id)
                    break
                if should_filter_event(single_mode, chunk):
                    continue
                await self.bridge.publish(
                    self.run_id,
                    external_stream_event_name(single_mode),
                    serialize(chunk, mode=single_mode),
                )
            return

        async for item in self._agent.astream(
            self.graph_input,
            config=runnable_config,
            stream_mode=self._lg_modes,
            subgraphs=self.stream_subgraphs,
        ):
            if self._abort_requested():
                logger.info("Run %s abort requested - stopping", self.run_id)
                break

            mode, chunk = unpack_stream_item(item, self._lg_modes, stream_subgraphs=self.stream_subgraphs)
            if mode is None:
                continue
            if should_filter_event(mode, chunk):
                continue
            await self.bridge.publish(
                self.run_id,
                external_stream_event_name(mode),
                serialize(chunk, mode=mode),
            )

    async def _finish_after_stream(self) -> None:
        if self._abort_requested():
            action = self._abort_action()
            cancel_mode = "rollback" if action == "rollback" else "interrupt"
            await self._finish_aborted(cancel_mode)
            return

        await self._finish_success()

    async def _emit_final_thread_status(self) -> None:
        final_thread_status = self._map_run_status_to_thread_status(self.result.status)
        await self._emit(
            LifecycleEventType.THREAD_STATUS_UPDATED,
            {"status": final_thread_status},
        )

    async def run(self) -> RunResult:
        try:
            await self._start()
            await self._prepare()
            await self._stream()
            await self._finish_after_stream()
        except asyncio.CancelledError:
            await self._finish_aborted("task_cancelled")
        except Exception as exc:
            await self._finish_failed(exc)
        finally:
            await self._emit_final_thread_status()
            if self._callback_artifacts is not None:
                await self._callback_artifacts.flush()
            await self.bridge.cleanup(self.run_id)

        return self.result


__all__ = ["_RunExecution"]
