"""Middleware wiring tests for lead final-answer evidence."""

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.middlewares.final_answer_evidence_middleware import DEDUPE_CAPACITY, FinalAnswerEvidenceMiddleware
from deerflow.runtime.context_keys import CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY


def _journal() -> MagicMock:
    return MagicMock()


def test_records_one_event_for_visible_terminal_answer():
    journal = _journal()
    runtime = SimpleNamespace(context={"__run_journal": journal, CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: frozenset()})
    message = AIMessage(id="final", content="I ran the tests.")
    state = {"messages": [HumanMessage(content="test"), message]}

    assert FinalAnswerEvidenceMiddleware().after_model(state, runtime) is None

    journal.record_final_answer_evidence.assert_called_once()
    evidence = journal.record_final_answer_evidence.call_args.args[0]
    assert evidence["status"] == "claims_without_matching_receipts"
    assert "secret" not in str(evidence)


def test_release_policy_dedupe_capacity_matches_runtime_bound():
    middleware = FinalAnswerEvidenceMiddleware()

    assert middleware.release_policy_parameters()["dedupe_capacity"] == DEDUPE_CAPACITY
    assert DEDUPE_CAPACITY > 0


def test_same_terminal_answer_is_recorded_once():
    journal = _journal()
    journal.run_id = "run-1"
    runtime = SimpleNamespace(context={"__run_journal": journal, "run_id": "run-1", CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: frozenset()})
    message = AIMessage(id="final", content="I ran the tests.")
    state = {"messages": [HumanMessage(content="test"), message]}
    middleware = FinalAnswerEvidenceMiddleware()

    middleware.after_model(state, runtime)
    middleware.after_model(state, runtime)

    journal.record_final_answer_evidence.assert_called_once()


def test_concurrent_async_hooks_record_the_same_answer_once():
    journal = _journal()
    journal.run_id = "run-1"
    runtime = SimpleNamespace(context={"__run_journal": journal, "run_id": "run-1", CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: frozenset()})
    middleware = FinalAnswerEvidenceMiddleware()
    state = {"messages": [AIMessage(id="final", content="I ran the tests.")]}

    async def invoke_twice():
        await asyncio.gather(middleware.aafter_model(state, runtime), middleware.aafter_model(state, runtime))

    asyncio.run(invoke_twice())

    journal.record_final_answer_evidence.assert_called_once()


def test_concurrent_thread_hooks_record_the_same_answer_once():
    journal = _journal()
    journal.run_id = "run-1"
    runtime = SimpleNamespace(context={"__run_journal": journal, CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: frozenset()})
    middleware = FinalAnswerEvidenceMiddleware()
    state = {"messages": [AIMessage(id="final", content="I ran the tests.")]}
    barrier = threading.Barrier(8)

    def invoke():
        barrier.wait()
        middleware.after_model(state, runtime)

    threads = [threading.Thread(target=invoke) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    journal.record_final_answer_evidence.assert_called_once()


def test_cross_thread_middleware_records_on_the_journal_owner_loop():
    from deerflow.runtime.events.store.memory import MemoryRunEventStore
    from deerflow.runtime.journal import RunJournal

    store = MemoryRunEventStore()
    journal = RunJournal("run-1", "thread-1", store, flush_threshold=1)

    async def exercise():
        runtime = SimpleNamespace(context={"__run_journal": journal, CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: frozenset()})
        state = {"messages": [AIMessage(id="final", content="I ran the tests.")]}
        await asyncio.to_thread(lambda: FinalAnswerEvidenceMiddleware().after_model(state, runtime))
        await asyncio.sleep(0)
        await journal.flush()

    asyncio.run(exercise())
    events = asyncio.run(store.list_events("thread-1", "run-1", event_types=["run.answer_evidence"]))
    assert len(events) == 1


def test_cross_thread_owner_loop_dispatch_actually_records():
    """The error-swallowing middleware must not hide a broken dispatch path."""
    from deerflow.runtime.events.store.memory import MemoryRunEventStore
    from deerflow.runtime.journal import RunJournal

    store = MemoryRunEventStore()

    async def exercise():
        journal = RunJournal("run-1", "thread-1", store, flush_threshold=1)
        await asyncio.to_thread(
            journal.record_final_answer_evidence,
            {"schema": "deerflow.final_answer_evidence.v1", "status": "no_action_claims"},
        )
        await asyncio.sleep(0)
        await journal.flush()

    asyncio.run(exercise())
    events = asyncio.run(store.list_events("thread-1", "run-1", event_types=["run.answer_evidence"]))
    assert len(events) == 1


def test_accepted_cross_thread_event_survives_producer_freeze():
    """An admitted callback must be drained even after producers stop accepting."""
    from functools import partial

    from deerflow.runtime.events.store.memory import MemoryRunEventStore
    from deerflow.runtime.journal import RunJournal

    store = MemoryRunEventStore()

    async def exercise():
        journal = RunJournal("run-1", "thread-1", store, flush_threshold=100)
        loop = asyncio.get_running_loop()
        original_schedule = loop.call_soon_threadsafe
        scheduled = []

        def capture_callback(callback, *args, context=None):
            if isinstance(callback, partial) and getattr(callback.func, "__name__", None) == "_record_admitted_producer_event":
                scheduled.append(callback)
                return
            original_schedule(callback, *args, context=context)

        loop.call_soon_threadsafe = capture_callback
        try:
            await asyncio.to_thread(
                journal.record_final_answer_evidence,
                {"schema": "deerflow.final_answer_evidence.v1", "status": "no_action_claims"},
            )
            assert len(scheduled) == 1
            assert journal._pending_producer_callbacks == 1

            # Freeze new producers, then deliver the callback that was already admitted.
            stop = asyncio.create_task(journal._stop_evidence_producers())
            await asyncio.sleep(0)
            assert not journal._accepting_evidence
            scheduled[0]()
            await asyncio.wait_for(stop, timeout=1)
        finally:
            loop.call_soon_threadsafe = original_schedule
        await journal.flush()

    asyncio.run(exercise())
    events = asyncio.run(store.list_events("thread-1", "run-1", event_types=["run.answer_evidence"]))
    assert len(events) == 1


def test_cross_thread_record_after_owner_loop_shutdown_is_dropped(caplog):
    from deerflow.runtime.events.store.memory import MemoryRunEventStore
    from deerflow.runtime.journal import RunJournal

    async def create_closed_journal():
        journal = RunJournal("run-1", "thread-1", MemoryRunEventStore(), flush_threshold=1)
        loop = asyncio.get_running_loop()
        loop.stop()
        return journal

    journal = asyncio.run(create_closed_journal())
    journal.record_final_answer_evidence({"schema": "deerflow.final_answer_evidence.v1"})

    assert "Dropping cross-thread final-answer evidence" in caplog.text


def test_real_lead_chain_records_receipt_evidence_without_message_content():
    from langchain.agents import create_agent
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.tools import StructuredTool

    from deerflow.agents.lead_agent.agent import build_middlewares
    from deerflow.agents.thread_state import ThreadState
    from deerflow.config.app_config import AppConfig
    from deerflow.runtime.events.store.memory import MemoryRunEventStore
    from deerflow.runtime.journal import RunJournal

    class FakeModel(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    store = MemoryRunEventStore()
    journal = RunJournal("run-1", "thread-1", store, flush_threshold=100)
    app_config = AppConfig.model_validate({"sandbox": {"use": "test"}, "read_before_write": {"enabled": False}})
    middlewares = build_middlewares({}, None, app_config=app_config)
    model = FakeModel(
        messages=iter(
            [
                AIMessage(content="", tool_calls=[{"name": "write_file", "args": {"path": "/mnt/user-data/outputs/private.md", "content": "private"}, "id": "call-1"}]),
                AIMessage(content="I wrote the report.", id="final"),
            ]
        )
    )
    graph = create_agent(model=model, tools=[StructuredTool.from_function(_write_file, name="write_file")], middleware=middlewares, state_schema=ThreadState)

    async def exercise():
        await graph.ainvoke(
            {"messages": [HumanMessage(id="old", content="old"), HumanMessage(content="write the report")]},
            {"configurable": {"thread_id": "thread-1"}},
            context={"__run_journal": journal, CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: frozenset({"old"})},
        )
        await journal.flush()

    asyncio.run(exercise())
    events = asyncio.run(store.list_events("thread-1", "run-1", event_types=["run.answer_evidence"]))

    assert len(events) == 1
    evidence = events[0]["content"]
    assert evidence["status"] == "matching_receipts_observed"
    assert evidence["lead_receipts"]["by_category"] == {"file_write": 1}
    assert "private" not in str(evidence)


def test_real_lead_chain_does_not_treat_a_blocked_write_as_evidence():
    from langchain.agents import create_agent
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.tools import StructuredTool

    from deerflow.agents.lead_agent.agent import build_middlewares
    from deerflow.agents.thread_state import ThreadState
    from deerflow.config.app_config import AppConfig
    from deerflow.runtime.events.store.memory import MemoryRunEventStore
    from deerflow.runtime.journal import RunJournal

    class FakeModel(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    store = MemoryRunEventStore()
    journal = RunJournal("run-1", "thread-1", store, flush_threshold=100)
    app_config = AppConfig.model_validate({"sandbox": {"use": "test"}})
    middlewares = build_middlewares({}, None, app_config=app_config)
    read_before_write = next(item for item in middlewares if type(item).__name__ == "ReadBeforeWriteMiddleware")
    read_before_write._content_reader = lambda _runtime, _path: "existing content"
    model = FakeModel(
        messages=iter(
            [
                AIMessage(content="", tool_calls=[{"name": "write_file", "args": {"path": "/mnt/user-data/outputs/private.md", "content": "private"}, "id": "call-1"}]),
                AIMessage(content="I wrote the report.", id="final"),
            ]
        )
    )
    graph = create_agent(model=model, tools=[StructuredTool.from_function(_write_file, name="write_file")], middleware=middlewares, state_schema=ThreadState)

    async def exercise():
        await graph.ainvoke(
            {"messages": [HumanMessage(content="write the report")]},
            {"configurable": {"thread_id": "thread-1"}},
            context={"__run_journal": journal, CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: frozenset()},
        )
        await journal.flush()

    asyncio.run(exercise())
    events = asyncio.run(store.list_events("thread-1", "run-1", event_types=["run.answer_evidence"]))

    evidence = events[0]["content"]
    assert evidence["status"] == "claims_without_matching_receipts"
    assert evidence["lead_receipts"]["status_counts"] == {"error": 1}


def _write_file(path: str, content: str) -> str:
    """Write a private test file."""
    return "written"


def test_record_failure_is_logged_and_not_cached_as_emitted(caplog):
    journal = _journal()
    journal.run_id = "run-1"
    journal.record_final_answer_evidence.side_effect = RuntimeError("store unavailable")
    runtime = SimpleNamespace(context={"__run_journal": journal, CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: frozenset()})
    middleware = FinalAnswerEvidenceMiddleware()
    state = {"messages": [AIMessage(id="final", content="I ran the tests.")]}

    middleware.after_model(state, runtime)
    middleware.after_model(state, runtime)

    assert journal.record_final_answer_evidence.call_count == 2
    assert "Failed to record run.answer_evidence event" in caplog.text


def test_distinct_terminal_answers_in_same_run_are_both_recorded():
    journal = _journal()
    runtime = SimpleNamespace(context={"__run_journal": journal, "run_id": "run-1", CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: frozenset()})
    middleware = FinalAnswerEvidenceMiddleware()

    middleware.after_model({"messages": [AIMessage(id="first", content="First answer.")]}, runtime)
    middleware.after_model({"messages": [AIMessage(id="second", content="Second answer.")]}, runtime)

    assert journal.record_final_answer_evidence.call_count == 2


def test_distinct_visible_ai_messages_are_not_collapsed_by_content_hash():
    journal = _journal()
    journal.run_id = "run-1"
    runtime = SimpleNamespace(context={"__run_journal": journal, CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: frozenset()})
    middleware = FinalAnswerEvidenceMiddleware()

    middleware.after_model({"messages": [AIMessage(content="Done.")]}, runtime)
    middleware.after_model({"messages": [AIMessage(content="Done.")]}, runtime)

    assert journal.record_final_answer_evidence.call_count == 2


def test_missing_run_id_does_not_cross_dedupe_identical_answers():
    journal = _journal()
    runtime = SimpleNamespace(context={"__run_journal": journal})
    middleware = FinalAnswerEvidenceMiddleware()
    state = {"messages": [AIMessage(id="final", content="Same answer.")]}

    middleware.after_model(state, runtime)
    middleware.after_model(state, runtime)

    assert journal.record_final_answer_evidence.call_count == 2


def test_dedupe_uses_the_journal_run_identity_not_context_metadata():
    journal = _journal()
    journal.run_id = "authoritative-run"
    runtime = SimpleNamespace(context={"__run_journal": journal, "run_id": "caller-controlled"})
    middleware = FinalAnswerEvidenceMiddleware()
    state = {"messages": [AIMessage(id="final", content="I ran the tests.")]}

    middleware.after_model(state, runtime)
    middleware.after_model(state, runtime)

    journal.record_final_answer_evidence.assert_called_once()


def test_journal_persists_the_event_with_the_dynamic_contract():
    from deerflow.runtime.events.store.memory import MemoryRunEventStore
    from deerflow.runtime.journal import RunJournal

    store = MemoryRunEventStore()
    journal = RunJournal("run-1", "thread-1", store, flush_threshold=100)
    runtime = SimpleNamespace(context={"__run_journal": journal, "run_id": "run-1", CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: frozenset()})
    state = {"messages": [HumanMessage(content="test"), AIMessage(id="final", content="I ran the tests.")]}

    FinalAnswerEvidenceMiddleware().after_model(state, runtime)
    asyncio.run(journal.flush())
    events = asyncio.run(store.list_events("thread-1", "run-1"))

    assert [event["event_type"] for event in events] == ["run.answer_evidence"]
    content = events[0]["content"]
    assert content["schema"] == "deerflow.final_answer_evidence.v1"
    assert content["coverage"] == "current_run_visible"


def test_skips_tool_call_and_empty_messages():
    journal = _journal()
    runtime = SimpleNamespace(context={"__run_journal": journal})
    for message in (AIMessage(content="", tool_calls=[{"name": "bash", "args": {}, "id": "c"}]), AIMessage(content="   ")):
        assert FinalAnswerEvidenceMiddleware().after_model({"messages": [message]}, runtime) is None
    journal.record_final_answer_evidence.assert_not_called()


def test_missing_journal_is_a_noop():
    assert FinalAnswerEvidenceMiddleware().after_model({"messages": [AIMessage(content="done")]}, SimpleNamespace(context={})) is None


def test_receipts_disabled_omits_middleware_from_lead_chain():
    from deerflow.agents.lead_agent.agent import build_middlewares
    from deerflow.config.app_config import AppConfig

    app_config = AppConfig.model_validate({"sandbox": {"use": "test"}, "verification": {"receipts_enabled": False}})
    middlewares = build_middlewares({}, None, app_config=app_config)

    assert "FinalAnswerEvidenceMiddleware" not in [type(item).__name__ for item in middlewares]


def test_receipts_enabled_registers_middleware_on_lead_only():
    from deerflow.agents.lead_agent.agent import build_middlewares
    from deerflow.agents.middlewares.tool_error_handling_middleware import build_subagent_runtime_middlewares
    from deerflow.config.app_config import AppConfig

    app_config = AppConfig.model_validate({"sandbox": {"use": "test"}})
    lead_middlewares = build_middlewares({}, None, app_config=app_config)
    lead_names = [type(item).__name__ for item in lead_middlewares]
    subagent_names = [type(item).__name__ for item in build_subagent_runtime_middlewares(app_config=app_config)]

    assert "FinalAnswerEvidenceMiddleware" in lead_names
    assert "FinalAnswerEvidenceMiddleware" not in subagent_names
    assert type(lead_middlewares[0]).__name__ == "InputSanitizationMiddleware"
    safety_name = "SafetyFinishReasonMiddleware"
    assert safety_name in lead_names
    assert lead_names.index(safety_name) < lead_names.index("FinalAnswerEvidenceMiddleware")
    assert lead_names.index("FinalAnswerEvidenceMiddleware") < lead_names.index("ClarificationMiddleware")


def test_subagent_chain_does_not_get_final_answer_evidence_even_with_receipts_enabled():
    from deerflow.agents.middlewares.tool_error_handling_middleware import build_subagent_runtime_middlewares
    from deerflow.config.app_config import AppConfig

    app_config = AppConfig.model_validate({"sandbox": {"use": "test"}, "verification": {"receipts_enabled": True}})
    subagent_names = [type(item).__name__ for item in build_subagent_runtime_middlewares(app_config=app_config)]

    assert "ToolReceiptMiddleware" in subagent_names
    assert "FinalAnswerEvidenceMiddleware" not in subagent_names


def test_real_graph_records_only_the_terminal_visible_answer():
    from langchain.agents import create_agent
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

    from deerflow.agents.thread_state import ThreadState

    class FakeModel(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    model = FakeModel(
        messages=iter(
            [
                AIMessage(content="", tool_calls=[{"name": "lookup", "args": {"query": "private"}, "id": "call-1"}]),
                AIMessage(content="I searched the source and found the answer.", id="final"),
            ]
        )
    )
    journal = _journal()
    graph = create_agent(
        model=model,
        tools=[_lookup],
        middleware=[FinalAnswerEvidenceMiddleware()],
        state_schema=ThreadState,
    )

    asyncio.run(
        graph.ainvoke(
            {"messages": [HumanMessage(content="search")]},
            {"configurable": {"thread_id": "answer-evidence-real-graph"}},
            context={"__run_journal": journal, CURRENT_RUN_PRE_EXISTING_MESSAGE_IDS_KEY: frozenset()},
        )
    )

    journal.record_final_answer_evidence.assert_called_once()
    changes = journal.record_final_answer_evidence.call_args.args[0]
    assert changes["status"] in {"matching_receipts_observed", "claims_without_matching_receipts"}
    assert "private" not in str(changes)


def test_evidence_observes_a_later_after_model_rewrite():
    from langchain.agents import create_agent
    from langchain.agents.middleware import AgentMiddleware
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

    from deerflow.agents.thread_state import ThreadState

    class RewriteMiddleware(AgentMiddleware):
        def after_model(self, state, runtime):
            message = state["messages"][-1]
            return {"messages": [message.model_copy(update={"content": "I ran the tests."})]}

    class FakeModel(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    model = FakeModel(messages=iter([AIMessage(content="The answer is 42.", id="final")]))
    journal = _journal()
    graph = create_agent(
        model=model,
        tools=[],
        middleware=[FinalAnswerEvidenceMiddleware(), RewriteMiddleware()],
        state_schema=ThreadState,
    )

    asyncio.run(
        graph.ainvoke(
            {"messages": [HumanMessage(content="test")]},
            {"configurable": {"thread_id": "answer-evidence-rewrite"}},
            context={"__run_journal": journal, "run_id": "run-rewrite"},
        )
    )

    journal.record_final_answer_evidence.assert_called_once()
    evidence = journal.record_final_answer_evidence.call_args.args[0]
    assert evidence["claimed_action_categories"] == ["command_execution"]


def _lookup(query: str) -> str:
    """Look up one private test value."""
    return f"result for {query}"
