"""Abstract interface for run metadata storage.

RunManager depends on this interface. Implementations:
- MemoryRunStore: in-memory dict (development, tests)
- Future: RunRepository backed by SQLAlchemy ORM

All methods accept an optional user_id for user isolation.
When user_id is None, no user filtering is applied (single-user mode).
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EditReplayVisibility:
    hidden_source_run_ids: set[str] = field(default_factory=set)
    hidden_attempt_run_ids: set[str] = field(default_factory=set)


class RunStore(abc.ABC):
    @abc.abstractmethod
    async def put(
        self,
        run_id: str,
        *,
        thread_id: str,
        assistant_id: str | None = None,
        user_id: str | None = None,
        model_name: str | None = None,
        status: str = "pending",
        operation_kind: str = "run",
        multitask_strategy: str = "reject",
        metadata: dict[str, Any] | None = None,
        kwargs: dict[str, Any] | None = None,
        error: str | None = None,
        stop_reason: str | None = None,
        created_at: str | None = None,
        owner_worker_id: str | None = None,
        lease_expires_at: str | None = None,
    ) -> None:
        pass

    @abc.abstractmethod
    async def get(
        self,
        run_id: str,
        *,
        user_id: str | None = None,
    ) -> dict[str, Any] | None:
        pass

    @abc.abstractmethod
    async def list_by_thread(
        self,
        thread_id: str,
        *,
        user_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        pass

    async def list_successful_regenerate_sources(
        self,
        thread_id: str,
        *,
        user_id: str | None = None,
    ) -> set[str]:
        """Return source run IDs superseded by successful regenerations.

        Implementations must inspect the complete thread and must not apply the
        normal bounded run-list limit.
        """
        raise NotImplementedError

    async def list_edit_regenerate_runs(
        self,
        thread_id: str,
        *,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return all edit-regenerate attempt runs for one thread, oldest first."""
        raise NotImplementedError

    async def get_many_by_thread(
        self,
        thread_id: str,
        run_ids: set[str],
        *,
        user_id: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Batch-load selected runs belonging to one thread."""
        raise NotImplementedError

    @abc.abstractmethod
    async def update_status(
        self,
        run_id: str,
        status: str,
        *,
        error: str | None = None,
        stop_reason: str | None = None,
    ) -> bool | None:
        """Update a run status.

        Returns ``False`` when the store can prove no row was updated. Older or
        lightweight stores may return ``None`` when they cannot report rowcount.
        """
        pass

    @abc.abstractmethod
    async def start_run(self, run_id: str) -> bool:
        """Atomically transition a pending run to running.

        Returns ``False`` when the row is missing or no longer pending.
        """
        pass

    @abc.abstractmethod
    async def delete(self, run_id: str) -> None:
        pass

    async def delete_thread_operation(self, run_id: str, *, user_id: str | None) -> None:
        """Release an admitted thread operation for its recorded owner.

        The default keeps legacy stores compatible: older implementations only
        accepted ``run_id``. User-aware stores should override this method so
        cleanup never depends on ambient request context.
        """
        await self.delete(run_id)

    @abc.abstractmethod
    async def update_model_name(
        self,
        run_id: str,
        model_name: str | None,
    ) -> None:
        """Update the model_name field for an existing run."""
        pass

    @abc.abstractmethod
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
        token_usage_by_model: dict[str, dict[str, int]] | None = None,
        message_count: int = 0,
        last_ai_message: str | None = None,
        first_human_message: str | None = None,
        error: str | None = None,
    ) -> bool | None:
        """Persist final completion fields.

        Implementations must not replace a different terminal status. Returns
        ``False`` when the row is missing or already has a conflicting terminal
        outcome.
        """
        pass

    async def update_run_progress(
        self,
        run_id: str,
        *,
        total_input_tokens: int | None = None,
        total_output_tokens: int | None = None,
        total_tokens: int | None = None,
        llm_call_count: int | None = None,
        lead_agent_tokens: int | None = None,
        subagent_tokens: int | None = None,
        middleware_tokens: int | None = None,
        token_usage_by_model: dict[str, dict[str, int]] | None = None,
        message_count: int | None = None,
        last_ai_message: str | None = None,
        first_human_message: str | None = None,
    ) -> None:
        """Persist a best-effort running snapshot without changing run status."""
        return None

    @abc.abstractmethod
    async def list_pending(self, *, before: str | None = None) -> list[dict[str, Any]]:
        pass

    @abc.abstractmethod
    async def list_inflight(self, *, before: str | None = None) -> list[dict[str, Any]]:
        """Return persisted runs that are still ``pending`` or ``running``."""
        pass

    @abc.abstractmethod
    async def aggregate_tokens_by_thread(self, thread_id: str, *, include_active: bool = False) -> dict[str, Any]:
        """Aggregate token usage for completed runs in a thread.

        Returns a dict with keys: total_tokens, total_input_tokens,
        total_output_tokens, total_runs, by_model (model_name → {tokens, runs}),
        by_caller ({lead_agent, subagent, middleware}).
        """
        pass

    @abc.abstractmethod
    async def update_lease(
        self,
        run_id: str,
        *,
        owner_worker_id: str,
        lease_expires_at: str,
    ) -> bool:
        """Renew the lease on an active run. Returns ``False`` when no row matched."""
        pass

    @abc.abstractmethod
    async def claim_for_takeover(
        self,
        run_id: str,
        *,
        grace_seconds: int,
        error: str,
        stop_reason: str | None = None,
    ) -> bool:
        """Atomically mark an expired-lease active run as ``error``.

        Only rows whose lease has expired past *grace_seconds* (or whose
        lease is NULL — pre-ownership data) are updated.  The conditional
        WHERE closes the race between the caller's stale read of the lease
        and a concurrent heartbeat renewal by the owning worker. When
        provided, *stop_reason* is persisted in the same atomic update.

        Returns ``False`` when:
          - the run is no longer ``pending`` / ``running``,
          - the lease is still valid (owner heartbeat is alive), or
          - the row doesn't exist.
        """
        pass

    @abc.abstractmethod
    async def list_inflight_with_expired_lease(
        self,
        *,
        before: str | None = None,
        grace_seconds: int = 10,
    ) -> list[dict[str, Any]]:
        """Return active runs whose lease has expired (or is NULL for pre-ownership rows)."""
        pass

    async def create_thread_operation_atomic(
        self,
        run_id: str,
        *,
        thread_id: str,
        owner_worker_id: str,
        lease_expires_at: str | None,
        operation_kind: str = "run",
        multitask_strategy: str = "reject",
        assistant_id: str | None = None,
        user_id: str | None = None,
        model_name: str | None = None,
        metadata: dict[str, Any] | None = None,
        kwargs: dict[str, Any] | None = None,
        created_at: str | None = None,
        grace_seconds: int = 10,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Atomically create an active thread operation with cross-process uniqueness.

        The default implementation preserves compatibility with stores that
        still implement the former ``create_run_atomic`` interface. Legacy
        stores support only normal run rows; internal operation kinds require
        an implementation of this method.

        Returns ``(new_run_dict, claimed_run_dicts)``.
        Raises ``IntegrityError`` on conflict for ``reject`` strategy.
        """
        legacy_impl = type(self).create_run_atomic
        if legacy_impl is RunStore.create_run_atomic:
            raise NotImplementedError("RunStore must implement create_thread_operation_atomic() or create_run_atomic()")
        if operation_kind != "run":
            raise NotImplementedError("Legacy RunStore.create_run_atomic() cannot create non-run thread operations")
        return await self.create_run_atomic(
            run_id,
            thread_id=thread_id,
            owner_worker_id=owner_worker_id,
            lease_expires_at=lease_expires_at,
            multitask_strategy=multitask_strategy,
            assistant_id=assistant_id,
            user_id=user_id,
            model_name=model_name,
            metadata=metadata,
            kwargs=kwargs,
            created_at=created_at,
            grace_seconds=grace_seconds,
        )

    async def create_run_atomic(
        self,
        run_id: str,
        *,
        thread_id: str,
        owner_worker_id: str,
        lease_expires_at: str | None,
        multitask_strategy: str = "reject",
        assistant_id: str | None = None,
        user_id: str | None = None,
        model_name: str | None = None,
        metadata: dict[str, Any] | None = None,
        kwargs: dict[str, Any] | None = None,
        created_at: str | None = None,
        grace_seconds: int = 10,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Deprecated compatibility alias for normal-run admission."""
        operation_impl = type(self).create_thread_operation_atomic
        if operation_impl is RunStore.create_thread_operation_atomic:
            raise NotImplementedError("RunStore must implement create_thread_operation_atomic() or create_run_atomic()")
        return await self.create_thread_operation_atomic(
            run_id,
            thread_id=thread_id,
            owner_worker_id=owner_worker_id,
            lease_expires_at=lease_expires_at,
            operation_kind="run",
            multitask_strategy=multitask_strategy,
            assistant_id=assistant_id,
            user_id=user_id,
            model_name=model_name,
            metadata=metadata,
            kwargs=kwargs,
            created_at=created_at,
            grace_seconds=grace_seconds,
        )
