import asyncio
import importlib
import re
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import NotRequired
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from langchain.agents import AgentState, create_agent
from langchain.agents.middleware import wrap_tool_call
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.errors import NodeCancelledError
from langgraph.types import Command

from deerflow.agents.factory import create_deerflow_agent
from deerflow.agents.features import RuntimeFeatures
from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware
from deerflow.agents.thread_state import BatchReceiptState, adapt_state_schema_for_mode, normalize_middleware_state_schemas
from deerflow.config.app_config import AppConfig
from deerflow.config.database_config import DatabaseConfig
from deerflow.config.subagent_batches_config import SubagentBatchesConfig
from deerflow.config.subagent_runtime_config import SubagentRuntimeConfig
from deerflow.mcp_scope import (
    THREAD_INCARNATION_CONTEXT_KEY,
    THREAD_INCARNATION_METADATA_GUARD_KEY,
)
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.subagent_batches import SubagentBatchRepository
from deerflow.runtime.checkpoint_mode import inject_checkpoint_mode
from deerflow.subagents.batch_runtime import BATCH_SUBMISSION_DIGEST_KEY, COMPACTED_BATCH_RECEIPTS_CHANNEL
from deerflow.subagents.batch_service import SubagentBatchService
from deerflow.subagents.config import SubagentConfig
from deerflow.subagents.runtime import SubagentRuntime
from deerflow.tools.builtins.batch_task_tool import BatchTaskItem

tool_module = importlib.import_module("deerflow.tools.builtins.batch_task_tool")
_MISSING = object()


def _runtime(thread_incarnation=_MISSING, *, call_id="call-1"):
    context = {
        "thread_id": "thread-1",
        "run_id": "run-1",
        "user_id": "user-1",
        "user_role": "member",
        "__knowledge_scope_execution": {
            "version": 1,
            "mode": "selected",
            "dataset_ids": ["dataset-1"],
        },
    }
    if thread_incarnation is not _MISSING:
        context[THREAD_INCARNATION_CONTEXT_KEY] = thread_incarnation
    return SimpleNamespace(
        state={"messages": [_dispatch(1, call_id=call_id)]},
        context=context,
        config={
            "metadata": {
                "model_name": "model-a",
                "allowed_subagents": ["general-purpose"],
                "tool_groups": ["web"],
                "mcp_plugins": ["stable-plugin"],
            },
            "configurable": {"thread_id": "thread-1"},
        },
    )


def _message(command: Command) -> ToolMessage:
    messages = command.update["messages"]
    assert len(messages) == 1 and isinstance(messages[0], ToolMessage)
    return messages[0]


class _ScriptedModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


class _CompactionState(AgentState):
    summary_text: NotRequired[str]


class _BatchCompactionState(BatchReceiptState, _CompactionState):
    pass


def _dispatch(job: int, *, call_id: str = "call_0") -> AIMessage:
    return AIMessage(
        content="",
        id=f"ai-{job}",
        tool_calls=[{"name": "batch_task", "id": call_id, "args": {"title": f"Job {job}", "items": [{"key": f"job-{job}", "prompt": f"Do job {job}"}], "subagent_type": "general-purpose"}}],
    )


@pytest_asyncio.fixture
async def batch_service(monkeypatch, tmp_path):
    _mock_subagent_catalog(monkeypatch)
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    try:
        repository = SubagentBatchRepository(get_session_factory())
        service = SubagentBatchService(repository=repository, config=SubagentBatchesConfig(), runtime_config=SubagentRuntimeConfig())
        yield service, repository
    finally:
        await close_engine()


@pytest.mark.asyncio
@pytest.mark.parametrize("sdk", [False, True], ids=["one-run", "sdk-invocations"])
async def test_reused_call_id_submits_both_model_responses(batch_service, sdk) -> None:
    service, repository = batch_service
    final = AIMessage(content="Done", id="ai-final")
    responses = [_dispatch(1), AIMessage(content="First done", id="ai-first-done"), _dispatch(2), final] if sdk else [_dispatch(1), _dispatch(2), final]
    model = _ScriptedModel(messages=iter(responses))
    checkpointer = InMemorySaver()
    if sdk:
        runtime = SubagentRuntime(
            SubagentRuntimeConfig(),
            batch_submitter=service,
            app_config=AppConfig(sandbox={"use": "deerflow.sandbox.local:LocalSandboxProvider"}),
        )
        graph = create_deerflow_agent(model, features=RuntimeFeatures(subagent=True, sandbox=False, loop_detection=False), subagent_runtime=runtime, checkpointer=checkpointer)
    else:
        graph = create_agent(model=model, tools=tool_module.bind_batch_tools(service), checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "thread-1"}}
    context = {"user_id": "user-1"} if sdk else {"user_id": "user-1", "run_id": "run-1"}
    state = await graph.ainvoke({"messages": [HumanMessage("Submit jobs")]}, config, context=context)
    if sdk:
        state = await graph.ainvoke({"messages": [HumanMessage("Submit another job")]}, config, context=context)

    receipts = [message for message in state["messages"] if isinstance(message, ToolMessage)]
    assert [(receipt.tool_call_id, receipt.status) for receipt in receipts] == [("call_0", "success"), ("call_0", "success")]
    batch_ids = [receipt.additional_kwargs["subagent_batch_id"] for receipt in receipts]
    batches = await repository.list_by_thread("thread-1", user_id="user-1")
    assert len(batches) == 2, f"Received two successful receipts for {batch_ids}, but stored {len(batches)} batch(es)"
    assert {batch["id"] for batch in batches} == set(batch_ids)
    for job, batch_id in enumerate(batch_ids, start=1):
        items = await repository.list_items(batch_id, user_id="user-1", include_prompt=True)
        assert [(item["batch_id"], item["item_key"], item["prompt"]) for item in items] == [(batch_id, f"job-{job}", f"Do job {job}")]


@pytest.mark.asyncio
async def test_checkpoint_replay_under_new_run_returns_original_batch(batch_service) -> None:
    service, repository = batch_service
    receipts = []

    @wrap_tool_call
    async def lose_first_receipt(request, handler):
        command = await handler(request)
        receipts.append(_message(command))
        if len(receipts) == 1:
            raise RuntimeError("Lost receipt before checkpoint")
        return command

    graph = create_agent(
        model=_ScriptedModel(messages=iter([_dispatch(1), AIMessage(content="Done")])),
        tools=tool_module.bind_batch_tools(service),
        checkpointer=InMemorySaver(),
        middleware=[lose_first_receipt],
    )
    config = {"configurable": {"thread_id": "thread-1"}}
    with pytest.raises(RuntimeError, match="Lost receipt before checkpoint"):
        await graph.ainvoke({"messages": [HumanMessage("Submit job")]}, config, context={"user_id": "user-1", "run_id": "run-1"})
    state = await graph.ainvoke(None, config, context={"user_id": "user-1", "run_id": "resumed-run"})

    assert [receipt.status for receipt in receipts] == ["success", "success"]
    batch_id = receipts[0].additional_kwargs["subagent_batch_id"]
    assert [message.additional_kwargs["subagent_batch_id"] for message in state["messages"] if isinstance(message, ToolMessage)] == [batch_id]
    assert [batch["id"] for batch in await repository.list_by_thread("thread-1", user_id="user-1")] == [batch_id]
    assert [item["item_key"] for item in await repository.list_items(batch_id, user_id="user-1")] == ["job-1"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scenario", "checkpoint_mode", "durability"),
    [
        pytest.param("unconfirmed-replay", "full", "async", id="unconfirmed-replay"),
        pytest.param("unconfirmed-replay-with-sibling", "full", "async", id="unconfirmed-replay-with-sibling"),
        pytest.param("later-response", "full", "async", id="later-response"),
        pytest.param("compacted-response", "full", "async", id="compacted-response"),
        pytest.param("compacted-before-upgrade", "full", "async", id="compacted-before-upgrade"),
        pytest.param("compacted-before-upgrade", "delta", "async", id="compacted-before-upgrade-delta"),
        pytest.param("compacted-before-upgrade", "full", "exit", id="compacted-before-upgrade-full-exit"),
        pytest.param("compacted-before-upgrade", "delta", "exit", id="compacted-before-upgrade-delta-exit"),
        pytest.param("unconfirmed-replay", "full", "exit", id="unconfirmed-replay-full-exit"),
        pytest.param("unconfirmed-replay-with-sibling", "full", "exit", id="unconfirmed-replay-with-sibling-full-exit"),
        pytest.param("unconfirmed-replay-with-sibling", "delta", "exit", id="unconfirmed-replay-with-sibling-delta-exit"),
    ],
)
@pytest.mark.parametrize("run_id", ["original-run", None], ids=["gateway-key", "sdk-key"])
async def test_upgrade_recovers_legacy_checkpoint_without_duplicate_batches(batch_service, monkeypatch, tmp_path, scenario, checkpoint_mode, durability, run_id):
    service, repository = batch_service
    confirm_in_sibling = scenario == "unconfirmed-replay-with-sibling"
    lost_receipt = scenario == "unconfirmed-replay" or confirm_in_sibling
    drop_receipt = lost_receipt
    compact_history = scenario == "compacted-response"
    compact_before_upgrade = scenario == "compacted-before-upgrade"
    config = {"configurable": {"thread_id": "thread-1"}}
    inject_checkpoint_mode(config, checkpoint_mode)
    resume_config = config
    schema = adapt_state_schema_for_mode(_CompactionState, checkpoint_mode)
    context = {"user_id": "user-1", "run_id": run_id}
    checkpoint_path = str(tmp_path / "legacy-checkpoints.sqlite")
    create_batch = repository.create_batch

    def summarization():
        return DeerFlowSummarizationMiddleware(
            model=_ScriptedModel(messages=iter([AIMessage(content="Earlier work summarized")])),
            trigger=("messages", 5),
            keep=("messages", 1),
            token_counter=len,
        )

    async def write_legacy_batch(**kwargs):
        # Keep a digest only for the sibling fixture so SQL can return the same
        # row for that identical request under the old key.
        if not confirm_in_sibling:
            kwargs.pop("submission_digest", None)
            kwargs["execution_spec"].pop(BATCH_SUBMISSION_DIGEST_KEY, None)
        kwargs["submission_key"] = f"{kwargs['run_id'] or kwargs['thread_id']}:{kwargs['tool_call_id']}"
        return await create_batch(**kwargs)

    @wrap_tool_call
    async def legacy_tool_call(request, handler):
        nonlocal drop_receipt
        receipt = _message(await handler(request))
        assert receipt.status == "success"
        if drop_receipt:
            drop_receipt = False
            raise RuntimeError("Lost legacy receipt before checkpoint")
        return Command(update={"messages": [receipt]})

    with monkeypatch.context() as legacy:
        legacy.setattr(repository, "create_batch", write_legacy_batch)
        legacy.setattr(repository, "find_submission", None)
        legacy_responses = [_dispatch(1), AIMessage(content="Done")]
        legacy_middleware = [legacy_tool_call]
        if compact_before_upgrade:
            legacy.setattr("deerflow.agents.middlewares.summarization_middleware.compacted_batch_receipt_update", lambda *_: {})
            legacy_middleware.append(summarization())
            legacy_responses.append(AIMessage(content="Acknowledged"))
        async with AsyncSqliteSaver.from_conn_string(checkpoint_path) as saver:
            graph = create_agent(
                model=_ScriptedModel(messages=iter(legacy_responses)),
                tools=tool_module.bind_batch_tools(service),
                checkpointer=saver,
                middleware=normalize_middleware_state_schemas(legacy_middleware, checkpoint_mode),
                state_schema=schema,
            )
            if lost_receipt:
                with pytest.raises(RuntimeError, match="Lost legacy receipt before checkpoint"):
                    await graph.ainvoke({"messages": [HumanMessage("Submit first job")]}, config, context=context)
                if confirm_in_sibling:
                    resume_config = (await graph.aget_state(config)).config
                    sibling_config = await graph.aupdate_state(
                        resume_config,
                        {"messages": [RemoveMessage(id="ai-1"), _dispatch(1).model_copy(update={"id": "ai-sibling"})]},
                        as_node="model",
                    )
                    sibling = await graph.ainvoke(None, sibling_config, context=context)
                    [sibling_receipt] = [message for message in sibling["messages"] if isinstance(message, ToolMessage)]
                    assert sibling_receipt.status == "success"
            else:
                await graph.ainvoke({"messages": [HumanMessage("Submit first job")]}, config, context=context)
                if compact_before_upgrade:
                    await graph.ainvoke({"messages": [HumanMessage("Acknowledge the earlier work")]}, config, context=context)
                    compacted = (await graph.aget_state(config)).values
                    assert compacted["summary_text"] == "Earlier work summarized"
                    assert COMPACTED_BATCH_RECEIPTS_CHANNEL not in compacted
                    assert not any(isinstance(message, ToolMessage) for message in compacted["messages"])

    [original] = await repository.list_by_thread("thread-1", user_id="user-1")
    responses = [AIMessage(content="Done")] if lost_receipt else [_dispatch(2), AIMessage(content="Done")]
    ancestry_walks = 0
    if compact_before_upgrade:
        responses.extend([_dispatch(3), AIMessage(content="Done")])
        checkpoint_ancestors = tool_module.task_checkpoint_ancestors

        async def count_ancestry_walks(*args, **kwargs):
            nonlocal ancestry_walks
            ancestry_walks += 1
            async for ancestor in checkpoint_ancestors(*args, **kwargs):
                yield ancestor

        monkeypatch.setattr(tool_module, "task_checkpoint_ancestors", count_ancestry_walks)

    middlewares = [summarization()] if compact_history else []
    async with AsyncSqliteSaver.from_conn_string(checkpoint_path) as saver:
        graph = create_agent(
            model=_ScriptedModel(messages=iter(responses)),
            tools=tool_module.bind_batch_tools(service),
            checkpointer=saver,
            middleware=normalize_middleware_state_schemas(middlewares, checkpoint_mode),
            state_schema=schema,
        )
        if lost_receipt:
            state = await graph.ainvoke(None, resume_config, context={**context, "run_id": "resumed-run"}, durability=durability)
            [receipt] = [message for message in state["messages"] if isinstance(message, ToolMessage)]
            assert receipt.status == "error"
            assert "Batch submission conflict" in receipt.content
            assert await repository.list_by_thread("thread-1", user_id="user-1") == [original]
            claimed = await repository.claim_items(now=datetime.now(UTC), lease_owner="worker", lease_seconds=60, limit=10)
            assert [item["batch_id"] for item in claimed] == [original["id"]]
        else:
            if not compact_before_upgrade:
                checkpoint_state = (await graph.aget_state(config)).values
                runtime = SimpleNamespace(state=checkpoint_state, context=context, config=config)
                tools = {tool.name: tool for tool in tool_module.bind_batch_tools(service)}
                arguments = dict(title="Job 1", items=[BatchTaskItem(key="job-1", prompt="Do job 1")], subagent_type="general-purpose", runtime=runtime, tool_call_id="call_0")
                replayed = _message(await tools["batch_task"].coroutine(**arguments))
                assert replayed.additional_kwargs["subagent_batch_id"] == original["id"]
                changed = _message(await tools["batch_task"].coroutine(**(arguments | {"title": "Changed"})))
                assert changed.status == "error"
                assert "Batch submission conflict" in changed.content
            state = await graph.ainvoke({"messages": [HumanMessage("Submit another job")]}, config, context={**context, "run_id": "new-run"}, durability=durability)
            if compact_history or compact_before_upgrade:
                assert state["summary_text"] == "Earlier work summarized"
                [second] = [message for message in state["messages"] if isinstance(message, ToolMessage)]
            else:
                first, second = [message for message in state["messages"] if isinstance(message, ToolMessage)]
                assert first.additional_kwargs["subagent_batch_id"] == original["id"]
            assert second.status == "success"
            assert second.additional_kwargs["subagent_batch_id"] != original["id"]
            second_id = second.additional_kwargs["subagent_batch_id"]
            assert {batch["id"] for batch in await repository.list_by_thread("thread-1", user_id="user-1")} == {original["id"], second_id}
            assert [item["item_key"] for item in await repository.list_items(second_id, user_id="user-1")] == ["job-2"]
            if compact_before_upgrade:
                assert ancestry_walks == 1
                state = await graph.ainvoke({"messages": [HumanMessage("Submit a third job")]}, config, context={**context, "run_id": "new-run"}, durability=durability)
                _, third = [message for message in state["messages"] if isinstance(message, ToolMessage)]
                assert third.status == "success"
                assert ancestry_walks == 1
                third_id = third.additional_kwargs["subagent_batch_id"]
                assert {batch["id"] for batch in await repository.list_by_thread("thread-1", user_id="user-1")} == {original["id"], second_id, third_id}
                assert [item["item_key"] for item in await repository.list_items(third_id, user_id="user-1")] == ["job-3"]

                compacting_graph = create_agent(
                    model=_ScriptedModel(messages=iter([AIMessage(content="Acknowledged")])),
                    tools=tool_module.bind_batch_tools(service),
                    checkpointer=saver,
                    middleware=normalize_middleware_state_schemas([summarization()], checkpoint_mode),
                    state_schema=schema,
                )
                await compacting_graph.ainvoke({"messages": [HumanMessage("Acknowledge the new jobs")]}, config, context=context, durability=durability)
                compacted = (await compacting_graph.aget_state(config)).values
                assert not any(isinstance(message, ToolMessage) for message in compacted["messages"])
                assert set(compacted[COMPACTED_BATCH_RECEIPTS_CHANNEL]) == {original["id"], second_id, third_id}

                tools = tool_module.bind_batch_tools(service)
                model = _ScriptedModel(messages=iter([_dispatch(4), AIMessage(content="Done")]))
                if checkpoint_mode == "full":
                    rebuilt_graph = create_deerflow_agent(model, tools, state_schema=schema, middleware=[], checkpointer=saver)
                else:
                    # Persisted delta graphs created directly with LangChain declare
                    # the receipt channel in their custom schema.
                    resumed_schema = adapt_state_schema_for_mode(_BatchCompactionState, checkpoint_mode)
                    rebuilt_graph = create_agent(model=model, tools=tools, state_schema=resumed_schema, checkpointer=saver)

                state = await rebuilt_graph.ainvoke({"messages": [HumanMessage("Submit a fourth job")]}, config, context={**context, "run_id": "new-run"}, durability=durability)
                [fourth] = [message for message in state["messages"] if isinstance(message, ToolMessage)]
                assert fourth.status == "success"
                assert ancestry_walks == 1
                assert state["summary_text"] == "Earlier work summarized"
                fourth_id = fourth.additional_kwargs["subagent_batch_id"]
                assert {batch["id"] for batch in await repository.list_by_thread("thread-1", user_id="user-1")} == {original["id"], second_id, third_id, fourth_id}
                assert [item["item_key"] for item in await repository.list_items(fourth_id, user_id="user-1")] == ["job-4"]
                assert COMPACTED_BATCH_RECEIPTS_CHANNEL not in state
                assert set((await rebuilt_graph.aget_state(config)).values[COMPACTED_BATCH_RECEIPTS_CHANNEL]) == {original["id"], second_id, third_id}


@pytest.mark.asyncio
@pytest.mark.parametrize("expose_lookup", [True, False], ids=["preflight", "insert-conflict"])
@pytest.mark.parametrize("digestless_first_write", [False, True], ids=["new-write", "previous-digestless-write"])
async def test_sdk_submits_with_a_repository_using_the_original_signature(batch_service, expose_lookup, digestless_first_write):
    _, repository = batch_service
    committed_ids = []

    class LegacyRepository:
        def __getattr__(self, name):
            if name == "find_submission" and not expose_lookup:
                raise AttributeError(name)
            return getattr(repository, name)

        async def create_batch(self, *, batch_id, user_id, thread_id, run_id, tool_call_id, submission_key, title, subagent_type, items, max_live_items, max_running_items, max_attempts, execution_spec, continuation=None):
            if not committed_ids and digestless_first_write:
                execution_spec = {key: value for key, value in execution_spec.items() if key != BATCH_SUBMISSION_DIGEST_KEY}
            batch = await repository.create_batch(
                batch_id=batch_id,
                user_id=user_id,
                thread_id=thread_id,
                run_id=run_id,
                tool_call_id=tool_call_id,
                submission_key=submission_key,
                title=title,
                subagent_type=subagent_type,
                items=items,
                max_live_items=max_live_items,
                max_running_items=max_running_items,
                max_attempts=max_attempts,
                execution_spec=execution_spec,
                continuation=continuation,
            )
            committed_ids.append(batch["id"])
            if len(committed_ids) == 1:
                raise asyncio.CancelledError("Lost receipt after committing the batch")
            return batch

    app_config = AppConfig(sandbox={"use": "deerflow.sandbox.local:LocalSandboxProvider"}, subagent_batches=SubagentBatchesConfig(enabled=True))
    async with SubagentRuntime.from_app_config(app_config, batch_repository=LegacyRepository()) as runtime:
        model = _ScriptedModel(messages=iter([_dispatch(1), AIMessage(content="Done")]))
        graph = create_deerflow_agent(model, features=RuntimeFeatures(subagent=True, sandbox=False, loop_detection=False), subagent_runtime=runtime, checkpointer=InMemorySaver())
        config = {"configurable": {"thread_id": "thread-1"}}
        context = {"user_id": "user-1", "run_id": "run-1"}
        with pytest.raises(NodeCancelledError, match="tools"):
            await graph.ainvoke({"messages": [HumanMessage("Submit a job")]}, config, context=context)
        [committed_id] = committed_ids
        assert all(not isinstance(message, ToolMessage) for message in (await graph.aget_state(config)).values["messages"])
        state = await graph.ainvoke(None, config, context=context)
        [receipt] = [message for message in state["messages"] if isinstance(message, ToolMessage)]
        assert receipt.status == "success", receipt.content
        [batch] = await repository.list_by_thread("thread-1", user_id="user-1")
        assert receipt.additional_kwargs["subagent_batch_id"] == batch["id"] == committed_id
        assert [item["item_key"] for item in await repository.list_items(committed_id, user_id="user-1")] == ["job-1"]


def test_batch_schema_advertises_continuation_only_with_run_capability():
    tools = list(tool_module.bind_batch_tools(AsyncMock()))
    limited = tool_module.restrict_batch_continuation(tools, available=False)
    interactive = tool_module.restrict_batch_continuation(tools, available=True)

    def properties(bound_tools):
        batch = next(tool for tool in bound_tools if tool.name == "batch_task")
        return convert_to_openai_tool(batch)["function"]["parameters"]["properties"]

    assert "continuation" in properties(interactive)
    assert properties(limited) == {name: field for name, field in properties(interactive).items() if name != "continuation"}
    assert "continuation" in properties(tools)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("thread_incarnation", "expected_present"),
    [
        ("incarnation-1", True),
        (None, True),
        (_MISSING, False),
    ],
)
async def test_batch_task_is_explicit_idempotent_submission(
    monkeypatch,
    thread_incarnation,
    expected_present,
) -> None:
    submitter = AsyncMock()
    submitter.submit.return_value = {
        "id": "subagent-batch-1",
        "status": "queued",
        "total_items": 2,
    }
    monkeypatch.setattr(tool_module, "get_subagent_batch_submitter", lambda: submitter)
    monkeypatch.setattr(
        tool_module,
        "get_available_subagent_names",
        lambda **_kwargs: ["general-purpose"],
    )
    monkeypatch.setattr(
        tool_module,
        "get_subagent_config",
        lambda *_args, **_kwargs: SubagentConfig(
            name="general-purpose",
            description="General purpose",
        ),
    )

    runtime = _runtime(thread_incarnation)
    runtime.context["non_interactive"] = True
    command = await tool_module.batch_task.coroutine(
        runtime=runtime,
        title="Process records",
        items=[
            BatchTaskItem(key="record-1", prompt="Process one"),
            BatchTaskItem(key="record-2", prompt="Process two"),
        ],
        subagent_type="general-purpose",
        tool_call_id="call-1",
        max_live_items=20,
        max_running_items=5,
    )

    message = _message(command)
    request = submitter.submit.await_args.args[0]
    assert re.fullmatch(r"batch-v1:[a-f0-9]{64}", request.submission_key)
    assert request.run_id == "run-1"
    assert request.execution_spec["mcp_plugins"] == ["stable-plugin"]
    assert "ask_clarification" in request.execution_spec["subagent_config"]["disallowed_tools"]
    assert request.user_id == "user-1"
    assert [item["key"] for item in request.items] == ["record-1", "record-2"]
    assert request.max_live_items == 20
    assert request.max_running_items == 5
    assert request.execution_spec["knowledge_scope"] == {
        "version": 1,
        "mode": "selected",
        "dataset_ids": ["dataset-1"],
    }
    assert (THREAD_INCARNATION_CONTEXT_KEY in request.execution_spec) is expected_present
    if expected_present:
        assert request.execution_spec[THREAD_INCARNATION_CONTEXT_KEY] is thread_incarnation
    assert message.additional_kwargs["subagent_batch_id"] == "subagent-batch-1"
    assert message.additional_kwargs["subagent_batch_status"] == "queued"
    assert "Current status: queued" in message.content


@pytest.mark.asyncio
async def test_submission_key_scopes_the_dispatch_independently_of_run(monkeypatch) -> None:
    _mock_subagent_catalog(monkeypatch)
    submitter = _explicit_submitter()
    monkeypatch.setattr(tool_module, "get_subagent_batch_submitter", lambda: submitter)

    async def submit(runtime, call_id="call-1"):
        command = await tool_module.batch_task.coroutine(runtime=runtime, title="Batch", items=[BatchTaskItem(key="a", prompt="Read")], subagent_type="general-purpose", tool_call_id=call_id)
        assert _message(command).status == "success"
        return submitter.submit.await_args.args[0]

    runtime = _runtime("incarnation-1")
    original = await submit(runtime)
    runtime.context["run_id"] = "resumed-run"
    replay = await submit(runtime)
    assert replay.run_id == "resumed-run"
    assert replay.submission_key == original.submission_key

    other_thread = _runtime("incarnation-1")
    other_thread.context["thread_id"] = "thread-2"
    other_dispatch = _runtime("incarnation-1")
    other_dispatch.state["messages"].append(_dispatch(2, call_id="call-1"))
    separated = [
        await submit(other_thread),
        await submit(_runtime("incarnation-2")),
        await submit(other_dispatch),
        await submit(_runtime("incarnation-1", call_id="call-2"), "call-2"),
    ]
    assert len({request.submission_key for request in [original, *separated]}) == 5


@pytest.mark.asyncio
@pytest.mark.parametrize("problem", ["missing", "empty-id", "ambiguous"])
async def test_batch_task_rejects_unidentifiable_dispatch(monkeypatch, problem) -> None:
    _mock_subagent_catalog(monkeypatch)
    submitter = _explicit_submitter()
    monkeypatch.setattr(tool_module, "get_subagent_batch_submitter", lambda: submitter)
    runtime = _runtime(call_id="call_0")
    dispatch = _dispatch(2)
    if problem == "missing":
        runtime.state["messages"] = [_dispatch(1, call_id="another-call")]
    elif problem == "empty-id":
        runtime.state["messages"].append(dispatch.model_copy(update={"id": ""}))
    else:
        runtime.state["messages"].append(dispatch.model_copy(update={"tool_calls": dispatch.tool_calls * 2}))

    command = await tool_module.batch_task.coroutine(runtime=runtime, title="Batch", items=[BatchTaskItem(key="a", prompt="Read")], subagent_type="general-purpose", tool_call_id="call_0")
    message = _message(command)
    assert message.status == "error"
    assert message.additional_kwargs == {"subagent_batch_error": True}
    submitter.submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_batch_task_rejects_stale_standalone_thread_incarnation(
    monkeypatch,
) -> None:
    submitter = AsyncMock()
    monkeypatch.setattr(tool_module, "get_subagent_batch_submitter", lambda: submitter)
    runtime = _runtime("incarnation-1")
    runtime.context[THREAD_INCARNATION_METADATA_GUARD_KEY] = True
    runtime.config["metadata"][THREAD_INCARNATION_CONTEXT_KEY] = "incarnation-2"

    with pytest.raises(RuntimeError, match="stale thread incarnation"):
        await tool_module.batch_task.coroutine(
            runtime=runtime,
            title="Stale lifecycle",
            items=[BatchTaskItem(key="record-1", prompt="Process one")],
            subagent_type="general-purpose",
            tool_call_id="call-1",
        )

    submitter.submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_batch_task_rejects_duplicate_item_keys_without_submitting(monkeypatch) -> None:
    submitter = AsyncMock()
    monkeypatch.setattr(tool_module, "get_subagent_batch_submitter", lambda: submitter)

    command = await tool_module.batch_task.coroutine(
        runtime=_runtime(),
        title="Duplicates",
        items=[
            BatchTaskItem(key="same", prompt="one"),
            BatchTaskItem(key="same", prompt="two"),
        ],
        subagent_type="general-purpose",
        tool_call_id="call-1",
    )

    message = _message(command)
    assert message.status == "error"
    assert "unique" in message.content
    submitter.submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_batch_keeps_the_existing_submitter_signature(monkeypatch) -> None:
    class ExistingSubmitter:
        async def cancel_batch(self, *, batch_id, user_id):
            return {"id": batch_id}

    monkeypatch.setattr(tool_module, "get_subagent_batch_submitter", lambda: ExistingSubmitter())
    result = await tool_module.cancel_batch.coroutine(runtime=_runtime(), batch_id="batch-1")
    assert result == "Batch batch-1 cancellation requested."


@pytest.mark.asyncio
async def test_bound_batch_tools_use_the_explicit_submitter(monkeypatch) -> None:
    explicit = AsyncMock()
    explicit.get_batch.return_value = {
        "id": "subagent-batch-explicit",
        "status": "running",
        "total_items": 2,
        "counts": {"running": 1, "succeeded": 1},
    }
    fallback = AsyncMock()
    monkeypatch.setattr(tool_module, "get_subagent_batch_submitter", lambda: fallback)

    tools = {tool.name: tool for tool in tool_module.bind_batch_tools(explicit)}
    result = await tools["batch_status"].coroutine(
        runtime=_runtime(),
        batch_id="subagent-batch-explicit",
    )

    assert "subagent-batch-explicit" in result
    explicit.get_batch.assert_awaited_once_with(
        batch_id="subagent-batch-explicit",
        user_id="user-1",
    )
    fallback.get_batch.assert_not_awaited()


@pytest.mark.asyncio
async def test_bound_batch_task_uses_the_explicit_app_config(monkeypatch) -> None:
    app_config = object()
    captured = {}
    submitter = AsyncMock()
    submitter.submit.return_value = {
        "id": "subagent-batch-explicit",
        "status": "queued",
        "total_items": 1,
    }

    def available_names(*, app_config, allowed_subagents):
        captured["names"] = (app_config, allowed_subagents)
        return ["general-purpose"]

    def subagent_config(name, *, app_config):
        captured["config"] = (name, app_config)
        return SubagentConfig(
            name="general-purpose",
            description="General purpose",
        )

    monkeypatch.setattr(tool_module, "get_available_subagent_names", available_names)
    monkeypatch.setattr(tool_module, "get_subagent_config", subagent_config)

    tools = {
        tool.name: tool
        for tool in tool_module.bind_batch_tools(
            submitter,
            app_config=app_config,
        )
    }
    await tools["batch_task"].coroutine(
        runtime=_runtime(call_id="call-explicit"),
        title="Explicit config",
        items=[BatchTaskItem(key="record-1", prompt="Process one")],
        subagent_type="general-purpose",
        tool_call_id="call-explicit",
        max_live_items=None,
        max_running_items=None,
    )

    assert captured["names"] == (app_config, ["general-purpose"])
    assert captured["config"] == ("general-purpose", app_config)
    submitter.submit.assert_awaited_once()


@pytest.mark.asyncio
async def test_bound_batch_tools_do_not_fall_back_after_runtime_stops(monkeypatch) -> None:
    fallback = AsyncMock()
    monkeypatch.setattr(tool_module, "get_subagent_batch_submitter", lambda: fallback)

    tools = {
        tool.name: tool
        for tool in tool_module.bind_batch_tools(
            submitter_provider=lambda: None,
        )
    }
    result = await tools["batch_status"].coroutine(
        runtime=_runtime(),
        batch_id="subagent-batch-stopped",
    )

    assert result == "Durable subagent batches are unavailable."
    fallback.get_batch.assert_not_awaited()


def _mock_subagent_catalog(monkeypatch) -> None:
    monkeypatch.setattr(
        tool_module,
        "get_available_subagent_names",
        lambda **_kwargs: ["general-purpose"],
    )
    monkeypatch.setattr(
        tool_module,
        "get_subagent_config",
        lambda *_args, **_kwargs: SubagentConfig(
            name="general-purpose",
            description="General purpose",
        ),
    )


def _explicit_submitter() -> AsyncMock:
    explicit = AsyncMock()
    explicit.submit.return_value = {
        "id": "subagent-batch-explicit",
        "status": "queued",
        "total_items": 1,
    }
    return explicit


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw_title", "expected_title"),
    [
        pytest.param(" \t\n ", "Subagent batch", id="blank"),
        pytest.param("  " + "a" * 257 + "  ", "a" * 256, id="overlong"),
        pytest.param("  " + "a" * 255 + " tail  ", "a" * 255, id="whitespace-at-cutoff"),
    ],
)
async def test_bound_batch_task_normalizes_title_for_explicit_submitter(monkeypatch, raw_title, expected_title) -> None:
    _mock_subagent_catalog(monkeypatch)
    submitter = _explicit_submitter()
    dispatch = _dispatch(1)
    dispatch.tool_calls[0]["args"]["title"] = raw_title
    graph = create_agent(
        model=_ScriptedModel(messages=iter([dispatch, AIMessage(content="Done")])),
        tools=tool_module.bind_batch_tools(submitter),
    )

    state = await graph.ainvoke(
        {"messages": [HumanMessage("Submit job")]},
        {"configurable": {"thread_id": "thread-1"}},
        context={"user_id": "user-1"},
    )

    receipt = next(message for message in state["messages"] if isinstance(message, ToolMessage))
    assert receipt.status == "success"
    submitter.submit.assert_awaited_once()
    assert submitter.submit.call_args.args[0].title == expected_title


@pytest.mark.asyncio
async def test_followup_captures_configurable_settings_with_context_precedence(monkeypatch):
    _mock_subagent_catalog(monkeypatch)
    submitter = _explicit_submitter()
    monkeypatch.setattr(tool_module, "get_subagent_batch_submitter", lambda: submitter)
    runtime = _runtime(call_id="batch-call")
    runtime.config["configurable"].update(thinking_enabled=False, reasoning_effort="high", max_concurrent_subagents=2, max_total_subagents=4)
    runtime.context["reasoning_effort"] = "low"
    await tool_module.batch_task.coroutine(
        title="Meeting records",
        items=[BatchTaskItem(key="a", prompt="Read")],
        subagent_type="general-purpose",
        continuation="Summarize",
        runtime=runtime,
        tool_call_id="batch-call",
    )
    captured = submitter.submit.call_args.args[0].continuation_context["context"]
    assert {key: captured[key] for key in ("thinking_enabled", "reasoning_effort", "max_concurrent_subagents", "max_total_subagents")} == {
        "thinking_enabled": False,
        "reasoning_effort": "low",
        "max_concurrent_subagents": 2,
        "max_total_subagents": 4,
    }


def test_bound_batch_tools_sync_path_uses_the_explicit_submitter(monkeypatch) -> None:
    """Sync invocation of a bound copy must not bypass the explicit submitter.

    ``get_available_tools`` wraps the process-wide batch tool singletons in
    place with a sync ``func``; a bound copy that only rebinds ``coroutine``
    would keep that wrapper around the unbound coroutine and fall through to
    the process-global submitter.
    """
    from deerflow.tools.tools import _ensure_sync_invocable_tool

    fallback = AsyncMock()
    monkeypatch.setattr(tool_module, "get_subagent_batch_submitter", lambda: fallback)
    _mock_subagent_catalog(monkeypatch)

    # Snapshot func so monkeypatch undoes the in-place wrap after this test.
    monkeypatch.setattr(tool_module.batch_task, "func", tool_module.batch_task.func)
    _ensure_sync_invocable_tool(tool_module.batch_task)

    explicit = _explicit_submitter()
    tools = {tool.name: tool for tool in tool_module.bind_batch_tools(explicit)}
    command = tools["batch_task"].func(
        runtime=_runtime(call_id="call-sync"),
        title="Sync path",
        items=[BatchTaskItem(key="record-1", prompt="Process one")],
        subagent_type="general-purpose",
        tool_call_id="call-sync",
    )

    message = _message(command)
    assert message.status == "success"
    assert message.additional_kwargs["subagent_batch_id"] == "subagent-batch-explicit"
    explicit.submit.assert_awaited_once()
    fallback.submit.assert_not_awaited()


def test_bound_batch_tools_expose_a_sync_invocation_path(monkeypatch) -> None:
    """A copy made before any sync wrap must still carry a usable sync func."""
    monkeypatch.setattr(tool_module, "get_subagent_batch_submitter", lambda: None)
    _mock_subagent_catalog(monkeypatch)

    for singleton in (tool_module.batch_task, tool_module.batch_status, tool_module.cancel_batch):
        monkeypatch.setattr(singleton, "func", None)

    explicit = _explicit_submitter()
    tools = {tool.name: tool for tool in tool_module.bind_batch_tools(explicit)}
    assert all(tool.func is not None for tool in tools.values())

    command = tools["batch_task"].func(
        runtime=_runtime(call_id="call-sync-fresh"),
        title="Sync path",
        items=[BatchTaskItem(key="record-1", prompt="Process one")],
        subagent_type="general-purpose",
        tool_call_id="call-sync-fresh",
    )

    message = _message(command)
    assert message.status == "success"
    assert message.additional_kwargs["subagent_batch_id"] == "subagent-batch-explicit"
    explicit.submit.assert_awaited_once()
