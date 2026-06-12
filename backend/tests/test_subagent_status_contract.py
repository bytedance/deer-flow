"""Contract tests for ``deerflow.subagents.status_contract``.

Bytedance/deer-flow issue #3146: the backend stamps
``ToolMessage.additional_kwargs.subagent_status`` so the frontend can read
the subagent state from a structured field instead of parsing the result
text. The mapping from "task tool result text" to status is shared with the
frontend through the cross-language fixture file
``contracts/subagent_status_contract.json``.

These tests pin the backend implementation against that fixture so any
edit on either side surfaces immediately as a test failure.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deerflow.subagents.status_contract import (
    SUBAGENT_ERROR_KEY,
    SUBAGENT_STATUS_KEY,
    SUBAGENT_STATUS_VALUES,
    extract_subagent_status,
    make_subagent_additional_kwargs,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONTRACT_PATH = _REPO_ROOT / "contracts" / "subagent_status_contract.json"


def _load_contract() -> dict:
    return json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))


def test_contract_file_exists():
    assert _CONTRACT_PATH.is_file(), f"missing shared fixture: {_CONTRACT_PATH}"


def test_status_values_match_contract():
    """Backend status enum stays aligned with the contract document."""
    contract = _load_contract()
    assert set(SUBAGENT_STATUS_VALUES) == set(contract["valid_status_values"])


@pytest.mark.parametrize("case", _load_contract()["cases"], ids=lambda c: c["name"])
def test_extract_subagent_status_matches_contract(case):
    """Every fixture case maps through ``extract_subagent_status`` to the
    expected status — covers task_tool's 5 normal returns, the 3
    pre-execution ``Error:`` returns, the middleware-wrapped exception
    case, whitespace handling, and the streaming chunk that must stay
    unrecognised.
    """
    status = extract_subagent_status(case["content"])
    assert status == case["expected_status"], f"case {case['name']!r}: expected {case['expected_status']!r}, got {status!r}"


def test_make_subagent_additional_kwargs_includes_status():
    kwargs = make_subagent_additional_kwargs("completed")
    assert kwargs == {SUBAGENT_STATUS_KEY: "completed"}


def test_make_subagent_additional_kwargs_includes_error_when_present():
    kwargs = make_subagent_additional_kwargs("failed", error="boom")
    assert kwargs == {SUBAGENT_STATUS_KEY: "failed", SUBAGENT_ERROR_KEY: "boom"}


def test_make_subagent_additional_kwargs_omits_blank_error():
    """Empty / whitespace error must not leak as ``subagent_error: ""``."""
    assert make_subagent_additional_kwargs("failed", error="") == {SUBAGENT_STATUS_KEY: "failed"}
    assert make_subagent_additional_kwargs("failed", error="   ") == {SUBAGENT_STATUS_KEY: "failed"}
    assert make_subagent_additional_kwargs("failed", error=None) == {SUBAGENT_STATUS_KEY: "failed"}


def test_make_subagent_additional_kwargs_rejects_unknown_status():
    with pytest.raises(ValueError, match="invalid subagent status"):
        make_subagent_additional_kwargs("garbage")  # type: ignore[arg-type]
