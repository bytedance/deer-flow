"""Tests for ProgressScoringMiddleware (issue #2805 MVP).

Covers, in order:
  - parsing/sanitizing the model's in-band evaluation block,
  - stripping the block from AIMessage content before it persists,
  - objective signal extraction (tool keys, result hashes, meta signatures),
  - the sliding-window stagnation policy (trigger conditions, re-arm,
    scope isolation),
  - hook behavior: replan hint queued in ``after_model`` and injected by
    ``wrap_model_call``; run cleanup in ``after_agent``; audit recording.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from deerflow.agents.middlewares import progress_scoring_middleware as module
from deerflow.agents.middlewares.audit_context import LOOP_DETECTION_RECORDER_CONTEXT_KEY
from deerflow.agents.middlewares.progress_scoring_middleware import (
    PROGRESS_EVAL_TAG,
    ProgressScoringMiddleware,
    StepEvaluation,
    _StepRecord,
    _strip_eval_blocks,
    parse_step_evaluation,
)
from deerflow.agents.middlewares.tool_result_meta import TOOL_META_KEY
from deerflow.config.progress_scoring_config import ProgressScoringConfig

# ---------------------------------------------------------------------------
# Helpers


def _make_runtime(thread_id="t1", run_id="r1"):
    runtime = MagicMock()
    runtime.context = {"thread_id": thread_id, "run_id": run_id}
    return runtime


def _make_request(messages, runtime):
    request = MagicMock()
    request.messages = list(messages)
    request.runtime = runtime
    request.override = lambda **updates: _override_request(request, updates)
    return request


def _override_request(request, updates):
    new = MagicMock()
    new.messages = updates.get("messages", request.messages)
    new.runtime = updates.get("runtime", request.runtime)
    new.override = lambda **u: _override_request(new, u)
    return new


def _capture_handler():
    captured: list = []

    def handler(req):
        captured.append(req)
        return MagicMock()

    return captured, handler


def _eval_block(payload: str) -> str:
    return f"```{PROGRESS_EVAL_TAG}\n{payload}\n```"


def _step(progress=0, usefulness=0, tool_key="bash:ls", result_hash="h", sig=(("success", None),)):
    evaluation = None if progress is None else StepEvaluation(tool_usefulness=usefulness, task_progress=progress)
    return _StepRecord(
        evaluation=evaluation,
        tool_keys=(tool_key,),
        result_hashes=(result_hash,),
        meta_signatures=sig,
    )


def _turn_state(
    *,
    cmd="ls",
    result="output",
    progress=0,
    usefulness=0,
    eval_payload=None,
):
    """One model turn: a tool call, its result, and the scored AIMessage."""
    if eval_payload is None:
        eval_payload = f'{{"tool_usefulness": {usefulness}, "task_progress": {progress}}}'
    call = {"name": "bash", "id": "call-1", "args": {"command": cmd}}
    return {
        "messages": [
            HumanMessage(content="go"),
            AIMessage(content="", tool_calls=[call]),
            ToolMessage(content=result, tool_call_id="call-1", name="bash"),
            AIMessage(content=f"working\n{_eval_block(eval_payload)}"),
        ]
    }


# ---------------------------------------------------------------------------
# Evaluation parsing


class TestParseStepEvaluation:
    def test_valid_block(self):
        payload = '{"tool_usefulness": 2, "task_progress": 1, "progress_type": "evidence_found", "evidence": ["found file"], "should_change_strategy": false}'
        eval = parse_step_evaluation(f"reply\n{_eval_block(payload)}")
        assert eval is not None
        assert eval.tool_usefulness == 2
        assert eval.task_progress == 1
        assert eval.progress_type == "evidence_found"
        assert eval.evidence == ("found file",)
        assert eval.should_change_strategy is False

    def test_missing_block_returns_none(self):
        assert parse_step_evaluation("plain reply") is None

    def test_invalid_json_returns_none(self):
        assert parse_step_evaluation(_eval_block("{not json")) is None

    def test_out_of_range_score_rejects_whole_evaluation(self):
        assert parse_step_evaluation(_eval_block('{"tool_usefulness": 4, "task_progress": 0}')) is None
        assert parse_step_evaluation(_eval_block('{"tool_usefulness": -1, "task_progress": 0}')) is None

    def test_missing_score_rejects_whole_evaluation(self):
        assert parse_step_evaluation(_eval_block('{"task_progress": 1}')) is None

    def test_bool_and_fractional_scores_rejected(self):
        assert parse_step_evaluation(_eval_block('{"tool_usefulness": true, "task_progress": 0}')) is None
        assert parse_step_evaluation(_eval_block('{"tool_usefulness": 1.5, "task_progress": 0}')) is None

    def test_whole_float_score_accepted(self):
        eval = parse_step_evaluation(_eval_block('{"tool_usefulness": 2.0, "task_progress": 1.0}'))
        assert eval is not None
        assert (eval.tool_usefulness, eval.task_progress) == (2, 1)

    def test_evidence_sanitized(self):
        payload = '{"tool_usefulness": 0, "task_progress": 0, "evidence": [1, "  ", "' + "x" * 200 + '", "a", "b", "c"]}'
        eval = parse_step_evaluation(_eval_block(payload))
        assert eval is not None
        assert len(eval.evidence) == 3
        assert all(isinstance(item, str) and item for item in eval.evidence)
        assert len(eval.evidence[0]) <= 120

    def test_non_bool_should_change_defaults_false(self):
        eval = parse_step_evaluation(_eval_block('{"tool_usefulness": 0, "task_progress": 0, "should_change_strategy": "yes"}'))
        assert eval is not None
        assert eval.should_change_strategy is False

    def test_non_dict_json_rejected(self):
        assert parse_step_evaluation(_eval_block("[1, 2]")) is None

    def test_list_content_blocks_parsed(self):
        payload = '{"tool_usefulness": 1, "task_progress": 3}'
        content = [
            {"type": "text", "text": "thinking"},
            {"type": "text", "text": f"reply\n{_eval_block(payload)}"},
        ]
        eval = parse_step_evaluation(content)
        assert eval is not None
        assert eval.task_progress == 3


class TestStripEvalBlocks:
    def test_strips_block_from_string(self):
        content = f"real reply\n\n{_eval_block('{"tool_usefulness": 0, "task_progress": 0}')}\n"
        stripped = _strip_eval_blocks(content)
        assert PROGRESS_EVAL_TAG not in stripped
        assert "real reply" in stripped

    def test_no_block_returns_same_object(self):
        content = "plain reply"
        assert _strip_eval_blocks(content) is content

    def test_block_only_content_stays(self):
        content = _eval_block('{"tool_usefulness": 0, "task_progress": 0}')
        # Nothing meaningful would remain; the original content is kept
        # rather than replaced with an empty assistant message.
        assert _strip_eval_blocks(content) == content

    def test_strips_from_text_blocks(self):
        content = [
            {"type": "text", "text": "real reply"},
            {"type": "text", "text": _eval_block('{"tool_usefulness": 0, "task_progress": 0}')},
        ]
        stripped = _strip_eval_blocks(content)
        assert stripped == [{"type": "text", "text": "real reply"}]

    def test_leaves_non_text_blocks_untouched(self):
        content = [{"type": "image_url", "image_url": {"url": "x"}}]
        assert _strip_eval_blocks(content) is content


# ---------------------------------------------------------------------------
# Config


class TestProgressScoringConfig:
    def test_disabled_by_default(self):
        assert ProgressScoringConfig().enabled is False

    def test_rearm_below_floor_rejected(self):
        with pytest.raises(ValueError, match="rearm_progress"):
            ProgressScoringConfig(rearm_progress=0.5)

    def test_min_evals_above_window_rejected(self):
        with pytest.raises(ValueError, match="min_evals"):
            ProgressScoringConfig(min_evals=9, window_size=8)


# ---------------------------------------------------------------------------
# Objective signals


class TestStepExtraction:
    def test_identical_turns_share_tool_key_and_hash(self):
        mw = ProgressScoringMiddleware()
        runtime = _make_runtime()
        mw.after_model(_turn_state(cmd="ls", result="out"), runtime)
        mw.after_model(_turn_state(cmd="ls", result="out"), runtime)
        state = mw._scope_state(mw._run_scope_key(runtime))
        keys = {key for record in state.window for key in record.tool_keys}
        hashes = {h for record in state.window for h in record.result_hashes}
        assert len(keys) == 1
        assert len(hashes) == 1

    def test_distinct_results_yield_distinct_hashes(self):
        mw = ProgressScoringMiddleware()
        runtime = _make_runtime()
        mw.after_model(_turn_state(result="a"), runtime)
        mw.after_model(_turn_state(result="b"), runtime)
        state = mw._scope_state(mw._run_scope_key(runtime))
        hashes = {h for record in state.window for h in record.result_hashes}
        assert len(hashes) == 2

    def test_turn_without_tool_results_records_no_step(self):
        mw = ProgressScoringMiddleware()
        runtime = _make_runtime()
        state = {"messages": [HumanMessage(content="hi"), AIMessage(content="answer")]}
        assert mw.after_model(state, runtime) is None
        assert not mw._scope_state(mw._run_scope_key(runtime)).window

    def test_meta_signature_read_from_tool_meta(self):
        mw = ProgressScoringMiddleware()
        messages = _turn_state()["messages"]
        tool_msg = messages[2]
        tool_msg.additional_kwargs = {TOOL_META_KEY: {"status": "error", "error_type": "not_found", "recoverable_by_model": True, "recommended_next_action": "rewrite_query", "source": "tool_return"}}
        runtime = _make_runtime()
        mw.after_model({"messages": messages}, runtime)
        record = mw._scope_state(mw._run_scope_key(runtime)).window[-1]
        assert record.meta_signatures == (("error", "not_found"),)


# ---------------------------------------------------------------------------
# Policy


class TestWindowPolicy:
    def _stats_and_check(self, records):
        mw = ProgressScoringMiddleware()
        state = mw._scope_state(("t", "r"))
        state.window.extend(records)
        stats = module._window_stats(state.window)
        return mw, state, stats

    def test_stagnant_window_triggers(self):
        mw, state, stats = self._stats_and_check([_step(progress=0), _step(progress=0), _step(progress=0)])
        hint = mw._check_policy(state, stats)
        assert hint is not None
        assert "PROGRESS STALLED" in hint
        assert state.intervened is True

    def test_insufficient_evals_no_trigger(self):
        mw, state, stats = self._stats_and_check([_step(progress=0), _step(progress=0), _step(progress=None)])
        assert stats.evals == 2
        assert mw._check_policy(state, stats) is None

    def test_high_progress_no_trigger(self):
        mw, state, stats = self._stats_and_check([_step(progress=2), _step(progress=2), _step(progress=2)])
        assert mw._check_policy(state, stats) is None

    def test_distinct_results_are_observable_change(self):
        records = [_step(progress=0, result_hash="h1"), _step(progress=0, result_hash="h2"), _step(progress=0, result_hash="h3")]
        mw, state, stats = self._stats_and_check(records)
        assert stats.observable_change is True
        assert mw._check_policy(state, stats) is None

    def test_varied_calls_with_identical_results_trigger(self):
        # The slow-burn shape loop detection's identical-set hash misses:
        # varied arguments, identical unproductive results, low self-score.
        records = [_step(progress=0, tool_key="bash:ls"), _step(progress=0, tool_key="bash:pwd"), _step(progress=0, tool_key="bash:whoami")]
        mw, state, stats = self._stats_and_check(records)
        assert stats.observable_change is False
        assert stats.repeated_result_hash_ratio > 0.6
        hint = mw._check_policy(state, stats)
        assert hint is not None

    def test_error_type_change_is_observable_change(self):
        records = [
            _step(progress=0, sig=(("error", "not_found"),)),
            _step(progress=0, sig=(("error", "auth"),)),
            _step(progress=0, sig=(("error", "not_found"),)),
        ]
        mw, state, stats = self._stats_and_check(records)
        assert stats.observable_change is True
        assert mw._check_policy(state, stats) is None

    def test_low_tool_usefulness_alone_never_triggers(self):
        # task_progress is the stagnation signal; tool_usefulness is
        # diagnostic only (issue acceptance criterion).
        mw, state, stats = self._stats_and_check([_step(progress=3, usefulness=0), _step(progress=3, usefulness=0), _step(progress=3, usefulness=0)])
        assert mw._check_policy(state, stats) is None

    def test_intervention_fires_once_then_rearms_on_recovery(self):
        mw, state, stats = self._stats_and_check([_step(progress=0), _step(progress=0), _step(progress=0)])
        assert mw._check_policy(state, stats) is not None
        # Still stagnant: no second hint while intervened.
        stats = module._window_stats(state.window)
        assert mw._check_policy(state, stats) is None
        # Window recovers (progress + observable change): re-armed.
        state.window.extend([_step(progress=3, result_hash="h1"), _step(progress=3, result_hash="h2")])
        stats = module._window_stats(state.window)
        assert mw._check_policy(state, stats) is None
        assert state.intervened is False
        # A fresh slump triggers again.
        state.window.clear()
        state.window.extend([_step(progress=0), _step(progress=0), _step(progress=0)])
        stats = module._window_stats(state.window)
        assert mw._check_policy(state, stats) is not None

    def test_window_is_bounded(self):
        mw = ProgressScoringMiddleware(window_size=3)
        state = mw._scope_state(("t", "r"))
        state.window.extend(_step(progress=0, result_hash=f"h{i}") for i in range(10))
        assert len(state.window) == 3


# ---------------------------------------------------------------------------
# Hooks: after_model / wrap_model_call / after_agent


class TestHooks:
    def test_stagnant_loop_queues_hint_and_injects_at_next_model_call(self):
        mw = ProgressScoringMiddleware()
        runtime = _make_runtime()
        for _ in range(3):
            result = mw.after_model(_turn_state(), runtime)
            # The eval block is stripped from the persisted AIMessage.
            assert result is not None
            assert PROGRESS_EVAL_TAG not in result["messages"][0].content
            assert result["messages"][0].content == "working"

        captured, handler = _capture_handler()
        request = _make_request([AIMessage(content="next")], runtime)
        mw.wrap_model_call(request, handler)
        injected = captured[0].messages[-1]
        assert isinstance(injected, HumanMessage)
        assert injected.name == "progress_scoring"
        assert "PROGRESS EVALUATION PROTOCOL" in injected.content
        assert "PROGRESS STALLED" in injected.content

    def test_hint_drained_after_injection(self):
        mw = ProgressScoringMiddleware()
        runtime = _make_runtime()
        for _ in range(3):
            mw.after_model(_turn_state(), runtime)

        captured, handler = _capture_handler()
        mw.wrap_model_call(_make_request([AIMessage(content="next")], runtime), handler)
        first = captured[0].messages[-1].content
        assert "PROGRESS STALLED" in first

        mw.wrap_model_call(_make_request([AIMessage(content="next")], runtime), handler)
        second = captured[1].messages[-1].content
        assert "PROGRESS STALLED" not in second

    def test_instructions_injected_even_without_hint(self):
        mw = ProgressScoringMiddleware()
        runtime = _make_runtime()
        captured, handler = _capture_handler()
        mw.wrap_model_call(_make_request([HumanMessage(content="hi")], runtime), handler)
        assert "PROGRESS EVALUATION PROTOCOL" in captured[0].messages[-1].content

    def test_no_hard_stop_or_tool_calls_strip(self):
        # The intervention is replan-first: repeated stagnant turns never
        # strip tool_calls or force a final answer (loop_detection's job).
        mw = ProgressScoringMiddleware()
        runtime = _make_runtime()
        payload = '{"tool_usefulness": 0, "task_progress": 0}'
        state = _turn_state()
        state["messages"][3] = AIMessage(
            content=f"working\n{_eval_block(payload)}",
            tool_calls=[{"name": "bash", "id": "call-1", "args": {"command": "ls"}}],
        )
        for _ in range(5):
            result = mw.after_model(state, runtime)
        msg = result["messages"][0]
        # tool_calls untouched (LangChain adds "type": "tool_call" on
        # normalization); the intervention is replan-first, never a stop.
        assert [(tc["name"], tc["id"], tc["args"]) for tc in msg.tool_calls] == [("bash", "call-1", {"command": "ls"})]
        assert "FORCED STOP" not in msg.content

    def test_progressful_loop_never_hints(self):
        mw = ProgressScoringMiddleware()
        runtime = _make_runtime()
        for i in range(5):
            mw.after_model(_turn_state(result=f"result-{i}", progress=2), runtime)
        assert not mw._pending_hints

    def test_scopes_isolated_by_run_id(self):
        mw = ProgressScoringMiddleware()
        runtime_a = _make_runtime(run_id="run-a")
        runtime_b = _make_runtime(run_id="run-b")
        for _ in range(3):
            mw.after_model(_turn_state(), runtime_a)
        for _ in range(3):
            mw.after_model(_turn_state(progress=2, result="other"), runtime_b)
        assert ("t1", "run-a") in mw._pending_hints
        assert ("t1", "run-b") not in mw._pending_hints

    def test_after_agent_drops_pending_hint(self):
        mw = ProgressScoringMiddleware()
        runtime = _make_runtime()
        for _ in range(3):
            mw.after_model(_turn_state(), runtime)
        assert mw._pending_hints
        mw.after_agent({"messages": []}, runtime)
        assert not mw._pending_hints

    def test_reset_clears_scope(self):
        mw = ProgressScoringMiddleware()
        runtime = _make_runtime()
        for _ in range(3):
            mw.after_model(_turn_state(), runtime)
        mw.reset()
        assert not mw._scopes
        assert not mw._pending_hints

    def test_audit_event_recorded_on_intervention(self):
        mw = ProgressScoringMiddleware()
        recorder = MagicMock()
        runtime = _make_runtime()
        runtime.context[LOOP_DETECTION_RECORDER_CONTEXT_KEY] = recorder
        for _ in range(3):
            mw.after_model(_turn_state(), runtime)
        recorder.record_middleware.assert_called_once()
        kwargs = recorder.record_middleware.call_args.kwargs
        assert kwargs["tag"] == "progress_scoring"
        assert kwargs["action"] == "replan_required"
        assert kwargs["changes"]["evals"] == 3
        assert kwargs["changes"]["avg_task_progress"] == 0.0

    def test_audit_never_breaks_run_on_recorder_failure(self):
        mw = ProgressScoringMiddleware()
        recorder = MagicMock()
        recorder.record_middleware.side_effect = RuntimeError("journal down")
        runtime = _make_runtime()
        runtime.context[LOOP_DETECTION_RECORDER_CONTEXT_KEY] = recorder
        for _ in range(3):
            result = mw.after_model(_turn_state(), runtime)
        assert result is not None


class TestFromConfig:
    def test_from_config_passes_parameters(self):
        config = ProgressScoringConfig(enabled=True, window_size=5, min_evals=2, progress_floor=0.5, repetition_threshold=0.7)
        mw = ProgressScoringMiddleware.from_config(config)
        assert (mw.window_size, mw.min_evals, mw.progress_floor, mw.repetition_threshold) == (5, 2, 0.5, 0.7)

    def test_default_config_matches_issue_mvp_defaults(self):
        mw = ProgressScoringMiddleware.from_config(ProgressScoringConfig())
        assert mw.min_evals == 3
        assert mw.progress_floor == 1.0
        # Sliding window, not single-step decision.
        assert mw.window_size >= 2
