"""Contract tests for the chat goal state the web UI reads.

The chat goal bar translates stand-down codes, recognizes host-written reasons
and reads ``goal_outcome`` from the history head, so the backend must keep
producing exactly what ``contracts/thread_goal_contract.json`` lists.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import get_args, get_type_hints
from unittest.mock import AsyncMock

import pytest
from _router_auth_helpers import call_unwrapped
from fastapi import BackgroundTasks
from langchain_core.messages import HumanMessage

from app.gateway.routers import threads
from app.gateway.services import SERVER_OWNED_STATE_CHANNELS
from deerflow.agents.goal_state import GoalOutcomeState
from deerflow.agents.thread_state import ThreadState
from deerflow.persistence.scheduled_task_runs import finalization
from deerflow.runtime import goal
from deerflow.runtime.runs import worker

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONTRACT = json.loads((_REPO_ROOT / "contracts" / "thread_goal_contract.json").read_text(encoding="utf-8"))
_MET = {"satisfied": True, "blocker": "none", "reason": "The report is complete."}


def test_stand_down_reason_codes_match_the_worker():
    unmet = {"satisfied": False, "blocker": "goal_not_met_yet", "reason": ""}
    # goal_not_met_yet never stands down by itself; the caps below decide it.
    blocked = {worker._stand_down_reason({}, {**unmet, "blocker": blocker}, 0) for blocker in goal.GOAL_BLOCKERS - {"none"}} - {None}
    caps = {
        worker._stand_down_reason({"continuation_count": goal.DEFAULT_MAX_GOAL_CONTINUATIONS}, unmet, 0),
        worker._stand_down_reason({"continuation_count": 0}, unmet, goal.DEFAULT_MAX_NO_PROGRESS_CONTINUATIONS),
    }
    literals = set(re.findall(r'stand_down_reason\s*=\s*"([a-z_:]+)"', Path(worker.__file__).read_text(encoding="utf-8")))
    assert literals, "pattern no longer matches worker.py; update this test"
    assert set(_CONTRACT["stand_down_reason_codes"]) == blocked | caps | literals


def test_check_failure_codes_match_the_scheduled_tasks_page():
    assert tuple(_CONTRACT["check_failure_codes"]) == finalization.CHECK_FAILURE_CODES
    assert set(_CONTRACT["check_failure_codes"]) <= set(_CONTRACT["stand_down_reason_codes"])


def test_goal_outcome_shape_matches_the_state_type_and_its_builder():
    contract = _CONTRACT["goal_outcome"]
    hints = get_type_hints(GoalOutcomeState)
    record = goal.build_goal_outcome(goal.build_goal_state("Ship it"), _MET, reply_message_id="ai-1")

    assert contract["channel"] == goal.GOAL_OUTCOME_CHANNEL
    assert contract["channel"] in get_type_hints(ThreadState)
    assert contract["channel"] in SERVER_OWNED_STATE_CHANNELS
    assert list(hints) == list(record) == contract["keys"]
    assert list(get_args(hints["status"])) == contract["statuses"]
    assert record["status"] in contract["statuses"]


def test_host_reason_texts_are_the_reasons_the_host_writes():
    pattern = r'GoalEvaluation\(\s*satisfied=False,\s*blocker="[a-z_]+",\s*reason="([^"]+)"'
    texts = {text for module in (goal, worker) for text in re.findall(pattern, Path(module.__file__).read_text(encoding="utf-8"))}
    assert texts, "pattern no longer matches goal.py/worker.py; update this test"
    assert set(_CONTRACT["host_reason_texts"]) == texts


@pytest.mark.asyncio
async def test_history_head_carries_exactly_the_contract_keys(monkeypatch):
    active = goal.build_goal_state("Ship it")
    values = {
        "title": "Report",
        "thread_data": {"workspace_path": "/synthetic/workspace"},
        "messages": [HumanMessage(id="h1", content="Ship it")],
        # Server writers never leave both set; the projection must still carry each.
        "goal": active,
        "goal_outcome": goal.build_goal_outcome(active, _MET, reply_message_id=None),
        "todos": [{"content": "write tests", "status": "pending"}],
        "artifacts": ["/mnt/user-data/outputs/report.md"],
    }
    snapshots = [SimpleNamespace(values=values, config={"configurable": {"checkpoint_id": checkpoint_id}}, parent_config=None, metadata={}, next=(), created_at=None) for checkpoint_id in ("head", "older")]
    accessor = SimpleNamespace(ahistory=AsyncMock(return_value=snapshots))
    monkeypatch.setattr(threads, "get_checkpointer", lambda _request: None)
    monkeypatch.setattr(threads, "build_thread_checkpoint_state_accessor", AsyncMock(return_value=(accessor, {})))

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    entries = await call_unwrapped(threads.get_thread_history, thread_id="contract-thread", body=threads.ThreadHistoryRequest(limit=2), request=request, background_tasks=BackgroundTasks())

    head, older = (entry.model_dump(mode="json")["values"] for entry in entries)
    assert set(head) == set(_CONTRACT["history_head_keys"])
    assert set(older) == {"title", "thread_data"}
