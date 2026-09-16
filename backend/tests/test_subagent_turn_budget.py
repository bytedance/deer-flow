"""Tests for translating a subagent turn budget into a LangGraph recursion limit.

Covers:
- Per-turn and per-invocation node counting from a middleware chain
- Sync-only, async-only, and both-sided hooks each costing exactly one node
- ``resolve_recursion_limit`` arithmetic, including a non-positive budget
- A pin test that compiles real ``create_agent`` graphs and binary-searches the
  smallest ``recursion_limit`` that completes N turns, so the formula is checked
  against the installed LangChain rather than against its documentation
"""

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.errors import GraphRecursionError

from deerflow.subagents.turn_budget import count_invocation_steps, count_turn_steps, find_jumping_hooks, resolve_recursion_limit


def _middleware(name: str, *hooks: str) -> AgentMiddleware:
    """Build a no-op middleware overriding exactly *hooks*."""
    namespace = {hook: (lambda self, state, runtime: None) for hook in hooks}
    return type(name, (AgentMiddleware,), namespace)()


class TestNodeCounting:
    def test_bare_chain_costs_model_plus_tools(self):
        assert count_turn_steps([]) == 2
        assert count_invocation_steps([]) == 0

    def test_each_model_hook_adds_one_node(self):
        chain = [_middleware("Before", "before_model"), _middleware("After", "after_model")]

        assert count_turn_steps(chain) == 4

    def test_one_middleware_implementing_both_model_hooks_adds_two_nodes(self):
        chain = [_middleware("Both", "before_model", "after_model")]

        assert count_turn_steps(chain) == 4

    def test_async_only_hook_costs_the_same_as_sync(self):
        """LangChain compiles one node per sync/async pair, whichever side exists."""
        sync_only = [_middleware("Sync", "after_model")]
        async_only = [_middleware("Async", "aafter_model")]
        both_sides = [_middleware("Both", "after_model", "aafter_model")]

        assert count_turn_steps(sync_only) == count_turn_steps(async_only) == count_turn_steps(both_sides) == 3

    def test_agent_hooks_are_charged_once_per_invocation_not_per_turn(self):
        chain = [_middleware("Lifecycle", "before_agent", "after_agent")]

        assert count_turn_steps(chain) == 2
        assert count_invocation_steps(chain) == 2

    def test_middleware_without_lifecycle_hooks_is_free(self):
        """A wrap-only middleware runs inside the model node, so it adds none."""

        class WrapOnly(AgentMiddleware):
            def wrap_model_call(self, request, handler):
                return handler(request)

        assert count_turn_steps([WrapOnly()]) == 2
        assert count_invocation_steps([WrapOnly()]) == 0

    def test_object_without_hooks_contributes_nothing(self):
        """A duck-typed entry compiles to no node, so a missing hook is not an override."""
        assert count_turn_steps([object()]) == 2
        assert count_invocation_steps([object()]) == 0


class TestResolveRecursionLimit:
    def test_scales_turns_by_the_assembled_chain(self):
        """Regression: passing ``max_turns`` through divided the budget by chain depth."""
        chain = [
            _middleware("Before", "before_model"),
            _middleware("After1", "after_model"),
            _middleware("After2", "after_model"),
            _middleware("After3", "after_model"),
            _middleware("After4", "after_model"),
        ]

        assert resolve_recursion_limit(150, chain) == 150 * 7

    def test_adds_invocation_steps_on_top_of_the_turn_budget(self):
        chain = [_middleware("Loop", "before_model"), _middleware("Lifecycle", "before_agent", "after_agent")]

        assert resolve_recursion_limit(10, chain) == 10 * 3 + 2

    def test_non_positive_budget_still_buys_one_turn(self):
        """LangGraph rejects a limit below 1; a misconfigured budget must not fail the run."""
        assert resolve_recursion_limit(0, []) == 2
        assert resolve_recursion_limit(-5, []) == 2


class TestFindJumpingHooks:
    """A jump re-enters the loop without traversing ``tools``.

    The flat per-turn multiplier does not model that, and how often a jump fires
    is data-dependent, so the condition is reported rather than priced in.
    """

    def test_reports_the_middleware_and_hook_that_declares_a_jump(self):
        class Jumper(AgentMiddleware):
            @hook_config(can_jump_to=["model"])
            def after_model(self, state, runtime):
                return None

        assert find_jumping_hooks([Jumper()]) == [("Jumper", "after_model")]

    def test_reports_an_async_hook_declaration(self):
        class AsyncJumper(AgentMiddleware):
            @hook_config(can_jump_to=["end"])
            async def abefore_model(self, state, runtime):
                return None

        assert find_jumping_hooks([AsyncJumper()]) == [("AsyncJumper", "abefore_model")]

    def test_plain_hooks_declare_no_jump(self):
        chain = [_middleware("Before", "before_model"), _middleware("After", "after_model")]

        assert find_jumping_hooks(chain) == []

    def test_agent_level_hooks_are_not_reported(self):
        """They run once per invocation; a jump out of them lands in the paid-for loop."""

        class LifecycleJumper(AgentMiddleware):
            @hook_config(can_jump_to=["model"])
            def before_agent(self, state, runtime):
                return None

        assert find_jumping_hooks([LifecycleJumper()]) == []

    def test_object_without_hooks_is_not_reported(self):
        assert find_jumping_hooks([object()]) == []


class _ScriptedModel(BaseChatModel):
    """Emits ``turns - 1`` tool calls, then a final text answer."""

    turns: int
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.calls += 1
        if self.calls < self.turns:
            message = AIMessage(content="", tool_calls=[{"name": "ping", "args": {}, "id": f"call-{self.calls}"}])
        else:
            message = AIMessage(content="done")
        return ChatResult(generations=[ChatGeneration(message=message)])


@tool
def ping() -> str:
    """Return a fixed token."""
    return "pong"


def _smallest_limit_completing(chain: list[AgentMiddleware], turns: int) -> int:
    """Binary-search the smallest ``recursion_limit`` that completes *turns* turns."""
    low, high = 1, 512
    while low < high:
        candidate = (low + high) // 2
        agent = create_agent(model=_ScriptedModel(turns=turns), tools=[ping], middleware=chain, checkpointer=False)
        try:
            agent.invoke({"messages": [("user", "go")]}, {"recursion_limit": candidate})
        except GraphRecursionError:
            low = candidate + 1
        else:
            high = candidate
    return low


class TestFormulaMatchesCompiledGraph:
    """Pins the arithmetic against the installed LangChain, not against its docs.

    If LangChain changes how it compiles middleware hooks into nodes, the
    subagent turn budget silently drifts again. These cases fail instead.
    """

    @pytest.mark.parametrize(
        "hooks",
        [
            (),
            (("Before", "before_model"),),
            (("After", "after_model"),),
            (("Before", "before_model"), ("After1", "after_model"), ("After2", "after_model")),
            (("Lifecycle", "before_agent", "after_agent"), ("After", "after_model")),
        ],
    )
    @pytest.mark.parametrize("turns", [1, 3])
    def test_resolved_limit_is_exactly_what_the_graph_needs(self, hooks, turns):
        chain = [_middleware(*spec) for spec in hooks]

        assert resolve_recursion_limit(turns, chain) == _smallest_limit_completing(chain, turns)

    def test_a_jumping_hook_makes_the_limit_a_lower_bound(self):
        """Why ``find_jumping_hooks`` exists, pinned against a real graph.

        The model here counts progress off the ToolMessages actually in state, so
        a jump — which re-enters the model without traversing ``tools`` — buys no
        progress and is pure overhead, the retry/repair shape.
        """

        class _ToolProgressModel(_ScriptedModel):
            def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
                executed = sum(1 for message in messages if getattr(message, "type", None) == "tool")
                if executed < self.turns:
                    message = AIMessage(content="", tool_calls=[{"name": "ping", "args": {}, "id": f"call-{executed}"}])
                else:
                    message = AIMessage(content="done")
                return ChatResult(generations=[ChatGeneration(message=message)])

        class _JumpOnce(AgentMiddleware):
            def __init__(self) -> None:
                super().__init__()
                self.jumped = False

            @hook_config(can_jump_to=["model"])
            def after_model(self, state, runtime):
                if self.jumped:
                    return None
                self.jumped = True
                return {"jump_to": "model"}

        tool_turns = 3
        budget_turns = tool_turns + 1  # the tool turns plus the turn that answers

        def build(limit):
            return create_agent(model=_ToolProgressModel(turns=tool_turns), tools=[ping], middleware=[_JumpOnce()], checkpointer=False).invoke({"messages": [("user", "go")]}, {"recursion_limit": limit})

        resolved = resolve_recursion_limit(budget_turns, [_JumpOnce()])
        with pytest.raises(GraphRecursionError):
            build(resolved)
        # One jump costs another before_model + model + after_model pass.
        build(resolved + count_turn_steps([_JumpOnce()]) - 1)

        assert find_jumping_hooks([_JumpOnce()]) == [("_JumpOnce", "after_model")]
