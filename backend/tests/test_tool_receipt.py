"""Tests for tool receipt core (deterministic verification layer)."""

from __future__ import annotations

from langchain_core.messages import AIMessage, ToolMessage

from deerflow.agents.middlewares.tool_receipt import (
    SUBAGENT_TOOL_RECEIPTS_KEY,
    TOOL_RECEIPT_KEY,
    child_receipts_for_result,
    extract_tool_receipts,
    make_tool_receipt,
    render_receipt_ledger,
    render_tool_receipts,
)
from deerflow.agents.middlewares.tool_result_meta import TOOL_META_KEY


def _msg(content: str, *, tool_call_id: str, name: str = "write_file", meta_status: str = "success") -> ToolMessage:
    return ToolMessage(
        content=content,
        tool_call_id=tool_call_id,
        name=name,
        additional_kwargs={TOOL_META_KEY: {"status": meta_status}},
    )


def _stamped_msg(content: str, *, tool_call_id: str, name: str, args: dict | None = None) -> ToolMessage:
    message = _msg(content, tool_call_id=tool_call_id, name=name)
    receipt = make_tool_receipt({"name": name, "id": tool_call_id, "args": args or {}}, message)
    message.additional_kwargs[TOOL_RECEIPT_KEY] = receipt
    return message


def test_make_tool_receipt_hashes_args_and_output():
    receipt = make_tool_receipt(
        {"name": "write_file", "id": "tc-1", "args": {"path": "/tmp/a.txt", "content": "hello"}},
        _msg("ok", tool_call_id="tc-1"),
    )
    assert receipt["tool_call_id"] == "tc-1"
    assert receipt["tool_name"] == "write_file"
    assert receipt["status"] == "success"
    assert len(receipt["args_sha256"]) == 16
    assert len(receipt["output_sha256"]) == 16
    assert receipt["output_bytes"] == 2


def test_make_tool_receipt_args_hash_is_key_order_invariant():
    first = make_tool_receipt({"name": "t", "id": "x", "args": {"a": 1, "b": 2}}, _msg("r", tool_call_id="x", name="t"))
    second = make_tool_receipt({"name": "t", "id": "x", "args": {"b": 2, "a": 1}}, _msg("r", tool_call_id="x", name="t"))
    assert first["args_sha256"] == second["args_sha256"]


def test_make_tool_receipt_uses_meta_error_status():
    receipt = make_tool_receipt(
        {"name": "web_fetch", "id": "tc-2", "args": {"url": "https://x"}},
        _msg("Error: 404", tool_call_id="tc-2", name="web_fetch", meta_status="error"),
    )
    assert receipt["status"] == "error"


def test_extract_assigns_sequential_ids_and_skips_unstamped():
    messages = [
        AIMessage(content="working", tool_calls=[{"name": "bash", "id": "tc-9", "args": {}}]),
        _msg("unstamped", tool_call_id="tc-0", name="bash"),
        _stamped_msg("first", tool_call_id="tc-1", name="write_file", args={"path": "/tmp/a"}),
        _stamped_msg("second", tool_call_id="tc-2", name="bash"),
    ]
    receipts = extract_tool_receipts(messages)
    assert [r["id"] for r in receipts] == ["r1", "r2"]
    assert receipts[0]["tool_name"] == "write_file"
    assert receipts[1]["tool_name"] == "bash"


def test_render_empty_and_budget():
    assert render_tool_receipts([]) == ""
    receipts = extract_tool_receipts([_stamped_msg("ok", tool_call_id="tc-1", name="write_file", args={"path": "/tmp/a"})])
    text = render_tool_receipts(receipts)
    assert "r1" in text and "write_file" in text and "success" in text
    # Anti-automation-bias (design rule 4): the ledger must always carry its evidence-boundary statement
    assert "do not validate claim correctness" in text
    assert len(render_tool_receipts(receipts, max_chars=10)) <= 14  # truncated + "\n..."
    for budget in range(5):
        assert len(render_tool_receipts(receipts, max_chars=budget)) <= budget


def test_render_budget_keeps_newest_receipts_with_original_ids():
    receipts = extract_tool_receipts([_stamped_msg(f"result-{index}", tool_call_id=f"tc-{index}", name=f"tool-{index}") for index in range(1, 13)])

    text = render_tool_receipts(receipts, max_chars=500)

    assert len(text) <= 500
    assert "[r12] tool-12" in text
    assert "[r1] tool-1" not in text
    assert "older receipts omitted" in text


def test_extract_skips_malformed_receipts():
    """Persisted/foreign receipt payloads must not crash or enter the ledger."""
    good = _stamped_msg("ok", tool_call_id="tc-good", name="bash")
    malformed = []
    for payload in [
        "not-a-dict",
        {},  # missing every field
        {"tool_call_id": "tc-1"},  # partial shape
        {**make_tool_receipt({"name": "t", "id": "tc-2", "args": {}}, _msg("x", tool_call_id="tc-2", name="t")), "output_bytes": "2"},  # wrong type
    ]:
        message = _msg("bad", tool_call_id="tc-bad", name="bash")
        message.additional_kwargs[TOOL_RECEIPT_KEY] = payload
        malformed.append(message)
    # A future-schema receipt (extra keys, valid core shape) must not crash
    # extraction either — its known fields are picked, unknown keys ignored.
    forward_compat = _msg("newer", tool_call_id="tc-newer", name="bash")
    forward_compat.additional_kwargs[TOOL_RECEIPT_KEY] = {
        **make_tool_receipt({"name": "bash", "id": "tc-newer", "args": {}}, forward_compat),
        "layer2_field": {"nested": True},
    }

    receipts = extract_tool_receipts([*malformed, good, forward_compat])

    assert [r["tool_call_id"] for r in receipts] == ["tc-good", "tc-newer"]
    assert [r["id"] for r in receipts] == ["r1", "r2"]
    # And the render path never sees a shape it can KeyError on.
    rendered = render_tool_receipts(receipts)
    assert "[r1] bash" in rendered and "[r2] bash" in rendered


def test_child_receipts_are_serialized_and_rendered_at_parent_boundary():
    child = _stamped_msg("child output", tool_call_id="child-1", name="write_file")
    serialized = [child.model_dump()]

    bundle = child_receipts_for_result(serialized)
    assert bundle and bundle[0]["id"] == "r1"

    parent = ToolMessage(
        content="Task Succeeded. Result: wrote the file [r1]",
        tool_call_id="parent-task-1",
        name="task",
        additional_kwargs={SUBAGENT_TOOL_RECEIPTS_KEY: bundle},
    )
    ledger = render_receipt_ledger([parent])
    assert "[task:parent-task-1/r1]" in ledger
    assert "child citation [r1]" in ledger
    assert "not proof of correctness or acceptance" in ledger


def test_child_receipt_bundle_is_bounded_and_rejects_malformed_entries():
    child = _stamped_msg("ok", tool_call_id="child-1", name="bash")
    valid = child.model_dump()
    malformed = {**valid, "additional_kwargs": {TOOL_RECEIPT_KEY: {"output_bytes": "not-an-int"}}}
    bundle = child_receipts_for_result([malformed, valid] * 300)
    assert len(bundle) == 256
    assert all(entry["tool_name"] == "bash" for entry in bundle)


def test_parent_ledger_retains_child_evidence_when_direct_history_is_large():
    direct = [_stamped_msg(f"result-{index}", tool_call_id=f"direct-{index}", name="bash") for index in range(1, 20)]
    child = _stamped_msg("child output", tool_call_id="child-1", name="write_file")
    parent = ToolMessage(
        content="Task Succeeded. Result: wrote the file [r1]",
        tool_call_id="parent-task-1",
        name="task",
        additional_kwargs={SUBAGENT_TOOL_RECEIPTS_KEY: child_receipts_for_result([child.model_dump()])},
    )

    ledger = render_receipt_ledger([*direct, parent], max_chars=500)

    assert len(ledger) <= 500
    assert "Subagent tool receipts" in ledger
    assert "[task:parent-task-1/r1]" in ledger


def test_parent_ledger_respects_tiny_budgets():
    child = _stamped_msg("child output", tool_call_id="child-1", name="write_file")
    parent = ToolMessage(
        content="Task Succeeded. Result: wrote the file [r1]",
        tool_call_id="parent-task-1",
        name="task",
        additional_kwargs={SUBAGENT_TOOL_RECEIPTS_KEY: child_receipts_for_result([child.model_dump()])},
    )

    for budget in range(6):
        assert len(render_receipt_ledger([parent], max_chars=budget)) <= budget
