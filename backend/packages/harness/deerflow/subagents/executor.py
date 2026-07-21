"""Subagent execution engine."""

import asyncio
import atexit
import html
import logging
import os
import threading
import uuid
from collections.abc import Callable, Coroutine, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from contextvars import Context, copy_context
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from langchain.agents import create_agent
from langchain.tools import BaseTool
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphRecursionError

from deerflow.agents.thread_state import SandboxState, ThreadDataState, ThreadState
from deerflow.authz.principal import normalize_authz_attributes
from deerflow.config import get_app_config
from deerflow.config.app_config import AppConfig
from deerflow.constants import DEFAULT_SKILLS_CONTAINER_PATH
from deerflow.models import create_chat_model
from deerflow.skills.tool_policy import ALWAYS_AVAILABLE_BUILTIN_TOOL_NAMES, filter_tools_by_skill_allowed_tools
from deerflow.skills.types import Skill
from deerflow.subagents.config import SubagentConfig, resolve_subagent_model_name
from deerflow.subagents.step_events import capture_new_step_messages
from deerflow.subagents.token_collector import SubagentTokenCollector
from deerflow.trace_context import DEERFLOW_TRACE_METADATA_KEY
from deerflow.tracing import build_tracing_callbacks, inject_langfuse_metadata
from deerflow.utils.messages import message_content_to_text

if TYPE_CHECKING:
    # Imported lazily at runtime inside _build_initial_state: importing
    # tool_search eagerly would run tools/builtins/__init__ -> task_tool ->
    # `from deerflow.subagents import SubagentExecutor`, which re-enters this
    # still-initializing package. Type-only here keeps the annotation precise.
    from deerflow.tools.builtins.tool_search import DeferredToolSetup

logger = logging.getLogger(__name__)

_SKILL_LOADER_TOOL_NAME = "read_file"


_previous_shutdown_isolated_subagent_loop = globals().get("_shutdown_isolated_subagent_loop")
if callable(_previous_shutdown_isolated_subagent_loop):
    atexit.unregister(_previous_shutdown_isolated_subagent_loop)
    _previous_shutdown_isolated_subagent_loop()


class SubagentStatus(Enum):
    """Status of a subagent execution."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"

    @property
    def is_terminal(self) -> bool:
        return self in {
            type(self).COMPLETED,
            type(self).FAILED,
            type(self).CANCELLED,
            type(self).TIMED_OUT,
        }


@dataclass
class SubagentResult:
    """Result of a subagent execution.

    Attributes:
        task_id: Unique identifier for this execution.
        trace_id: Trace ID for distributed tracing (links parent and subagent logs).
        status: Current status of the execution.
        result: The final result message (if completed).
        error: Error message (if failed).
        stop_reason: Why a guardrail cap ended the run early
            (``token_capped`` / ``turn_capped`` / ``loop_capped``), or ``None``
            for a clean run. A capped run keeps a normal status — ``completed``
            when it produced usable output (the partial work survives on
            ``result``), ``failed`` when it did not — and carries the cap here
            so the lead can tell "finished" from "capped" (#3875 Phase 2).
        started_at: When execution started.
        completed_at: When execution completed.
        ai_messages: List of complete AI messages (as dicts) generated during execution.
    """

    task_id: str
    trace_id: str
    status: SubagentStatus
    result: str | None = None
    error: str | None = None
    stop_reason: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    ai_messages: list[dict[str, Any]] | None = None
    token_usage_records: list[dict[str, int | str | None]] = field(default_factory=list)
    usage_reported: bool = False
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    _state_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self):
        """Initialize mutable defaults."""
        if self.ai_messages is None:
            self.ai_messages = []

    def update_token_usage_records(self, records: list[dict[str, int | str | None]]) -> None:
        """Publish the latest cumulative collector snapshot while still running."""
        with self._state_lock:
            if not self.status.is_terminal:
                self.token_usage_records = list(records)

    def try_set_terminal(
        self,
        status: SubagentStatus,
        *,
        result: str | None = None,
        error: str | None = None,
        stop_reason: str | None = None,
        completed_at: datetime | None = None,
        ai_messages: list[dict[str, Any]] | None = None,
        token_usage_records: list[dict[str, int | str | None]] | None = None,
    ) -> bool:
        """Set a terminal status exactly once.

        Background timeout/cancellation and the execution worker can race on the
        same result holder.  The first terminal transition wins; late terminal
        writes must not change status or payload fields.
        """
        if not status.is_terminal:
            raise ValueError(f"Status {status} is not terminal")

        with self._state_lock:
            if self.status.is_terminal:
                return False

            if result is not None:
                self.result = result
            if error is not None:
                self.error = error
            if stop_reason is not None:
                self.stop_reason = stop_reason
            if ai_messages is not None:
                self.ai_messages = ai_messages
            if token_usage_records is not None:
                self.token_usage_records = token_usage_records
            self.completed_at = completed_at or datetime.now()
            self.status = status
            return True


def _extract_final_result(final_state: Any, *, trace_id: str, name: str) -> str:
    """Extract a human-readable result string from the streamed subagent state.

    Finds the last ``AIMessage`` in the conversation and stringifies its
    content via the shared :func:`message_content_to_text` helper; falls back
    to the last message of any type when no AIMessage is present. Returns a
    sentinel string (``"No response generated"``) when there is nothing to
    extract — including when the shared helper yields an empty string — so
    callers never confuse a missing result with a legitimately empty one.

    Used on both the normal-completion path and the max-turns path
    (#3875 Phase 2): when ``recursion_limit`` aborts the run mid-flight,
    ``final_state`` holds the last chunk streamed before the limit fired, so
    this recovers the partial work instead of dropping it.
    """
    if final_state is None:
        logger.warning(f"[trace={trace_id}] Subagent {name} no final state")
        return "No response generated"

    messages = final_state.get("messages", [])
    logger.info(f"[trace={trace_id}] Subagent {name} final messages count: {len(messages)}")

    last_ai_message = None
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            last_ai_message = msg
            break

    if last_ai_message is not None:
        text = message_content_to_text(last_ai_message.content)
        return text if text else "No response generated"

    if messages:
        last_message = messages[-1]
        logger.warning(f"[trace={trace_id}] Subagent {name} no AIMessage found, using last message: {type(last_message)}")
        raw_content = last_message.content if hasattr(last_message, "content") else str(last_message)
        text = message_content_to_text(raw_content)
        return text if text else "No response generated"

    logger.warning(f"[trace={trace_id}] Subagent {name} no messages in final state")
    return "No response generated"


def _extract_llm_error_fallback(final_state: Any) -> str | None:
    """Return the user-facing error for a terminal LLM fallback message.

    ``LLMErrorHandlingMiddleware`` converts provider exceptions into marked
    ``AIMessage`` objects so the graph can terminate cleanly. Clean graph
    termination is not task success, however: subagent callers need the
    structured marker translated into the existing failed terminal state.

    Only the last assistant message is authoritative, and scanning just the
    tail (rather than all messages) is deliberate. Subagents share the
    parent's ``thread_id`` (see ``_aexecute``'s ``run_config``), and LangGraph
    replays the full parent message history through ``stream_mode="values"``,
    so ``final_state`` can contain a *stale* fallback marker left by an earlier
    parent-history turn. The lead-agent run path scans every message and must
    mask those stale markers via ``pre_existing_message_ids``
    (``runtime/runs/worker.py::_extract_llm_error_fallback_message``). Here no
    masking is needed: a fallback ``AIMessage`` carries no ``tool_calls``, so it
    always terminates the run, and a subagent always appends at least its own
    terminal assistant message — the last ``AIMessage`` is therefore never a
    stale parent-history marker. Do not "fix" this by scanning all messages;
    that reintroduces the stale-marker false positive worker.py guards against.

    Error-looking message text without the marker remains ordinary output.
    """
    if final_state is None:
        return None

    for message in reversed(final_state.get("messages", [])):
        if not isinstance(message, AIMessage):
            continue

        metadata = message.additional_kwargs
        if metadata.get("deerflow_error_fallback") is not True:
            return None

        content = message_content_to_text(message.content).strip()
        if content:
            return content

        # Defensive: ``_build_error_fallback_message`` always sets a non-empty
        # user-facing ``content`` (and ``error_detail`` via ``_extract_error_detail``,
        # which falls back to the exception class name). These branches only
        # guard against a future middleware that emits an empty fallback.
        detail = metadata.get("error_detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
        return "LLM request failed"

    return None


# Global storage for background task results
_background_tasks: dict[str, SubagentResult] = {}
_background_tasks_lock = threading.Lock()

# Thread pool for background task scheduling and orchestration
_scheduler_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="subagent-scheduler-")

# Persistent event loop for isolated subagent executions triggered from an
# already-running parent loop. Reusing one long-lived loop avoids creating a
# fresh loop per execution and then closing async resources bound to it.
_isolated_subagent_loop: asyncio.AbstractEventLoop | None = None
_isolated_subagent_loop_thread: threading.Thread | None = None
_isolated_subagent_loop_started: threading.Event | None = None
_isolated_subagent_loop_lock = threading.Lock()


def _run_isolated_subagent_loop(
    loop: asyncio.AbstractEventLoop,
    started_event: threading.Event,
) -> None:
    """Run the persistent isolated subagent loop in a dedicated daemon thread."""
    asyncio.set_event_loop(loop)
    loop.call_soon(started_event.set)
    try:
        loop.run_forever()
    finally:
        started_event.clear()


def _shutdown_isolated_subagent_loop() -> None:
    """Stop and close the persistent isolated subagent loop."""
    global _isolated_subagent_loop, _isolated_subagent_loop_thread, _isolated_subagent_loop_started

    with _isolated_subagent_loop_lock:
        loop = _isolated_subagent_loop
        thread = _isolated_subagent_loop_thread
        _isolated_subagent_loop = None
        _isolated_subagent_loop_thread = None
        _isolated_subagent_loop_started = None

    if loop is None:
        return

    if loop.is_running():
        loop.call_soon_threadsafe(loop.stop)

    if thread is not None and thread.is_alive() and thread is not threading.current_thread():
        thread.join(timeout=1)

    thread_stopped = thread is None or not thread.is_alive()
    loop_stopped = not loop.is_running()

    if not loop.is_closed():
        if thread_stopped and loop_stopped:
            loop.close()
        else:
            logger.warning(
                "Skipping close of isolated subagent loop because shutdown did not complete within timeout (thread_alive=%s, loop_running=%s)",
                thread is not None and thread.is_alive(),
                loop.is_running(),
            )


atexit.register(_shutdown_isolated_subagent_loop)


def _get_isolated_subagent_loop() -> asyncio.AbstractEventLoop:
    """Return the persistent event loop used by isolated subagent executions."""
    global _isolated_subagent_loop, _isolated_subagent_loop_thread, _isolated_subagent_loop_started
    with _isolated_subagent_loop_lock:
        thread_is_alive = _isolated_subagent_loop_thread is not None and _isolated_subagent_loop_thread.is_alive()
        loop_is_usable = _isolated_subagent_loop is not None and not _isolated_subagent_loop.is_closed() and _isolated_subagent_loop.is_running() and thread_is_alive

        if not loop_is_usable:
            loop = asyncio.new_event_loop()
            started_event = threading.Event()
            thread = threading.Thread(
                target=_run_isolated_subagent_loop,
                args=(loop, started_event),
                name="subagent-persistent-loop",
                daemon=True,
            )
            thread.start()
            if not started_event.wait(timeout=5):
                loop.call_soon_threadsafe(loop.stop)
                thread.join(timeout=1)
                loop.close()
                raise RuntimeError("Timed out starting isolated subagent event loop")
            _isolated_subagent_loop = loop
            _isolated_subagent_loop_thread = thread
            _isolated_subagent_loop_started = started_event

        if _isolated_subagent_loop is None:
            raise RuntimeError("Isolated subagent event loop is not initialized")
        return _isolated_subagent_loop


def _submit_to_isolated_loop_in_context(
    context: Context,
    coro_factory: Callable[[], Coroutine[Any, Any, SubagentResult]],
) -> Future[SubagentResult]:
    """Submit a coroutine to the isolated loop while preserving ContextVar state."""
    return context.run(
        lambda: asyncio.run_coroutine_threadsafe(
            coro_factory(),
            _get_isolated_subagent_loop(),
        )
    )


def _filter_tools(
    all_tools: list[BaseTool],
    allowed: list[str] | None,
    disallowed: list[str] | None,
) -> list[BaseTool]:
    """Filter tools based on subagent configuration.

    Args:
        all_tools: List of all available tools.
        allowed: Optional allowlist of tool names. If provided, only these tools are included.
        disallowed: Optional denylist of tool names. These tools are always excluded.

    Returns:
        Filtered list of tools.
    """
    filtered = all_tools

    # Apply allowlist if specified
    if allowed is not None:
        allowed_set = set(allowed)
        filtered = [t for t in filtered if t.name in allowed_set]

    # Apply denylist
    if disallowed is not None:
        disallowed_set = set(disallowed)
        filtered = [t for t in filtered if t.name not in disallowed_set]

    return filtered


class SubagentExecutor:
    """Executor for running subagents."""

    def __init__(
        self,
        config: SubagentConfig,
        tools: list[BaseTool],
        app_config: AppConfig | None = None,
        parent_model: str | None = None,
        sandbox_state: SandboxState | None = None,
        thread_data: ThreadDataState | None = None,
        thread_id: str | None = None,
        trace_id: str | None = None,
        user_id: str | None = None,
        user_role: str | None = None,
        oauth_provider: str | None = None,
        oauth_id: str | None = None,
        run_id: str | None = None,
        channel_user_id: str | None = None,
        is_internal: bool = False,
        authz_attributes: Mapping[str, Any] | None = None,
        deerflow_trace_id: str | None = None,
    ):
        """Initialize the executor.

        Args:
            config: Subagent configuration.
            tools: List of all available tools (will be filtered).
            app_config: Resolved AppConfig. When None, ``_create_agent`` falls
                back to ``get_app_config()`` (matches the lead-agent factory's
                pattern).
            parent_model: The parent agent's model name for inheritance.
            sandbox_state: Sandbox state from parent agent.
            thread_data: Thread data from parent agent.
            thread_id: Thread ID for sandbox operations.
            trace_id: Trace ID from parent for distributed tracing.
            user_id: User ID captured from the parent tool's runtime context.
                When None, the tracing layer falls back to DEFAULT_USER_ID.
            user_role: Authenticated user's role, propagated so GuardrailMiddleware
                on the subagent can apply role-aware policy to delegated calls.
            oauth_provider: External identity provider, when authenticated via SSO.
            oauth_id: Subject id at the external identity provider.
            run_id: Parent run id, so delegated guardrail decisions attribute to
                the same run as the lead agent.
            deerflow_trace_id: DeerFlow request-level correlation id propagated
                from the parent run for Langfuse metadata correlation.
        """
        self.config = config
        self.app_config = app_config
        self.parent_model = parent_model
        # Resolve eagerly only when it does not require loading config.yaml; otherwise defer
        # to _create_agent (which already loads app_config) so unit tests can construct
        # executors without a config file present.
        if config.model != "inherit" or parent_model is not None or app_config is not None:
            self.model_name: str | None = resolve_subagent_model_name(config, parent_model, app_config=app_config)
        else:
            self.model_name = None
        self.sandbox_state = sandbox_state
        self.thread_data = thread_data
        self.thread_id = thread_id
        # Generate trace_id if not provided (for top-level calls)
        self.trace_id = trace_id or str(uuid.uuid4())[:8]
        self.user_id = user_id
        # Guardrail attribution propagated from the parent runtime context.
        self.user_role = user_role
        self.oauth_provider = oauth_provider
        self.oauth_id = oauth_id
        self.run_id = run_id
        # IM-channel sender identity captured at task_tool dispatch: group
        # chats share one thread across senders, so delegated bash commands
        # must export the dispatching turn's id, not none at all.
        self.channel_user_id = channel_user_id
        # Authorization identity propagated from the parent runtime context.
        # is_internal is written unconditionally (including False) so the
        # subagent's GuardrailMiddleware sees the same provenance as the lead.
        self.is_internal = is_internal
        self.authz_attributes = normalize_authz_attributes(authz_attributes)
        self.deerflow_trace_id = deerflow_trace_id

        self._base_tools = _filter_tools(
            tools,
            config.tools,
            config.disallowed_tools,
        )
        self.tools = self._base_tools
        # Guard middlewares that expose ``consume_stop_reason`` (currently
        # ``TokenBudgetMiddleware`` and ``LoopDetectionMiddleware``), captured in
        # ``_create_agent`` so ``_aexecute`` can read each after the run and
        # surface whichever cap fired (token_capped / loop_capped) to the lead
        # (#3875 Phase 2). Collected as a list — every guard must be checked,
        # not just the first — because the v2 contract advertises more than one
        # cap reason.
        self._stop_reason_middlewares: list[Any] = []

        logger.info(f"[trace={self.trace_id}] SubagentExecutor initialized: {config.name} with {len(self.tools)} tools")

    def _create_agent(self, tools: list[BaseTool] | None = None, *, deferred_setup: "DeferredToolSetup | None" = None):
        """Create the agent instance.

        ``deferred_setup`` (assembled in ``_build_initial_state``) carries the
        deferred MCP tool names + catalog hash so the subagent gets the same
        DeferredToolFilterMiddleware the lead agent has. ``None`` is a no-op.
        """
        app_config = self.app_config or get_app_config()
        if self.model_name is None:
            self.model_name = resolve_subagent_model_name(self.config, self.parent_model, app_config=app_config)
        model = create_chat_model(name=self.model_name, thinking_enabled=False, app_config=app_config, attach_tracing=False)

        from deerflow.agents.middlewares.tool_error_handling_middleware import build_subagent_runtime_middlewares

        # Reuse shared middleware composition with lead agent. ``agent_name``
        # lets the builder resolve the per-agent token_budget override.
        mcp_routing_middleware = None
        if deferred_setup is not None and deferred_setup.deferred_names:
            from deerflow.tools.builtins.tool_search import build_mcp_routing_middleware

            mcp_routing_middleware = build_mcp_routing_middleware(
                tools if tools is not None else self.tools,
                deferred_setup,
                top_k=app_config.tool_search.auto_promote_top_k,
            )
        middleware_kwargs = {
            "app_config": app_config,
            "model_name": self.model_name,
            "lazy_init": True,
            "deferred_setup": deferred_setup,
            "agent_name": self.config.name,
        }
        if mcp_routing_middleware is not None:
            middleware_kwargs["mcp_routing_middleware"] = mcp_routing_middleware
        middlewares = build_subagent_runtime_middlewares(**middleware_kwargs)
        # Collect every guard middleware that exposes ``consume_stop_reason``
        # (TokenBudgetMiddleware, LoopDetectionMiddleware) so _aexecute can read
        # each after the run and surface whichever cap fired. Duck-typed
        # (``hasattr``) so this file needs no import of the middleware classes;
        # a list (not ``next(...)``) so every guard is checked and a later one
        # is picked up automatically.
        self._stop_reason_middlewares = [m for m in middlewares if hasattr(m, "consume_stop_reason")]

        # system_prompt is included in initial state messages (see _build_initial_state)
        # to avoid multiple SystemMessages which some LLM APIs don't support.
        return create_agent(
            model=model,
            tools=tools if tools is not None else self.tools,
            middleware=middlewares,
            system_prompt=None,
            state_schema=ThreadState,
            checkpointer=False,
        )

    def _consume_guard_stop_reason(self) -> str | None:
        """Pop and return the guard-cap stop reason set during the last run.

        Checks every guard middleware that exposes ``consume_stop_reason``
        (collected in :meth:`_create_agent`) and returns the first non-``None``
        reason — ``"token_capped"`` when the token-budget hard stop fired,
        ``"loop_capped"`` when loop detection forced a stop, otherwise ``None``.
        Each guard's cap does not raise (the run still completes with a final
        answer), so this is how the executor learns a completion was actually
        capped. Typically at most one guard fires per run, but checking all of
        them keeps the contract's full cap vocabulary reachable.
        """
        for mw in self._stop_reason_middlewares:
            reason = mw.consume_stop_reason(self.run_id)
            if reason is not None:
                return reason
        return None

    async def _load_skills(self) -> list[Skill]:
        """Load enabled skill metadata based on config.skills."""
        if self.config.skills is not None and len(self.config.skills) == 0:
            logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} skills=[] — skipping skill loading")
            return []

        try:
            from deerflow.skills.storage import get_or_new_skill_storage

            storage_kwargs = {"app_config": self.app_config} if self.app_config is not None else {}
            storage = await asyncio.to_thread(get_or_new_skill_storage, **storage_kwargs)
            # Use asyncio.to_thread to avoid blocking the event loop (LangGraph ASGI requirement)
            all_skills = await asyncio.to_thread(storage.load_skills, enabled_only=True)
            logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} loaded {len(all_skills)} enabled skills from disk")
        except Exception:
            logger.exception(f"[trace={self.trace_id}] Failed to load skills for subagent {self.config.name}")
            raise

        if not all_skills:
            logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} no enabled skills found")
            return []

        # Filter by config.skills whitelist
        if self.config.skills is not None:
            allowed = set(self.config.skills)
            return [s for s in all_skills if s.name in allowed]
        return all_skills

    def _apply_skill_allowed_tools(self, skills: list[Skill]) -> list[BaseTool]:
        return filter_tools_by_skill_allowed_tools(
            self._base_tools,
            skills,
            always_allowed_tool_names=ALWAYS_AVAILABLE_BUILTIN_TOOL_NAMES,
        )

    def _skills_container_path(self) -> str:
        """Return the configured skills mount path, falling back safely in tests."""
        if self.app_config is not None:
            configured = getattr(getattr(self.app_config, "skills", None), "container_path", None)
            return configured or DEFAULT_SKILLS_CONTAINER_PATH

        try:
            configured = get_app_config().skills.container_path
        except Exception:
            return DEFAULT_SKILLS_CONTAINER_PATH
        return configured or DEFAULT_SKILLS_CONTAINER_PATH

    def _skill_mutability_label(self, category: object) -> str:
        category_value = getattr(category, "value", category)
        if category_value == "custom":
            return "[custom, editable]"
        if category_value == "legacy":
            return "[legacy, read-only]"
        return "[built-in]"

    def _render_available_skill(self, skill: Skill, container_path: str) -> str:
        """Render escaped skill metadata for the progressive-loading prompt."""
        name = html.escape(getattr(skill, "name", ""), quote=False)
        description = html.escape(getattr(skill, "description", ""), quote=False)
        location = html.escape(skill.get_container_file_path(container_path), quote=False)
        category = getattr(skill, "category", "public")
        return f"    <skill>\n        <name>{name}</name>\n        <description>{description} {self._skill_mutability_label(category)}</description>\n        <location>{location}</location>\n    </skill>"

    def _build_skill_section(self, skills: list[Skill]) -> str:
        """Build a metadata-only skill section for progressive loading."""
        if not skills:
            return ""

        container_path = self._skills_container_path()
        skill_items = "\n".join(self._render_available_skill(skill, container_path) for skill in skills)
        return f"""<skill_system>
You have access to skills that provide optimized workflows for specific tasks. Each skill contains best practices, frameworks, and references to additional resources.

**Progressive Loading Pattern:**
1. When a task matches a skill's use case, immediately call `{_SKILL_LOADER_TOOL_NAME}` on the skill's main file using the path provided in the skill tag below
2. Read and understand the skill's workflow and instructions
3. The skill file contains references to external resources under the same folder
4. Load referenced resources only when needed during execution
5. Follow the skill's instructions precisely

**Skills are located at:** {html.escape(container_path, quote=False)}

<available_skills>
{skill_items}
</available_skills>

</skill_system>"""

    async def _build_eager_skill_section(self, skills: list[Skill]) -> str:
        """Build escaped eager skill instructions when read_file is unavailable."""
        skill_items: list[str] = []
        for skill in skills:
            try:
                content = await asyncio.to_thread(skill.skill_file.read_text, encoding="utf-8")
            except Exception as exc:
                raise RuntimeError(f"Failed to load instructions for skill {skill.name!r} from {skill.skill_file} because {_SKILL_LOADER_TOOL_NAME} is unavailable") from exc

            content = content.strip()
            if not content:
                continue
            name = html.escape(skill.name, quote=True)
            body = html.escape(content, quote=False)
            skill_items.append(f'<skill name="{name}">\n{body}\n</skill>')

        return "\n".join(skill_items)

    async def _build_initial_state(self, task: str) -> tuple[dict[str, Any], list[BaseTool], "DeferredToolSetup"]:
        """Build the initial state for agent execution.

        Args:
            task: The task description.

        Returns:
            ``(state, final_tools, deferred_setup)``. ``final_tools`` is the
            policy-filtered tool list with the ``tool_search`` tool appended when
            deferral applies; ``deferred_setup`` is consumed by ``_create_agent``
            so the agent build and the injected ``<available-deferred-tools>``
            section share one catalog/hash.
        """
        # Lazy import: see the TYPE_CHECKING note at the top of this module -
        # importing tool_search runs tools/builtins/__init__, which would
        # re-enter this package during its own initialization.
        from deerflow.tools.builtins.tool_search import assemble_deferred_tools, get_deferred_tools_prompt_section, get_mcp_routing_hints_prompt_section

        # Load skills as conversation items (Codex pattern)
        skills = await self._load_skills()
        filtered_tools = self._apply_skill_allowed_tools(skills)
        # Assemble deferred tool_search AFTER policy filtering (fail-closed),
        # mirroring the lead path so subagents stop binding full MCP schemas.
        # The generated tool_search helper is intentionally not subject to the
        # subagent's name-level allow/deny (config.tools / disallowed_tools):
        # its catalog is built from the already-filtered list, so it can never
        # surface a tool the policy denied. This matches the lead agent.
        enabled = (self.app_config or get_app_config()).tool_search.enabled
        final_tools, deferred_setup = assemble_deferred_tools(filtered_tools, enabled=enabled)
        if skills and not any(tool.name == _SKILL_LOADER_TOOL_NAME for tool in final_tools):
            logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} {_SKILL_LOADER_TOOL_NAME} unavailable; eagerly loading skill instructions")
            skill_section = await self._build_eager_skill_section(skills)
        else:
            skill_section = self._build_skill_section(skills)

        # Combine system_prompt and skills into a single SystemMessage.
        # Some LLM APIs reject multiple SystemMessages with
        # "System message must be at the beginning."
        system_parts: list[str] = []
        if self.config.system_prompt:
            system_parts.append(self.config.system_prompt)
        if skill_section:
            system_parts.append(skill_section)
        # Name the deferred MCP tools in the prompt; their schemas stay withheld
        # until tool_search promotes them. Empty set -> "" -> appends nothing.
        deferred_section = get_deferred_tools_prompt_section(deferred_names=deferred_setup.deferred_names)
        if deferred_section:
            system_parts.append(deferred_section)
        mcp_routing_hints_section = get_mcp_routing_hints_prompt_section(filtered_tools, deferred_names=deferred_setup.deferred_names)
        if mcp_routing_hints_section:
            system_parts.append(mcp_routing_hints_section)

        messages: list[Any] = []
        if system_parts:
            messages.append(SystemMessage(content="\n\n".join(system_parts)))

        # Then the actual task
        messages.append(HumanMessage(content=task))

        state: dict[str, Any] = {
            "messages": messages,
        }

        # Pass through sandbox and thread data from parent
        if self.sandbox_state is not None:
            state["sandbox"] = self.sandbox_state
        if self.thread_data is not None:
            state["thread_data"] = self.thread_data

        return state, final_tools, deferred_setup

    async def _aexecute(self, task: str, result_holder: SubagentResult | None = None) -> SubagentResult:
        """Execute a task asynchronously.

        Args:
            task: The task description for the subagent.
            result_holder: Optional pre-created result object to update during execution.

        Returns:
            SubagentResult with the execution result.
        """
        if result_holder is not None:
            # Use the provided result holder (for async execution with real-time updates)
            result = result_holder
        else:
            # Create a new result for synchronous execution
            task_id = str(uuid.uuid4())[:8]
            result = SubagentResult(
                task_id=task_id,
                trace_id=self.trace_id,
                status=SubagentStatus.RUNNING,
                started_at=datetime.now(),
            )
        ai_messages = result.ai_messages
        if ai_messages is None:
            ai_messages = []
            result.ai_messages = ai_messages
        # O(1) duplicate detection for streamed AI messages. ``stream_mode="values"``
        # re-yields the full state every super-step, so the same trailing message is
        # re-examined on each chunk; an id-keyed set keeps that check O(1) instead of
        # rescanning the append-only ``ai_messages`` list (O(n) per chunk -> O(n^2)
        # over a run, which reaches max_turns=150 for deep-research subagents).
        seen_message_ids: set[str] = {mid for msg in ai_messages if (mid := msg.get("id"))}
        # Cursor into the append-only message history so each ``values``-mode
        # chunk only re-scans the newly-appended tail (see capture_new_step_messages).
        processed_message_count = 0

        collector: SubagentTokenCollector | None = None
        try:
            state, final_tools, deferred_setup = await self._build_initial_state(task)
            agent = self._create_agent(final_tools, deferred_setup=deferred_setup)

            # Token collector for subagent LLM calls
            collector_caller = f"subagent:{self.config.name}"
            collector = SubagentTokenCollector(caller=collector_caller)

            # Do not put checkpoint coordinates (thread_id/checkpoint_ns/etc.)
            # in the child config. LangGraph inherits those coordinates from
            # the ambient parent run so this execution keeps its subgraph
            # namespace. Business consumers receive thread_id via ``context``
            # below instead.
            run_config: RunnableConfig = {
                "recursion_limit": self.config.max_turns,
                "callbacks": [collector],
                "tags": [collector_caller],
            }

            # Inject tracing callbacks at the graph level so a single subagent run
            # produces one trace with all node / LLM / tool calls as child spans.
            # This mirrors the lead agent pattern: graph-level tracing paired with
            # attach_tracing=False on the model avoids double-counted traces.
            tracing_callbacks = build_tracing_callbacks()
            if tracing_callbacks:
                existing_callbacks = list(run_config.get("callbacks") or [])
                run_config["callbacks"] = [*existing_callbacks, *tracing_callbacks]

            # Normalize subagent name for tracing so it matches the lead-agent
            # naming shape (lowercase, hyphens only). Inline because there is no
            # shared helper — runtime/runs/naming.py only handles lead-agent runs.
            if self.config.name:
                normalized_name = self.config.name.strip().lower().replace("_", "-")
                assistant_id = f"subagent:{normalized_name}"
            else:
                assistant_id = "subagent"

            # Inject Langfuse trace-attribute metadata so the subagent trace
            # links to the parent thread and carries the correct session/user IDs.
            inject_langfuse_metadata(
                run_config,
                thread_id=self.thread_id,
                user_id=self.user_id,
                assistant_id=assistant_id,
                model_name=self.model_name,
                environment=os.environ.get("DEER_FLOW_ENV") or os.environ.get("ENVIRONMENT"),
                deerflow_trace_id=self.deerflow_trace_id,
            )

            context: dict[str, Any] = {}
            if self.thread_id:
                context["thread_id"] = self.thread_id
            if self.app_config is not None:
                context["app_config"] = self.app_config
            # Propagate guardrail attribution so delegated tool calls are
            # evaluated with the parent run's identity (role-aware policy,
            # audit). user_id reuses the resolved tracing id; on every
            # authenticated/IM path this equals the parent context value.
            context["user_id"] = self.user_id
            context["user_role"] = self.user_role
            context["oauth_provider"] = self.oauth_provider
            context["oauth_id"] = self.oauth_id
            context["run_id"] = self.run_id
            if self.channel_user_id:
                context["channel_user_id"] = self.channel_user_id
            # Authorization identity: is_internal written unconditionally
            # (including False); attributes copied again on write-back.
            context["is_internal"] = self.is_internal
            context["authz_attributes"] = dict(self.authz_attributes)
            if self.deerflow_trace_id:
                context[DEERFLOW_TRACE_METADATA_KEY] = self.deerflow_trace_id
            context["is_subagent"] = True

            logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} starting async execution with max_turns={self.config.max_turns}")

            # Use stream instead of invoke to get real-time updates
            # This allows us to collect AI messages as they are generated
            final_state = None

            # Pre-check: bail out immediately if already cancelled before streaming starts
            if result.cancel_event.is_set():
                logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} cancelled before streaming")
                result.try_set_terminal(
                    SubagentStatus.CANCELLED,
                    error="Cancelled by user",
                    token_usage_records=collector.snapshot_records(),
                )
                return result

            async for chunk in agent.astream(state, config=run_config, context=context, stream_mode="values"):  # type: ignore[arg-type]
                # Cooperative cancellation: check if parent requested stop.
                # Note: cancellation is only detected at astream iteration boundaries,
                # so long-running tool calls within a single iteration will not be
                # interrupted until the next chunk is yielded.
                if result.cancel_event.is_set():
                    logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} cancelled by parent")
                    result.try_set_terminal(
                        SubagentStatus.CANCELLED,
                        error="Cancelled by user",
                        token_usage_records=collector.snapshot_records(),
                    )
                    return result

                final_state = chunk
                result.update_token_usage_records(collector.snapshot_records())

                # Capture every step message (assistant turns AND tool outputs)
                # appended since the last chunk. A single super-step can append
                # several ToolMessages when the model emits multiple tool calls in
                # one turn, so capturing only messages[-1] would drop all but the
                # last output (#3779). Dedup/serialization live in capture_step_message.
                messages = chunk.get("messages", [])
                previous_count = len(ai_messages)
                processed_message_count = capture_new_step_messages(messages, ai_messages, seen_message_ids, processed_message_count)
                if len(ai_messages) > previous_count:
                    logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} captured {len(ai_messages) - previous_count} step message(s); total #{len(ai_messages)}")

            logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} completed async execution")
            token_usage_records = collector.snapshot_records()
            llm_error = _extract_llm_error_fallback(final_state)
            if llm_error is not None:
                result.try_set_terminal(
                    SubagentStatus.FAILED,
                    error=llm_error,
                    token_usage_records=token_usage_records,
                )
            else:
                final_result = _extract_final_result(final_state, trace_id=self.trace_id, name=self.config.name)
                # A guard hard-stop (token budget or loop detection) does not raise
                # — it strips tool_calls so the run completes with a final answer.
                # ``consume_stop_reason`` on each guard tells us whether that
                # happened so we can mark the completed result with the cap reason
                # (token_capped / loop_capped) for the lead (#3875 Phase 2). It
                # pops the reason, so keep it on the branch that consumes it — a
                # fallback carries no tool_calls, so no guard hard-stop can have
                # co-occurred on the FAILED branch anyway.
                stop_reason = self._consume_guard_stop_reason()
                result.try_set_terminal(
                    SubagentStatus.COMPLETED,
                    result=final_result,
                    stop_reason=stop_reason,
                    token_usage_records=token_usage_records,
                )

        except GraphRecursionError:
            # ``recursion_limit`` on run_config == ``self.config.max_turns``
            # (set above). Hitting it means the subagent exhausted its turn
            # budget. Route into the additive ``stop_reason`` channel (#3875
            # Phase 2) rather than a dedicated status enum (which would break v1
            # contract consumers). If the run streamed usable partial work,
            # surface it as ``completed``; otherwise ``failed``. Either way the
            # lead can tell "out of budget" from "broken subagent" without
            # parsing result text.
            #
            # Prefer a guard's stop reason if one already fired this run: a
            # token-budget / loop hard-stop strips tool_calls to force a final
            # answer, and if ``recursion_limit`` then trips on the next
            # super-step before that answer lands, the guard was the binding
            # constraint — not the turn budget. Consulting the guards here (same
            # lookup as the normal-completion path above) keeps the two paths
            # consistent and pops the reason so it is not orphaned in the dict.
            max_turns = self.config.max_turns
            logger.warning(f"[trace={self.trace_id}] Subagent {self.config.name} reached max_turns={max_turns} (GraphRecursionError); recovering partial result")
            records = collector.snapshot_records() if collector is not None else None
            stop_reason = self._consume_guard_stop_reason() or "turn_capped"

            # A handled LLM provider failure (#4042) carries non-empty
            # user-facing text on its terminal ``AIMessage`` just like genuine
            # partial output, so it must be checked here too or it is
            # indistinguishable from the raw-text scan below and gets
            # misclassified as a completed task. Consult the same marker the
            # normal-completion path above uses, before falling back to that scan.
            llm_error = _extract_llm_error_fallback(final_state)
            if llm_error is not None:
                result.try_set_terminal(
                    SubagentStatus.FAILED,
                    error=llm_error,
                    stop_reason=stop_reason,
                    token_usage_records=records,
                )
            else:
                messages = (final_state or {}).get("messages", [])
                usable_partial: str | None = None
                for m in reversed(messages):
                    if isinstance(m, AIMessage):
                        text = message_content_to_text(m.content).strip()
                        if text:
                            usable_partial = text
                        break
                if usable_partial is not None:
                    result.try_set_terminal(
                        SubagentStatus.COMPLETED,
                        result=usable_partial,
                        stop_reason=stop_reason,
                        token_usage_records=records,
                    )
                else:
                    result.try_set_terminal(
                        SubagentStatus.FAILED,
                        error=f"Reached max_turns={max_turns}",
                        stop_reason=stop_reason,
                        token_usage_records=records,
                    )

        except Exception as e:
            logger.exception(f"[trace={self.trace_id}] Subagent {self.config.name} async execution failed")
            result.try_set_terminal(
                SubagentStatus.FAILED,
                error=str(e),
                token_usage_records=collector.snapshot_records() if collector is not None else None,
            )

        return result

    def _execute_in_isolated_loop(self, task: str, result_holder: SubagentResult | None = None) -> SubagentResult:
        """Execute the subagent on the persistent isolated event loop.

        This method is used by the sync ``execute()`` path when the caller is
        already running inside an event loop. Because ``execute()`` is a sync
        API, this path blocks the caller while the actual coroutine runs on the
        long-lived isolated loop. Reusing that loop keeps shared async clients
        from being tied to a short-lived loop that gets closed per execution.
        """
        future: Future[SubagentResult] | None = None
        parent_context = copy_context()
        try:
            future = _submit_to_isolated_loop_in_context(
                parent_context,
                lambda: self._aexecute(task, result_holder),
            )
            return future.result(timeout=self.config.timeout_seconds)
        except FuturesTimeoutError:
            if result_holder is not None:
                result_holder.cancel_event.set()
            if future is not None:
                future.cancel()
            raise
        except Exception:
            if future is None:
                logger.debug(
                    f"[trace={self.trace_id}] Failed to submit subagent {self.config.name} to the isolated event loop",
                    exc_info=True,
                )
            else:
                logger.debug(
                    f"[trace={self.trace_id}] Subagent {self.config.name} failed while executing on the isolated event loop",
                    exc_info=True,
                )
            raise

    def execute(self, task: str, result_holder: SubagentResult | None = None) -> SubagentResult:
        """Execute a task synchronously (wrapper around async execution).

        This method runs the async execution in a new event loop, allowing
        asynchronous tools (like MCP tools) to be used within the thread pool.

        When called from within an already-running event loop (e.g., when the
        parent agent is async), this method synchronously waits on the
        persistent isolated loop to avoid event loop conflicts with shared
        async primitives like httpx clients.

        Args:
            task: The task description for the subagent.
            result_holder: Optional pre-created result object to update during execution.

        Returns:
            SubagentResult with the execution result.
        """
        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop is not None and loop.is_running():
                logger.debug(f"[trace={self.trace_id}] Subagent {self.config.name} detected running event loop, using isolated loop")
                return self._execute_in_isolated_loop(task, result_holder)

            # Standard path: no running event loop, use asyncio.run
            return asyncio.run(self._aexecute(task, result_holder))
        except Exception as e:
            logger.exception(f"[trace={self.trace_id}] Subagent {self.config.name} execution failed")
            # Create a result with error if we don't have one
            if result_holder is not None:
                result = result_holder
            else:
                result = SubagentResult(
                    task_id=str(uuid.uuid4())[:8],
                    trace_id=self.trace_id,
                    status=SubagentStatus.RUNNING,
                )
            result.try_set_terminal(SubagentStatus.FAILED, error=str(e))
            return result

    def execute_async(self, task: str, task_id: str | None = None) -> str:
        """Start a task execution in the background.

        Args:
            task: The task description for the subagent.
            task_id: Optional task ID to use. If not provided, a random UUID will be generated.

        Returns:
            Task ID that can be used to check status later.
        """
        # Use provided task_id or generate a new one
        if task_id is None:
            task_id = str(uuid.uuid4())[:8]

        # Create initial pending result
        result = SubagentResult(
            task_id=task_id,
            trace_id=self.trace_id,
            status=SubagentStatus.PENDING,
        )

        logger.info(f"[trace={self.trace_id}] Subagent {self.config.name} starting async execution, task_id={task_id}, timeout={self.config.timeout_seconds}s")

        with _background_tasks_lock:
            _background_tasks[task_id] = result

        parent_context = copy_context()

        # Submit to scheduler pool
        def run_task():
            with _background_tasks_lock:
                _background_tasks[task_id].status = SubagentStatus.RUNNING
                _background_tasks[task_id].started_at = datetime.now()
                result_holder = _background_tasks[task_id]

            try:
                # Submit execution directly to the persistent isolated loop so the
                # background path does not create a temporary loop via execute().
                execution_future = _submit_to_isolated_loop_in_context(
                    parent_context,
                    lambda: self._aexecute(task, result_holder),
                )
                try:
                    # Wait for execution with timeout
                    execution_future.result(timeout=self.config.timeout_seconds)
                except FuturesTimeoutError:
                    logger.error(f"[trace={self.trace_id}] Subagent {self.config.name} execution timed out after {self.config.timeout_seconds}s")
                    # Signal cooperative cancellation and cancel the future
                    result_holder.cancel_event.set()
                    result_holder.try_set_terminal(
                        SubagentStatus.TIMED_OUT,
                        error=f"Execution timed out after {self.config.timeout_seconds} seconds",
                    )
                    execution_future.cancel()
            except Exception as e:
                logger.exception(f"[trace={self.trace_id}] Subagent {self.config.name} async execution failed")
                with _background_tasks_lock:
                    task_result = _background_tasks[task_id]
                task_result.try_set_terminal(SubagentStatus.FAILED, error=str(e))

        _scheduler_pool.submit(run_task)
        return task_id


MAX_CONCURRENT_SUBAGENTS = 3


def request_cancel_background_task(task_id: str) -> None:
    """Signal a running background task to stop.

    Sets the cancel_event on the task, which is checked cooperatively
    by ``_aexecute`` during ``agent.astream()`` iteration.  This allows
    subagent threads — which cannot be force-killed via ``Future.cancel()``
    — to stop at the next iteration boundary.

    Args:
        task_id: The task ID to cancel.
    """
    with _background_tasks_lock:
        result = _background_tasks.get(task_id)
        if result is not None:
            result.cancel_event.set()
            logger.info("Requested cancellation for background task %s", task_id)


def get_background_task_result(task_id: str) -> SubagentResult | None:
    """Get the result of a background task.

    Args:
        task_id: The task ID returned by execute_async.

    Returns:
        SubagentResult if found, None otherwise.
    """
    with _background_tasks_lock:
        return _background_tasks.get(task_id)


def list_background_tasks() -> list[SubagentResult]:
    """List all background tasks.

    Returns:
        List of all SubagentResult instances.
    """
    with _background_tasks_lock:
        return list(_background_tasks.values())


def cleanup_background_task(task_id: str) -> None:
    """Remove a completed task from background tasks.

    Should be called by task_tool after it finishes polling and returns the result.
    This prevents memory leaks from accumulated completed tasks.

    Only removes tasks that are in a terminal state (COMPLETED/FAILED/TIMED_OUT)
    to avoid race conditions with the background executor still updating the task entry.

    Args:
        task_id: The task ID to remove.
    """
    with _background_tasks_lock:
        result = _background_tasks.get(task_id)
        if result is None:
            # Nothing to clean up; may have been removed already.
            logger.debug("Requested cleanup for unknown background task %s", task_id)
            return

        # Only clean up tasks that are in a terminal state to avoid races with
        # the background executor still updating the task entry.
        if result.status.is_terminal or result.completed_at is not None:
            del _background_tasks[task_id]
            logger.debug("Cleaned up background task: %s", task_id)
        else:
            logger.debug(
                "Skipping cleanup for non-terminal background task %s (status=%s)",
                task_id,
                result.status.value if hasattr(result.status, "value") else result.status,
            )
