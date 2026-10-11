"""Gateway orphan recovery invokes the same guarded scheduled-goal cleanup."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.gateway import deps


@pytest.mark.anyio
async def test_recovery_cleanup_only_considers_scheduled_goals():
    manager, checkpointer = object(), object()
    records = [SimpleNamespace(run_id="ordinary", metadata={}), SimpleNamespace(run_id="scheduled", metadata={"scheduled_goal_objective": "report exists"})]
    with patch("deerflow.runtime.runs.worker.clear_recovered_scheduled_goal", new=AsyncMock()) as clear:
        await deps._cleanup_recovered_scheduled_goals(records, run_manager=manager, checkpointer=checkpointer)
    clear.assert_awaited_once_with(records[1], run_manager=manager, checkpointer=checkpointer)


@pytest.mark.anyio
async def test_recovery_cleanup_failure_does_not_skip_other_orphans():
    records = [SimpleNamespace(run_id="one", metadata={"scheduled_goal_objective": "one"}), SimpleNamespace(run_id="two", metadata={"scheduled_goal_objective": "two"})]
    with patch("deerflow.runtime.runs.worker.clear_recovered_scheduled_goal", new=AsyncMock(side_effect=[RuntimeError("checkpoint unavailable"), None])) as clear:
        await deps._cleanup_recovered_scheduled_goals(records, run_manager=object(), checkpointer=object())
    assert clear.await_count == 2
