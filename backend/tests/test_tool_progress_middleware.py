"""Tests for ToolProgressMiddleware state machine (RFC #3177)."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.types import Command

from deerflow.agents.middlewares.tool_progress_middleware import (
    ToolProgressMiddleware,
    is_near_duplicate,
    word_set,
)
from deerflow.agents.middlewares.tool_result_meta import TOOL_META_KEY

# ---------------------------------------------------------------------------
# Helpers


def _make_runtime(thread_id: str = "t1", run_id: str = "r1") -> MagicMock:
    rt = MagicMock()
    rt.context = {"thread_id": thread_id, "run_id": run_id}
    return rt


def _make_tool_request(tool_name: str = "web_search", *, runtime: MagicMock | None = None) -> SimpleNamespace:
    rt = runtime or _make_runtime()
    return SimpleNamespace(
        tool_call={"name": tool_name, "id": f"tc-{tool_name}"},
        runtime=rt,
    )


def _meta_kwargs(
    *,
    status: str = "success",
    error_type: str | None = None,
    recoverable_by_model: bool = True,
    recommended_next_action: str = "continue",
    source: str = "content_analysis",
) -> dict[str, object]:
    return {
        TOOL_META_KEY: {
            "status": status,
            "error_type": error_type,
            "recoverable_by_model": recoverable_by_model,
            "recommended_next_action": recommended_next_action,
            "source": source,
        }
    }


def _make_tool_message(
    content: str = "A" * 200,
    *,
    tool_name: str = "web_search",
    meta_kwargs: dict[str, object] | None = None,
) -> ToolMessage:
    return ToolMessage(
        content=content,
        tool_call_id=f"tc-{tool_name}",
        name=tool_name,
        status="success",
        additional_kwargs=meta_kwargs or _meta_kwargs(),
    )


def _make_non_recoverable_error_message(
    content: str = "Error: rate limited",
    *,
    tool_name: str = "web_search",
    error_type: str = "rate_limited",
    recommended_next_action: str = "summarize",
) -> ToolMessage:
    """Non-recoverable stagnation error (recoverable_by_model=False, non-stop).
    Unlike auth/config, these go through the stagnation counter, but should
    still reach BLOCKED because the model cannot fix them by retrying.
    """
    return ToolMessage(
        content=content,
        tool_call_id=f"tc-{tool_name}",
        name=tool_name,
        status="error",
        additional_kwargs=_meta_kwargs(
            status="error",
            error_type=error_type,
            recoverable_by_model=False,
            recommended_next_action=recommended_next_action,
        ),
    )


def _make_error_message(
    content: str = "Error: no results found",
    *,
    tool_name: str = "web_search",
    error_type: str = "no_results",
    recoverable_by_model: bool = True,
    recommended_next_action: str = "rewrite_query",
) -> ToolMessage:
    return ToolMessage(
        content=content,
        tool_call_id=f"tc-{tool_name}",
        name=tool_name,
        status="error",
        additional_kwargs=_meta_kwargs(
            status="error",
            error_type=error_type,
            recoverable_by_model=recoverable_by_model,
            recommended_next_action=recommended_next_action,
        ),
    )


def _make_model_request(messages: list, runtime: MagicMock) -> MagicMock:
    req = MagicMock()
    req.messages = list(messages)
    req.runtime = runtime

    def _override(**kw) -> MagicMock:
        updated = MagicMock()
        updated.messages = kw.get("messages", req.messages)
        updated.runtime = runtime
        updated.override = req.override
        return updated

    req.override = _override
    return req


def _make_mw(**kwargs) -> ToolProgressMiddleware:
    defaults = {
        "stagnation_threshold": 3,
        "warn_escalation_count": 2,
        "inject_assessment": True,
        "jaccard_threshold": 0.8,
        "min_words": 5,
    }
    defaults.update(kwargs)
    return ToolProgressMiddleware(**defaults)


# ---------------------------------------------------------------------------
# Unit tests: word_set and is_near_duplicate


def test_word_set_extracts_words_ge_3():
    ws = word_set("go quick brown fox")
    assert "go" not in ws
    assert "quick" in ws
    assert "brown" in ws
    assert "fox" in ws


def test_is_near_duplicate_above_threshold():
    ws1 = frozenset("quick brown fox jumps over lazy dog".split())
    ws2 = frozenset("quick brown fox jumps over lazy dog".split())
    assert is_near_duplicate(ws2, [ws1], threshold=0.8, min_words=5)


def test_is_near_duplicate_near_threshold():
    # ws1 has 8 words; ws2 shares 7 of them and adds 1 new word.
    # intersection=7, union=9  →  Jaccard = 7/9 ≈ 0.778 < 0.8 → NOT duplicate.
    # ws3 shares all 8 original words and adds 1 new word.
    # intersection=8, union=9  →  Jaccard = 8/9 ≈ 0.889 >= 0.8 → IS duplicate.
    base = frozenset("alpha bravo charlie delta echo foxtrot golf hotel".split())
    nearly_below = frozenset("alpha bravo charlie delta echo foxtrot golf india".split())  # 7/9 ≈ 0.778
    nearly_above = frozenset("alpha bravo charlie delta echo foxtrot golf hotel india".split())  # 8/9 ≈ 0.889
    assert not is_near_duplicate(nearly_below, [base], threshold=0.8, min_words=5)
    assert is_near_duplicate(nearly_above, [base], threshold=0.8, min_words=5)


def test_is_near_duplicate_below_threshold():
    ws1 = frozenset("apple banana cherry delta echo".split())
    ws2 = frozenset("xray yankee zulu alpha bravo".split())
    assert not is_near_duplicate(ws2, [ws1], threshold=0.8, min_words=5)


def test_is_near_duplicate_too_short_skips_check():
    ws1 = frozenset("apple".split())
    ws2 = frozenset("apple".split())
    # min_words=5 but len==1, so not a duplicate
    assert not is_near_duplicate(ws2, [ws1], threshold=0.8, min_words=5)


# ---------------------------------------------------------------------------
# Scenario 1: Normal call → no hint, phase stays active


def test_normal_call_no_hint_phase_active():
    mw = _make_mw()
    rt = _make_runtime()
    req = _make_tool_request(runtime=rt)
    msg = _make_tool_message("A" * 300)

    def handler(_r):
        return msg

    result = mw.wrap_tool_call(req, handler)

    assert result is msg
    assert mw._phase_states["t1"]["web_search"].phase == "active"
    assert mw._phase_states["t1"]["web_search"].consecutive_problems == 0


# ---------------------------------------------------------------------------
# Scenario 2: consecutive no_results → hint injected, phase=warned


def test_repeated_no_results_reaches_warned():
    mw = _make_mw(stagnation_threshold=2)
    rt = _make_runtime()
    req = _make_tool_request(runtime=rt)
    error_msg = _make_error_message()

    def handler(_r):
        return error_msg

    # stagnation_threshold=2, so the second problem call tips into warned
    mw.wrap_tool_call(req, handler)
    mw.wrap_tool_call(req, handler)

    state = mw._phase_states["t1"]["web_search"]
    assert state.phase == "warned"
    assert state.consecutive_problems == 2

    # Hint should be queued
    hints = mw._drain_pending(rt)
    assert len(hints) == 1
    assert "PROGRESS HINT" in hints[0]


# ---------------------------------------------------------------------------
# Scenario 3: Non-recoverable errors escalate warned → blocked


def test_warned_to_blocked_after_escalation():
    mw = _make_mw(stagnation_threshold=2, warn_escalation_count=2)
    rt = _make_runtime()
    req = _make_tool_request(runtime=rt)
    # Non-recoverable error (rate_limited): model cannot fix this by retrying,
    # so stagnation should escalate to BLOCKED.
    error_msg = _make_non_recoverable_error_message()

    def handler(_r):
        return error_msg

    for _ in range(4):
        mw.wrap_tool_call(req, handler)

    state = mw._phase_states["t1"]["web_search"]
    assert state.phase == "blocked"
    assert state.block_reason is not None


# ---------------------------------------------------------------------------
# Scenario 4: Blocked tool is front-gate intercepted (handler NOT called)


def test_blocked_tool_is_intercepted_without_calling_handler():
    mw = _make_mw(stagnation_threshold=2, warn_escalation_count=1)
    rt = _make_runtime()
    req = _make_tool_request(runtime=rt)
    # Non-recoverable error: stagnation escalates to BLOCKED, handler is never called.
    error_msg = _make_non_recoverable_error_message()
    call_count = [0]

    def handler(r):
        call_count[0] += 1
        return error_msg

    # 2 calls → warned + 1 more = blocked
    for _ in range(3):
        mw.wrap_tool_call(req, handler)

    assert mw._phase_states["t1"]["web_search"].phase == "blocked"
    call_count_before = call_count[0]

    # Next call should be intercepted
    result = mw.wrap_tool_call(req, handler)

    assert call_count[0] == call_count_before
    assert isinstance(result, ToolMessage)
    assert "[TOOL_BLOCKED]" in result.content


# ---------------------------------------------------------------------------
# Scenario 4b: Recoverable errors never escalate to BLOCKED — WARNED is terminal


def test_recoverable_errors_stay_warned_indefinitely():
    # stagnation_threshold=2, warn_escalation_count=1 → would block at call 3 for
    # non-recoverable errors, but recoverable errors must stay in WARNED forever.
    mw = _make_mw(stagnation_threshold=2, warn_escalation_count=1)
    rt = _make_runtime()
    req = _make_tool_request(runtime=rt)
    error_msg = _make_error_message()  # recoverable_by_model=True

    def handler(_r):
        return error_msg

    # 10 calls — well past the threshold+escalation
    for _ in range(10):
        mw.wrap_tool_call(req, handler)

    state = mw._phase_states["t1"]["web_search"]
    assert state.phase == "warned", "recoverable errors must never escalate to BLOCKED"
    assert state.consecutive_problems == 10


def test_recoverable_error_re_injects_hint_past_escalation():
    # After crossing threshold+escalation for a recoverable error, each additional
    # problem call should still queue a hint.
    mw = _make_mw(stagnation_threshold=2, warn_escalation_count=1, inject_assessment=True)
    rt = _make_runtime()
    req = _make_tool_request(runtime=rt)
    error_msg = _make_error_message()

    def handler(_r):
        return error_msg

    # Reach warned (call 2) and past escalation (call 3+)
    for _ in range(4):
        mw.wrap_tool_call(req, handler)

    # All hints from call 2 onward should have been queued (capped at _MAX_PENDING_PER_RUN=3).
    # >= 2 proves that at least one hint was queued *inside* the escalation zone (calls 3+),
    # not just the initial WARNED hint at call 2.
    hints = mw._drain_pending(rt)
    assert len(hints) >= 2
    assert all("PROGRESS HINT" in h for h in hints)


# ---------------------------------------------------------------------------
# Scenario 5: Auth error → immediately blocked (no warned phase)


def test_auth_error_immediately_blocked():
    mw = _make_mw(stagnation_threshold=5)
    rt = _make_runtime()
    req = _make_tool_request(runtime=rt)
    auth_msg = _make_error_message(
        error_type="auth",
        recoverable_by_model=False,
        recommended_next_action="stop",
    )

    def handler(_r):
        return auth_msg

    mw.wrap_tool_call(req, handler)

    state = mw._phase_states["t1"]["web_search"]
    assert state.phase == "blocked"
    assert "auth" in state.block_reason.lower() or "Authentication" in state.block_reason
    # consecutive_problems must be 1 (not 0) even on immediate-block paths so diagnostic
    # logs and future consumers see a consistent non-zero count after a failed call.
    assert state.consecutive_problems == 1


# ---------------------------------------------------------------------------
# Scenario 6: Valid result after problems resets to active


def test_valid_result_after_problems_resets_to_active():
    mw = _make_mw(stagnation_threshold=3, warn_escalation_count=5)
    rt = _make_runtime()
    req = _make_tool_request(runtime=rt)
    error_msg = _make_error_message()
    good_msg = _make_tool_message("A" * 300)

    def handler_error(_r):
        return error_msg

    def handler_good(_r):
        return good_msg

    mw.wrap_tool_call(req, handler_error)
    mw.wrap_tool_call(req, handler_error)
    mw.wrap_tool_call(req, handler_error)

    state = mw._phase_states["t1"]["web_search"]
    assert state.phase == "warned"

    # Good result resets
    mw.wrap_tool_call(req, handler_good)

    state = mw._phase_states["t1"]["web_search"]
    assert state.phase == "active"
    assert state.consecutive_problems == 0


# ---------------------------------------------------------------------------
# Scenario 7: Two different tools have independent states


def test_two_tools_have_independent_states():
    mw = _make_mw(stagnation_threshold=2, warn_escalation_count=1)
    rt = _make_runtime()
    req_search = _make_tool_request("web_search", runtime=rt)
    req_read = _make_tool_request("read_file", runtime=rt)

    # Non-recoverable errors so web_search escalates to BLOCKED.
    error_search = _make_non_recoverable_error_message(tool_name="web_search")
    error_read = _make_error_message(tool_name="read_file")

    # Drive web_search to BLOCKED (2 → warned, 1 more → blocked)
    for _ in range(3):
        mw.wrap_tool_call(req_search, lambda r: error_search)

    assert mw._phase_states["t1"]["web_search"].phase == "blocked"

    # read_file should still be active — independent state per tool name
    mw.wrap_tool_call(req_read, lambda r: error_read)
    assert mw._phase_states["t1"]["read_file"].phase == "active"


# ---------------------------------------------------------------------------
# Scenario 8: Jaccard near-duplicate result counts as problem


def test_jaccard_near_duplicate_counts_as_problem():
    mw = _make_mw(stagnation_threshold=2, warn_escalation_count=5, jaccard_threshold=0.8, min_words=5)
    rt = _make_runtime()
    req = _make_tool_request(runtime=rt)

    # First call: good unique content (establishes baseline)
    words = "apple banana cherry delta echo foxtrot golf hotel india juliet"
    msg1 = _make_tool_message(words)
    mw.wrap_tool_call(req, lambda r: msg1)

    # Second call: exact same content (Jaccard = 1.0) → near-duplicate → problem count goes up
    msg2 = _make_tool_message(words)
    mw.wrap_tool_call(req, lambda r: msg2)

    state = mw._phase_states["t1"]["web_search"]
    assert state.consecutive_problems >= 1


# ---------------------------------------------------------------------------
# Scenario 9: Different Jaccard content does NOT count as problem


def test_jaccard_different_content_not_a_problem():
    mw = _make_mw(stagnation_threshold=3, warn_escalation_count=5, jaccard_threshold=0.8, min_words=5)
    rt = _make_runtime()
    req = _make_tool_request(runtime=rt)

    words1 = "apple banana cherry delta echo foxtrot golf hotel india juliet"
    words2 = "xray yankee zulu alpha bravo charlie sierra tango uniform victor"
    msg1 = _make_tool_message(words1)
    msg2 = _make_tool_message(words2)

    mw.wrap_tool_call(req, lambda r: msg1)
    mw.wrap_tool_call(req, lambda r: msg2)

    state = mw._phase_states["t1"]["web_search"]
    assert state.consecutive_problems == 0
    assert state.phase == "active"


# ---------------------------------------------------------------------------
# Scenario 9b: production default min_words=10 skips Jaccard for short content


def test_jaccard_skipped_when_content_below_production_min_words():
    """Production default min_words=10 must skip Jaccard for content with 6-9 unique words.

    _make_mw() uses min_words=5 to make most tests easier to set up.  This test
    uses the production default (min_words=10) to verify that short but repeated
    content does NOT count as a near-duplicate stagnation problem.
    """
    mw = ToolProgressMiddleware(
        stagnation_threshold=3,
        warn_escalation_count=2,
        jaccard_threshold=0.8,
        min_words=10,  # production default
    )
    rt = _make_runtime()
    req = _make_tool_request(runtime=rt)

    # 7 unique words — above min_words=5 but below production min_words=10.
    # With min_words=10 the Jaccard check is skipped → never a problem → phase stays active.
    words = "apple banana cherry delta echo foxtrot golf"
    msg = _make_tool_message(words)

    for _ in range(5):
        mw.wrap_tool_call(req, lambda r: msg)

    state = mw._phase_states["t1"]["web_search"]
    assert state.phase == "active", "7-word repeated content must not trigger stagnation with production min_words=10"
    assert state.consecutive_problems == 0


# ---------------------------------------------------------------------------
# Scenario 10: exempt_tools are not tracked


def test_exempt_tools_not_tracked():
    mw = _make_mw(stagnation_threshold=1, warn_escalation_count=1)
    rt = _make_runtime()
    req = _make_tool_request("ask_clarification", runtime=rt)
    error_msg = _make_error_message(tool_name="ask_clarification")

    def handler(_r):
        return error_msg

    for _ in range(5):
        mw.wrap_tool_call(req, handler)

    assert "ask_clarification" not in mw._phase_states.get("t1", {})


# ---------------------------------------------------------------------------
# Scenario 11: before_agent clears stale pending hints from previous runs


def test_before_agent_clears_stale_pending():
    mw = _make_mw(stagnation_threshold=2, warn_escalation_count=5)
    rt_run1 = _make_runtime(thread_id="t1", run_id="old-run")
    rt_run2 = _make_runtime(thread_id="t1", run_id="new-run")
    req = _make_tool_request(runtime=rt_run1)
    error_msg = _make_error_message()

    # Produce a hint for old-run
    mw.wrap_tool_call(req, lambda r: error_msg)
    mw.wrap_tool_call(req, lambda r: error_msg)

    mw._drain_pending(rt_run1)
    # Re-queue manually to simulate pending state
    mw._queue_assessment(rt_run1, "old hint")

    # before_agent with new-run should clear the old-run's pending hints
    state_mock = MagicMock()
    mw.before_agent(state_mock, rt_run2)

    # Old pending should be gone
    leftovers = mw._pending.get(("t1", "old-run"), [])
    assert leftovers == []


@pytest.mark.anyio
async def test_abefore_agent_clears_stale_pending():
    mw = _make_mw(stagnation_threshold=2, warn_escalation_count=5)
    rt_run1 = _make_runtime(thread_id="t1", run_id="old-run")
    rt_run2 = _make_runtime(thread_id="t1", run_id="new-run")
    req = _make_tool_request(runtime=rt_run1)
    error_msg = _make_error_message()

    mw.wrap_tool_call(req, lambda r: error_msg)
    mw.wrap_tool_call(req, lambda r: error_msg)
    mw._drain_pending(rt_run1)
    mw._queue_assessment(rt_run1, "old hint")

    state_mock = MagicMock()
    await mw.abefore_agent(state_mock, rt_run2)

    leftovers = mw._pending.get(("t1", "old-run"), [])
    assert leftovers == []


def test_before_agent_preserves_current_run_hints():
    # _clear_stale_pending deletes keys where thread_id matches but run_id differs.
    # Hints for the *current* run must not be evicted.
    mw = _make_mw(stagnation_threshold=2, warn_escalation_count=5)
    rt = _make_runtime(thread_id="t1", run_id="current-run")
    # _queue_assessment guards against phantom entries by checking _phase_states; seed the
    # thread so the direct call below isn't silently dropped by the L1 guard.
    mw._phase_states["t1"] = {}
    mw._queue_assessment(rt, "current hint")

    state_mock = MagicMock()
    mw.before_agent(state_mock, rt)

    preserved = mw._pending.get(("t1", "current-run"), [])
    assert preserved == ["current hint"]


def test_before_agent_resets_blocked_states_for_new_run():
    """BLOCKED and WARNED tool states must both be cleared at the start of a new run.

    A tool BLOCKED in run R1 must not silently remain blocked in R2.
    A tool WARNED in R1 must not carry its consecutive_problems count into R2
    (the model has not seen the warning context, so it would be hard-blocked
    without ever receiving a hint in the current session).
    recent_word_sets must also be cleared so stale Jaccard windows don't cause
    false near-duplicate detections on the first success call of the new run.
    """
    mw = _make_mw(stagnation_threshold=1, warn_escalation_count=1)
    rt_run1 = _make_runtime(thread_id="t1", run_id="run-1")
    rt_run2 = _make_runtime(thread_id="t1", run_id="run-2")
    req = _make_tool_request(runtime=rt_run1)

    # Drive the tool to BLOCKED via auth error (immediate block, no WARN stage)
    auth_msg = ToolMessage(
        content="Error: invalid api key",
        tool_call_id="tc-web_search",
        name="web_search",
        status="error",
        additional_kwargs=_meta_kwargs(
            status="error",
            error_type="auth",
            recoverable_by_model=False,
            recommended_next_action="stop",
        ),
    )
    mw.wrap_tool_call(req, lambda _r: auth_msg)
    assert mw._phase_states["t1"]["web_search"].phase == "blocked"

    # Simulate start of run 2
    state_mock = MagicMock()
    mw.before_agent(state_mock, rt_run2)

    # _reset_run_states always replaces the entry in-place; it is never None.
    tool_state = mw._phase_states.get("t1", {}).get("web_search")
    assert tool_state is not None
    assert tool_state.phase == "active"
    assert tool_state.consecutive_problems == 0
    assert tool_state.block_reason is None
    assert tool_state.recent_word_sets == ()


def test_before_agent_resets_warned_states_for_new_run():
    """WARNED tool state must also be cleared by before_agent.

    A tool with phase='warned' and accumulated consecutive_problems at end of run R1
    must not carry that count into R2; the model has no warning context and would
    be hard-blocked after just a few calls without receiving a hint.
    """
    mw = _make_mw(stagnation_threshold=2, warn_escalation_count=5)
    rt_run1 = _make_runtime(thread_id="t1", run_id="run-1")
    rt_run2 = _make_runtime(thread_id="t1", run_id="run-2")
    req = _make_tool_request(runtime=rt_run1)
    error_msg = _make_error_message()

    # Drive to WARNED (stagnation_threshold=2 means 2 problems → warned)
    mw.wrap_tool_call(req, lambda _r: error_msg)
    mw.wrap_tool_call(req, lambda _r: error_msg)
    assert mw._phase_states["t1"]["web_search"].phase == "warned"
    assert mw._phase_states["t1"]["web_search"].consecutive_problems == 2

    state_mock = MagicMock()
    mw.before_agent(state_mock, rt_run2)

    tool_state = mw._phase_states.get("t1", {}).get("web_search")
    assert tool_state is not None
    assert tool_state.phase == "active"
    assert tool_state.consecutive_problems == 0
    assert tool_state.recent_word_sets == ()


def test_before_agent_resets_active_state_consecutive_problems_and_word_sets():
    """ACTIVE tools with sub-threshold problems must also be cleaned at run boundaries.

    An ACTIVE tool (phase never left 'active') can exit a run with non-zero
    consecutive_problems and non-empty recent_word_sets.  If _reset_run_states only
    touched BLOCKED/WARNED tools, the counter from R1 would bleed into R2: a single
    problem on R2's first call could then trip WARNED against stale R1 context that
    the model has never seen.
    """
    # stagnation_threshold=3 so two errors keep the tool ACTIVE.
    mw = _make_mw(stagnation_threshold=3, warn_escalation_count=5)
    rt_run1 = _make_runtime(thread_id="t1", run_id="run-1")
    rt_run2 = _make_runtime(thread_id="t1", run_id="run-2")
    req = _make_tool_request(runtime=rt_run1)

    # Two successes → recent_word_sets grows.
    success_a = _make_tool_message("alpha beta gamma delta epsilon zeta eta theta iota kappa")
    success_b = _make_tool_message("lambda mu nu xi omicron pi rho sigma tau upsilon phi chi")
    mw.wrap_tool_call(req, lambda _r: success_a)
    mw.wrap_tool_call(req, lambda _r: success_b)

    # One recoverable error → consecutive_problems=1, phase stays ACTIVE.
    error_msg = _make_error_message()
    mw.wrap_tool_call(req, lambda _r: error_msg)

    state_r1 = mw._phase_states.get("t1", {}).get("web_search")
    assert state_r1 is not None
    assert state_r1.phase == "active"
    assert state_r1.consecutive_problems == 1
    assert len(state_r1.recent_word_sets) > 0

    # Start of run 2: all per-run state must be cleared.
    state_mock = MagicMock()
    mw.before_agent(state_mock, rt_run2)

    state_r2 = mw._phase_states.get("t1", {}).get("web_search")
    assert state_r2 is not None
    assert state_r2.phase == "active"
    assert state_r2.consecutive_problems == 0
    assert state_r2.recent_word_sets == ()


# ---------------------------------------------------------------------------
# Scenario 12: LRU eviction when max_tracked_threads exceeded


def test_get_block_reason_does_not_create_phantom_entries():
    # _get_block_reason is called on every wrap_tool_call before the handler.
    # It must not insert an empty entry for new threads (which could prematurely
    # evict another thread's WARNED state via LRU).
    mw = _make_mw(max_tracked_threads=2, stagnation_threshold=2)
    rt_a = _make_runtime(thread_id="thread-a")
    rt_b = _make_runtime(thread_id="thread-b")
    rt_c = _make_runtime(thread_id="thread-c")

    req_a = _make_tool_request(runtime=rt_a)
    error_msg = _make_error_message()

    # Drive thread-a to WARNED state (needs 2 error calls with threshold=2).
    mw.wrap_tool_call(req_a, lambda r: error_msg)
    mw.wrap_tool_call(req_a, lambda r: error_msg)
    assert mw._phase_states["thread-a"]["web_search"].phase == "warned"

    # Drive thread-b so it has a real entry too.
    req_b = _make_tool_request(runtime=rt_b)
    good_msg = _make_tool_message("A" * 300)
    mw.wrap_tool_call(req_b, lambda r: good_msg)
    assert "thread-b" in mw._phase_states

    # Now thread-c makes its very first call. max_tracked_threads=2, so adding
    # thread-c must evict one of {thread-a, thread-b} — but the eviction must
    # only happen in _update_state_from_result (the write path), not in
    # _get_block_reason (the read path that runs first).
    # After wrap_tool_call completes, the two survivors should be thread-b and
    # thread-c (thread-a is oldest because thread-b was accessed most recently).
    req_c = _make_tool_request(tool_name="read_file", runtime=rt_c)
    mw.wrap_tool_call(req_c, lambda r: good_msg)

    # thread-c must now have a real entry (not an empty phantom).
    assert "thread-c" in mw._phase_states
    assert mw._phase_states["thread-c"].get("read_file") is not None

    # No more than max_tracked_threads entries should exist.
    assert len(mw._phase_states) <= 2


def test_lru_eviction_of_oldest_thread():
    mw = _make_mw(max_tracked_threads=2)
    error_msg = _make_error_message()

    for i in range(3):
        rt = _make_runtime(thread_id=f"thread-{i}")
        req = _make_tool_request(runtime=rt)
        mw.wrap_tool_call(req, lambda r: error_msg)

    assert len(mw._phase_states) == 2
    # thread-0 should have been evicted (oldest); thread-1 and thread-2 remain
    assert "thread-0" not in mw._phase_states
    assert "thread-1" in mw._phase_states
    assert "thread-2" in mw._phase_states


def test_pending_evicted_with_phase_states_on_lru_overflow():
    """M1 regression: _pending keys for evicted threads must be cleaned up.

    When _phase_states evicts a thread via LRU, any pending hint entries
    for that thread must also be removed so _pending cannot grow unboundedly.
    """
    mw = _make_mw(max_tracked_threads=2, stagnation_threshold=2)
    error_msg = _make_error_message()

    # Thread-0: produce a hint (reach WARNED) so it has a pending entry.
    rt0 = _make_runtime(thread_id="thread-0", run_id="run-0")
    req0 = _make_tool_request(runtime=rt0)
    mw.wrap_tool_call(req0, lambda r: error_msg)
    mw.wrap_tool_call(req0, lambda r: error_msg)
    # Verify thread-0 has a pending hint.
    assert len(mw._pending.get(("thread-0", "run-0"), [])) >= 1

    # Thread-1: occupy the second slot.
    rt1 = _make_runtime(thread_id="thread-1", run_id="run-1")
    req1 = _make_tool_request(runtime=rt1)
    good_msg = _make_tool_message("A" * 300)
    mw.wrap_tool_call(req1, lambda r: good_msg)

    # Thread-2: adding this forces LRU eviction of thread-0.
    rt2 = _make_runtime(thread_id="thread-2", run_id="run-2")
    req2 = _make_tool_request(runtime=rt2)
    mw.wrap_tool_call(req2, lambda r: good_msg)

    # thread-0 must be evicted from phase_states.
    assert "thread-0" not in mw._phase_states

    # The pending entry for thread-0 must also be gone (no memory leak).
    assert ("thread-0", "run-0") not in mw._pending, "_pending entry for evicted thread-0 should have been cleaned up"


# ---------------------------------------------------------------------------
# Hint injection via wrap_model_call


def test_hint_injected_into_model_call():
    mw = _make_mw(stagnation_threshold=2, warn_escalation_count=5)
    rt = _make_runtime()
    req = _make_tool_request(runtime=rt)
    error_msg = _make_error_message()

    # Trigger hint
    mw.wrap_tool_call(req, lambda r: error_msg)
    mw.wrap_tool_call(req, lambda r: error_msg)

    model_req = _make_model_request([], rt)
    captured_messages = []

    def model_handler(r):
        captured_messages.extend(r.messages)
        return MagicMock()

    mw.wrap_model_call(model_req, model_handler)

    assert any(isinstance(m, HumanMessage) for m in captured_messages)
    hint_msgs = [m for m in captured_messages if isinstance(m, HumanMessage)]
    assert any("PROGRESS HINT" in m.content for m in hint_msgs)


def test_partial_success_hint_is_specific_not_generic():
    mw = _make_mw(stagnation_threshold=2, warn_escalation_count=5)
    rt = _make_runtime()
    req = _make_tool_request(runtime=rt)
    partial_msg = ToolMessage(
        content="Here are some partial results from the search.",
        tool_call_id="tc-web_search",
        name="web_search",
        status="success",
        additional_kwargs=_meta_kwargs(
            status="partial_success",
            recommended_next_action="rewrite_query",
        ),
    )

    def handler(_r):
        return partial_msg

    mw.wrap_tool_call(req, handler)
    mw.wrap_tool_call(req, handler)

    hints = mw._drain_pending(rt)
    assert len(hints) == 1
    assert "incomplete results" in hints[0].lower()
    assert "not producing new information" not in hints[0]


def test_jaccard_near_dup_hint_is_specific_and_actionable():
    """Near-duplicate success hint must be specific (not generic fallback) and include action guidance.

    Before the fix, status='success'/error_type=None fell through to the generic fallback
    '[PROGRESS HINT] The tool is not producing new information.' with no action suffix
    (recommended_next_action='continue' was absent from action_map).  The fix adds a
    'success' key to the base dict and a 'continue' key to the action_map.
    """
    mw = _make_mw(stagnation_threshold=2, warn_escalation_count=5, jaccard_threshold=0.8, min_words=5)
    rt = _make_runtime()
    req = _make_tool_request(runtime=rt)

    # First call: good unique content to seed recent_word_sets.
    words = "apple banana cherry delta echo foxtrot golf hotel india juliet"
    good_msg = _make_tool_message(words)
    mw.wrap_tool_call(req, lambda r: good_msg)

    # Second and third calls: exact same content → near-duplicate → stagnation_threshold=2 → WARNED.
    dup_msg = _make_tool_message(words)

    def handler(_r):
        return dup_msg

    mw.wrap_tool_call(req, handler)
    mw.wrap_tool_call(req, handler)

    hints = mw._drain_pending(rt)
    assert len(hints) == 1
    hint = hints[0]
    # Must contain a specific near-dup message, not the generic fallback.
    assert "duplicate" in hint.lower(), f"expected 'duplicate' in hint, got: {hint!r}"
    # Must include an actionable suggestion (from action_map["continue"]).
    assert "rephras" in hint.lower() or "different" in hint.lower(), f"expected action guidance in hint, got: {hint!r}"


def test_no_hint_when_inject_assessment_disabled():
    mw = _make_mw(stagnation_threshold=2, warn_escalation_count=5, inject_assessment=False)
    rt = _make_runtime()
    req = _make_tool_request(runtime=rt)
    error_msg = _make_error_message()

    mw.wrap_tool_call(req, lambda r: error_msg)
    mw.wrap_tool_call(req, lambda r: error_msg)

    hints = mw._drain_pending(rt)
    assert hints == []


def test_augment_request_deduplicates_identical_hints():
    """L2: _augment_request must deduplicate identical hint strings via dict.fromkeys.

    If the same hint text appears multiple times in the queue (e.g. two successive
    no_results errors produce identical hint strings), only one copy should be
    injected into the model message.
    """
    mw = _make_mw(stagnation_threshold=2, warn_escalation_count=5, inject_assessment=True)
    rt = _make_runtime()

    # _queue_assessment guards against phantom entries; seed the thread so the direct
    # calls below aren't dropped by the L1 guard.
    mw._phase_states["t1"] = {}
    # Manually queue two identical hints to simulate duplicates.
    mw._queue_assessment(rt, "[PROGRESS HINT] same hint text")
    mw._queue_assessment(rt, "[PROGRESS HINT] same hint text")

    model_req = _make_model_request([], rt)
    captured: list = []

    def model_handler(r):
        captured.extend(r.messages)
        return MagicMock()

    mw.wrap_model_call(model_req, model_handler)

    hint_msgs = [m for m in captured if isinstance(m, HumanMessage)]
    assert len(hint_msgs) == 1
    # The single injected message must contain the hint exactly once.
    assert hint_msgs[0].content.count("[PROGRESS HINT] same hint text") == 1


# ---------------------------------------------------------------------------
# L1: _assess_and_transition called with already-blocked state is idempotent


def test_assess_and_transition_blocked_state_immediate_stop_is_idempotent():
    """L1: _assess_and_transition must handle an already-blocked state without error.

    The docstring states the immediate-block branch re-applies idempotently.
    This test verifies that re-entering with a blocked state + stop-action meta
    stays blocked and does not corrupt the block_reason.
    """
    from deerflow.agents.middlewares.tool_progress_middleware import ToolPhaseState

    mw = _make_mw()
    blocked_state = ToolPhaseState(
        phase="blocked",
        consecutive_problems=5,
        block_reason="Authentication failure — this tool cannot be used.",
    )
    auth_meta_kwargs = _meta_kwargs(
        status="error",
        error_type="auth",
        recoverable_by_model=False,
        recommended_next_action="stop",
    )[TOOL_META_KEY]
    from deerflow.agents.middlewares.tool_result_meta import ToolResultMeta

    auth_meta = ToolResultMeta(**auth_meta_kwargs)

    new_state, hint = mw._assess_and_transition(blocked_state, auth_meta, "")

    assert new_state.phase == "blocked"
    assert new_state.block_reason is not None
    assert hint is None  # no hint on immediate block path


def test_assess_and_transition_blocked_state_non_stop_increments_count():
    """L1: A blocked state receiving a non-stop problem increments counter, stays blocked.

    Simulates a concurrent race where two threads both process results for the
    same tool: the second thread's _assess_and_transition receives a stale
    'blocked' snapshot.  The result must remain blocked.
    """
    from deerflow.agents.middlewares.tool_progress_middleware import ToolPhaseState

    mw = _make_mw(stagnation_threshold=2, warn_escalation_count=1)
    blocked_state = ToolPhaseState(
        phase="blocked",
        consecutive_problems=3,
        block_reason="Repeated rate-limiting — summarize current findings and proceed.",
    )
    rate_meta_kwargs = _meta_kwargs(
        status="error",
        error_type="rate_limited",
        recoverable_by_model=False,
        recommended_next_action="summarize",
    )[TOOL_META_KEY]
    from deerflow.agents.middlewares.tool_result_meta import ToolResultMeta

    rate_meta = ToolResultMeta(**rate_meta_kwargs)

    new_state, _hint = mw._assess_and_transition(blocked_state, rate_meta, "")

    # Must stay blocked (not regress to warned or active).
    assert new_state.phase == "blocked"
    # Counter must NOT be incremented: blocked is terminal, state returned unchanged.
    assert new_state.consecutive_problems == 3


def test_assess_and_transition_blocked_recoverable_does_not_regress_to_warned():
    """L1: A blocked state with recoverable errors must not silently regress to warned.

    Before the fix, _assess_and_transition had no guard for already-blocked states.
    A recoverable error arriving on a blocked state (concurrent race) would take
    the `warned` branch because recoverable_by_model=True, demoting the phase from
    blocked back to warned. This test locks the fixed behavior.
    """
    from deerflow.agents.middlewares.tool_progress_middleware import ToolPhaseState

    mw = _make_mw(stagnation_threshold=2, warn_escalation_count=1)
    blocked_state = ToolPhaseState(
        phase="blocked",
        consecutive_problems=5,
        block_reason="Repeated no-results — rewrite your query or try a different tool.",
    )
    # Recoverable no_results error (would normally only WARN, never block on its own)
    no_results_meta_kwargs = _meta_kwargs(
        status="error",
        error_type="no_results",
        recoverable_by_model=True,
        recommended_next_action="rewrite_query",
    )[TOOL_META_KEY]
    from deerflow.agents.middlewares.tool_result_meta import ToolResultMeta

    no_results_meta = ToolResultMeta(**no_results_meta_kwargs)

    new_state, hint = mw._assess_and_transition(blocked_state, no_results_meta, "")

    assert new_state.phase == "blocked", "blocked must not regress to warned even when the new error is recoverable"
    assert hint is None
    assert new_state is blocked_state  # exact same object returned (no copy)


# ---------------------------------------------------------------------------
# Tool without runtime attribute is passed through


def test_no_runtime_passthrough():
    mw = _make_mw()
    req = SimpleNamespace(tool_call={"name": "web_search", "id": "tc-1"})
    # No runtime attribute
    msg = _make_tool_message()

    def handler(_r):
        return msg

    result = mw.wrap_tool_call(req, handler)
    assert result is msg


# ---------------------------------------------------------------------------
# Command results are passed through unchanged


def test_command_result_passthrough():
    mw = _make_mw()
    rt = _make_runtime()
    req = _make_tool_request(runtime=rt)
    cmd = Command(goto="some_node")

    def handler(_r):
        return cmd

    result = mw.wrap_tool_call(req, handler)
    assert result is cmd


# ---------------------------------------------------------------------------
# from_config round-trip


def test_from_config():
    from deerflow.config.tool_progress_config import ToolProgressConfig

    cfg = ToolProgressConfig(
        enabled=True,
        stagnation_threshold=4,
        warn_escalation_count=3,
        jaccard_similarity_threshold=0.7,
        min_word_count_for_similarity=8,
    )
    mw = ToolProgressMiddleware.from_config(cfg)
    assert mw._stagnation_threshold == 4
    assert mw._warn_escalation == 3
    assert mw._jaccard_threshold == pytest.approx(0.7)
    assert mw._min_words == 8


def test_from_config_empty_exempt_tools_clears_exemptions():
    """Empty exempt_tools in config must produce an empty set, not the default fallback.

    H1 regression: `exempt_tools or {default}` would silently ignore an empty set
    because set() is falsy in Python. The fix uses `is not None` so an explicit
    empty set from config actually disables all exemptions.
    """
    from deerflow.config.tool_progress_config import ToolProgressConfig

    cfg = ToolProgressConfig(enabled=True, exempt_tools=set())
    mw = ToolProgressMiddleware.from_config(cfg)
    assert mw._exempt_tools == set(), "empty exempt_tools in config must clear all exemptions, not fall back to defaults"


def test_exempt_tools_none_uses_defaults():
    """None exempt_tools in __init__ must use the built-in default set."""
    mw = ToolProgressMiddleware(exempt_tools=None)
    assert "ask_clarification" in mw._exempt_tools
    assert "write_todos" in mw._exempt_tools
    assert "present_files" in mw._exempt_tools


def test_from_config_default_exempt_tools_round_trip():
    """Default exempt_tools from config must match the __init__ default."""
    from deerflow.config.tool_progress_config import ToolProgressConfig

    cfg = ToolProgressConfig(enabled=True)
    mw = ToolProgressMiddleware.from_config(cfg)
    assert mw._exempt_tools == {"ask_clarification", "write_todos", "present_files", "task"}


# ---------------------------------------------------------------------------
# Defensive meta parsing: malformed dicts must not crash the middleware


def test_wrap_tool_call_malformed_meta_passthrough():
    """Malformed deerflow_tool_meta dict must not crash the middleware."""
    mw = _make_mw()
    rt = _make_runtime()
    req = _make_tool_request(runtime=rt)
    bad_msg = ToolMessage(
        content="some content",
        tool_call_id="tc-web_search",
        name="web_search",
        status="success",
        additional_kwargs={TOOL_META_KEY: {"unexpected_field": True}},
    )

    def handler(_r):
        return bad_msg

    result = mw.wrap_tool_call(req, handler)

    assert result is bad_msg
    assert mw._phase_states.get("t1", {}).get("web_search") is None


def test_missing_meta_on_non_exempt_tool_emits_warning(caplog):
    """When deerflow_tool_meta is completely absent for a non-exempt tool,
    the middleware must emit a warning pointing to the likely ordering misconfiguration.
    """
    import logging

    mw = _make_mw()
    rt = _make_runtime()
    req = _make_tool_request(runtime=rt)
    no_meta_msg = ToolMessage(
        content="some content",
        tool_call_id="tc-web_search",
        name="web_search",
        status="success",
        additional_kwargs={},  # no TOOL_META_KEY at all
    )

    with caplog.at_level(logging.WARNING, logger="deerflow.agents.middlewares.tool_progress_middleware"):
        mw.wrap_tool_call(req, lambda _r: no_meta_msg)

    assert any("deerflow_tool_meta missing" in r.message for r in caplog.records), "Expected a warning about missing meta for non-exempt tool"


# ---------------------------------------------------------------------------
# Async path: awrap_tool_call mirrors sync path


@pytest.mark.anyio
async def test_awrap_tool_call_normal_passthrough():
    mw = _make_mw()
    rt = _make_runtime()
    req = _make_tool_request(runtime=rt)
    msg = _make_tool_message("A" * 300)

    result = await mw.awrap_tool_call(req, AsyncMock(return_value=msg))

    assert result is msg
    assert mw._phase_states["t1"]["web_search"].phase == "active"


@pytest.mark.anyio
async def test_awrap_tool_call_blocked_intercepted_without_calling_handler():
    mw = _make_mw(stagnation_threshold=2, warn_escalation_count=1)
    rt = _make_runtime()
    req = _make_tool_request(runtime=rt)
    # Non-recoverable error: stagnation escalates to BLOCKED.
    error_msg = _make_non_recoverable_error_message()
    call_count = [0]

    async def handler(r):
        call_count[0] += 1
        return error_msg

    # 3 calls: 2 → warned, 1 more → blocked
    for _ in range(3):
        await mw.awrap_tool_call(req, handler)

    assert mw._phase_states["t1"]["web_search"].phase == "blocked"
    before = call_count[0]

    result = await mw.awrap_tool_call(req, handler)

    assert call_count[0] == before
    assert isinstance(result, ToolMessage)
    assert "[TOOL_BLOCKED]" in result.content


@pytest.mark.anyio
async def test_awrap_tool_call_auth_error_immediately_blocked():
    mw = _make_mw(stagnation_threshold=5)
    rt = _make_runtime()
    req = _make_tool_request(runtime=rt)
    auth_msg = _make_error_message(
        error_type="auth",
        recoverable_by_model=False,
        recommended_next_action="stop",
    )

    await mw.awrap_tool_call(req, AsyncMock(return_value=auth_msg))

    state = mw._phase_states["t1"]["web_search"]
    assert state.phase == "blocked"
    assert state.block_reason is not None


@pytest.mark.anyio
async def test_awrap_tool_call_no_runtime_passthrough():
    mw = _make_mw()
    req = SimpleNamespace(tool_call={"name": "web_search", "id": "tc-1"})
    msg = _make_tool_message()

    result = await mw.awrap_tool_call(req, AsyncMock(return_value=msg))

    assert result is msg
    assert "t1" not in mw._phase_states


@pytest.mark.anyio
async def test_awrap_tool_call_command_result_passthrough():
    mw = _make_mw()
    rt = _make_runtime()
    req = _make_tool_request(runtime=rt)
    cmd = Command(goto="some_node")

    result = await mw.awrap_tool_call(req, AsyncMock(return_value=cmd))

    assert result is cmd


@pytest.mark.anyio
async def test_awrap_tool_call_malformed_meta_passthrough():
    """Malformed deerflow_tool_meta dict must not crash the middleware."""
    mw = _make_mw()
    rt = _make_runtime()
    req = _make_tool_request(runtime=rt)
    bad_msg = ToolMessage(
        content="some content",
        tool_call_id="tc-web_search",
        name="web_search",
        status="success",
        additional_kwargs={TOOL_META_KEY: {"unexpected_field": True}},
    )

    result = await mw.awrap_tool_call(req, AsyncMock(return_value=bad_msg))

    assert result is bad_msg
    # No state was tracked — malformed meta is silently skipped
    assert mw._phase_states.get("t1", {}).get("web_search") is None


@pytest.mark.anyio
async def test_awrap_model_call_drains_and_injects_hints():
    mw = _make_mw(stagnation_threshold=2, warn_escalation_count=5)
    rt = _make_runtime()
    req = _make_tool_request(runtime=rt)
    error_msg = _make_error_message()

    # Trigger hint via sync path (state machine is shared)
    mw.wrap_tool_call(req, lambda r: error_msg)
    mw.wrap_tool_call(req, lambda r: error_msg)

    model_req = _make_model_request([], rt)
    captured: list = []

    async def model_handler(r):
        captured.extend(r.messages)
        return MagicMock()

    await mw.awrap_model_call(model_req, model_handler)

    hint_msgs = [m for m in captured if isinstance(m, HumanMessage)]
    assert any("PROGRESS HINT" in m.content for m in hint_msgs)


# ---------------------------------------------------------------------------
# Logging behavior

_MW_LOGGER = "deerflow.agents.middlewares.tool_progress_middleware"


def test_log_active_to_warned_emits_info(caplog):
    mw = _make_mw(stagnation_threshold=2)
    rt = _make_runtime()
    req = _make_tool_request(runtime=rt)
    error_msg = _make_error_message()

    with caplog.at_level(logging.INFO, logger=_MW_LOGGER):
        mw.wrap_tool_call(req, lambda _r: error_msg)
        mw.wrap_tool_call(req, lambda _r: error_msg)

    info_records = [r for r in caplog.records if r.levelname == "INFO" and "WARNED" in r.message]
    assert len(info_records) == 1
    assert "web_search" in info_records[0].message


def test_log_immediate_block_emits_warning(caplog):
    mw = _make_mw(stagnation_threshold=5)
    rt = _make_runtime()
    req = _make_tool_request(runtime=rt)
    auth_msg = _make_error_message(
        error_type="auth",
        recoverable_by_model=False,
        recommended_next_action="stop",
    )

    with caplog.at_level(logging.WARNING, logger=_MW_LOGGER):
        mw.wrap_tool_call(req, lambda _r: auth_msg)

    warning_records = [r for r in caplog.records if r.levelname == "WARNING" and "BLOCKED" in r.message]
    assert len(warning_records) == 1
    assert "web_search" in warning_records[0].message


def test_log_escalation_block_emits_warning(caplog):
    mw = _make_mw(stagnation_threshold=2, warn_escalation_count=2)
    rt = _make_runtime()
    req = _make_tool_request(runtime=rt)
    error_msg = _make_non_recoverable_error_message()

    with caplog.at_level(logging.WARNING, logger=_MW_LOGGER):
        for _ in range(4):
            mw.wrap_tool_call(req, lambda _r: error_msg)

    warning_records = [r for r in caplog.records if r.levelname == "WARNING" and "BLOCKED" in r.message]
    assert len(warning_records) == 1


def test_log_blocked_call_intercepted_emits_info(caplog):
    mw = _make_mw(stagnation_threshold=2, warn_escalation_count=1)
    rt = _make_runtime()
    req = _make_tool_request(runtime=rt)
    error_msg = _make_non_recoverable_error_message()

    for _ in range(3):
        mw.wrap_tool_call(req, lambda _r: error_msg)

    with caplog.at_level(logging.INFO, logger=_MW_LOGGER):
        mw.wrap_tool_call(req, lambda _r: error_msg)

    intercepted = [r for r in caplog.records if "intercepted" in r.message and "web_search" in r.message]
    assert len(intercepted) == 1


def test_log_warned_to_active_reset_emits_info(caplog):
    mw = _make_mw(stagnation_threshold=2, warn_escalation_count=5)
    rt = _make_runtime()
    req = _make_tool_request(runtime=rt)
    error_msg = _make_error_message()
    good_msg = _make_tool_message("A" * 300)

    # Drive to WARNED
    mw.wrap_tool_call(req, lambda _r: error_msg)
    mw.wrap_tool_call(req, lambda _r: error_msg)

    with caplog.at_level(logging.INFO, logger=_MW_LOGGER):
        mw.wrap_tool_call(req, lambda _r: good_msg)

    reset_records = [r for r in caplog.records if r.levelname == "INFO" and "ACTIVE" in r.message]
    assert len(reset_records) == 1
    assert "web_search" in reset_records[0].message


def test_log_hint_injection_emits_debug(caplog):
    mw = _make_mw(stagnation_threshold=2, warn_escalation_count=5)
    rt = _make_runtime()
    req = _make_tool_request(runtime=rt)
    error_msg = _make_error_message()

    mw.wrap_tool_call(req, lambda _r: error_msg)
    mw.wrap_tool_call(req, lambda _r: error_msg)

    model_req = _make_model_request([], rt)
    with caplog.at_level(logging.DEBUG, logger=_MW_LOGGER):
        mw.wrap_model_call(model_req, lambda _r: MagicMock())

    debug_records = [r for r in caplog.records if r.levelname == "DEBUG" and "injecting" in r.message]
    assert len(debug_records) == 1
    assert "injecting 1 hint" in debug_records[0].message


# ---------------------------------------------------------------------------
# Coexistence: ToolProgressMiddleware + LoopDetectionMiddleware


def test_tool_progress_and_loop_detection_coexist_without_interfering():
    """ToolProgressMiddleware and LoopDetectionMiddleware operate on separate signals
    and must not interfere when both are active simultaneously.

    ToolProgressMiddleware (position 8): result-quality guard, fires after tool execution,
    tracks per-(thread, tool) stagnation, BLOCKs specific tools.
    LoopDetectionMiddleware (position 19): call-pattern guard, fires after model response,
    tracks repeated tool_call signatures, hard-stops the whole turn.

    Both can inject HumanMessage hints in the same model call; neither reads or writes
    the other's internal state.
    """
    from langchain_core.messages import AIMessage

    from deerflow.agents.middlewares.loop_detection_middleware import LoopDetectionMiddleware

    tp_mw = _make_mw(stagnation_threshold=2, warn_escalation_count=5, inject_assessment=True)
    ld_mw = LoopDetectionMiddleware(warn_threshold=3, hard_limit=10)

    tp_rt = _make_runtime(thread_id="t1", run_id="r1")
    # LoopDetection uses its own runtime/thread context
    ld_rt = _make_runtime(thread_id="ld-thread", run_id="ld-run")
    req = _make_tool_request(runtime=tp_rt)

    # --- Drive ToolProgress to WARNED via repeated error results (result-quality signal) ---
    error_msg = _make_error_message()  # recoverable error, stagnation_threshold=2
    tp_mw.wrap_tool_call(req, lambda _: error_msg)
    tp_mw.wrap_tool_call(req, lambda _: error_msg)

    assert tp_mw._phase_states["t1"]["web_search"].phase == "warned"
    tp_hints = list(tp_mw._pending.get(("t1", "r1"), []))
    assert len(tp_hints) == 1, "ToolProgress must queue exactly one hint at stagnation"

    # --- Drive LoopDetection to WARNED via repeated AIMessage tool_calls (call-pattern signal) ---
    repeated_call = [{"name": "web_search", "args": {"query": "q"}, "id": "tc-1"}]
    ld_state = {"messages": [AIMessage(content="", tool_calls=repeated_call)]}
    for _ in range(3):  # warn_threshold=3
        ld_mw._apply(ld_state, ld_rt)

    ld_warnings_live = ld_mw._pending_warnings.get(("ld-thread", "ld-run"), [])
    assert len(ld_warnings_live) >= 1, "LoopDetection must queue at least one warning"
    # Snapshot a copy so the final cross-contamination check compares a frozen
    # baseline to the live state — a same-object comparison would always be True.
    ld_warnings_snapshot = list(ld_warnings_live)

    # --- Verify no cross-contamination between the two middlewares ---
    # ToolProgress internal state is not visible to LoopDetection
    assert not hasattr(ld_mw, "_phase_states"), "LoopDetection must not have _phase_states"
    # LoopDetection internal state is not visible to ToolProgress
    assert not hasattr(tp_mw, "_history"), "ToolProgress must not have _history"
    # LoopDetection does not track ToolProgress's thread id
    assert "t1" not in ld_mw._history, "LoopDetection must not have entries for ToolProgress's thread"
    # ToolProgress does not have loop detection warnings
    assert not any("LOOP" in h for h in tp_hints), "ToolProgress hints must not contain loop-detection text"

    # --- ToolProgress hint injection is independent of LoopDetection ---
    model_req = _make_model_request([], tp_rt)
    captured: list = []

    def capture_handler(r):
        captured.extend(r.messages)
        return MagicMock()

    tp_mw.wrap_model_call(model_req, capture_handler)
    injected = [m for m in captured if isinstance(m, HumanMessage)]
    assert len(injected) == 1, "ToolProgress must inject exactly one hint message"
    assert "PROGRESS HINT" in injected[0].content

    # After ToolProgress drains, its queue is empty; LoopDetection warnings unchanged.
    # Compare live state against the snapshot taken before the model call — a same-object
    # comparison would be trivially True and would not detect accidental modifications.
    assert tp_mw._pending.get(("t1", "r1"), []) == []
    assert ld_mw._pending_warnings.get(("ld-thread", "ld-run"), []) == ld_warnings_snapshot
