"""Every coded scheduled-task error is listed in the cross-language contract."""

import json
import re
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.gateway import scheduled_task_access, scheduled_task_errors, scheduled_task_validation
from app.gateway.routers import scheduled_tasks
from app.gateway.scheduled_task_errors import SCHEDULER_AGENT_ERROR_CODES, SCHEDULER_UI_ERROR_CODES, scheduler_error, tool_error_payload

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONTRACT = json.loads((_REPO_ROOT / "contracts" / "scheduled_task_errors_contract.json").read_text(encoding="utf-8"))
_RAISE = re.compile(r'scheduler_error\(\s*\d+,\s*"([a-z_]+)"')


def test_contract_sets_match_the_backend_and_are_disjoint():
    assert _CONTRACT["version"] == 1
    assert set(_CONTRACT["ui_codes"]) == SCHEDULER_UI_ERROR_CODES
    assert set(_CONTRACT["agent_only_codes"]) == SCHEDULER_AGENT_ERROR_CODES
    assert SCHEDULER_UI_ERROR_CODES.isdisjoint(SCHEDULER_AGENT_ERROR_CODES)
    assert len(_CONTRACT["ui_codes"]) == len(set(_CONTRACT["ui_codes"]))


@pytest.mark.parametrize("module", [scheduled_tasks, scheduled_task_validation, scheduled_task_access, scheduled_task_errors])
def test_every_raised_code_is_in_the_contract(module):
    source = Path(module.__file__).read_text(encoding="utf-8")
    raised = set(_RAISE.findall(source))
    assert raised, f"pattern no longer matches {module.__name__}; update this test"
    assert raised <= SCHEDULER_UI_ERROR_CODES | SCHEDULER_AGENT_ERROR_CODES


def test_no_plain_string_http_exceptions_remain_in_scheduled_task_code():
    for module in (scheduled_tasks, scheduled_task_validation, scheduled_task_access):
        assert "HTTPException(status_code=" not in Path(module.__file__).read_text(encoding="utf-8"), module.__name__


def test_error_shape_and_tool_payload():
    error = scheduler_error(409, "limits_exhausted", "All 5 automatic runs are used.", limit="max_runs", used=5)
    assert error.status_code == 409
    assert error.detail == {"code": "limits_exhausted", "message": "All 5 automatic runs are used.", "params": {"limit": "max_runs", "used": 5}}
    assert scheduler_error(404, "task_not_found", "Scheduled task not found").detail == {"code": "task_not_found", "message": "Scheduled task not found"}
    assert tool_error_payload(error) == {"error": "All 5 automatic runs are used.", "code": "limits_exhausted", "status_code": 409, "params": {"limit": "max_runs", "used": 5}}
    assert tool_error_payload(HTTPException(503, "Scheduled task repo not available")) == {"error": "Scheduled task repo not available", "code": "error", "status_code": 503}
