import copy
from typing import get_type_hints

import pytest
from hypothesis import given
from hypothesis import strategies as st
from langchain.agents import AgentState, create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, RemoveMessage, ToolMessageChunk
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


def _outcome(call):
    try:
        return ("result", call())
    except Exception as exc:
        return ("error", type(exc), str(exc))


@st.composite
def _message_merge_cases(draw):
    message_ids = ["a", "b", "c", "missing"]
    state_ids = draw(st.lists(st.sampled_from(message_ids[:-1]), max_size=6))
    state = [
        {
            "role": draw(st.sampled_from(["user", "assistant"])),
            "content": f"state-{index}",
            "id": message_id,
        }
        for index, message_id in enumerate(state_ids)
    ]

    operation = st.one_of(
        st.tuples(
            st.just("message"),
            st.sampled_from(message_ids),
            st.sampled_from(["user", "assistant", "ai_chunk", "tool_chunk"]),
            st.text(max_size=12),
        ),
        st.tuples(
            st.just("remove"),
            st.sampled_from([*message_ids, REMOVE_ALL_MESSAGES]),
            st.none(),
            st.none(),
        ),
    )
    raw_writes = draw(st.lists(st.lists(operation, max_size=6), max_size=8))
    writes = []
    for raw_write in raw_writes:
        write = []
        for kind, message_id, role, content in raw_write:
            if kind == "remove":
                write.append(RemoveMessage(id=message_id))
            elif role == "ai_chunk":
                write.append(AIMessageChunk(id=message_id, content=content))
            elif role == "tool_chunk":
                write.append(ToolMessageChunk(id=message_id, content=content, tool_call_id=f"call-{message_id}"))
            else:
                write.append({"role": role, "content": content, "id": message_id})
        writes.append(write)
    return state, writes


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


@given(case=_message_merge_cases())
def test_merge_message_writes_randomized_differential(case: tuple[list, list]) -> None:
    state, writes = case

    expected = _outcome(lambda: _fold(copy.deepcopy(state), copy.deepcopy(writes)))
    actual = _outcome(lambda: merge_message_writes(copy.deepcopy(state), copy.deepcopy(writes)))

    assert actual == expected


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


@given(case=_message_merge_cases(), data=st.data())
def test_merge_message_writes_randomized_batching_invariance(case: tuple[list, list], data: st.DataObject) -> None:
    state, writes = case
    split = data.draw(st.integers(min_value=0, max_value=len(writes)))

    expected = _outcome(lambda: merge_message_writes(copy.deepcopy(state), copy.deepcopy(writes)))

    def batched():
        intermediate = merge_message_writes(copy.deepcopy(state), copy.deepcopy(writes[:split]))
        return merge_message_writes(intermediate, copy.deepcopy(writes[split:]))

    assert _outcome(batched) == expected


def test_merge_message_writes_matches_unknown_remove_error() -> None:
    writes = [[RemoveMessage(id="missing")]]

    with pytest.raises(ValueError) as expected:
        _fold([], writes)
    with pytest.raises(type(expected.value)) as actual:
        merge_message_writes([], writes)

    assert str(actual.value) == str(expected.value)


@pytest.mark.parametrize(
    ("state", "writes"),
    [
        (
            [HumanMessage(id="duplicate", content="first"), HumanMessage(id="duplicate", content="second")],
            [[AIMessage(id="duplicate", content="replacement")]],
        ),
        (
            [HumanMessage(id="duplicate", content="first"), HumanMessage(id="duplicate", content="second")],
            [[RemoveMessage(id="duplicate")]],
        ),
        (
            [HumanMessage(id="same", content="old")],
            [[RemoveMessage(id="same"), AIMessage(id="same", content="same-write replacement")]],
        ),
        (
            [HumanMessage(id="same", content="old")],
            [[RemoveMessage(id="same")], [AIMessage(id="same", content="later-write append")]],
        ),
        (
            [HumanMessage(id="seed", content="old")],
            [
                [
                    RemoveMessage(id="unknown-but-ignored"),
                    RemoveMessage(id=REMOVE_ALL_MESSAGES),
                    RemoveMessage(id="suffix-is-returned-verbatim"),
                ]
            ],
        ),
    ],
    ids=[
        "duplicate-id-replacement",
        "duplicate-id-removal",
        "same-write-remove-then-replace",
        "cross-write-remove-then-append",
        "remove-all-short-circuit",
    ],
)
def test_merge_message_writes_preserves_add_messages_edge_semantics(state: list, writes: list) -> None:
    assert merge_message_writes(copy.deepcopy(state), copy.deepcopy(writes)) == _fold(copy.deepcopy(state), copy.deepcopy(writes))


@pytest.mark.parametrize(
    ("state", "writes"),
    [
        ([], [None]),
        ([HumanMessage(id="seed", content="seed")], [None]),
        ([], [[HumanMessage(id="added", content="added")], None]),
        (
            [HumanMessage(id="removed", content="removed")],
            [[RemoveMessage(id="removed")], None],
        ),
    ],
)
def test_merge_message_writes_preserves_null_write_errors(state: list, writes: list) -> None:
    expected = _outcome(lambda: _fold(copy.deepcopy(state), copy.deepcopy(writes)))
    actual = _outcome(lambda: merge_message_writes(copy.deepcopy(state), copy.deepcopy(writes)))

    assert actual == expected


def test_merge_message_writes_preserves_missing_id_allocation_order(monkeypatch: pytest.MonkeyPatch) -> None:
    state = [HumanMessage(content="state")]
    writes = [
        [AIMessage(content="first"), HumanMessage(content="second")],
        [AIMessage(content="third")],
    ]

    expected_ids = iter(["state-id", "first-id", "second-id", "third-id"])
    monkeypatch.setattr("langgraph.graph.message.uuid.uuid4", lambda: next(expected_ids))
    expected = _fold(copy.deepcopy(state), copy.deepcopy(writes))

    actual_ids = iter(["state-id", "first-id", "second-id", "third-id"])
    monkeypatch.setattr("langgraph.graph.message.uuid.uuid4", lambda: next(actual_ids))
    actual = merge_message_writes(copy.deepcopy(state), copy.deepcopy(writes))

    assert actual == expected


def test_merge_message_writes_normalizes_state_and_each_write_once(monkeypatch: pytest.MonkeyPatch) -> None:
    import deerflow.agents.thread_state as thread_state

    state = [HumanMessage(id="state", content="state")]
    writes = [
        [AIMessage(id="first", content="first")],
        [AIMessage(id="second", content="second")],
        [AIMessage(id="third", content="third")],
    ]
    original = thread_state.convert_to_messages
    normalized_inputs = []

    def record_conversion(messages):
        normalized_inputs.append(messages)
        return original(messages)

    monkeypatch.setattr(thread_state, "convert_to_messages", record_conversion)

    merge_message_writes(state, writes)

    assert normalized_inputs == [state, *writes]


def test_merge_message_writes_empty_batch_does_not_assign_state_ids() -> None:
    state = [HumanMessage(content="unchanged")]

    result = merge_message_writes(state, [])

    assert result == state
    assert state[0].id is None


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
