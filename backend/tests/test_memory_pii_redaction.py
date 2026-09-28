"""Memory-queue PII redaction (#3190 vector 5, follow-up to #5527)."""

from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime

from deerflow.agents.human_input import HUMAN_INPUT_RESPONSE_KEY
from deerflow.agents.middlewares import memory_middleware as memory_middleware_module
from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware
from deerflow.agents.middlewares.pii_redaction_middleware import redact_text
from deerflow.config.memory_config import MemoryConfig
from deerflow.config.pii_redaction_config import PiiRedactionConfig
from deerflow.utils.messages import ORIGINAL_USER_CONTENT_KEY

_TOKEN_SECRET = "unit-test-deployment-secret-0123456789"

EMAIL_TOKEN = redact_text("alice@example.com", PiiRedactionConfig(enabled=True, token_secret=_TOKEN_SECRET))


def _middleware(pii_config):
    manager = MagicMock()
    mw = MemoryMiddleware(
        agent_name="researcher",
        memory_config=MemoryConfig(enabled=True),
        pii_redaction_config=pii_config,
    )
    return mw, manager


def _run(mw, manager, monkeypatch, messages):
    monkeypatch.setattr(memory_middleware_module, "get_memory_manager", lambda: manager)
    runtime = Runtime(context={"thread_id": "thread-123", "user_id": "runtime-user"})
    mw.after_agent({"messages": messages}, runtime)
    return manager.add.call_args


def test_queue_payload_redacted_when_enabled(monkeypatch):
    mw, manager = _middleware(PiiRedactionConfig(enabled=True, token_secret=_TOKEN_SECRET))
    call = _run(mw, manager, monkeypatch, [HumanMessage("reach alice@example.com"), AIMessage("noted")])
    queued = call.args[1]
    assert EMAIL_TOKEN in queued[0].content and "alice@example.com" not in queued[0].content
    assert queued[1].content == "noted"


def test_queue_payload_untouched_without_config(monkeypatch):
    mw, manager = _middleware(None)
    call = _run(mw, manager, monkeypatch, [HumanMessage("reach alice@example.com")])
    assert "alice@example.com" in call.args[1][0].content


def test_queue_payload_untouched_when_disabled(monkeypatch):
    mw, manager = _middleware(PiiRedactionConfig(enabled=False))
    call = _run(mw, manager, monkeypatch, [HumanMessage("reach alice@example.com")])
    assert "alice@example.com" in call.args[1][0].content


def test_detector_toggles_respected(monkeypatch):
    mw, manager = _middleware(PiiRedactionConfig(enabled=True, redact_email=False, token_secret=_TOKEN_SECRET))
    call = _run(mw, manager, monkeypatch, [HumanMessage("reach alice@example.com")])
    assert "alice@example.com" in call.args[1][0].content


def test_original_messages_not_mutated(monkeypatch):
    mw, manager = _middleware(PiiRedactionConfig(enabled=True, token_secret=_TOKEN_SECRET))
    original = HumanMessage("reach alice@example.com")
    _run(mw, manager, monkeypatch, [original])
    assert original.content == "reach alice@example.com"


def test_same_value_shares_token_across_turns(monkeypatch):
    mw, manager = _middleware(PiiRedactionConfig(enabled=True, token_secret=_TOKEN_SECRET))
    call = _run(
        mw,
        manager,
        monkeypatch,
        [HumanMessage("alice@example.com"), AIMessage("got alice@example.com")],
    )
    queued = call.args[1]
    assert queued[0].content == EMAIL_TOKEN
    assert EMAIL_TOKEN in queued[1].content


def test_existing_placeholder_in_later_message_keeps_identity_stable(monkeypatch):
    # Round-5 review on #5577: sequential numbering made an unchanged
    # message's token depend on batch contents (a higher existing placeholder
    # in a later batch would shift it, breaking OpenViking capture dedup).
    # Value-derived tokens keep the unchanged message's identity stable.
    mw, manager = _middleware(PiiRedactionConfig(enabled=True, token_secret=_TOKEN_SECRET))
    alice_token = redact_text("alice@example.com", PiiRedactionConfig(enabled=True, token_secret=_TOKEN_SECRET))
    messages = [
        HumanMessage("Bob's email is bob@example.com"),
        AIMessage(f"Alice's email is {alice_token} and Bob's email is [EMAIL_2]"),
    ]
    first = _run(mw, manager, monkeypatch, messages).args[1]
    second = _run(mw, manager, monkeypatch, messages).args[1]
    bob_token = redact_text("bob@example.com", PiiRedactionConfig(enabled=True, token_secret=_TOKEN_SECRET))
    assert first[0].content == f"Bob's email is {bob_token}"
    assert second[0].content == first[0].content
    assert f"Alice's email is {alice_token}" in first[1].content


def _flush_hook_call(monkeypatch, pii_config, messages):
    import deerflow.agents.memory.summarization_hook as hook_module
    from deerflow.agents.middlewares.summarization_middleware import SummarizationEvent

    manager = MagicMock()
    monkeypatch.setattr(hook_module, "get_memory_manager", lambda: manager)
    monkeypatch.setattr(hook_module, "resolve_runtime_user_id", lambda runtime: "u1")
    event = SummarizationEvent(
        messages_to_summarize=tuple(messages),
        preserved_messages=(),
        thread_id="thread-123",
        agent_name="researcher",
        runtime=None,
    )
    hook_module.memory_flush_hook(event, pii_redaction_config=pii_config)
    return manager.add_nowait.call_args.args[1]


def test_compaction_flush_hook_redacts_queued_payload(monkeypatch):
    # Review round 2 on #5577: the compaction-triggered memory_flush_hook
    # queues messages that compaction is about to remove from state, so the
    # after-agent redaction can never repair a raw batch queued here.
    queued = _flush_hook_call(
        monkeypatch,
        PiiRedactionConfig(enabled=True, token_secret=_TOKEN_SECRET),
        [HumanMessage("reach alice@example.com"), AIMessage("noted")],
    )
    assert EMAIL_TOKEN in queued[0].content and "alice@example.com" not in queued[0].content
    assert queued[1].content == "noted"


def test_compaction_flush_hook_untouched_without_config(monkeypatch):
    queued = _flush_hook_call(monkeypatch, None, [HumanMessage("reach alice@example.com")])
    assert "alice@example.com" in queued[0].content


def test_compaction_flush_hook_untouched_when_disabled(monkeypatch):
    queued = _flush_hook_call(monkeypatch, PiiRedactionConfig(enabled=False), [HumanMessage("reach alice@example.com")])
    assert "alice@example.com" in queued[0].content


def test_tool_call_args_redacted(monkeypatch):
    # OpenViking-style retention keeps the full message object, including
    # parsed tool_calls and provider-format arguments in additional_kwargs.
    mw, manager = _middleware(PiiRedactionConfig(enabled=True, token_secret=_TOKEN_SECRET))
    ai = AIMessage(
        content="",
        tool_calls=[{"name": "memory_search", "args": {"query": "alice@example.com"}, "id": "call_1"}],
        additional_kwargs={
            "tool_calls": [
                {"function": {"name": "memory_search", "arguments": '{"query": "alice@example.com"}'}},
            ],
        },
    )
    call = _run(mw, manager, monkeypatch, [HumanMessage("hi"), ai])
    queued = call.args[1][1]
    assert "alice@example.com" not in str(queued.tool_calls)
    assert EMAIL_TOKEN in str(queued.tool_calls)
    assert "alice@example.com" not in str(queued.additional_kwargs.get("tool_calls"))
    assert EMAIL_TOKEN in str(queued.additional_kwargs.get("tool_calls"))


def test_non_text_block_text_field_redacted(monkeypatch):
    # DeerMem's format_conversation_for_update reads the "text" value of any
    # dict block, not only type=="text" — the helper must follow.
    mw, manager = _middleware(PiiRedactionConfig(enabled=True, token_secret=_TOKEN_SECRET))
    call = _run(mw, manager, monkeypatch, [HumanMessage([{"type": "custom_card", "text": "alice@example.com"}])])
    block = call.args[1][0].content[0]
    assert block["text"] == EMAIL_TOKEN


def test_tool_argument_keys_redacted(monkeypatch):
    # Review round 6: tool arguments can carry user data in mapping keys.
    mw, manager = _middleware(PiiRedactionConfig(enabled=True, token_secret=_TOKEN_SECRET))
    ai = AIMessage(
        content="",
        tool_calls=[
            {"name": "memory_search", "args": {"contacts": {"alice@example.com": "manager"}}, "id": "call_1"},
        ],
    )
    call = _run(mw, manager, monkeypatch, [HumanMessage("hi"), ai])
    args = call.args[1][1].tool_calls[0]["args"]
    assert args["contacts"] == {EMAIL_TOKEN: "manager"}
    assert "alice@example.com" not in str(args)


def test_distinct_identities_keep_distinct_tokens():
    # Review round 6: a 24-bit truncation collided distinct identities; at
    # 128 bits the review's collision pair stays distinct, including when
    # both appear together in one message.
    cfg = PiiRedactionConfig(enabled=True, token_secret=_TOKEN_SECRET)
    a = redact_text("contact3513@example.com", cfg)
    b = redact_text("contact3727@example.com", cfg)
    assert a != b
    both = redact_text("contact3513@example.com and contact3727@example.com", cfg)
    assert a in both and b in both


def test_original_user_content_provenance_redacted(monkeypatch):
    # Review round 12 on #5577: UploadsMiddleware preserves the raw user turn
    # in additional_kwargs.original_user_content, so a redacted content alone
    # still leaks the raw value to the memory backend. The queued copy must
    # redact the provenance field too, and the thread-state message must stay
    # untouched.
    mw, manager = _middleware(PiiRedactionConfig(enabled=True, token_secret=_TOKEN_SECRET))
    original = HumanMessage("reach alice@example.com", additional_kwargs={ORIGINAL_USER_CONTENT_KEY: "reach alice@example.com"})
    _run(mw, manager, monkeypatch, [original])
    queued = manager.add.call_args.args[1][0]
    assert EMAIL_TOKEN in queued.content and "alice@example.com" not in queued.content
    assert EMAIL_TOKEN in queued.additional_kwargs[ORIGINAL_USER_CONTENT_KEY]
    assert "alice@example.com" not in queued.additional_kwargs[ORIGINAL_USER_CONTENT_KEY]
    assert original.additional_kwargs[ORIGINAL_USER_CONTENT_KEY] == "reach alice@example.com"
    assert original.content == "reach alice@example.com"


def test_original_user_content_redacted_in_compaction_flush_hook(monkeypatch):
    # Same provenance leak through the compaction-triggered hook, which shares
    # redact_queued_messages: one fix must cover both enqueues.
    queued = _flush_hook_call(
        monkeypatch,
        PiiRedactionConfig(enabled=True, token_secret=_TOKEN_SECRET),
        [HumanMessage("reach alice@example.com", additional_kwargs={ORIGINAL_USER_CONTENT_KEY: "reach alice@example.com"})],
    )
    assert EMAIL_TOKEN in queued[0].additional_kwargs[ORIGINAL_USER_CONTENT_KEY]
    assert "alice@example.com" not in queued[0].additional_kwargs[ORIGINAL_USER_CONTENT_KEY]


def _human_input_response(value: str) -> dict:
    return {
        "version": 1,
        "kind": "human_input_response",
        "source": "clarification",
        "request_id": "req-1",
        "response_kind": "text",
        "value": value,
    }


def test_human_input_response_value_redacted(monkeypatch):
    # Review round 13 on #5577: clarification replies keep the raw user answer
    # in additional_kwargs.human_input_response.value (DeerMem reads that
    # mapping), so the queued copy must redact the value while preserving the
    # protocol fields. The same message also carries original_user_content —
    # both rewrites must survive in one merged additional_kwargs update.
    mw, manager = _middleware(PiiRedactionConfig(enabled=True, token_secret=_TOKEN_SECRET))
    original = HumanMessage(
        "my email is alice@example.com",
        additional_kwargs={
            HUMAN_INPUT_RESPONSE_KEY: _human_input_response("my email is alice@example.com"),
            ORIGINAL_USER_CONTENT_KEY: "my email is alice@example.com",
        },
    )
    _run(mw, manager, monkeypatch, [original])
    queued = manager.add.call_args.args[1][0]
    assert EMAIL_TOKEN in queued.content and "alice@example.com" not in queued.content

    queued_response = queued.additional_kwargs[HUMAN_INPUT_RESPONSE_KEY]
    assert EMAIL_TOKEN in queued_response["value"] and "alice@example.com" not in queued_response["value"]
    assert queued_response["version"] == 1
    assert queued_response["kind"] == "human_input_response"
    assert queued_response["source"] == "clarification"
    assert queued_response["request_id"] == "req-1"
    assert queued_response["response_kind"] == "text"
    assert EMAIL_TOKEN in queued.additional_kwargs[ORIGINAL_USER_CONTENT_KEY]
    assert "alice@example.com" not in str(queued.additional_kwargs)

    assert original.additional_kwargs[HUMAN_INPUT_RESPONSE_KEY]["value"] == "my email is alice@example.com"
    assert original.additional_kwargs[ORIGINAL_USER_CONTENT_KEY] == "my email is alice@example.com"
    assert original.content == "my email is alice@example.com"


def test_human_input_response_redacted_in_compaction_flush_hook(monkeypatch):
    # Same leak through the compaction-triggered hook, which shares
    # redact_queued_messages: one fix must cover both enqueues.
    queued = _flush_hook_call(
        monkeypatch,
        PiiRedactionConfig(enabled=True, token_secret=_TOKEN_SECRET),
        [HumanMessage("my email is alice@example.com", additional_kwargs={HUMAN_INPUT_RESPONSE_KEY: _human_input_response("my email is alice@example.com")})],
    )
    assert EMAIL_TOKEN in queued[0].additional_kwargs[HUMAN_INPUT_RESPONSE_KEY]["value"]
    assert "alice@example.com" not in str(queued[0].additional_kwargs[HUMAN_INPUT_RESPONSE_KEY])
