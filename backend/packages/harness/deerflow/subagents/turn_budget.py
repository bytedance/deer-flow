"""Translating a subagent's turn budget into a LangGraph recursion limit.

``max_turns`` is a per-agent policy an operator writes in ``config.yaml``:
how many times this agent may think and act before it is cut off. LangGraph's
``recursion_limit`` counts something else — super-steps, one per graph node
executed — and ``create_agent`` compiles every middleware lifecycle hook into
its own node (``{middleware}.before_model``, ``{middleware}.after_model``), so
one turn costs

    before_model nodes + ``model`` + after_model nodes + ``tools``

super-steps. The agent-level hooks add ``before_agent + after_agent`` on top,
once per invocation rather than once per turn.

Passing ``max_turns`` straight through as ``recursion_limit`` therefore divides
the operator's budget by the depth of the middleware chain — the subagent chain
compiles seven to eight loop nodes, so ``max_turns=150`` bought roughly eighteen
turns — and silently shrinks every agent's budget again each time a middleware
is added. This module does the translation instead, deriving the multiplier from
the chain that was actually assembled.

Hook participation is read the way LangChain's own factory reads it: a
class-level identity check against :class:`AgentMiddleware`'s base
implementation. A middleware that leaves a hook alone costs nothing, and an
extension middleware wrapped by ``IsolatedMiddleware`` — which mirrors that
identity precisely so LangChain sees the wrapper as the middleware it wraps —
is counted exactly like its inner middleware.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain.agents.middleware import AgentMiddleware

# The nodes every turn traverses whatever the middleware chain looks like:
# LangChain's ``model`` node, and the ``tools`` node the loop returns through.
# The turn that answers without tool calls skips ``tools`` but instead pays the
# graph's entry step, so the per-turn cost is the same either way — which is why
# this is a flat multiplier and not a multiplier plus a one-off correction.
_LOOP_NODES_PER_TURN = 2

# Sync/async hook pairs, in the grouping LangChain compiles them: one node per
# pair, whichever side (or both) a middleware overrides.
_LOOP_HOOK_PAIRS = (("before_model", "abefore_model"), ("after_model", "aafter_model"))
_INVOCATION_HOOK_PAIRS = (("before_agent", "abefore_agent"), ("after_agent", "aafter_agent"))


def _implements(middleware: Any, hook_pair: tuple[str, str]) -> bool:
    """Whether *middleware* overrides either side of one sync/async hook pair.

    An object that does not carry the hook at all compiles to no node, so it
    counts as not implementing it — LangChain's own check assumes an
    :class:`AgentMiddleware` subclass and would raise on anything else.
    """
    middleware_type = type(middleware)
    for hook in hook_pair:
        implementation = getattr(middleware_type, hook, None)
        if implementation is not None and implementation is not getattr(AgentMiddleware, hook, None):
            return True
    return False


def _count_nodes(middlewares: Sequence[Any], hook_pairs: tuple[tuple[str, str], ...]) -> int:
    """Nodes *middlewares* contribute across *hook_pairs* (one per implemented pair)."""
    return sum(1 for middleware in middlewares for hook_pair in hook_pairs if _implements(middleware, hook_pair))


def count_turn_steps(middlewares: Sequence[Any]) -> int:
    """Super-steps one agent turn costs with *middlewares* in the chain."""
    return _count_nodes(middlewares, _LOOP_HOOK_PAIRS) + _LOOP_NODES_PER_TURN


def count_invocation_steps(middlewares: Sequence[Any]) -> int:
    """Super-steps spent once per invocation, outside the agent loop."""
    return _count_nodes(middlewares, _INVOCATION_HOOK_PAIRS)


def resolve_recursion_limit(max_turns: int, middlewares: Sequence[Any]) -> int:
    """The ``recursion_limit`` that buys *max_turns* turns through this chain.

    A non-positive ``max_turns`` is clamped to one turn: LangGraph rejects a
    ``recursion_limit`` below 1, and a misconfigured budget should still let the
    agent answer once rather than fail the run before it starts.
    """
    return max(1, max_turns) * count_turn_steps(middlewares) + count_invocation_steps(middlewares)
