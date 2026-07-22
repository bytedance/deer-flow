from typing import get_type_hints

import pytest
from hypothesis import given
from hypothesis import strategies as st
from langchain.agents import AgentState, create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, RemoveMessage
from langgraph.channels import DeltaChannel
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph
from langgraph.graph.message import REMOVE_ALL_MESSAGES, add_messages

from deerflow.agents.thread_state import (
    DeltaThreadState,
    ThreadState,
    adapt_state_schema_for_mode,
    get_thread_state_schema,
    merge_message_writes,
    normalize_middleware_state_schemas,
)


def _fold(state: list, writes: list) -> list:
    result = list(state)
    for write in writes:
        result = list(add_messages(result, write))
    return result


@pytest.mark.parametrize(
    "writes",
    [
        [[HumanMessage(id="h1", content="one")], [AIMessage(id="a1", content="two")]],
        [[AIMessage(id="same", content="old")], [AIMessage(id="same", content="new")]],
        [[HumanMessage(id="h1", content="one")], [RemoveMessage(id="h1")]],
        [
            [HumanMessage(id="h1", content="one"), AIMessage(id="a1", content="two")],
            [RemoveMessage(id=REMOVE_ALL_MESSAGES), HumanMessage(id="h2", content="kept")],
        ],
    ],
)
def test_merge_message_writes_matches_sequential_add_messages(writes: list) -> None:
    assert merge_message_writes([], writes) == _fold([], writes)


@given(split=st.integers(min_value=0, max_value=3))
def test_merge_message_writes_is_batching_invariant(split: int) -> None:
    state = [HumanMessage(id="h0", content="seed")]
    writes = [
        [AIMessage(id="a1", content="first")],
        [AIMessage(id="a1", content="replacement")],
        [HumanMessage(id="h2", content="last")],
    ]
    xs = writes[:split]
    ys = writes[split:]
    assert merge_message_writes(merge_message_writes(state, xs), ys) == merge_message_writes(state, writes)


def test_merge_message_writes_matches_unknown_remove_error() -> None:
    writes = [[RemoveMessage(id="missing")]]

    with pytest.raises(ValueError) as expected:
        _fold([], writes)
    with pytest.raises(type(expected.value)) as actual:
        merge_message_writes([], writes)

    assert str(actual.value) == str(expected.value)


@pytest.mark.parametrize(
    "write",
    [
        [{"role": "user", "content": "from a dict", "id": "dict-1"}],
        AIMessageChunk(id="chunk-1", content="from a chunk"),
    ],
)
def test_merge_message_writes_matches_message_coercion(write: object) -> None:
    assert merge_message_writes([], [write]) == _fold([], [write])


def test_raw_tuple_coercion_matches_add_messages_reducer_parity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("langgraph.graph.message.uuid.uuid4", lambda: "tuple-id")
    writes = [[("human", "from a tuple")]]

    assert merge_message_writes([], writes) == _fold([], writes)


def test_mode_selects_expected_state_schema() -> None:
    assert get_thread_state_schema("full") is ThreadState
    assert get_thread_state_schema("delta") is DeltaThreadState
    message_hint = get_type_hints(DeltaThreadState, include_extras=True)["messages"]
    assert any(isinstance(item, DeltaChannel) for item in message_hint.__metadata__)


def test_delta_adaptation_replaces_agent_state_message_reducer() -> None:
    adapted = adapt_state_schema_for_mode(AgentState, "delta")
    hint = get_type_hints(adapted, include_extras=True)["messages"]
    assert any(isinstance(item, DeltaChannel) for item in hint.__metadata__)


def test_agents_package_exports_delta_thread_state() -> None:
    from deerflow.agents import DeltaThreadState as ExportedDeltaThreadState

    assert ExportedDeltaThreadState is DeltaThreadState


class _FirstState(AgentState):
    first: str


class _SecondState(AgentState):
    second: int


class _FirstMiddleware(AgentMiddleware):
    state_schema = _FirstState


class _SecondMiddleware(AgentMiddleware):
    state_schema = _SecondState


class _FakeModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):  # type: ignore[override]
        return self


def _compile_with_middleware(middleware: list[AgentMiddleware], mode: str):
    return create_agent(
        model=_FakeModel(responses=[AIMessage(id="response", content="done")]),
        tools=None,
        middleware=normalize_middleware_state_schemas(middleware, mode),
        state_schema=get_thread_state_schema(mode),
    )


def test_delta_normalization_compiles_stable_channel_without_mutating_middleware() -> None:
    first = _FirstMiddleware()
    second = _SecondMiddleware()
    middleware = [first, second]

    for _ in range(10):
        graph = _compile_with_middleware(middleware, "delta")
        assert isinstance(graph.channels["messages"], DeltaChannel)

    assert first.state_schema is _FirstState
    assert second.state_schema is _SecondState

    full_graph = _compile_with_middleware(middleware, "full")
    assert type(full_graph.channels["messages"]).__name__ == "BinaryOperatorAggregate"
    assert first.state_schema is _FirstState
    assert second.state_schema is _SecondState


@pytest.mark.parametrize(
    "write",
    [
        HumanMessage(content="root BaseMessage"),
        {"role": "user", "content": "root message dict"},
        [HumanMessage(content="BaseMessage in list")],
        [{"role": "user", "content": "message dict in list"}],
    ],
    ids=["base-message", "dict", "base-message-list", "dict-list"],
)
def test_production_message_forms_keep_assigned_ids_across_delta_replay(write: object) -> None:
    builder = StateGraph(DeltaThreadState)

    def write_messages(_state):
        return {"messages": write}

    builder.add_node("writer", write_messages)
    builder.set_entry_point("writer")
    builder.set_finish_point("writer")
    graph = builder.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "stable-message-replay"}}

    graph.invoke({}, config)
    first = graph.get_state(config).values["messages"]
    second = graph.get_state(config).values["messages"]

    assert first[0].id is not None
    assert second[0].id == first[0].id
