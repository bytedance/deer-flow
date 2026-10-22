import copy
import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from deerflow.runtime.goal import GoalEvaluation, attach_goal_evaluation, build_goal_state, compute_no_progress_count, latest_visible_assistant_signature
from deerflow.runtime.goal_progress import observe_goal_operations

EVALUATION = GoalEvaluation(satisfied=False, blocker="goal_not_met_yet", reason="Work remains.", evidence_summary="")


def operation(index=1, *, call_id=None, status="success", content="OK", receipt=False):
    call_id = call_id or f"call-{index}"
    call = {"name": "write_file", "args": {"path": f"/tmp/part-{index}.txt", "content": f"Part {index}"}, "id": call_id}
    result = ToolMessage(content=content, tool_call_id=call_id, status=status)
    if receipt:
        from deerflow.agents.middlewares.tool_receipt import make_tool_receipt

        result.additional_kwargs["deerflow_tool_receipt"] = make_tool_receipt(call, result)
    return [AIMessage(content="", tool_calls=[call]), result]


def turn(*operations, text="More work remains."):
    return [HumanMessage(content="Continue", additional_kwargs={"hide_from_ui": True, "deerflow_goal_continuation": True}), *[message for pair in operations for message in pair], AIMessage(content=text)]


def evaluate(goal, messages):
    signature = latest_visible_assistant_signature(messages)
    observation = observe_goal_operations(goal, messages, text_signature=signature)
    count = compute_no_progress_count(goal, EVALUATION, evidence_signature=signature, operation_progress=observation)
    return attach_goal_evaluation(goal, EVALUATION, run_id="offline", no_progress_count=count, evidence_signature=signature, operation_progress=observation)


def test_same_reply_with_new_success_resets_count():
    goal = evaluate(build_goal_state("Write the parts"), turn(operation()))
    goal = evaluate(goal, turn(operation(call_id="repeat")))
    assert goal["no_progress_count"] == 1
    assert evaluate(goal, turn(operation(2)))["no_progress_count"] == 0


def test_rephrased_reply_repeated_operation_does_not_reset():
    goal = evaluate(build_goal_state("Write the parts"), turn(operation()))
    assert evaluate(goal, turn(operation(call_id="new-id"), text="Making steady progress"))["no_progress_count"] == 1


def test_alternating_subsets_cannot_reuse_old_work():
    goal = evaluate(build_goal_state("Write the parts"), turn(operation()))
    goal = evaluate(goal, turn(operation(), operation(2)))
    assert goal["no_progress_count"] == 0
    goal = evaluate(goal, turn(operation()))
    assert goal["no_progress_count"] == 1
    assert evaluate(goal, turn(operation(), operation(2)))["no_progress_count"] == 2


@pytest.mark.parametrize("count", [65, 256, 1000])
def test_exact_history_has_no_64_operation_cutoff(count):
    goal = evaluate(build_goal_state("Write the parts"), turn(*(operation(index) for index in range(count))))
    assert len(goal["last_evaluation"]["operation_progress"]["seen_keys"]) == count
    goal = json.loads(json.dumps(goal))
    assert evaluate(goal, turn(operation(count - 1, call_id="restart")))["no_progress_count"] == 1
    assert evaluate(goal, turn(operation(count)))["no_progress_count"] == 0


@pytest.mark.parametrize("body,status,kwargs", [("Error: missing file", "success", {}), ("varied error", "error", {}), ("partial result", "success", {"deerflow_tool_meta": {"status": "partial_success"}})])
def test_failures_do_not_gain_progress_from_new_arguments(body, status, kwargs):
    goal = evaluate(build_goal_state("Write the parts"), turn(operation()))
    failed = operation(2, status=status, content=body)
    failed[1].additional_kwargs.update(kwargs)
    assert evaluate(goal, turn(failed, text="Trying another way"))["no_progress_count"] == 1


def test_unpaired_tool_result_cannot_reset_count():
    goal = evaluate(build_goal_state("Write the parts"), turn(operation()))
    assert evaluate(goal, turn([ToolMessage(content="OK", tool_call_id="orphan")], text="Trying again"))["no_progress_count"] == 1


def test_latest_hidden_human_message_bounds_current_interval():
    goal = evaluate(build_goal_state("Write the parts"), turn(operation()))
    messages = turn(operation(2)) + turn(operation())
    assert evaluate(goal, messages)["no_progress_count"] == 1
    assert len(evaluate(goal, messages)["last_evaluation"]["operation_progress"]["seen_keys"]) == 1


def test_receipt_setting_and_ids_do_not_change_identity_or_mutate_messages():
    goal = evaluate(build_goal_state("Write the parts"), turn(operation(receipt=True)))
    messages = turn(operation(call_id="different", receipt=False))
    original = copy.deepcopy(messages)
    assert evaluate(goal, messages)["no_progress_count"] == 1
    assert messages == original


def test_pure_text_preserves_native_behavior_after_tool_turn():
    goal = evaluate(build_goal_state("Write the parts"), turn(operation()))
    for text in ["More work remains.", "A changed reply"]:
        messages = turn(text=text)
        expected = compute_no_progress_count(goal, EVALUATION, evidence_signature=latest_visible_assistant_signature(messages))
        assert evaluate(goal, messages)["no_progress_count"] == expected


def test_legacy_goal_migration_cannot_gain_extra_budget():
    goal = attach_goal_evaluation(build_goal_state("Write the parts"), EVALUATION, run_id="old", no_progress_count=1, evidence_signature=latest_visible_assistant_signature(turn(operation())))
    assert evaluate(goal, turn(operation(2)))["no_progress_count"] == 2
    assert evaluate(goal, turn(operation(2), text="Changed reply"))["no_progress_count"] == 0


@pytest.mark.parametrize("with_tool", [False, True])
def test_legacy_changed_reply_and_repeat_keep_native_counter(with_tool):
    goal = attach_goal_evaluation(build_goal_state("Write the parts"), EVALUATION, run_id="old", no_progress_count=1, evidence_signature=latest_visible_assistant_signature(turn()))
    messages = turn(*([operation(2)] if with_tool else []), text="A genuinely changed reply")
    goal = evaluate(goal, messages)
    assert goal["no_progress_count"] == 0
    assert evaluate(goal, messages)["no_progress_count"] == 1


def test_new_goal_and_clear_do_not_retain_old_keys():
    goal = evaluate(build_goal_state("Write the parts"), turn(operation(), operation(2)))
    replacement = evaluate(build_goal_state("A replacement goal"), turn(operation(3)))
    assert len(replacement["last_evaluation"]["operation_progress"]["seen_keys"]) == 1
    assert goal["objective"] == "Write the parts"


def test_tool_failure_cannot_be_overridden_by_stale_success_metadata():
    goal = evaluate(build_goal_state("Write the parts"), turn(operation()))
    failed = operation(2, status="error")
    failed[1].additional_kwargs["deerflow_tool_meta"] = {"status": "success"}
    assert evaluate(goal, turn(failed))["no_progress_count"] == 1


def test_persistence_merges_operations_from_fresh_goal_state():
    goal = evaluate(build_goal_state("Write the parts"), turn(operation()))
    old_observation = observe_goal_operations(goal, turn(operation(2)), text_signature="old")
    current = evaluate(goal, turn(operation(3)))
    result = attach_goal_evaluation(current, EVALUATION, run_id="racing-evaluation", operation_progress=old_observation)
    assert len(result["last_evaluation"]["operation_progress"]["seen_keys"]) == 3


def test_serialized_message_dicts_have_same_operation_identity():
    messages = turn(operation())
    goal = evaluate(build_goal_state("Write the parts"), messages)
    assert evaluate(goal, [message.model_dump() for message in messages])["no_progress_count"] == 1


def test_matching_failed_receipt_cannot_gain_progress():
    goal = evaluate(build_goal_state("Write the parts"), turn(operation()))
    failed = operation(2, receipt=True)
    failed[1].additional_kwargs["deerflow_tool_receipt"]["status"] = "error"
    assert evaluate(goal, turn(failed))["no_progress_count"] == 1


def test_foreign_receipt_is_not_used_to_classify_current_result():
    goal = evaluate(build_goal_state("Write the parts"), turn(operation()))
    current = operation(2, receipt=True)
    current[1].additional_kwargs["deerflow_tool_receipt"].update(status="error", tool_call_id="different")
    assert evaluate(goal, turn(current))["no_progress_count"] == 0


def test_legacy_fetched_error_page_reuses_existing_tool_classification():
    goal = evaluate(build_goal_state("Read the sources"), turn(operation()))
    call = {"name": "web_fetch", "args": {"url": "https://example.invalid/missing"}, "id": "fetch"}
    messages = turn([AIMessage(content="", tool_calls=[call]), ToolMessage(content="# 404 Not Found\nnginx", tool_call_id="fetch")])
    assert evaluate(goal, messages)["no_progress_count"] == 1


@pytest.mark.parametrize("serialized", [False, True])
def test_native_todo_reminder_cannot_hide_successful_operations(serialized):
    from langgraph.runtime import Runtime

    from deerflow.agents.middlewares.todo_middleware import TodoMiddleware

    goal = evaluate(build_goal_state("Write the parts"), turn(operation()))
    goal = evaluate(goal, turn(operation()))
    assert goal["no_progress_count"] == 1
    messages = turn(operation(2))[:-1]
    reminder_update = TodoMiddleware().before_model({"messages": messages, "todos": [{"content": "Write the next part", "status": "pending"}]}, Runtime())
    assert reminder_update is not None
    messages.extend(reminder_update["messages"])
    assert messages[-1].name == "todo_reminder"
    messages.append(AIMessage(content="More work remains."))
    if serialized:
        messages = [message.model_dump() for message in messages]
    assert evaluate(goal, messages)["no_progress_count"] == 0


@pytest.mark.parametrize("serialized", [False, True])
def test_valid_hidden_card_reply_starts_a_new_interval(serialized):
    goal = evaluate(build_goal_state("Write the parts"), turn(operation()))
    answer = HumanMessage(
        content="Use option A",
        additional_kwargs={
            "hide_from_ui": True,
            "human_input_response": {"version": 1, "kind": "human_input_response", "source": "ask_clarification", "request_id": "request-1", "response_kind": "text", "value": "Use option A"},
        },
    )
    messages = [*turn(operation(2))[:-1], answer, *operation(), AIMessage(content="More work remains.")]
    if serialized:
        messages = [message.model_dump() for message in messages]
    assert evaluate(goal, messages)["no_progress_count"] == 1


def _externalized_bash_operation(tmp_path, *, call_id, receipts=True, content=None):
    from deerflow.agents.middlewares.tool_output_budget_middleware import _patch_tool_message
    from deerflow.agents.middlewares.tool_receipt import make_tool_receipt
    from deerflow.agents.middlewares.tool_result_meta import normalize_tool_message
    from deerflow.config.tool_output_config import ToolOutputConfig

    call = {"name": "bash", "args": {"command": "cat /tmp/large-input.txt"}, "id": call_id}
    raw = normalize_tool_message(ToolMessage(content=content or ("same data\n" * 1400 + "\nExit Code: 0"), tool_call_id=call_id, name="bash"))
    if receipts:
        raw.additional_kwargs["deerflow_tool_receipt"] = make_tool_receipt(call, raw)
    visible = _patch_tool_message(raw, ToolOutputConfig(), str(tmp_path))
    assert visible.content != raw.content
    return [AIMessage(content="", tool_calls=[call]), visible]


@pytest.mark.parametrize("receipts", [False, True])
def test_externalized_output_path_and_call_id_cannot_manufacture_progress(tmp_path, monkeypatch, receipts):
    from deerflow.agents.middlewares import tool_output_budget_middleware

    monkeypatch.setattr(tool_output_budget_middleware, "get_blob_store_if_enabled", lambda: None)
    first = _externalized_bash_operation(tmp_path, call_id="first", receipts=receipts)
    repeat = _externalized_bash_operation(tmp_path, call_id="repeat", receipts=receipts)
    assert first[1].content != repeat[1].content
    goal = evaluate(build_goal_state("Read the source"), turn(first))
    goal = evaluate(goal, turn(repeat, text="Rephrased progress"))
    assert goal["no_progress_count"] == 1
    assert len(goal["last_evaluation"]["operation_progress"]["seen_keys"]) == (1 if receipts else 0)


def test_raw_and_untransformed_receipts_off_results_share_identity():
    goal = evaluate(build_goal_state("Write the parts"), turn(operation(receipt=False)))
    assert evaluate(goal, turn(operation(call_id="receipts-enabled", receipt=True)))["no_progress_count"] == 1


def test_changed_raw_externalized_result_is_new_progress_without_reading_saved_file(tmp_path, monkeypatch):
    from pathlib import Path

    from deerflow.agents.middlewares import tool_output_budget_middleware

    monkeypatch.setattr(tool_output_budget_middleware, "get_blob_store_if_enabled", lambda: None)
    first = _externalized_bash_operation(tmp_path, call_id="first")
    changed = _externalized_bash_operation(tmp_path, call_id="changed", content="different data\n" * 1400 + "\nExit Code: 0")

    def denied(*args, **kwargs):
        raise AssertionError("Goal observation must not read externalized tool files")

    monkeypatch.setattr(Path, "read_bytes", denied)
    monkeypatch.setattr(Path, "read_text", denied)
    goal = evaluate(build_goal_state("Read the source"), turn(first))
    goal = evaluate(goal, turn(first))
    assert goal["no_progress_count"] == 1
    assert evaluate(goal, turn(changed))["no_progress_count"] == 0
