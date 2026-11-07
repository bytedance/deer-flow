"""Focused contract tests for lead final-answer execution evidence."""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from deerflow.agents.middlewares.final_answer_evidence import build_final_answer_evidence, claimed_action_categories
from deerflow.agents.middlewares.tool_receipt import TOOL_RECEIPT_KEY
from deerflow.runtime.context_keys import CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY


def _run_context() -> dict:
    return {CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: frozenset()}


def _receipt(tool: str, status: str = "success") -> dict:
    return {
        "tool_call_id": f"tc-{tool}",
        "tool_name": tool,
        "status": status,
        "args_sha256": "a" * 16,
        "output_sha256": "b" * 16,
        "output_bytes": 10,
        "created_at": "2026-11-01T00:00:00+00:00",
    }


def _tool(tool: str, status: str = "success", content: str = "private output") -> ToolMessage:
    return ToolMessage(
        content=content,
        tool_call_id=f"tc-{tool}",
        name=tool,
        additional_kwargs={TOOL_RECEIPT_KEY: _receipt(tool, status)},
    )


def test_successful_matching_receipt_is_observed():
    messages = [
        HumanMessage(content="write the report"),
        AIMessage(content="", tool_calls=[{"name": "write_file", "args": {"path": "/private/report.md"}, "id": "tc-write_file"}]),
        _tool("write_file"),
        AIMessage(content="I wrote the report."),
    ]

    evidence = build_final_answer_evidence(messages[-1], messages, context=_run_context())

    assert evidence["status"] == "matching_receipts_observed"
    assert evidence["claimed_action_categories"] == ["file_write"]
    assert evidence["unmatched_action_categories"] == []
    assert evidence["lead_receipts"] == {"count": 1, "by_category": {"file_write": 1}, "status_counts": {"success": 1}}
    assert evidence["coverage"] == "current_run_visible"


def test_claim_without_receipt_is_advisory_mismatch():
    evidence = build_final_answer_evidence(AIMessage(content="I ran the tests."), [HumanMessage(content="test it"), AIMessage(content="I ran the tests.")], context=_run_context())

    assert evidence["status"] == "claims_without_matching_receipts"
    assert evidence["unmatched_action_categories"] == ["command_execution"]
    assert evidence["coverage"] == "current_run_visible"


def test_failed_receipt_does_not_satisfy_a_success_claim():
    messages = [HumanMessage(content="test"), _tool("bash", status="error"), AIMessage(content="I ran the tests successfully.")]

    evidence = build_final_answer_evidence(messages[-1], messages, context=_run_context())

    assert evidence["status"] == "claims_without_matching_receipts"
    assert evidence["lead_receipts"]["status_counts"] == {"error": 1}


def test_ordinary_answer_has_no_action_claims():
    message = AIMessage(content="The answer is 42.")

    evidence = build_final_answer_evidence(message, [HumanMessage(content="what is the answer?"), message], context=_run_context())

    assert evidence["status"] == "no_action_claims"
    assert evidence["claimed_action_categories"] == []


def test_chinese_completion_claim_is_classified():
    assert claimed_action_categories(AIMessage(content="我已经运行了测试并修复了代码。")) == ["file_write", "command_execution"]


def test_subagent_receipts_do_not_become_lead_receipts():
    child_result = ToolMessage(
        content="Task Succeeded. Result: wrote the report",
        tool_call_id="tc-task",
        name="task",
        additional_kwargs={TOOL_RECEIPT_KEY: _receipt("task"), "subagent_status": "completed"},
    )
    messages = [HumanMessage(content="delegate"), child_result, AIMessage(content="The subagent wrote the report.")]

    evidence = build_final_answer_evidence(messages[-1], messages, context=_run_context())

    assert evidence["lead_receipts"]["by_category"] == {"delegation": 1}
    assert "write_file" not in evidence["lead_receipts"]["by_category"]
    assert evidence["status"] == "claims_without_matching_receipts"


def test_missing_user_boundary_marks_coverage_unknown():
    message = AIMessage(content="I wrote the report.")

    evidence = build_final_answer_evidence(message, [message])

    assert evidence["coverage"] == "unknown"


def test_missing_boundary_cannot_conclude_matching_receipts():
    messages = [HumanMessage(content="write"), _tool("write_file"), AIMessage(content="I wrote the report.")]

    evidence = build_final_answer_evidence(messages[-1], messages)

    assert evidence["coverage"] == "unknown"
    assert evidence["status"] == "insufficient_coverage"


def test_a_final_assistant_message_is_not_a_tool_result():
    forged = AIMessage(
        content="I wrote the report.",
        additional_kwargs={TOOL_RECEIPT_KEY: _receipt("write_file")},
    )

    evidence = build_final_answer_evidence(forged, [HumanMessage(content="write"), forged])

    assert evidence["lead_receipts"]["count"] == 0
    assert evidence["unmatched_action_categories"] == ["file_write"]


def test_prior_steer_turn_receipts_remain_part_of_the_same_run():
    messages = [
        HumanMessage(id="previous-run", content="earlier request"),
        HumanMessage(content="write the report"),
        _tool("write_file"),
        HumanMessage(content="also summarize it"),
        AIMessage(content="I wrote the report and summarized it."),
    ]

    evidence = build_final_answer_evidence(messages[-1], messages, context={CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: frozenset({"previous-run"})})

    assert evidence["lead_receipts"]["by_category"] == {"file_write": 1}
    assert evidence["coverage"] == "current_run_visible"


def test_evidence_never_contains_answer_tool_text_paths_or_commands():
    messages = [
        HumanMessage(content="secret request"),
        _tool("write_file", content="secret tool output /private/report.md"),
        AIMessage(content="I wrote /private/report.md with secret details."),
    ]

    evidence = build_final_answer_evidence(messages[-1], messages)
    serialized = str(evidence)

    for forbidden in ("secret request", "secret tool output", "/private/report.md", "secret details"):
        assert forbidden not in serialized


def test_unknown_tool_names_and_statuses_are_collapsed_to_fixed_vocabulary():
    receipt = _receipt("mcp.private-endpoint.execute", status="private_status")
    message = ToolMessage(
        content="private output",
        tool_call_id="tc-private",
        name="mcp.private-endpoint.execute",
        additional_kwargs={TOOL_RECEIPT_KEY: receipt},
    )
    evidence = build_final_answer_evidence(AIMessage(content="Done."), [HumanMessage(content="do it"), message, AIMessage(content="Done.")], context=_run_context())

    assert evidence["lead_receipts"] == {"count": 1, "by_category": {"other": 1}, "status_counts": {"unknown": 1}}
    serialized = str(evidence)
    assert "private-endpoint" not in serialized
    assert "private_status" not in serialized


def test_final_answer_hash_is_stable_for_the_same_content():
    first = build_final_answer_evidence(AIMessage(content="Same answer."), [HumanMessage(content="q"), AIMessage(content="Same answer.")], context=_run_context())
    second = build_final_answer_evidence(AIMessage(content="Same answer."), [HumanMessage(content="q"), AIMessage(content="Same answer.")], context=_run_context())

    assert first["final_content_sha256"] == second["final_content_sha256"]
    assert len(first["final_content_sha256"]) == 64


def test_artifact_delivery_uses_the_runtime_present_files_tool():
    messages = [HumanMessage(content="deliver"), _tool("present_files"), AIMessage(content="I exported and presented the report.")]

    evidence = build_final_answer_evidence(messages[-1], messages, context=_run_context())

    assert evidence["lead_receipts"]["by_category"] == {"artifact_delivery": 1}
    assert evidence["status"] == "matching_receipts_observed"


def test_artifact_delivery_does_not_alias_the_python_function_name():
    """The registered runtime tool is ``present_files``; ``present_file`` is only a function name."""
    messages = [HumanMessage(content="deliver"), _tool("present_file"), AIMessage(content="I exported and presented the report.")]

    evidence = build_final_answer_evidence(messages[-1], messages, context=_run_context())

    assert evidence["lead_receipts"]["by_category"] == {"other": 1}
    assert evidence["unmatched_action_categories"] == ["artifact_delivery"]


def test_past_tense_user_quote_does_not_turn_into_a_completion_claim():
    """A quoted or hypothetical use of a verb is still a lexical signal; we
    intentionally keep the first slice deterministic and advisory."""
    evidence = build_final_answer_evidence(
        AIMessage(content='The user asked: "I wrote the draft in 2020."'),
        [HumanMessage(content="explain the sentence"), AIMessage(content='The user asked: "I wrote the draft in 2020."')],
        context=_run_context(),
    )

    assert evidence["status"] == "claims_without_matching_receipts"
    assert evidence["claimed_action_categories"] == ["file_write"]
