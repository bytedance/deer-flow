"""Contract tests for host-written scheduled goal strings.

The tasks page (``frontend/src/core/scheduled-tasks/goal-outcome.ts``) and the
IM notice renderer translate these values instead of showing them raw, so the
backend must keep producing exactly what ``contracts/scheduled_goal_notes_contract.json``
lists.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.scheduler.notification_delivery import render_notification_text
from deerflow.persistence.scheduled_task_runs import finalization
from deerflow.runtime.goal import DEFAULT_MAX_GOAL_CONTINUATIONS, DEFAULT_MAX_NO_PROGRESS_CONTINUATIONS, GOAL_BLOCKERS
from deerflow.runtime.runs import worker

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONTRACT = json.loads((_REPO_ROOT / "contracts" / "scheduled_goal_notes_contract.json").read_text(encoding="utf-8"))
_CODES = set(_CONTRACT["unmet_reason_codes"])


def test_last_error_strings_match_contract():
    assert finalization.AGENT_STOP_LAST_ERROR_PREFIX == _CONTRACT["agent_stop_last_error_prefix"]
    assert finalization.AUTO_PAUSE_LAST_ERROR == _CONTRACT["auto_pause_last_error"]


def test_blocker_stand_down_codes_are_in_contract():
    # An unsatisfied verdict never carries the "none" blocker.
    assert {f"blocked:{blocker}" for blocker in GOAL_BLOCKERS - {"none"}} <= _CODES


def test_cap_stand_down_reasons_are_in_contract():
    evaluation = {"satisfied": False, "blocker": "goal_not_met_yet", "reason": ""}
    at_cap = {"continuation_count": DEFAULT_MAX_GOAL_CONTINUATIONS}
    assert worker._stand_down_reason(at_cap, evaluation, 0) in _CODES
    assert worker._stand_down_reason({"continuation_count": 0}, evaluation, DEFAULT_MAX_NO_PROGRESS_CONTINUATIONS) in _CODES


def test_literal_stand_down_reasons_and_no_verdict_are_in_contract():
    source = Path(worker.__file__).read_text(encoding="utf-8")
    literals = set(re.findall(r'stand_down_reason\s*=\s*"([a-z_:]+)"', source))
    assert literals, "pattern no longer matches worker.py; update this test"
    assert literals <= _CODES
    assert '"no_verdict"' in Path(finalization.__file__).read_text(encoding="utf-8")
    assert "no_verdict" in _CODES


@pytest.mark.parametrize("code", sorted(_CODES))
def test_im_notice_translates_every_contract_code(code):
    text = render_notification_text({"event": "run_unmet", "task_id": "task-a", "payload": {"reason_code": code}})
    assert "Reason: unknown." not in text
    assert code not in text
