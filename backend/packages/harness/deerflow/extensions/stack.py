"""The anchor table and the single composition entry point.

This is where DeerFlow's stack shape is encoded. Two structural facts drive it:

* The stack is built at two nested points — `build_lead_runtime_middlewares()`
  produces the base, then `build_middlewares()` appends ~18 lead-specific
  middlewares that are all *inner* of it. MODEL_PHYSICAL lands in the second
  group, so extension injection must happen after the final list is assembled,
  never inside the base builder.
* First item in the list is the outermost wrapper (LangChain composition rule).
"""

from __future__ import annotations

from collections.abc import Sequence

from deerflow_extension_api import AgentBuildContext, AgentScope, Placement

from deerflow.extensions.anchors import (
    PlacementAnchor,
    inner_of_last,
    inner_of_last_after,
    innermost,
    outer_of,
    outer_of_last,
    outermost,
)
from deerflow.extensions.injection import inject_middlewares
from deerflow.extensions.ordering import assert_ordering
from deerflow.extensions.registry import LoadedExtensions


def _anchors() -> dict[Placement, PlacementAnchor]:
    from deerflow.agents.middlewares.clarification_middleware import ClarificationMiddleware
    from deerflow.agents.middlewares.llm_error_handling_middleware import LLMErrorHandlingMiddleware
    from deerflow.agents.middlewares.safety_finish_reason_middleware import SafetyFinishReasonMiddleware
    from deerflow.agents.middlewares.terminal_response_middleware import TerminalResponseMiddleware

    return {
        # Outer of the retry loop, so one logical decision stays one event even
        # when LLMErrorHandlingMiddleware retries underneath.
        Placement.MODEL_LOGICAL: outer_of(LLMErrorHandlingMiddleware),
        # Inner of every lead-agent request transform. Deliberately NOT
        # innermost(): ClarificationMiddleware sits inner of this point today,
        # and moving the anchor past it would change what "the final request"
        # means.
        Placement.MODEL_PHYSICAL: PlacementAnchor.of(
            inner_of_last_after(
                SafetyFinishReasonMiddleware,
                after=(TerminalResponseMiddleware,),
            ),
            inner_of_last(TerminalResponseMiddleware),
            outer_of_last(ClarificationMiddleware),
            innermost(),
        ),
        Placement.TOOL_VISIBLE: outermost(),
        # As close to the tool callable as the chain allows. Deliberately NOT
        # inner_of(ToolErrorHandlingMiddleware): SkillToolPolicyMiddleware and
        # ClarificationMiddleware are appended later and also wrap tool calls,
        # so anchoring there left two wrappers inner of "raw" and the placement
        # silently stopped meaning what it says.
        #
        # ClarificationMiddleware remains the one carve-out, the same shape as
        # MODEL_PHYSICAL's above: it must stay last (it short-circuits the tool
        # loop with Command(goto=END)), and it only ever intercepts
        # ask_clarification — it does not transform the result of any tool that
        # actually executes, so TOOL_RAW still sees raw results.
        Placement.TOOL_RAW: PlacementAnchor.of(
            outer_of_last(ClarificationMiddleware),
            innermost(),
        ),
        Placement.STANDARD: PlacementAnchor.of(
            outer_of(LLMErrorHandlingMiddleware),
            innermost(),
        ),
    }


class _AnchorTable(dict):
    """Resolve the table lazily so importing this module stays cheap and
    free of middleware import cycles."""

    _loaded = False

    def _ensure(self) -> None:
        if not _AnchorTable._loaded:
            self.update(_anchors())
            _AnchorTable._loaded = True

    def __getitem__(self, key):
        self._ensure()
        return dict.__getitem__(self, key)

    def get(self, key, default=None):
        self._ensure()
        return dict.get(self, key, default)

    def __iter__(self):
        self._ensure()
        return dict.__iter__(self)

    def __len__(self):
        self._ensure()
        return dict.__len__(self)

    def snapshot(self) -> dict[Placement, PlacementAnchor]:
        """Return a populated plain-dict copy.

        CPython's ``dict(subclass)`` fast path can copy the underlying storage
        without calling this class's lazy ``__iter__`` or ``__len__`` hooks.
        Callers that need a copy must therefore force resolution explicitly.
        """
        self._ensure()
        return dict(self)


PLACEMENT_ANCHORS = _AnchorTable()


def _placement_anchors_for_scope(scope: AgentScope) -> dict[Placement, PlacementAnchor]:
    if scope != AgentScope.SUBAGENT:
        return PLACEMENT_ANCHORS

    from deerflow.agents.middlewares.system_message_coalescing_middleware import SystemMessageCoalescingMiddleware

    anchors = PLACEMENT_ANCHORS.snapshot()
    anchors[Placement.MODEL_PHYSICAL] = PlacementAnchor.of(
        inner_of_last(SystemMessageCoalescingMiddleware),
        PLACEMENT_ANCHORS[Placement.MODEL_PHYSICAL],
    )
    return anchors


def compose_with_extensions(
    middlewares: Sequence[object],
    scope: AgentScope,
    ctx: AgentBuildContext | None,
    extensions: LoadedExtensions | None = None,
) -> list[object]:
    """Merge extension contributions into a fully-assembled stack and validate.

    Call this once, at the end of the outermost builder. Calling it inside the
    base builder would place MODEL_PHYSICAL contributions above the ~18
    lead-specific middlewares appended afterwards.
    """
    from deerflow.extensions import get_agent_build_extensions, record_runtime_diagnostic

    resolved = extensions if extensions is not None else get_agent_build_extensions()

    if not resolved.has_middleware_contributors:
        assert_ordering(middlewares, {})
        return middlewares if isinstance(middlewares, list) else list(middlewares)

    if ctx is None:
        raise ValueError("AgentBuildContext is required when middleware extensions are loaded")

    result = list(middlewares)

    result, provenance, diagnostics = inject_middlewares(
        result,
        _placement_anchors_for_scope(scope),
        scope,
        ctx,
        resolved,
        isolation_diagnostic_sink=record_runtime_diagnostic,
    )
    _record_diagnostics(diagnostics)
    assert_ordering(result, provenance)
    return result


def _record_diagnostics(diagnostics) -> None:
    """Diagnostics raised while building a stack are logged by their producers;
    this hook exists so the Gateway can also surface them on app.state."""
    from deerflow.extensions import record_runtime_diagnostics

    record_runtime_diagnostics(diagnostics)


def middleware_implements(middleware: object, hook_name: str) -> bool:
    """Whether ``middleware`` actually overrides ``hook_name``.

    Placement guarantees are per hook chain, not per list index: a middleware's
    position only means something on the chains it participates in. This is how
    the guarantee tests tell participation from mere presence.
    """
    from langchain.agents.middleware import AgentMiddleware

    own = getattr(type(middleware), hook_name, None)
    base = getattr(AgentMiddleware, hook_name, None)
    return own is not None and own is not base
