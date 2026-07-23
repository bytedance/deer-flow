"""Contract tests for ``deerflow.subagents.status_contract``."""

from __future__ import annotations

import json
from pathlib import Path

from deerflow.subagents.status_contract import (
    SUBAGENT_ERROR_KEY,
    SUBAGENT_METADATA_TEXT_MAX_CHARS,
    SUBAGENT_MODEL_NAME_KEY,
    SUBAGENT_RESULT_BRIEF_KEY,
    SUBAGENT_RESULT_SHA256_KEY,
    SUBAGENT_STATUS_KEY,
    SUBAGENT_STATUS_VALUES,
    SUBAGENT_STOP_REASON_KEY,
    SUBAGENT_STOP_REASON_VALUES,
    SUBAGENT_TOKEN_USAGE_KEY,
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


def test_stop_reason_values_match_contract():
    """Backend stop_reason vocabulary stays aligned with the contract document (#3875 Phase 2)."""
    contract = _load_contract()
    assert set(SUBAGENT_STOP_REASON_VALUES) == set(contract["valid_stop_reason_values"])


def test_make_subagent_additional_kwargs_includes_status():
    kwargs = make_subagent_additional_kwargs("completed")
    assert kwargs == {SUBAGENT_STATUS_KEY: "completed"}


def test_make_subagent_additional_kwargs_carries_terminal_runtime_metadata():
    kwargs = make_subagent_additional_kwargs(
        "completed",
        result="done",
        model_name="claude-3-7-sonnet",
        token_usage={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
    )

    assert kwargs[SUBAGENT_MODEL_NAME_KEY] == "claude-3-7-sonnet"
    assert kwargs[SUBAGENT_TOKEN_USAGE_KEY] == {
        "input_tokens": 100,
        "output_tokens": 20,
        "total_tokens": 120,
    }


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


def test_make_subagent_additional_kwargs_stamps_stop_reason_when_present():
    """#3875 Phase 2: a capped run keeps a normal status and carries the cap
    on the additive ``subagent_stop_reason`` field. A token-capped run produced
    a final answer, so it is ``completed`` + ``token_capped`` and stays
    result-bearing (the partial work survives on ``result_brief``)."""
    kwargs = make_subagent_additional_kwargs("completed", result="investigated 3 of 5 sources", stop_reason="token_capped")
    assert kwargs[SUBAGENT_STATUS_KEY] == "completed"
    assert kwargs[SUBAGENT_RESULT_BRIEF_KEY] == "investigated 3 of 5 sources"
    assert len(kwargs[SUBAGENT_RESULT_SHA256_KEY]) == 64
    assert kwargs[SUBAGENT_STOP_REASON_KEY] == "token_capped"
    # A clean completed run (no cap) does not carry the field at all.
    assert SUBAGENT_STOP_REASON_KEY not in make_subagent_additional_kwargs("completed", result="done")


def test_format_subagent_result_message_completed_with_stop_reason_notes_the_cap():
    """The model-visible text folds a ``(capped: ...)`` note in so the lead can
    tell a budget-capped completion from a clean one without parsing metadata."""
    content, metadata_error = format_subagent_result_message("completed", result="investigated 3 of 5 sources", stop_reason="token_capped")
    assert content.startswith("Task Succeeded (capped: token budget)")
    assert "investigated 3 of 5 sources" in content
    # completed suppresses the error blob; the cap lives on stop_reason only.
    assert metadata_error is None


def test_format_subagent_result_message_failed_with_stop_reason_notes_the_cap():
    """A turn-capped run with no usable output is ``failed`` + ``turn_capped``;
    the cap note distinguishes "out of budget" from a broken subagent."""
    content, metadata_error = format_subagent_result_message("failed", error="Reached max_turns=10", stop_reason="turn_capped")
    assert content.startswith("Task failed (capped: turn budget)")
    assert metadata_error == "Reached max_turns=10"


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


def test_read_subagent_result_metadata_reads_stop_reason_for_capped_run():
    """A capped run's reader surfaces the additive ``stop_reason`` alongside
    the normal status/result fields so the delegation ledger and frontend can
    show "capped" without parsing result text (#3875 Phase 2)."""
    parsed = read_subagent_result_metadata(
        {
            SUBAGENT_STATUS_KEY: "completed",
            SUBAGENT_RESULT_BRIEF_KEY: "investigated 3 of 5 sources",
            SUBAGENT_RESULT_SHA256_KEY: "a" * 64,
            SUBAGENT_STOP_REASON_KEY: "turn_capped",
        }
    )
    assert parsed == {
        "status": "completed",
        "result_brief": "investigated 3 of 5 sources",
        "result_sha256": "a" * 64,
        "stop_reason": "turn_capped",
    }


def test_read_subagent_result_metadata_normalizes_legacy_max_turns_reached():
    """Phase 1 (#3949) wrote ``max_turns_reached`` into checkpointed thread
    history; Phase 2 (#3980) stopped producing it. The reader normalizes the
    legacy value so old delegations still resolve terminally instead of
    stranding as ``in_progress`` in the durable ledger — partial ``result_brief``
    preserved as ``completed + turn_capped`` (Phase 1 was result-bearing), or
    ``failed + turn_capped`` when no result survived."""
    # With a recovered partial -> completed + turn_capped, partial preserved.
    parsed = read_subagent_result_metadata(
        {
            SUBAGENT_STATUS_KEY: "max_turns_reached",
            SUBAGENT_RESULT_BRIEF_KEY: "investigated 3 of 5 sources",
            SUBAGENT_RESULT_SHA256_KEY: "a" * 64,
            SUBAGENT_ERROR_KEY: "Reached max_turns=150",
        }
    )
    assert parsed == {
        "status": "completed",
        "result_brief": "investigated 3 of 5 sources",
        "result_sha256": "a" * 64,
        "stop_reason": "turn_capped",
    }

    # No usable result -> failed + turn_capped (terminal, not in_progress).
    parsed_no_result = read_subagent_result_metadata(
        {
            SUBAGENT_STATUS_KEY: "max_turns_reached",
            SUBAGENT_ERROR_KEY: "Reached max_turns=150",
        }
    )
    assert parsed_no_result == {
        "status": "failed",
        "error": "Reached max_turns=150",
        "stop_reason": "turn_capped",
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


def test_make_subagent_additional_kwargs_rejects_unknown_stop_reason():
    import pytest

    with pytest.raises(ValueError, match="invalid subagent stop_reason"):
        make_subagent_additional_kwargs("completed", stop_reason="garbage")  # type: ignore[arg-type]
