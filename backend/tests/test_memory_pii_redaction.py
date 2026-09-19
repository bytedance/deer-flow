"""Memory-queue PII redaction (#3190 vector 5, follow-up to #5527)."""

from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime

from deerflow.agents.middlewares import memory_middleware as memory_middleware_module
from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware
from deerflow.agents.middlewares.pii_redaction_middleware import redact_text
from deerflow.config.memory_config import MemoryConfig
from deerflow.config.pii_redaction_config import PiiRedactionConfig

EMAIL_TOKEN = redact_text("alice@example.com", PiiRedactionConfig(enabled=True))


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
    mw, manager = _middleware(PiiRedactionConfig(enabled=True))
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
    mw, manager = _middleware(PiiRedactionConfig(enabled=True, redact_email=False))
    call = _run(mw, manager, monkeypatch, [HumanMessage("reach alice@example.com")])
    assert "alice@example.com" in call.args[1][0].content


def test_original_messages_not_mutated(monkeypatch):
    mw, manager = _middleware(PiiRedactionConfig(enabled=True))
    original = HumanMessage("reach alice@example.com")
    _run(mw, manager, monkeypatch, [original])
    assert original.content == "reach alice@example.com"


def test_same_value_shares_token_across_turns(monkeypatch):
    mw, manager = _middleware(PiiRedactionConfig(enabled=True))
    call = _run(
        mw,
        manager,
        monkeypatch,
        [HumanMessage("alice@example.com"), AIMessage("got alice@example.com")],
    )
    queued = call.args[1]
    assert queued[0].content == EMAIL_TOKEN
    assert EMAIL_TOKEN in queued[1].content
