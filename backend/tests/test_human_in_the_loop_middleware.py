"""Tests for the tool-approval (human-in-the-loop) middleware."""

import json
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Annotated, TypedDict

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Command

from deerflow.agents.middlewares.human_in_the_loop import (
    DISABLE_TOOL_APPROVAL_KEY,
    NON_INTERACTIVE_KEY,
    TOOL_APPROVAL_OMIT_KEY,
    DeerFlowHumanInTheLoopMiddleware,
    create_interrupt_middleware,
)
from deerflow.config.tool_config import InterruptOnConfig as InterruptOnConfigModel
from deerflow.config.tool_config import ToolConfig
from deerflow.sandbox.tools import bash_tool as real_bash_tool


@tool
def bash_tool(command: str, timeout: int = 30) -> str:
    """Run a shell command."""
    return command


class _InterruptReached(Exception):
    """Sentinel raised in place of ``interrupt()`` to prove the gate fired."""


def _runtime(**context):
    """A ``Runtime`` stand-in.

    ``_should_interrupt`` builds a real ``ToolRuntime`` out of these attributes
    whenever a ``when`` predicate is configured, so all of them must exist.
    """
    return SimpleNamespace(
        context=context or {},
        stream_writer=None,
        store=None,
        execution_info=None,
        server_info=None,
    )


def _state(tool_calls):
    return {
        "messages": [
            HumanMessage(content="do it"),
            AIMessage(content="", tool_calls=tool_calls, id="ai-1"),
        ]
    }


def _call(name="bash_tool", args=None, call_id="call-1"):
    return {"type": "tool_call", "name": name, "args": args or {"command": "rm -rf /"}, "id": call_id}


def _middleware(allowed_decisions=("approve", "edit", "reject", "respond"), **extra):
    return DeerFlowHumanInTheLoopMiddleware(interrupt_on={"bash_tool": {"allowed_decisions": list(allowed_decisions), **extra}})


@contextmanager
def _patched_interrupt(decisions):
    """Stand in for LangGraph's ``interrupt()``.

    Outside a running graph the real ``interrupt()`` raises ``RuntimeError``
    from ``get_config()``, so the resume value is injected by patching the
    module-level symbol the middleware calls. Pass ``None`` to make the call
    raise :class:`_InterruptReached` instead of resuming.
    """
    import deerflow.agents.middlewares.human_in_the_loop as mod

    captured = {}
    original = mod.interrupt

    def fake_interrupt(request):
        captured["request"] = request
        if decisions is None:
            raise _InterruptReached
        return {"decisions": list(decisions)}

    mod.interrupt = fake_interrupt
    try:
        yield captured
    finally:
        mod.interrupt = original


def _resume(middleware, state, decisions, runtime=None):
    """Drive ``after_model`` past its interrupt with *decisions*."""
    with _patched_interrupt(decisions) as captured:
        result = middleware.after_model(state, runtime or _runtime())
    return result, captured.get("request")


def _assert_gated(middleware, state, runtime=None):
    """Assert the middleware reached its interrupt, and return the request."""
    with _patched_interrupt(None) as captured:
        with pytest.raises(_InterruptReached):
            middleware.after_model(state, runtime or _runtime())
    return captured["request"]


def _assert_not_gated(middleware, state, runtime=None):
    """Assert ``after_model`` returned without ever interrupting."""
    with _patched_interrupt(None) as captured:
        assert middleware.after_model(state, runtime or _runtime()) is None
    assert "request" not in captured


class TestNoInterruptNeeded:
    def test_no_messages(self):
        _assert_not_gated(_middleware(), {"messages": []})

    def test_no_tool_calls(self):
        _assert_not_gated(_middleware(), {"messages": [AIMessage(content="all done", id="ai-1")]})

    def test_unconfigured_tool_is_auto_approved(self):
        _assert_not_gated(_middleware(), _state([_call(name="read_file", args={"path": "a.txt"})]))


class TestDowngradeSwitches:
    """Non-interactive runs must never park on an interrupt."""

    def test_disable_tool_approval_auto_approves(self):
        runtime = _runtime(**{DISABLE_TOOL_APPROVAL_KEY: True})
        _assert_not_gated(_middleware(), _state([_call()]), runtime)

    def test_non_interactive_auto_approves(self):
        """A run with nobody watching must not park, however it said so.

        The scheduler and the MCP task-notification launcher mark their runs
        ``non_interactive`` and never set ``disable_tool_approval``; treating
        only the latter as a downgrade parks a scheduled run in the checkpoint
        with no client able to resume it.
        """
        runtime = _runtime(**{NON_INTERACTIVE_KEY: True})
        _assert_not_gated(_middleware(), _state([_call()]), runtime)

    def test_non_interactive_false_still_gates(self):
        runtime = _runtime(**{NON_INTERACTIVE_KEY: False})
        _assert_gated(_middleware(), _state([_call()]), runtime)

    def test_omitted_tool_is_not_gated(self):
        runtime = _runtime(**{TOOL_APPROVAL_OMIT_KEY: ["bash_tool"]})
        _assert_not_gated(_middleware(), _state([_call()]), runtime)

    def test_omit_accepts_a_bare_string(self):
        runtime = _runtime(**{TOOL_APPROVAL_OMIT_KEY: "bash_tool"})
        _assert_not_gated(_middleware(), _state([_call()]), runtime)

    def test_omitting_a_different_tool_still_gates(self):
        runtime = _runtime(**{TOOL_APPROVAL_OMIT_KEY: ["read_file"]})
        request = _assert_gated(_middleware(), _state([_call()]), runtime)
        assert [r["name"] for r in request["action_requests"]] == ["bash_tool"]

    def test_empty_context_still_gates(self):
        _assert_gated(_middleware(), _state([_call()]))

    def test_missing_context_attribute_still_gates(self):
        """A runtime with no ``context`` at all must not read as "disabled"."""
        _assert_gated(_middleware(), _state([_call()]), SimpleNamespace())


class TestDecisions:
    def test_approve_keeps_the_tool_call(self):
        result, _ = _resume(_middleware(), _state([_call()]), [{"type": "approve"}])
        (revised, *rest) = result["messages"]
        assert rest == []
        assert [tc["name"] for tc in revised.tool_calls] == ["bash_tool"]
        assert revised.tool_calls[0]["args"] == {"command": "rm -rf /"}

    def test_edit_replaces_the_args(self):
        decision = {
            "type": "edit",
            "edited_action": {"name": "bash_tool", "args": {"command": "ls"}},
        }
        result, _ = _resume(_middleware(), _state([_call()]), [decision])
        revised = result["messages"][0]
        assert revised.tool_calls[0]["args"] == {"command": "ls"}
        # The id must survive so the ToolMessage still correlates.
        assert revised.tool_calls[0]["id"] == "call-1"

    def test_reject_answers_the_call_instead_of_executing_it(self):
        """The call is kept and paired with an error ``ToolMessage``.

        The agent's ``model -> tools`` edge only dispatches tool calls that have
        no matching ``ToolMessage``, so answering the call is what prevents
        execution. Dropping the call instead would leave the provider's
        assistant turn without a result for an id it still lists.
        """
        result, _ = _resume(_middleware(), _state([_call()]), [{"type": "reject", "message": "too risky"}])
        revised, tool_message = result["messages"]
        assert [tc["id"] for tc in revised.tool_calls] == ["call-1"]
        assert isinstance(tool_message, ToolMessage)
        assert tool_message.tool_call_id == "call-1"
        assert tool_message.status == "error"
        assert tool_message.content == "too risky"

    def test_respond_answers_on_behalf_of_the_tool(self):
        result, _ = _resume(_middleware(), _state([_call()]), [{"type": "respond", "message": "use ls instead"}])
        revised, tool_message = result["messages"]
        assert [tc["id"] for tc in revised.tool_calls] == ["call-1"]
        assert isinstance(tool_message, ToolMessage)
        assert tool_message.status == "success"
        assert tool_message.content == "use ls instead"

    def test_decision_count_mismatch_raises(self):
        with pytest.raises(ValueError, match="does not match"):
            _resume(_middleware(), _state([_call()]), [{"type": "approve"}, {"type": "approve"}])

    def test_disallowed_decision_type_raises(self):
        middleware = _middleware(allowed_decisions=("approve", "reject"))
        with pytest.raises(ValueError, match="not allowed"):
            _resume(middleware, _state([_call()]), [{"type": "respond", "message": "nope"}])


class TestOriginalMessageNotMutated:
    """The revised turn is a clone; the streamed instance stays untouched."""

    def test_edit_does_not_mutate_the_message_the_caller_already_holds(self):
        original = AIMessage(
            content="",
            id="ai-1",
            tool_calls=[_call()],
            additional_kwargs={"tool_calls": [{"id": "call-1", "function": {"name": "bash_tool"}}]},
        )
        state = {"messages": [HumanMessage(content="do it"), original]}
        decision = {
            "type": "edit",
            "edited_action": {"name": "bash_tool", "args": {"command": "ls"}},
        }

        result, _ = _resume(_middleware(), state, [decision])
        revised = result["messages"][0]

        assert revised is not original
        # Same id, so the state reducer replaces rather than appends.
        assert revised.id == original.id
        assert revised.tool_calls[0]["args"] == {"command": "ls"}
        # The instance already streamed to clients keeps its original args.
        assert original.tool_calls[0]["args"] == {"command": "rm -rf /"}


class TestEditRewritesEveryProviderSurface:
    """An edited call must not leave its original args reachable anywhere.

    ``edit`` keeps the call id and changes only the args, so an id-keyed filter
    alone carries the pre-review payload forward on every surface other than
    ``tool_calls``. The tool node runs the edited args while the next model
    request can be serialized from a stale surface — telling the model ``rm``
    ran when the human approved ``ls``. Which surface a provider adapter reads
    varies, so all of them are asserted.
    """

    EDIT = {"type": "edit", "edited_action": {"name": "bash_tool", "args": {"command": "ls"}}}

    def _revise(self, **message_kwargs):
        message_kwargs.setdefault("content", "")
        original = AIMessage(id="ai-1", tool_calls=[_call()], **message_kwargs)
        state = {"messages": [HumanMessage(content="do it"), original]}
        result, _ = _resume(_middleware(), state, [self.EDIT])
        return original, result["messages"][0]

    def test_rewrites_the_raw_provider_payload(self):
        """OpenAI-style ``additional_kwargs``: a JSON string under ``function.arguments``."""
        original, revised = self._revise(
            additional_kwargs={"tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "bash_tool", "arguments": '{"command": "rm -rf /"}'}}]},
        )

        assert json.loads(revised.additional_kwargs["tool_calls"][0]["function"]["arguments"]) == {"command": "ls"}
        # The streamed instance is untouched.
        assert json.loads(original.additional_kwargs["tool_calls"][0]["function"]["arguments"]) == {"command": "rm -rf /"}

    def test_rewrites_an_anthropic_tool_use_content_block(self):
        _original, revised = self._revise(content=[{"type": "tool_use", "id": "call-1", "name": "bash_tool", "input": {"command": "rm -rf /"}}])

        block = revised.content[0]
        assert block["input"] == {"command": "ls"}
        # ``partial_json`` would otherwise re-leak the streamed original.
        assert "partial_json" not in block

    def test_rewrites_an_openai_responses_function_call_block(self):
        """Matched by ``call_id``; the ``fc_…`` item id is not the tool-call id."""
        _original, revised = self._revise(content=[{"type": "function_call", "id": "fc_1", "call_id": "call-1", "name": "bash_tool", "arguments": '{"command": "rm -rf /"}'}])

        block = revised.content[0]
        assert json.loads(block["arguments"]) == {"command": "ls"}
        assert block["id"] == "fc_1"

    def test_rewrites_a_v1_tool_call_content_block(self):
        """LangChain standard content: ``extras.arguments`` wins in the Responses translator."""
        _original, revised = self._revise(
            content=[{"type": "tool_call", "id": "call-1", "name": "bash_tool", "args": {"command": "rm -rf /"}, "extras": {"arguments": '{"command": "rm -rf /"}'}}],
        )

        block = revised.content[0]
        assert block["args"] == {"command": "ls"}
        assert json.loads(block["extras"]["arguments"]) == {"command": "ls"}

    def test_leaves_an_untouched_sibling_call_alone(self):
        """Only the edited id is rewritten; an approved sibling keeps its args."""
        original = AIMessage(
            content=[
                {"type": "tool_use", "id": "call-1", "name": "bash_tool", "input": {"command": "rm -rf /"}},
                {"type": "tool_use", "id": "call-2", "name": "bash_tool", "input": {"command": "keep-me"}},
            ],
            id="ai-1",
            tool_calls=[_call(), _call(args={"command": "keep-me"}, call_id="call-2")],
            additional_kwargs={
                "tool_calls": [
                    {"id": "call-1", "type": "function", "function": {"name": "bash_tool", "arguments": '{"command": "rm -rf /"}'}},
                    {"id": "call-2", "type": "function", "function": {"name": "bash_tool", "arguments": '{"command": "keep-me"}'}},
                ]
            },
        )
        state = {"messages": [HumanMessage(content="do it"), original]}

        result, _ = _resume(_middleware(), state, [self.EDIT, {"type": "approve"}])
        revised = result["messages"][0]

        assert [tc["args"] for tc in revised.tool_calls] == [{"command": "ls"}, {"command": "keep-me"}]
        assert [block["input"] for block in revised.content] == [{"command": "ls"}, {"command": "keep-me"}]
        assert [json.loads(raw["function"]["arguments"]) for raw in revised.additional_kwargs["tool_calls"]] == [{"command": "ls"}, {"command": "keep-me"}]

    def test_approve_does_not_rewrite_anything(self):
        """No edit means no rewrite: the surfaces pass through by identity."""
        original = AIMessage(
            content=[{"type": "tool_use", "id": "call-1", "name": "bash_tool", "input": {"command": "rm -rf /"}}],
            id="ai-1",
            tool_calls=[_call()],
            additional_kwargs={"tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "bash_tool", "arguments": '{"command": "rm -rf /"}'}}]},
        )
        state = {"messages": [HumanMessage(content="do it"), original]}

        result, _ = _resume(_middleware(), state, [{"type": "approve"}])
        revised = result["messages"][0]

        assert revised.content[0] is original.content[0]
        assert revised.additional_kwargs["tool_calls"][0] is original.additional_kwargs["tool_calls"][0]

    def test_an_edit_may_not_rename_the_call(self):
        """A rename would execute a tool its own gate never approved.

        Upstream's ``edit`` accepts ``edited_action["name"]``, but ``interrupt_on``
        is keyed by tool name: renaming would carry this call's approval over to a
        different tool, whose own ``interrupt_on`` (and ``when`` predicate, and
        ``args_schema``) never ran. It is also the one edit the surface sync could
        not honour — ``rewrite_tool_call_args`` rewrites args, not names.
        """
        decision = {"type": "edit", "edited_action": {"name": "ls_tool", "args": {"path": "/"}}}

        with pytest.raises(ValueError, match="may not rename"):
            _resume(_middleware(), _state([_call()]), [decision])

    def test_an_edit_that_keeps_the_name_is_still_allowed(self):
        """The guard rejects renames only; an ordinary args edit is untouched."""
        _original, revised = self._revise()

        assert revised.tool_calls[0]["name"] == "bash_tool"
        assert revised.tool_calls[0]["args"] == {"command": "ls"}

    def test_rejected_call_keeps_its_original_args_on_every_surface(self):
        """``reject`` keeps the call and answers it; nothing is rewritten.

        The args must stay as the model emitted them, because the pairing
        ``ToolMessage`` is what prevents execution — not a changed payload.
        """
        original = AIMessage(
            content=[{"type": "tool_use", "id": "call-1", "name": "bash_tool", "input": {"command": "rm -rf /"}}],
            id="ai-1",
            tool_calls=[_call()],
        )
        state = {"messages": [HumanMessage(content="do it"), original]}

        result, _ = _resume(_middleware(), state, [{"type": "reject", "message": "no"}])
        revised, _tool_message = result["messages"]

        assert revised.tool_calls[0]["args"] == {"command": "rm -rf /"}
        assert revised.content[0]["input"] == {"command": "rm -rf /"}


class TestParallelToolCalls:
    def test_only_configured_calls_are_reviewed(self):
        state = _state(
            [
                _call(name="read_file", args={"path": "a.txt"}, call_id="call-a"),
                _call(call_id="call-b"),
                _call(name="read_file", args={"path": "b.txt"}, call_id="call-c"),
            ]
        )
        result, request = _resume(_middleware(), state, [{"type": "reject", "message": "no"}])

        # Exactly one review was requested, for the gated tool only.
        assert [r["name"] for r in request["action_requests"]] == ["bash_tool"]

        revised, tool_message = result["messages"]
        # Every call survives in its original order; only the rejected one is
        # pre-answered so the tool node skips it.
        assert [tc["id"] for tc in revised.tool_calls] == ["call-a", "call-b", "call-c"]
        assert tool_message.tool_call_id == "call-b"

    def test_decisions_map_positionally_to_gated_calls(self):
        """Decision *i* belongs to the *i*-th gated call, not the *i*-th call."""
        state = _state(
            [
                _call(name="read_file", args={"path": "a.txt"}, call_id="call-a"),
                _call(args={"command": "one"}, call_id="call-b"),
                _call(args={"command": "two"}, call_id="call-c"),
            ]
        )
        decisions = [
            {"type": "edit", "edited_action": {"name": "bash_tool", "args": {"command": "edited-b"}}},
            {"type": "approve"},
        ]
        result, request = _resume(_middleware(), state, decisions)

        assert [r["args"]["command"] for r in request["action_requests"]] == ["one", "two"]

        revised = result["messages"][0]
        by_id = {tc["id"]: tc["args"] for tc in revised.tool_calls}
        # The first decision landed on call-b (first gated), not call-a.
        assert by_id["call-a"] == {"path": "a.txt"}
        assert by_id["call-b"] == {"command": "edited-b"}
        assert by_id["call-c"] == {"command": "two"}


class TestWhenPredicate:
    def test_when_false_skips_the_interrupt(self):
        _assert_not_gated(_middleware(when=lambda request: False), _state([_call()]))

    def test_when_true_still_interrupts(self):
        _assert_gated(_middleware(when=lambda request: True), _state([_call()]))

    def test_when_receives_the_tool_call(self):
        seen = {}

        def when(request):
            seen["tool_call"] = request.tool_call
            return False

        _assert_not_gated(_middleware(when=when), _state([_call()]))
        assert seen["tool_call"]["id"] == "call-1"


class TestArgsSchemaForEdit:
    """``edit`` needs the arg shape, which batch-mode interrupts can't supply."""

    def test_schema_is_forwarded_to_the_review_config(self):
        middleware = DeerFlowHumanInTheLoopMiddleware(
            interrupt_on={
                "bash_tool": {
                    "allowed_decisions": ["approve", "edit"],
                    "args_schema": {"type": "object", "properties": {"command": {"type": "string"}}},
                }
            }
        )
        _, request = _resume(middleware, _state([_call()]), [{"type": "approve"}])
        review_config = request["review_configs"][0]
        assert review_config["args_schema"]["properties"]["command"]["type"] == "string"

    def test_no_schema_key_when_edit_is_not_allowed(self):
        _, request = _resume(_middleware(allowed_decisions=("approve", "reject")), _state([_call()]), [{"type": "approve"}])
        assert "args_schema" not in request["review_configs"][0]

    def test_edit_without_a_schema_still_interrupts(self, caplog):
        """A missing schema degrades to raw-JSON editing rather than failing."""
        _, request = _resume(_middleware(allowed_decisions=("approve", "edit")), _state([_call()]), [{"type": "approve"}])
        assert "args_schema" not in request["review_configs"][0]
        assert "no args schema was captured" in caplog.text


class TestCreateInterruptMiddleware:
    def test_returns_none_when_no_tool_requests_approval(self):
        app_config = SimpleNamespace(tools=[ToolConfig(name="bash_tool", group="sandbox", use="deerflow.sandbox.tools:bash_tool")])
        assert create_interrupt_middleware(app_config) is None

    def test_builds_from_config(self):
        app_config = SimpleNamespace(
            tools=[
                ToolConfig(
                    name="bash_tool",
                    group="sandbox",
                    use="deerflow.sandbox.tools:bash_tool",
                    interrupt_on=InterruptOnConfigModel(allowed_decisions=["approve", "reject"], description="Review it"),
                )
            ]
        )
        middleware = create_interrupt_middleware(app_config)
        assert middleware is not None
        config = middleware.interrupt_on["bash_tool"]
        assert config["allowed_decisions"] == ["approve", "reject"]
        assert config["description"] == "Review it"
        # ``when`` must be absent, not present-and-None: upstream calls it.
        assert "when" not in config

    def test_captures_args_schema_for_edit(self):
        app_config = SimpleNamespace(
            tools=[
                ToolConfig(
                    name="bash_tool",
                    group="sandbox",
                    use="deerflow.sandbox.tools:bash_tool",
                    interrupt_on=InterruptOnConfigModel(allowed_decisions=["approve", "edit"]),
                )
            ]
        )
        middleware = create_interrupt_middleware(app_config, tools=[bash_tool])
        schema = middleware.interrupt_on["bash_tool"]["args_schema"]
        assert "command" in schema["properties"]

    def test_captures_args_schema_for_a_tool_with_an_injected_runtime(self):
        """The stub above has no injected args; every real sandbox tool does.

        A tool whose signature starts with ``runtime: ToolRuntime`` cannot be
        described by ``get_input_jsonschema()`` at all: ``ToolRuntime`` holds
        callables, so pydantic raises ``PydanticInvalidForJsonSchema`` and the
        schema capture degraded to a warning — leaving ``bash``, the tool most
        likely to be gated, with no edit form. ``tool_call_schema`` excludes
        injected args by design, which is also the correct contract here: a
        reviewer edits what the model filled, never framework-injected values.
        """
        app_config = SimpleNamespace(
            tools=[
                ToolConfig(
                    name="bash",
                    group="sandbox",
                    use="deerflow.sandbox.tools:bash_tool",
                    interrupt_on=InterruptOnConfigModel(allowed_decisions=["approve", "edit"]),
                )
            ]
        )

        middleware = create_interrupt_middleware(app_config, tools=[real_bash_tool])

        schema = middleware.interrupt_on["bash"]["args_schema"]
        assert "command" in schema["properties"]
        assert "runtime" not in schema["properties"]

    def test_skips_args_schema_when_edit_is_not_allowed(self):
        app_config = SimpleNamespace(
            tools=[
                ToolConfig(
                    name="bash_tool",
                    group="sandbox",
                    use="deerflow.sandbox.tools:bash_tool",
                    interrupt_on=InterruptOnConfigModel(allowed_decisions=["approve"]),
                )
            ]
        )
        middleware = create_interrupt_middleware(app_config, tools=[bash_tool])
        assert "args_schema" not in middleware.interrupt_on["bash_tool"]

    def test_ignores_ask_clarification_defensively(self):
        """Config validation blocks this; the builder must not trust that alone."""
        clarification = ToolConfig.model_construct(
            name="ask_clarification",
            group="builtin",
            use="deerflow.tools.builtins:ask_clarification",
            interrupt_on=InterruptOnConfigModel(allowed_decisions=["approve"]),
        )
        assert create_interrupt_middleware(SimpleNamespace(tools=[clarification])) is None


class _GraphState(TypedDict):
    messages: Annotated[list, add_messages]


def _run_through_real_graph(middleware, tool_calls, *, park_context, resume_context, decisions):
    """Drive ``middleware.after_model`` as a real graph node under a real checkpointer.

    Unlike ``_resume`` (which calls ``after_model`` directly with a patched
    ``interrupt()``), this compiles an actual ``StateGraph`` with
    ``InMemorySaver`` so a resume genuinely replays the node function from the
    top with fresh ``runtime.context`` -- the only way to exercise the
    park/resume desync this middleware's ``@task`` wrapping defends against.
    Returns the final message list after the resume completes.
    """

    def node(state, runtime):
        return middleware.after_model(state, runtime) or {}

    graph = StateGraph(_GraphState, context_schema=dict)
    graph.add_node("node", node)
    graph.add_edge(START, "node")
    graph.add_edge("node", END)
    compiled = graph.compile(checkpointer=InMemorySaver())

    config = {"configurable": {"thread_id": "t-1"}}
    state = _state(tool_calls)

    for _ in compiled.stream(state, config, context=park_context):
        pass

    for _ in compiled.stream(Command(resume={"decisions": decisions}), config, context=resume_context):
        pass

    return compiled.get_state(config).values["messages"]


async def _run_through_real_async_graph(middleware, tool_calls, *, park_context, resume_context, decisions):
    """The async counterpart of :func:`_run_through_real_graph`.

    Not redundant with it: LangGraph resolves a ``@task`` future through
    ``CONFIG_KEY_CALL``, which is ``_call`` (a plain executor submit, resolvable
    with ``.result()``) under the sync runner but ``_acall`` under the async one
    -- and ``_acall``'s future is completed by the pregel tick loop, so it is
    only ever resolved by ``await``. The sync helper above therefore cannot
    catch an ``after_model`` that calls ``.result()`` on the async future; that
    shipped as ``asyncio.InvalidStateError: Result is not set`` on every real
    async run while the whole sync suite stayed green. Every gateway run is
    async, so this path is the production one.
    """

    async def node(state, runtime):
        return await middleware.aafter_model(state, runtime) or {}

    graph = StateGraph(_GraphState, context_schema=dict)
    graph.add_node("node", node)
    graph.add_edge(START, "node")
    graph.add_edge("node", END)
    compiled = graph.compile(checkpointer=InMemorySaver())

    config = {"configurable": {"thread_id": "t-async-1"}}
    state = _state(tool_calls)

    async for _ in compiled.astream(state, config, context=park_context):
        pass

    async for _ in compiled.astream(Command(resume={"decisions": decisions}), config, context=resume_context):
        pass

    return (await compiled.aget_state(config)).values["messages"]


class TestAsyncRunnerResolvesTheReviewBatch:
    """The async path must await the ``@task`` future, never ``.result()`` it.

    Upstream's ``aafter_model`` just calls ``after_model`` synchronously, which
    made the sync-only future resolution look correct in every direct-call and
    sync-graph test while crashing every real Gateway run.
    """

    @pytest.mark.asyncio
    async def test_parks_and_resumes_under_the_async_runner(self):
        middleware = DeerFlowHumanInTheLoopMiddleware(interrupt_on={"bash_tool": {"allowed_decisions": ["approve", "reject"]}})

        messages = await _run_through_real_async_graph(
            middleware,
            [_call(call_id="call-1")],
            park_context={},
            resume_context={},
            decisions=[{"type": "approve"}],
        )

        revised = next(m for m in reversed(messages) if isinstance(m, AIMessage))
        assert [tc["id"] for tc in revised.tool_calls] == ["call-1"]

    @pytest.mark.asyncio
    async def test_async_resume_keeps_the_park_time_review_batch(self):
        """Replay safety must hold on the async path too, not just the sync one."""
        middleware = DeerFlowHumanInTheLoopMiddleware(
            interrupt_on={
                "bash_tool": {"allowed_decisions": ["approve", "reject"]},
                "other_tool": {"allowed_decisions": ["approve", "reject"]},
            }
        )
        tool_calls = [_call(call_id="call-1"), _call(name="other_tool", args={"x": 1}, call_id="call-2")]

        messages = await _run_through_real_async_graph(
            middleware,
            tool_calls,
            park_context={TOOL_APPROVAL_OMIT_KEY: []},
            resume_context={TOOL_APPROVAL_OMIT_KEY: ["bash_tool"]},
            decisions=[{"type": "approve"}, {"type": "approve"}],
        )

        revised = next(m for m in reversed(messages) if isinstance(m, AIMessage))
        assert [tc["id"] for tc in revised.tool_calls] == ["call-1", "call-2"]


class TestReplaySafeAcrossContextChange:
    """The park-trip's review batch must survive a resume with a changed context.

    A client is allowed to bundle a changed ``tool_approval_omit`` (e.g.
    "approve, and don't ask again") together with the ``decisions`` that
    answer the very batch it is changing, in one ``Command(resume=...)``
    call. Recomputing which calls need review from that new context would
    desync the resumed ``decisions`` list against a shrunk ``interrupt_indices``,
    either raising a spurious count-mismatch error or silently letting a call
    that was pending review execute unreviewed.
    """

    def test_omit_added_at_resume_does_not_desync_decision_count(self):
        """Two calls parked for review; omitting one at resume must not raise."""
        middleware = DeerFlowHumanInTheLoopMiddleware(
            interrupt_on={
                "bash_tool": {"allowed_decisions": ["approve", "reject"]},
                "other_tool": {"allowed_decisions": ["approve", "reject"]},
            }
        )
        tool_calls = [_call(call_id="call-1"), _call(name="other_tool", args={"x": 1}, call_id="call-2")]

        messages = _run_through_real_graph(
            middleware,
            tool_calls,
            park_context={TOOL_APPROVAL_OMIT_KEY: []},
            resume_context={TOOL_APPROVAL_OMIT_KEY: ["bash_tool"]},
            decisions=[{"type": "approve"}, {"type": "approve"}],
        )

        revised = next(m for m in reversed(messages) if isinstance(m, AIMessage))
        # Both decisions landed: the resume-time omit change never desynced
        # the 2 decisions against a recomputed, shrunk review batch.
        assert [tc["id"] for tc in revised.tool_calls] == ["call-1", "call-2"]

    def test_omit_added_at_resume_still_answers_the_parked_review_not_skip_it(self):
        """The now-omitted call was still reviewed and rejected, never silently run."""
        middleware = DeerFlowHumanInTheLoopMiddleware(interrupt_on={"bash_tool": {"allowed_decisions": ["approve", "reject"]}})
        tool_calls = [_call(call_id="call-1")]

        messages = _run_through_real_graph(
            middleware,
            tool_calls,
            park_context={TOOL_APPROVAL_OMIT_KEY: []},
            resume_context={TOOL_APPROVAL_OMIT_KEY: ["bash_tool"]},
            decisions=[{"type": "reject", "message": "too risky"}],
        )

        revised, tool_message = (m for m in messages if isinstance(m, (AIMessage, ToolMessage)))
        assert isinstance(tool_message, ToolMessage)
        assert tool_message.tool_call_id == "call-1"
        assert tool_message.status == "error"
        assert tool_message.content == "too risky"
