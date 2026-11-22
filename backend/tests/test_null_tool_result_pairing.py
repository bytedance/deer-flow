"""Missing call IDs must not swallow middleware-generated tool guidance."""

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_openai.chat_models.base import _convert_message_to_dict

from deerflow.agents.middlewares.dangling_tool_call_middleware import DanglingToolCallMiddleware


@pytest.mark.parametrize("call_id,result_id", [(None, ""), ("", None), (None, None), ("", "")])
def test_missing_ids_preserve_result_and_provider_pairing(call_id, result_id):
    call = AIMessage(content="", tool_calls=[{"name": "write_file", "id": call_id, "args": {"path": "a.md"}}])
    # Normal middleware replies use ""; model_construct also covers old None-ID history.
    constructor = ToolMessage.model_construct if result_id is None else ToolMessage
    result = constructor(content="Error: read the file before writing it", tool_call_id=result_id, name="write_file", status="error")
    patched = DanglingToolCallMiddleware()._build_patched_messages([call, result])

    assert patched is not None
    assert len(patched) == 2
    assert patched[1].content == result.content
    assert patched[1].status == "error"
    wire_call, wire_result = map(_convert_message_to_dict, patched)
    assert wire_call["tool_calls"][0]["id"] == wire_result["tool_call_id"]
    assert wire_result["tool_call_id"]
    assert call.tool_calls[0]["id"] == call_id
    assert result.tool_call_id == result_id


def test_mixed_missing_ids_keep_partial_same_name_results_ambiguous():
    call = AIMessage(content="", tool_calls=[{"name": "bash", "id": call_id, "args": {}} for call_id in (None, "")])
    result = ToolMessage(content="UNATTRIBUTABLE", tool_call_id="", name="bash")
    patched = DanglingToolCallMiddleware()._build_patched_messages([call, result])

    assert patched is not None
    assert all(message.content != "UNATTRIBUTABLE" for message in patched[1:])
    assert len(patched[1:]) == 2
    assert all(message.status == "error" for message in patched[1:])


def test_missing_id_does_not_override_a_different_tool_name():
    call = AIMessage(content="", tool_calls=[{"name": "write_file", "id": None, "args": {}}])
    result = ToolMessage(content="UNRELATED", tool_call_id="", name="bash")
    patched = DanglingToolCallMiddleware()._build_patched_messages([call, result])

    assert patched is not None
    assert patched[1].content != "UNRELATED"
    assert patched[1].status == "error"


def test_mixed_missing_ids_complete_parallel_turn_keeps_input_order():
    call = AIMessage(content="", tool_calls=[{"name": "bash", "id": call_id, "args": {}} for call_id in (None, "")])
    replies = [ToolMessage(content=text, tool_call_id="", name="bash") for text in ("FIRST", "SECOND")]
    patched = DanglingToolCallMiddleware()._build_patched_messages([call, *replies])

    assert patched is not None
    assert [message.content for message in patched[1:]] == ["FIRST", "SECOND"]
    assert [message.tool_call_id for message in patched[1:]] == [tc["id"] for tc in patched[0].tool_calls]


@pytest.mark.parametrize("sentinel", ["None", "missing_tool_call_id"])
def test_producer_sentinel_ids_pair_with_a_null_call_id(sentinel):
    """Producers spell a missing ID as "None" or "missing_tool_call_id", not ""."""
    call = AIMessage(content="", tool_calls=[{"name": "write_file", "id": None, "args": {"path": "a.md"}}])
    result = ToolMessage(content="Error: read the file before writing it", tool_call_id=sentinel, name="write_file", status="error")
    patched = DanglingToolCallMiddleware()._build_patched_messages([call, result])

    assert patched is not None
    assert len(patched) == 2
    assert patched[1].content == result.content
    assert patched[1].status == "error"
    wire_call, wire_result = map(_convert_message_to_dict, patched)
    assert wire_call["tool_calls"][0]["id"] == wire_result["tool_call_id"]


def test_producer_sentinel_pairing_does_not_invent_one_for_a_valid_id():
    """A sentinel result must not steal the slot of a call that does have an ID."""
    call = AIMessage(content="", tool_calls=[{"name": "write_file", "id": "call_1", "args": {}}])
    result = ToolMessage(content="UNRELATED", tool_call_id="missing_tool_call_id", name="write_file")
    patched = DanglingToolCallMiddleware()._build_patched_messages([call, result])

    assert patched is not None
    assert patched[1].content != "UNRELATED"
    assert patched[1].status == "error"


def test_producer_sentinels_complete_a_parallel_turn_in_input_order():
    """Mixed call spellings plus sentinel results: order still identifies the calls."""
    call = AIMessage(content="", tool_calls=[{"name": "bash", "id": call_id, "args": {}} for call_id in (None, "")])
    replies = [ToolMessage(content=text, tool_call_id="missing_tool_call_id", name="bash") for text in ("FIRST", "SECOND")]
    patched = DanglingToolCallMiddleware()._build_patched_messages([call, *replies])

    assert patched is not None
    assert [message.content for message in patched[1:]] == ["FIRST", "SECOND"]
    assert [message.tool_call_id for message in patched[1:]] == [tc["id"] for tc in patched[0].tool_calls]
