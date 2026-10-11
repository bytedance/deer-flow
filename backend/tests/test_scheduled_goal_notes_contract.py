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
@pytest.mark.parametrize(("locale", "unknown"), [("en-US", "no reason was recorded"), ("zh-CN", "没有记录原因")])
def test_im_notice_translates_every_contract_code(code, locale, unknown):
    text = render_notification_text({"event": "run_unmet", "task_id": "task-a", "payload": {"reason_code": code, "locale": locale}})
    assert unknown not in text
    assert code not in text


def test_contract_version_three_keeps_version_two_keys():
    assert _CONTRACT["version"] == 3
    assert _CONTRACT["scheduled_origin_key"] == "deerflow_scheduled_origin"
    assert {"agent_stop_last_error_prefix", "auto_pause_last_error", "unmet_reason_codes", "check_failure_codes", "host_run_errors"} <= set(_CONTRACT)


def test_lifecycle_vocabulary_matches_finalization_constants():
    assert tuple(_CONTRACT["lifecycle_events"]) == finalization.LIFECYCLE_EVENTS
    assert {event: tuple(reasons) for event, reasons in _CONTRACT["lifecycle_reasons"].items()} == finalization.LIFECYCLE_REASONS
    assert set(_CONTRACT["lifecycle_reasons"]) == set(_CONTRACT["lifecycle_events"])
    assert tuple(_CONTRACT["notification_events"]) == finalization.NOTIFICATION_EVENTS
    # The existing outbox name of the automatic pause is kept, so queued rows stay valid.
    assert "task_paused" in _CONTRACT["notification_events"]
    assert set(finalization.RUN_EVENT_BY_STATUS.values()) <= set(_CONTRACT["notification_events"])


def test_scheduled_origin_key_matches_the_gateway_constant():
    from app.gateway.services import SCHEDULED_ORIGIN_KEY

    assert _CONTRACT["scheduled_origin_key"] == SCHEDULED_ORIGIN_KEY


def test_check_failure_codes_match_finalization_and_are_unmet_reasons():
    assert tuple(_CONTRACT["check_failure_codes"]) == finalization.CHECK_FAILURE_CODES
    assert set(_CONTRACT["check_failure_codes"]) <= _CODES


def test_host_run_errors_match_the_host_note_constants():
    from deerflow.scheduler import host_notes

    assert _CONTRACT["host_run_errors"] == {
        "restarted": host_notes.RUN_ERROR_RESTARTED,
        "lease_lost": host_notes.RUN_ERROR_LEASE_LOST,
        "queue_timeout": host_notes.RUN_ERROR_QUEUE_TIMEOUT,
        "paused_while_queued": host_notes.RUN_ERROR_PAUSED_WHILE_QUEUED,
        "deleted_while_queued": host_notes.RUN_ERROR_DELETED_WHILE_QUEUED,
        "end_reached": host_notes.RUN_ERROR_END_REACHED,
        "interrupted": host_notes.RUN_ERROR_INTERRUPTED,
    }


@pytest.mark.parametrize(
    ("last_error", "expected"),
    [
        (f"{finalization.AGENT_STOP_LAST_ERROR_PREFIX}run-1", True),
        (finalization.AUTO_PAUSE_LAST_ERROR, True),
        (finalization.AGENT_STOP_LAST_ERROR_PREFIX, False),
        (f"{finalization.AGENT_STOP_LAST_ERROR_PREFIX} run-1", False),
        ("boom", False),
        (None, False),
    ],
)
def test_host_pause_marker_recognizes_only_host_pauses(last_error, expected):
    assert finalization.is_host_pause_marker(last_error) is expected
