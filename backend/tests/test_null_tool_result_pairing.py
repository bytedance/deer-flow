"""Missing call IDs must not swallow middleware-generated tool guidance."""

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_openai.chat_models.base import _convert_message_to_dict

from deerflow.agents.middlewares.dangling_tool_call_middleware import _ABSENT_TOOL_CALL_ID_SPELLINGS, DanglingToolCallMiddleware


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


@pytest.mark.parametrize("sentinel", sorted(_ABSENT_TOOL_CALL_ID_SPELLINGS))
def test_producer_sentinel_ids_pair_with_a_null_call_id(sentinel):
    """Producers spell a missing ID as "None" or a fallback sentinel, not ""."""
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


def _sandbox_audit_block(tool_call):
    from deerflow.agents.middlewares.sandbox_audit_middleware import SandboxAuditMiddleware

    return SandboxAuditMiddleware()._build_block_message(SimpleNamespace(tool_call=tool_call), "destructive command")


def _guardrail_denial(tool_call):
    from deerflow.guardrails.middleware import GuardrailMiddleware
    from deerflow.guardrails.provider import GuardrailDecision, GuardrailReason

    decision = GuardrailDecision(allow=False, reasons=[GuardrailReason(code="oap.denied", message="no")])
    return GuardrailMiddleware(provider=None)._build_denied_message(SimpleNamespace(tool_call=tool_call), decision)


def _read_before_write_denial(tool_call):
    from deerflow.agents.middlewares.read_before_write_middleware import ReadBeforeWriteMiddleware
    from deerflow.sandbox.exceptions import SandboxAuthorizationError

    return ReadBeforeWriteMiddleware._authorization_error_result(SimpleNamespace(tool_call=tool_call), SandboxAuthorizationError())


@pytest.mark.parametrize(
    "producer,id_key_present,expected_id",
    [
        (_sandbox_audit_block, True, "missing_id"),
        (_guardrail_denial, False, "missing_id"),
        (_guardrail_denial, True, "None"),
        (_read_before_write_denial, True, "missing-tool-call-id"),
    ],
    ids=["sandbox-audit", "guardrail-id-absent", "guardrail-id-null", "read-before-write"],
)
def test_producer_reply_for_a_null_call_id_survives_pairing(producer, id_key_present, expected_id):
    """Each producer's own missing-ID spelling must pair, so its reason reaches the model."""
    call = AIMessage(content="", tool_calls=[{"name": "bash", "id": None, "args": {"command": "rm -rf /"}}])
    tool_call = dict(call.tool_calls[0])
    if not id_key_present:
        tool_call.pop("id")
    result = producer(tool_call)
    patched = DanglingToolCallMiddleware()._build_patched_messages([call, result])

    assert result.tool_call_id == expected_id
    assert patched is not None
    assert len(patched) == 2
    assert patched[1].content == result.content
    wire_call, wire_result = map(_convert_message_to_dict, patched)
    assert wire_call["tool_calls"][0]["id"] == wire_result["tool_call_id"]


def _is_tool_call_id_get(node: ast.AST) -> bool:
    """Match ``<...>tool_call.get("id"[, default])``."""
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get"):
        return False
    if not (node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == "id"):
        return False
    receiver = node.func.value
    name = receiver.attr if isinstance(receiver, ast.Attribute) else getattr(receiver, "id", "")
    return name == "tool_call"


def _producer_id_fallbacks() -> dict[str, str]:
    """Every string a ``tool_call.get("id")`` fallback can produce, keyed by where it appears."""
    import deerflow

    package_root = Path(deerflow.__file__).parent
    found: dict[str, str] = {}
    for path in sorted(package_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        constants = {
            target.id: node.value.value for node in tree.body if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str) for target in node.targets if isinstance(target, ast.Name)
        }

        def resolve(value: ast.AST) -> str | None:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                return value.value
            if isinstance(value, ast.Name):
                return constants.get(value.id)
            return None

        for node in ast.walk(tree):
            fallback = None
            if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or) and _is_tool_call_id_get(node.values[0]):
                fallback = node.values[-1]
            elif _is_tool_call_id_get(node) and len(node.args) > 1:
                fallback = node.args[1]
            if fallback is not None and (spelling := resolve(fallback)):
                found[f"{path.relative_to(package_root).as_posix()}:{node.lineno}"] = spelling
    return found


def test_every_producer_missing_id_fallback_is_a_known_absent_spelling():
    """A new ``tool_call.get("id") or "..."`` sentinel must be added to the pairing set."""
    fallbacks = _producer_id_fallbacks()
    assert fallbacks, "scanner found no producers; the AST match has drifted"
    unknown = {where: spelling for where, spelling in fallbacks.items() if spelling and spelling not in _ABSENT_TOOL_CALL_ID_SPELLINGS}
    assert not unknown, f"add these to _ABSENT_TOOL_CALL_ID_SPELLINGS: {unknown}"
