"""Tool-execution approval middleware (human in the loop).

DeerFlow has two distinct human-in-the-loop paths and they must not be
confused:

* ``ask_clarification`` (:mod:`~deerflow.agents.middlewares.clarification_middleware`)
  is a *model-initiated question*. It ends the turn with ``Command(goto=END)``
  and the human "resumes" by sending an ordinary next ``HumanMessage``.
* **This** middleware is a *system-initiated gate* on tool execution. It raises
  a real LangGraph ``interrupt()``, so the run stays parked in the checkpoint as
  a pending task and is resumed with ``Command(resume={"decisions": [...]})``.

Because the resume contracts are incompatible, ``ask_clarification`` can never
be an approval target; :class:`~deerflow.config.tool_config.ToolConfig`
rejects that combination and :func:`create_interrupt_middleware` drops it
defensively.

Runs that have no human on the other end must not park forever: every tool call
is auto-approved when the run context carries ``disable_tool_approval`` (set by
IM channels, mirroring the existing ``disable_clarification`` switch) or
``non_interactive`` (already set by the scheduler and the MCP task-notification
launcher).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware.human_in_the_loop import (
    ActionRequest,
    HITLRequest,
    HumanInTheLoopMiddleware,
    InterruptOnConfig,
    ReviewConfig,
)
from langchain.agents.middleware.types import AgentState, ContextT
from langchain_core.messages import AIMessage, ToolCall, ToolMessage
from langgraph.func import task
from langgraph.types import interrupt

from deerflow.agents.middlewares.tool_call_metadata import clone_ai_message_with_tool_calls
from deerflow.config.app_config import AppConfig, get_app_config
from deerflow.config.tool_config import NON_APPROVABLE_TOOL_NAMES
from deerflow.reflection import resolve_variable

if TYPE_CHECKING:
    from collections.abc import Sequence

    from langchain_core.tools import BaseTool
    from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)

# Run-context key that auto-approves every tool call. Set by non-interactive
# callers (IM channels, webhooks) because an interrupt there would park the
# thread with nobody able to resume it.
DISABLE_TOOL_APPROVAL_KEY = "disable_tool_approval"

# The pre-existing marker for a run with no human on the other end: the
# scheduler and the MCP task-notification launcher set it, and the lead-agent
# factory already strips ``ask_clarification`` on it. It is honoured here too,
# so a non-interactive entrypoint cannot park a thread merely by not knowing
# about the newer key. Mirrors ``sandbox/middleware.py``, which treats the two
# as one signal for network approval.
NON_INTERACTIVE_KEY = "non_interactive"

# Run-context key holding tool names the human already chose to stop being
# asked about ("Yes, and don't ask again" in the TUI). Scoped to one caller's
# session rather than persisted as config.
TOOL_APPROVAL_OMIT_KEY = "tool_approval_omit"


def _tool_args_schema(tool: BaseTool) -> dict[str, Any] | None:
    """Best-effort JSON schema for the args a model fills on *tool*.

    Needed for the ``edit`` decision: the reviewer edits raw tool args, so the
    client has to know their shape. LangGraph's batch-mode ``ToolCallRequest``
    is built with ``tool=None`` and no ``runtime.tools``, so the schema cannot
    be recovered inside ``after_model`` — it is captured at assembly time.

    Derived from ``tool_call_schema``, not ``get_input_jsonschema()``. The
    latter describes *every* parameter, injected ones included, which is both
    wrong for this purpose and fatal for the tools that most need approval:
    every sandbox tool takes a ``runtime: ToolRuntime`` argument the framework
    fills, and ``ToolRuntime`` holds callables, so asking pydantic for its JSON
    schema raises ``PydanticInvalidForJsonSchema`` and ``bash`` silently lost
    its edit form. ``tool_call_schema`` drops injected args by design, leaving
    exactly the fields a human should be editing.
    """
    try:
        schema = tool.tool_call_schema
        # dict when the tool was declared with a raw JSON ``args_schema``;
        # a pydantic model class otherwise.
        resolved = schema if isinstance(schema, dict) else schema.model_json_schema()
    except Exception:
        logger.debug("Could not derive an args schema for tool %r", getattr(tool, "name", tool), exc_info=True)
        return None
    return resolved if isinstance(resolved, dict) else None


class DeerFlowHumanInTheLoopMiddleware(HumanInTheLoopMiddleware):
    """Approve, edit, reject, or answer for a tool call before it executes.

    Extends the upstream middleware in three ways:

    * honours the ``disable_tool_approval`` and ``non_interactive`` run-context
      switches, so non-interactive runs never park;
    * honours the ``tool_approval_omit`` run-context list, so a client can
      offer "don't ask again" for the rest of a session;
    * forwards the configured ``args_schema`` to the client and rebuilds the
      ``AIMessage`` instead of mutating it in place.
    """

    def _approval_disabled(self, runtime: Runtime[ContextT]) -> bool:
        """Whether this run auto-approves every tool call.

        Either marker is enough. Reading both means a non-interactive
        entrypoint downgrades correctly without having to opt in twice, which
        is what a scheduled run relies on.
        """
        context = getattr(runtime, "context", None)
        if not context:
            return False
        return bool(context.get(DISABLE_TOOL_APPROVAL_KEY) or context.get(NON_INTERACTIVE_KEY))

    def _omitted_tools(self, runtime: Runtime[ContextT]) -> frozenset[str]:
        """Tool names the human opted out of being asked about."""
        context = getattr(runtime, "context", None)
        if not context:
            return frozenset()
        omitted = context.get(TOOL_APPROVAL_OMIT_KEY)
        if not omitted:
            return frozenset()
        if isinstance(omitted, str):
            return frozenset({omitted})
        if not isinstance(omitted, (list, tuple, set, frozenset)):
            # A client-supplied value can reach here un-sanitized (Gateway only
            # normalizes the ``body.context`` path, not a verbatim-copied
            # ``body.config["context"]``). Degrade to "omit nothing" instead of
            # raising ``TypeError`` on a non-iterable like an int or bool.
            logger.warning("Ignoring malformed %r context value: %r", TOOL_APPROVAL_OMIT_KEY, omitted)
            return frozenset()
        return frozenset(str(name) for name in omitted)

    def _create_action_and_config(
        self,
        tool_call: ToolCall,
        config: InterruptOnConfig,
        state: AgentState[Any],
        runtime: Runtime[ContextT],
    ) -> tuple[ActionRequest, ReviewConfig]:
        """Forward the configured args schema so ``edit`` forms can be rendered.

        Upstream builds the ``ReviewConfig`` without ``args_schema`` even when
        ``InterruptOnConfig`` carries one, which leaves an ``edit`` decision
        with nothing to render.
        """
        action_request, review_config = super()._create_action_and_config(tool_call, config, state, runtime)

        if "edit" not in config["allowed_decisions"]:
            return action_request, review_config

        schema = config.get("args_schema")
        if schema is not None:
            review_config["args_schema"] = schema
        else:
            # Not fatal: the client can fall back to editing raw JSON args.
            logger.warning(
                "Tool %r allows the 'edit' decision but no args schema was captured; the client may not be able to render an edit form.",
                tool_call["name"],
            )

        return action_request, review_config

    def _build_review_batch(
        self,
        tool_calls: list[ToolCall],
        state: AgentState[Any],
        mw_runtime: Runtime[ContextT],
    ) -> tuple[list[ActionRequest], list[ReviewConfig], list[int]]:
        """Decide which of *tool_calls* need human review, and build their requests.

        Called through :meth:`_run_review_batch`, which wraps it in a
        ``@task`` while inside a real graph run. LangGraph replays
        ``after_model`` from the top on every resume, but only re-derives
        this decision from whatever ``state``/``runtime.context`` looks like
        on *that* trip. A client is allowed to change ``tool_approval_omit``
        (e.g. "approve, and don't ask again") in the very same resume call
        that answers this batch's decisions, and the same hazard applies to
        any ``when`` predicate that reads mutable state — recomputing here
        would then desync the resumed ``decisions`` list against a shrunk or
        grown ``interrupt_indices``, either raising a spurious mismatch error
        or, worse, silently letting a still-pending call through with no
        review at all. The ``@task`` wrapper makes this decision once, at
        park time, and replays that exact result on resume instead.

        The parameter is named ``mw_runtime`` rather than ``runtime``:
        LangGraph's ``RunnableCallable`` treats a parameter literally named
        ``runtime`` as a reserved injection point and overwrites whatever is
        passed positionally, which raised ``TypeError: got multiple values
        for argument 'runtime'`` when this ran as a real ``@task`` inside a
        graph (it never surfaced in the direct-call unit-test style, which
        never goes through ``RunnableCallable``).
        """
        omitted_tools = self._omitted_tools(mw_runtime)

        action_requests: list[ActionRequest] = []
        review_configs: list[ReviewConfig] = []
        interrupt_indices: list[int] = []

        for idx, tool_call in enumerate(tool_calls):
            config = self.interrupt_on.get(tool_call["name"])
            if config is None or tool_call["name"] in omitted_tools:
                continue
            if not self._should_interrupt(tool_call, config, state, mw_runtime):
                continue
            action_request, review_config = self._create_action_and_config(tool_call, config, state, mw_runtime)
            action_requests.append(action_request)
            review_configs.append(review_config)
            interrupt_indices.append(idx)

        return action_requests, review_configs, interrupt_indices

    def _review_batch_future(
        self,
        tool_calls: list[ToolCall],
        state: AgentState[Any],
        runtime: Runtime[ContextT],
    ) -> Any | None:
        """Schedule :meth:`_build_review_batch` as a memoized LangGraph task.

        Wrapping it in ``langgraph.func.task`` makes LangGraph cache its
        return value against this node-task's call index, the same mechanism
        ``interrupt()`` itself uses — so a resume trip gets back the park
        trip's exact result instead of recomputing it.

        Returns ``None`` outside a real graph run (a direct unit-test call to
        ``after_model()``, with no checkpointer and thus no possibility of a
        resume replay), where ``task()`` raises because it needs the running
        config. Callers then compute the batch directly, which keeps that call
        style working unchanged.

        The returned future must be resolved the way the surrounding execution
        path demands: ``.result()`` under the sync runner, ``await`` under the
        async one. They are not interchangeable — see :meth:`aafter_model`.
        """
        try:
            return task(self._build_review_batch)(tool_calls, state, runtime)
        except RuntimeError:
            return None

    def _last_reviewable_ai_message(self, state: AgentState[Any], runtime: Runtime[ContextT]) -> AIMessage | None:
        """The ``AIMessage`` whose tool calls this turn may gate, if any.

        Shared by :meth:`after_model` and :meth:`aafter_model` so both paths
        apply the same preconditions before scheduling the review batch.
        """
        messages = state["messages"]
        if not messages:
            return None

        if self._approval_disabled(runtime):
            return None

        last_ai_msg = next((msg for msg in reversed(messages) if isinstance(msg, AIMessage)), None)
        if not last_ai_msg or not last_ai_msg.tool_calls:
            return None
        return last_ai_msg

    def after_model(self, state: AgentState[Any], runtime: Runtime[ContextT]) -> dict[str, Any] | None:
        """Gate the pending tool calls of the latest ``AIMessage`` on human review.

        This is the **sync** execution path. ``_review_batch_future`` returns a
        future the sync pregel runner has already submitted to its executor, so
        ``.result()`` resolves it. The async runner hands back a future driven by
        its own tick loop, which must be awaited instead — hence the separate
        :meth:`aafter_model`.

        Args:
            state: The current agent state.
            runtime: The runtime context.

        Returns:
            A ``messages`` update carrying the revised ``AIMessage`` plus any
            synthetic ``ToolMessage`` for rejected or answered calls, or
            ``None`` when nothing needed review.

        Raises:
            ValueError: If the human returned a different number of decisions
                than the number of interrupted tool calls.
        """
        last_ai_msg = self._last_reviewable_ai_message(state, runtime)
        if last_ai_msg is None:
            return None

        future = self._review_batch_future(last_ai_msg.tool_calls, state, runtime)
        batch = self._build_review_batch(last_ai_msg.tool_calls, state, runtime) if future is None else future.result()

        return self._gate_on_review_batch(last_ai_msg, batch)

    async def aafter_model(self, state: AgentState[Any], runtime: Runtime[ContextT]) -> dict[str, Any] | None:
        """Async counterpart of :meth:`after_model`.

        Upstream's ``aafter_model`` merely calls ``self.after_model(...)``
        synchronously. That is fine for a middleware whose body is pure, but
        this one schedules a LangGraph ``@task``: under the async runner
        ``CONFIG_KEY_CALL`` resolves to ``_acall``, whose future is completed by
        the pregel tick loop and is only ever resolved by ``await``. Calling
        ``.result()`` on it therefore raised
        ``asyncio.InvalidStateError: Result is not set`` on every real async run
        while the sync path and direct unit-test calls stayed green. Overriding
        the async hook is what keeps the ``@task`` memoization — the replay
        safety the whole park/resume contract rests on — usable at all.
        """
        last_ai_msg = self._last_reviewable_ai_message(state, runtime)
        if last_ai_msg is None:
            return None

        future = self._review_batch_future(last_ai_msg.tool_calls, state, runtime)
        batch = self._build_review_batch(last_ai_msg.tool_calls, state, runtime) if future is None else await future

        return self._gate_on_review_batch(last_ai_msg, batch)

    def _gate_on_review_batch(
        self,
        last_ai_msg: AIMessage,
        batch: tuple[list[ActionRequest], list[ReviewConfig], list[int]],
    ) -> dict[str, Any] | None:
        """Park on *batch* and fold the human's decisions back into the turn.

        Split out of :meth:`after_model` so the sync and async paths differ only
        in how they resolve the review-batch future, never in the gating
        semantics that follow.
        """
        action_requests, review_configs, interrupt_indices = batch

        if not action_requests:
            return None

        hitl_request = HITLRequest(action_requests=action_requests, review_configs=review_configs)

        # Parks the run in the checkpoint as a pending task. Execution resumes
        # from here on ``Command(resume={"decisions": [...]})``.
        decisions = interrupt(hitl_request)["decisions"]

        if (decisions_len := len(decisions)) != (interrupt_count := len(interrupt_indices)):
            msg = f"Number of human decisions ({decisions_len}) does not match number of hanging tool calls ({interrupt_count})."
            raise ValueError(msg)

        revised_tool_calls: list[ToolCall] = []
        artificial_tool_messages: list[ToolMessage] = []
        decision_positions = {idx: position for position, idx in enumerate(interrupt_indices)}

        for idx, tool_call in enumerate(last_ai_msg.tool_calls):
            position = decision_positions.get(idx)
            if position is None:
                # Auto-approved (no config, omitted, or ``when`` declined).
                revised_tool_calls.append(tool_call)
                continue

            config = self.interrupt_on[tool_call["name"]]
            revised_tool_call, tool_message = self._process_decision(decisions[position], tool_call, config)
            if revised_tool_call is not None:
                revised_tool_calls.append(revised_tool_call)
            if tool_message:
                artificial_tool_messages.append(tool_message)

        # Rebuild rather than mutate. Upstream assigns ``last_ai_msg.tool_calls``
        # in place, which rewrites the very object already streamed to clients
        # and leaves the provider's raw copy in ``additional_kwargs["tool_calls"]``
        # describing the pre-review args. The clone re-syncs that raw copy and
        # keeps the same id, so the state reducer replaces the original message.
        revised_ai_msg = clone_ai_message_with_tool_calls(last_ai_msg, revised_tool_calls)

        return {"messages": [revised_ai_msg, *artificial_tool_messages]}


def create_interrupt_middleware(
    app_config: AppConfig | None = None,
    tools: Sequence[BaseTool] | None = None,
) -> DeerFlowHumanInTheLoopMiddleware | None:
    """Build the tool-approval middleware from ``tools[].interrupt_on`` config.

    Args:
        app_config: Application configuration; falls back to ``get_app_config()``.
        tools: The agent's assembled tools, used to capture argument schemas for
            the ``edit`` decision. LangGraph's batch-mode request omits the tool
            list, so schemas must be captured here at assembly time.

    Returns:
        The middleware, or ``None`` when no tool requests approval — the common
        case, which leaves the middleware chain exactly as it was.
    """
    resolved_app_config = app_config or get_app_config()

    interrupt_on: dict[str, bool | InterruptOnConfig] = {}

    for tool_config in resolved_app_config.tools:
        tool_interrupt = tool_config.interrupt_on
        if not tool_interrupt:
            continue
        if tool_config.name in NON_APPROVABLE_TOOL_NAMES:
            # Config validation already rejects this; stay defensive because a
            # parked ``ask_clarification`` could not be resumed by either path.
            logger.warning("Ignoring interrupt_on for %r: the tool implements its own human-in-the-loop flow.", tool_config.name)
            continue

        config: InterruptOnConfig = {"allowed_decisions": list(tool_interrupt.allowed_decisions)}

        description = resolve_variable(tool_interrupt.description_use) if tool_interrupt.description_use else tool_interrupt.description
        if description is not None:
            config["description"] = description
        if tool_interrupt.when_use:
            config["when"] = resolve_variable(tool_interrupt.when_use)

        interrupt_on[tool_config.name] = config

    if not interrupt_on:
        return None

    for tool in tools or ():
        config = interrupt_on.get(getattr(tool, "name", None))
        if not isinstance(config, dict) or "edit" not in config["allowed_decisions"]:
            continue
        schema = _tool_args_schema(tool)
        if schema is not None:
            config["args_schema"] = schema

    return DeerFlowHumanInTheLoopMiddleware(interrupt_on=interrupt_on)
