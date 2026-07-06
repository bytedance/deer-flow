"""Contract tests for ``deerflow.subagents.status_contract``."""

from __future__ import annotations

import json
from pathlib import Path

from deerflow.subagents.status_contract import (
    SUBAGENT_ERROR_KEY,
    SUBAGENT_METADATA_TEXT_MAX_CHARS,
    SUBAGENT_RESULT_BRIEF_KEY,
    SUBAGENT_RESULT_SHA256_KEY,
    SUBAGENT_STATUS_KEY,
    SUBAGENT_STATUS_VALUES,
    _bound_metadata_text,
    format_subagent_result_message,
    make_subagent_additional_kwargs,
    read_subagent_result_metadata,
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


def test_make_subagent_additional_kwargs_includes_status():
    kwargs = make_subagent_additional_kwargs("completed")
    assert kwargs == {SUBAGENT_STATUS_KEY: "completed"}


def test_make_subagent_additional_kwargs_includes_error_when_present():
    kwargs = make_subagent_additional_kwargs("failed", error="boom")
    assert kwargs == {SUBAGENT_STATUS_KEY: "failed", SUBAGENT_ERROR_KEY: "boom"}


def test_make_subagent_additional_kwargs_includes_bounded_result_metadata():
    kwargs = make_subagent_additional_kwargs("completed", result="done")
    assert kwargs[SUBAGENT_STATUS_KEY] == "completed"
    assert kwargs[SUBAGENT_RESULT_BRIEF_KEY] == "done"
    assert len(kwargs[SUBAGENT_RESULT_SHA256_KEY]) == 64
    assert SUBAGENT_ERROR_KEY not in kwargs


def test_make_subagent_additional_kwargs_bounds_large_result_metadata():
    huge = "x" * (SUBAGENT_METADATA_TEXT_MAX_CHARS + 5000)
    kwargs = make_subagent_additional_kwargs("completed", result=huge)
    assert len(kwargs[SUBAGENT_RESULT_BRIEF_KEY]) <= SUBAGENT_METADATA_TEXT_MAX_CHARS
    assert kwargs[SUBAGENT_RESULT_BRIEF_KEY] != huge
    assert len(kwargs[SUBAGENT_RESULT_SHA256_KEY]) == 64


def test_make_subagent_additional_kwargs_max_turns_reached_carries_result_and_error():
    """#3875 Phase 2: a turn-capped run is result-bearing — the partial work
    the executor recovered must travel on ``subagent_result_brief`` / ``sha256``
    (so the delegation ledger and card keep it) AND the cap notice must travel
    on ``subagent_error``. This is the one status that carries both."""
    kwargs = make_subagent_additional_kwargs("max_turns_reached", result="investigated 3 of 5 sources", error="Reached max_turns=150")
    assert kwargs[SUBAGENT_STATUS_KEY] == "max_turns_reached"
    assert kwargs[SUBAGENT_RESULT_BRIEF_KEY] == "investigated 3 of 5 sources"
    assert len(kwargs[SUBAGENT_RESULT_SHA256_KEY]) == 64
    assert kwargs[SUBAGENT_ERROR_KEY] == "Reached max_turns=150"


def test_format_subagent_result_message_max_turns_reached_leads_with_partial_result():
    """The model-visible text leads with the recovered partial result and
    names the cap; the metadata error carries the cap reason only."""
    content, metadata_error = format_subagent_result_message("max_turns_reached", result="investigated 3 of 5 sources", error="Reached max_turns=150")
    assert content.startswith("Task reached max turns")
    assert "investigated 3 of 5 sources" in content
    assert metadata_error == "Reached max_turns=150"


def test_format_subagent_result_message_max_turns_reached_uses_sentinel_when_no_partial():
    content, _metadata_error = format_subagent_result_message("max_turns_reached", result=None, error="Reached max_turns=150")
    assert "No partial result was produced" in content


def test_bound_metadata_text_respects_small_caps():
    text = "A" * 100

    assert _bound_metadata_text(text, cap=0) == ""
    assert _bound_metadata_text(text, cap=1) == "A"
    assert len(_bound_metadata_text(text, cap=15)) <= 15


def test_make_subagent_additional_kwargs_omits_blank_error():
    """Empty / whitespace error must not leak as ``subagent_error: ""``."""
    assert make_subagent_additional_kwargs("failed", error="") == {SUBAGENT_STATUS_KEY: "failed"}
    assert make_subagent_additional_kwargs("failed", error="   ") == {SUBAGENT_STATUS_KEY: "failed"}
    assert make_subagent_additional_kwargs("failed", error=None) == {SUBAGENT_STATUS_KEY: "failed"}


def test_make_subagent_additional_kwargs_bounds_large_error_metadata():
    huge = "boom " * 2000
    kwargs = make_subagent_additional_kwargs("failed", error=huge)
    assert kwargs[SUBAGENT_STATUS_KEY] == "failed"
    assert len(kwargs[SUBAGENT_ERROR_KEY]) <= SUBAGENT_METADATA_TEXT_MAX_CHARS
    assert SUBAGENT_RESULT_BRIEF_KEY not in kwargs


def test_read_subagent_result_metadata_returns_bounded_payload():
    parsed = read_subagent_result_metadata(
        {
            SUBAGENT_STATUS_KEY: "completed",
            SUBAGENT_RESULT_BRIEF_KEY: "structured",
            SUBAGENT_RESULT_SHA256_KEY: "a" * 64,
            SUBAGENT_ERROR_KEY: "ignored",
        }
    )
    assert parsed == {
        "status": "completed",
        "result_brief": "structured",
        "result_sha256": "a" * 64,
    }


def test_read_subagent_result_metadata_max_turns_reached_reads_result_brief_and_error():
    """A turn-capped result carries both result metadata and the cap error;
    the reader must surface both so the delegation ledger can prefer the
    partial result and still expose the cap reason."""
    parsed = read_subagent_result_metadata(
        {
            SUBAGENT_STATUS_KEY: "max_turns_reached",
            SUBAGENT_RESULT_BRIEF_KEY: "investigated 3 of 5 sources",
            SUBAGENT_RESULT_SHA256_KEY: "a" * 64,
            SUBAGENT_ERROR_KEY: "Reached max_turns=150",
        }
    )
    assert parsed == {
        "status": "max_turns_reached",
        "result_brief": "investigated 3 of 5 sources",
        "result_sha256": "a" * 64,
        "error": "Reached max_turns=150",
    }


def test_read_subagent_result_metadata_rejects_unknown_status():
    assert read_subagent_result_metadata({SUBAGENT_STATUS_KEY: "future"}) is None


def test_read_subagent_result_metadata_rejects_non_hex_sha256():
    """A 64-char value that is not a lowercase hex digest must be dropped."""
    base = {SUBAGENT_STATUS_KEY: "completed", SUBAGENT_RESULT_BRIEF_KEY: "structured"}
    for bad_hash in ("z" * 64, "A" * 64, "a" * 63, "a" * 65, ("a" * 63) + " "):
        parsed = read_subagent_result_metadata({**base, SUBAGENT_RESULT_SHA256_KEY: bad_hash})
        assert parsed == {"status": "completed", "result_brief": "structured"}, bad_hash


def test_make_subagent_additional_kwargs_rejects_unknown_status():
    import pytest

    with pytest.raises(ValueError, match="invalid subagent status"):
        make_subagent_additional_kwargs("garbage")  # type: ignore[arg-type]
