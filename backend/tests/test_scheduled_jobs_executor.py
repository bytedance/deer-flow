"""Unit tests for ``AgentJobExecutor`` thread resolution.

Focus: the ``fixed`` thread-strategy pin behaviour. A fixed-strategy job
with no pinned ``fixed_thread_id`` must generate a fresh id on its first
run and write it back so every later run reuses the same thread (and thus
accumulates conversation history). See ``app/scheduled_jobs/executor.py``.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.scheduled_jobs.executor import AgentJobExecutor

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeJobsRepo:
    """Records ``update_job_spec`` calls and remembers the pinned id."""

    def __init__(self) -> None:
        self.updates: list[tuple[str, dict[str, Any]]] = []
        self.fixed_thread_id: str | None = None

    async def update_job_spec(
        self,
        job_id: str,
        *,
        fixed_thread_id: str | None = None,
        user_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        self.updates.append((job_id, {"fixed_thread_id": fixed_thread_id, "user_id": user_id, **kwargs}))
        if fixed_thread_id is not None:
            self.fixed_thread_id = fixed_thread_id
        return {"id": job_id, "fixed_thread_id": self.fixed_thread_id}


class _FakeRunsRepo:
    def __init__(self) -> None:
        self.created: dict[str, Any] | None = None
        self.terminal: dict[str, Any] | None = None

    async def create_run(self, **kwargs: Any) -> dict[str, Any]:
        self.created = kwargs
        return {"id": "run-1"}

    async def mark_terminal(self, run_id: str, **kwargs: Any) -> dict[str, Any] | None:
        self.terminal = {"run_id": run_id, **kwargs}
        return None


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def chat(self, message: str, *, thread_id: str | None = None, **kwargs: Any) -> str:
        self.calls.append((message, thread_id))
        return "ok-result"


class _NoopDelivery:
    async def deliver(self, **kwargs: Any) -> None:
        pass


def _build_executor(
    *,
    jobs_repo: _FakeJobsRepo | None = None,
    runs_repo: _FakeRunsRepo | None = None,
    client: _FakeClient | None = None,
) -> tuple[AgentJobExecutor, _FakeJobsRepo, _FakeRunsRepo, _FakeClient]:
    jobs_repo = jobs_repo or _FakeJobsRepo()
    runs_repo = runs_repo or _FakeRunsRepo()
    client = client or _FakeClient()
    executor = AgentJobExecutor(
        jobs_repo,
        runs_repo,
        delivery=_NoopDelivery(),
        client_factory=lambda **_: client,
    )
    return executor, jobs_repo, runs_repo, client


# ---------------------------------------------------------------------------
# _resolve_thread_id — direct unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fixed_without_id_pins_new_thread_id() -> None:
    """First run of a fixed job with no pinned id generates a fresh id and
    writes it back so future runs reuse it."""
    executor, jobs_repo, _, _ = _build_executor()

    thread_id = await executor._resolve_thread_id("job-1", "fixed", None)

    assert thread_id  # a uuid was generated
    assert jobs_repo.updates == [("job-1", {"fixed_thread_id": thread_id, "user_id": None})]
    assert jobs_repo.fixed_thread_id == thread_id


@pytest.mark.asyncio
async def test_fixed_with_pinned_id_reuses_without_write() -> None:
    """A fixed job that already has a pinned id reuses it and does NOT
    write back (no spurious updates)."""
    executor, jobs_repo, _, _ = _build_executor()

    thread_id = await executor._resolve_thread_id("job-1", "fixed", "existing-thread")

    assert thread_id == "existing-thread"
    assert jobs_repo.updates == []
    assert jobs_repo.fixed_thread_id is None


@pytest.mark.asyncio
async def test_new_strategy_does_not_pin() -> None:
    """``new`` strategy never writes back — each run is intentionally
    stateless."""
    executor, jobs_repo, _, _ = _build_executor()

    thread_id = await executor._resolve_thread_id("job-1", "new", None)

    assert thread_id  # fresh uuid
    assert jobs_repo.updates == []


@pytest.mark.asyncio
async def test_pinned_thread_survives_across_runs() -> None:
    """End-to-end intent: the first run pins a thread id, and a
    subsequent run (job reloaded from DB carrying the pin) reuses it."""
    executor, jobs_repo, _, _ = _build_executor()

    first = await executor._resolve_thread_id("job-1", "fixed", None)
    # Simulate the job row being reloaded from the DB carrying the pin.
    second = await executor._resolve_thread_id("job-1", "fixed", jobs_repo.fixed_thread_id)

    assert second == first
    assert len(jobs_repo.updates) == 1  # only the first run wrote back


# ---------------------------------------------------------------------------
# execute() — integration of the pin into the full run path
# ---------------------------------------------------------------------------


def _fixed_job(*, fixed_thread_id: str | None) -> dict[str, Any]:
    return {
        "id": "job-1",
        "user_id": "alice",
        "description": "Summarise my inbox.",
        "agent_name": None,
        "thread_strategy": "fixed",
        "fixed_thread_id": fixed_thread_id,
    }


@pytest.mark.asyncio
async def test_execute_fixed_job_pins_and_uses_thread_id() -> None:
    """The pinned thread id flows to both the run record and the agent
    ``chat`` call."""
    executor, jobs_repo, runs_repo, client = _build_executor()

    result = await executor.execute(_fixed_job(fixed_thread_id=None))

    assert result.status == "ok"
    assert result.thread_id == jobs_repo.fixed_thread_id
    assert runs_repo.created["thread_id"] == jobs_repo.fixed_thread_id
    assert client.calls == [("Summarise my inbox.", jobs_repo.fixed_thread_id)]
    assert runs_repo.terminal is not None and runs_repo.terminal["status"] == "ok"


@pytest.mark.asyncio
async def test_execute_fixed_job_with_pinned_id_reuses() -> None:
    """A fixed job that already carries a pinned id reuses it and does
    not write back again."""
    executor, jobs_repo, _, client = _build_executor()

    await executor.execute(_fixed_job(fixed_thread_id="pre-pinned"))

    assert jobs_repo.updates == []
    assert client.calls[0][1] == "pre-pinned"


# ---------------------------------------------------------------------------
# _default_client_factory — subagent default
# ---------------------------------------------------------------------------


def test_default_client_factory_enables_subagent_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scheduled jobs must run with subagent delegation enabled so heavy
    research/report tasks can be offloaded via the ``task`` tool without
    polluting the lead agent's context (see ``executor.py`` docstring)."""
    captured: dict[str, Any] = {}

    class _FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    import deerflow.client as client_mod

    monkeypatch.setattr(client_mod, "DeerFlowClient", _FakeClient)

    from app.scheduled_jobs.executor import _default_client_factory

    _default_client_factory(agent_name="analyst")

    assert captured.get("subagent_enabled") is True
    assert captured.get("agent_name") == "analyst"


def test_default_client_factory_respects_explicit_subagent_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit ``subagent_enabled`` in kwargs wins over the default —
    escape hatch for future per-job control."""
    captured: dict[str, Any] = {}

    class _FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    import deerflow.client as client_mod

    monkeypatch.setattr(client_mod, "DeerFlowClient", _FakeClient)

    from app.scheduled_jobs.executor import _default_client_factory

    _default_client_factory(agent_name=None, subagent_enabled=False)

    assert captured.get("subagent_enabled") is False
