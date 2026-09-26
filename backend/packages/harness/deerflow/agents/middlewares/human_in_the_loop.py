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
is auto-approved when the run context carries ``disable_tool_approval`` (this
middleware's own opt-out, set by a client with no approval surface, mirroring
the existing ``disable_clarification`` switch) or when
:func:`~deerflow.agents.interaction_policy.resolve_run_interaction_policy` says
the run is unattended — the shared signal that also covers ``non_interactive``
(scheduler, MCP task notifications), ``interaction_mode`` (webhook runs), and
``channel_name``, and that ``ClarificationMiddleware`` and
``sandbox/middleware.py`` read the same way.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from jsonschema import Draft202012Validator
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

from deerflow.agents.interaction_policy import resolve_run_interaction_policy
from deerflow.agents.middlewares.tool_call_args import rewrite_tool_call_args
from deerflow.agents.middlewares.tool_call_metadata import clone_ai_message_with_tool_calls
from deerflow.config.app_config import AppConfig, get_app_config
from deerflow.config.tool_config import NON_APPROVABLE_TOOL_NAMES
from deerflow.reflection import resolve_variable

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool
    from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)

# Run-context key that auto-approves every tool call. Set by non-interactive
# callers (IM channels, webhooks) because an interrupt there would park the
# thread with nobody able to resume it.
DISABLE_TOOL_APPROVAL_KEY = "disable_tool_approval"

# The pre-existing marker for a run with no human on the other end, set by the
# scheduler and the MCP task-notification launcher. It is honoured here too, so
# a non-interactive entrypoint cannot park a thread merely by not knowing about
# the newer key — but *not* by reading this key directly:
# ``resolve_run_interaction_policy`` is what maps it (along with
# ``interaction_mode`` and ``channel_name``) onto one interaction policy, and
# ``_approval_disabled`` goes through that resolver exactly as
# ``clarification_middleware.py`` and ``sandbox/middleware.py`` do. Kept as a
# name because it is the key callers set and tests assert on.
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

        Two independent reasons, and the second is deliberately not a raw-key
        read. ``disable_tool_approval`` is this middleware's own opt-out, set by
        a client that has no approval surface. Everything else routes through
        :func:`resolve_run_interaction_policy`, the repo's single definition of
        "no human is attached to this run" — the same call
        ``ClarificationMiddleware._clarification_disabled`` and
        ``sandbox/middleware.py`` make.

        Sharing the resolver rather than reading ``non_interactive`` directly is
        what keeps the two human-in-the-loop middlewares from disagreeing. The
        resolver also honours ``interaction_mode`` (a GitHub webhook run sets
        ``webhook``) and ``channel_name``, so a run whose only non-interactive
        marker is one of those would otherwise park here with nothing able to
        post ``Command(resume=...)`` — while clarification correctly treated it
        as unattended. ``interaction_mode`` further takes *precedence* over
        ``non_interactive`` inside the resolver, so a raw read of that key can
        invert the answer relative to clarification on the same run.

        A malformed ``interaction_mode`` raises from the resolver, as it already
        does for the other two callers; failing the run beats silently choosing
        an interaction policy nobody asked for.
        """
        context = getattr(runtime, "context", None)
        if not context:
            return False
        if context.get(DISABLE_TOOL_APPROVAL_KEY):
            return True
        return not resolve_run_interaction_policy({"context": context}).allows_clarification

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

        Called through :meth:`_review_batch_future`, which wraps it in a
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

    @staticmethod
    def _check_decision(decision: Any, tool_call: ToolCall, config: InterruptOnConfig) -> None:
        """Validate one human decision before it is turned into a tool call.

        Runs *before* upstream's ``_process_decision`` (inherited from
        ``HumanInTheLoopMiddleware``, not defined here) rather than after,
        because that method reads ``edited_action["name"]`` unguarded — a client
        omitting the key would raise a bare ``KeyError`` from library code before
        any check here could describe the contract.

        Only ``edit`` is checked. The other decision types carry no tool args,
        and upstream already raises a clear ``ValueError`` for a type that the
        tool's ``allowed_decisions`` does not permit.
        """
        if not isinstance(decision, Mapping):
            msg = f"Each tool-approval decision must be a mapping, got {type(decision).__name__}."
            raise ValueError(msg)
        if decision.get("type") != "edit":
            return

        edited_action = decision.get("edited_action")
        if not isinstance(edited_action, Mapping):
            msg = f"An 'edit' decision for {tool_call['name']!r} must carry an 'edited_action' mapping, got {type(edited_action).__name__}."
            raise ValueError(msg)

        # Upstream's ``edit`` accepts ``edited_action["name"]``, letting a
        # decision rename the call. Refused here: ``interrupt_on`` is keyed by
        # tool name, so a rename would run a *different* tool under the approval
        # its own gate never issued — and ``when``/``args_schema`` were resolved
        # for the original name. Rejecting is also what keeps the surface sync in
        # ``_gate_on_review_batch`` sound: ``rewrite_tool_call_args`` rewrites
        # args on every provider surface but not names, so a rename would leave
        # the raw payload and content blocks naming the old tool.
        if "name" not in edited_action:
            msg = f"An 'edit' decision for {tool_call['name']!r} must carry 'name' (unchanged) in its 'edited_action'."
            raise ValueError(msg)
        if (edited_name := edited_action["name"]) != tool_call["name"]:
            msg = f"A tool-approval 'edit' decision may not rename the call: {tool_call['name']!r} -> {edited_name!r}. Reject the call instead."
            raise ValueError(msg)

        args = edited_action.get("args")
        if not isinstance(args, Mapping):
            msg = f"An 'edit' decision for {tool_call['name']!r} must carry an 'args' mapping, got {type(args).__name__}."
            raise ValueError(msg)

        # The captured ``args_schema`` is the contract the human was *shown* —
        # it is forwarded into the ``ReviewConfig`` precisely so a client can
        # render a schema-driven edit form. Nothing downstream re-checks what
        # comes back: ``_process_decision`` builds the revised call straight out
        # of ``edited_action``, and a tool declared with a raw-JSON
        # ``args_schema`` gets no pydantic validation at execution either, so a
        # bad edit would simply run. Validating here turns it into the same
        # ``ValueError`` this module raises for the other malformed-resume cases.
        #
        # Exactly the schema, nothing stricter. In practice that means a missing
        # or mistyped *required* field is caught, while an unknown key is not:
        # pydantic emits no ``additionalProperties: false``, and injecting one
        # here would make an approved call fail where the identical call
        # succeeds with approval switched off — including for a human who
        # resubmits, unchanged, the args they were shown. The tool ignores
        # fields it does not declare.
        schema = config.get("args_schema")
        if not isinstance(schema, Mapping):
            # No schema was captured (``_tool_args_schema`` logs that case), so
            # the client was editing raw JSON with nothing to validate against.
            return
        try:
            # Both steps are guarded, not just construction: ``Draft202012Validator``
            # accepts an invalid schema and only raises when it walks it, so a
            # bad schema surfaces from ``iter_errors`` (``UnknownType`` for a
            # bogus ``type``) rather than from the constructor.
            errors = sorted(Draft202012Validator(dict(schema)).iter_errors(dict(args)), key=lambda err: list(err.absolute_path))
        except Exception:
            # A schema our own capture got wrong is not the human's problem;
            # refusing their edit over it would be the wrong failure.
            logger.warning("Could not validate an edit against %r's args schema; allowing it.", tool_call["name"], exc_info=True)
            return
        if errors:
            detail = "; ".join(f"{'/'.join(map(str, err.absolute_path)) or '<root>'}: {err.message}" for err in errors[:5])
            msg = f"An 'edit' decision for {tool_call['name']!r} does not satisfy the tool's args schema: {detail}"
            raise ValueError(msg)

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
        resume_value = interrupt(hitl_request)

        # Validate the resume payload rather than subscripting it. ``start_run``
        # forwards any non-``None`` ``command.resume`` straight into
        # ``Command(resume=...)``, so what arrives here is client-shaped: a bare
        # string, a mapping with no ``decisions``, or a ``decisions`` that is not
        # a list. Each of those would surface as a raw ``KeyError`` or
        # ``TypeError`` from deep inside this method instead of the ``ValueError``
        # this module documents for a bad resume. It fails closed either way —
        # the run errors and the checkpoint keeps its pending write, so the
        # thread can be resumed again — but only one of the two failures tells
        # the operator what the contract was.
        if not isinstance(resume_value, Mapping):
            msg = f"A tool-approval resume must be a mapping with a 'decisions' list, got {type(resume_value).__name__}."
            raise ValueError(msg)
        if "decisions" not in resume_value:
            msg = f"A tool-approval resume must carry a 'decisions' list; got keys {sorted(map(str, resume_value))}."
            raise ValueError(msg)
        decisions = resume_value["decisions"]
        if not isinstance(decisions, Sequence) or isinstance(decisions, (str, bytes)):
            msg = f"A tool-approval resume's 'decisions' must be a list, got {type(decisions).__name__}."
            raise ValueError(msg)

        if (decisions_len := len(decisions)) != (interrupt_count := len(interrupt_indices)):
            msg = f"Number of human decisions ({decisions_len}) does not match number of hanging tool calls ({interrupt_count})."
            raise ValueError(msg)

        revised_tool_calls: list[ToolCall] = []
        artificial_tool_messages: list[ToolMessage] = []
        edited_args: dict[str, dict[str, Any]] = {}
        decision_positions = {idx: position for position, idx in enumerate(interrupt_indices)}

        for idx, tool_call in enumerate(last_ai_msg.tool_calls):
            position = decision_positions.get(idx)
            if position is None:
                # Auto-approved (no config, omitted, or ``when`` declined).
                revised_tool_calls.append(tool_call)
                continue

            config = self.interrupt_on[tool_call["name"]]
            decision = decisions[position]
            self._check_decision(decision, tool_call, config)
            revised_tool_call, tool_message = self._process_decision(decision, tool_call, config)
            if revised_tool_call is not None:
                revised_tool_calls.append(revised_tool_call)
                if revised_tool_call is not tool_call and revised_tool_call.get("args") != tool_call.get("args") and isinstance(call_id := tool_call.get("id"), str) and call_id:
                    edited_args[call_id] = revised_tool_call["args"]
            if tool_message:
                artificial_tool_messages.append(tool_message)

        # An ``edit`` decision keeps the call id and changes only its args, so
        # the clone below — which filters by id — would carry the *original*
        # args forward on every surface other than ``tool_calls``: the raw
        # provider payload in ``additional_kwargs["tool_calls"]`` and the
        # content tool-call blocks (Anthropic ``tool_use``, OpenAI Responses
        # ``function_call``, v1 ``tool_call``). The tool node executes the
        # edited args while the next model request could be serialized from a
        # stale surface, telling the model ``rm`` ran when the human approved
        # ``ls``. ``rewrite_tool_call_args`` is the shared helper that rewrites
        # all of those surfaces together; run it first so the clone only has to
        # drop calls, never reconcile args.
        if edited_args:
            last_ai_msg = rewrite_tool_call_args(last_ai_msg, edited_args)

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
