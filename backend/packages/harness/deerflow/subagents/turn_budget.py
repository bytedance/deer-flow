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

The per-turn cost is a flat multiplier, which models the straight
``before_model -> model -> tools`` loop and nothing else. A hook that declares
``can_jump_to`` and returns ``{"jump_to": ...}`` re-enters the loop without
traversing ``tools``, spending another ``before_model + model + after_model``
pass that buys no tool result — so a chain containing one makes the resolved
limit a lower bound rather than an exact budget. How often a jump fires is
data-dependent and unbounded, so it cannot be folded into the arithmetic;
:func:`find_jumping_hooks` exposes the condition instead, and the subagent
executor warns when a counted hook declares one. No middleware in today's
subagent chain does.
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

# Where LangChain's ``hook_config(can_jump_to=...)`` decorator leaves its
# declaration; the factory reads the same attribute off the same hook methods.
_JUMP_DECLARATION_ATTR = "__can_jump_to__"


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


def find_jumping_hooks(middlewares: Sequence[Any]) -> list[tuple[str, str]]:
    """Counted hooks that declare a jump, as ``(middleware, hook)`` name pairs.

    Such a hook can re-enter the agent loop without traversing ``tools``, which
    costs super-steps the flat per-turn multiplier does not model, so a non-empty
    result means :func:`resolve_recursion_limit` is a lower bound. Only the
    per-turn hooks are inspected: ``before_agent`` / ``after_agent`` run once per
    invocation, and a jump out of them lands in the loop the budget already pays
    for. The declaration is read off the same attribute, on the same overridden
    methods, that LangChain's factory reads it from.
    """
    jumping: list[tuple[str, str]] = []
    for middleware in middlewares:
        middleware_type = type(middleware)
        for hook_pair in _LOOP_HOOK_PAIRS:
            for hook in hook_pair:
                # No identity check against the base method is needed here, unlike
                # in the node counting above: only ``hook_config`` writes this
                # attribute, and it is never on ``AgentMiddleware``'s own hooks, so
                # a middleware that leaves the hook alone reads back as no jump.
                if getattr(getattr(middleware_type, hook, None), _JUMP_DECLARATION_ATTR, None):
                    jumping.append((middleware_type.__name__, hook))
    return jumping


def resolve_recursion_limit(max_turns: int, middlewares: Sequence[Any]) -> int:
    """The ``recursion_limit`` that buys *max_turns* turns through this chain.

    A non-positive ``max_turns`` is clamped to one turn: LangGraph rejects a
    ``recursion_limit`` below 1, and a misconfigured budget should still let the
    agent answer once rather than fail the run before it starts.

    The result is exact for a chain of non-jumping hooks and a lower bound
    otherwise; see :func:`find_jumping_hooks`.
    """
    return max(1, max_turns) * count_turn_steps(middlewares) + count_invocation_steps(middlewares)
