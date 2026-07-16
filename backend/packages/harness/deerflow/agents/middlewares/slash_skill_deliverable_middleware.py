"""Gate slash-activated skills that declare ``required-outputs`` in frontmatter.

When a skill's SKILL.md lists ``required-outputs``, the lead agent must leave
those basenames under ``thread_data.outputs_path`` before the turn can END.
Missing files get a packaging reminder + ``jump_to=model``; exhaustion stamps
``deerflow_error_fallback`` so the run worker finishes as an error (lead-run
completion contract; see #4027 TerminalResponseMiddleware pattern and #4176
false-success without skill package output).
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse, hook_config
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage
from langgraph.runtime import Runtime

from deerflow.agents.middlewares._bounded_dict import BoundedDict
from deerflow.runtime.secret_context import _SLASH_SKILL_NAME_KEY, _SLASH_SKILL_REQUIRED_OUTPUTS_KEY
from deerflow.skills.slash import parse_slash_skill_reference
from deerflow.utils.messages import is_real_user_message

logger = logging.getLogger(__name__)

_DEFAULT_MAX_RECOVERY_ATTEMPTS = 2

_TOOL_CALL_FINISH_REASONS = {"tool_calls", "function_call"}

# Optional shape rules for known packaged skill names that use ``package_*.py``.
# Skills outside these sets still need ``source`` / ``schema_version`` / ``generated_at``.
_ARTICLE_HTML_SKILLS = frozenset(
    {
        "content-article-generation",
        "content-article-review",
        "content-article-layout",
        "content-article-images",
        "content-article-publish",
    }
)
_RESEARCH_SKILLS = frozenset({"content-research"})
_COVER_SKILLS = frozenset({"content-article-cover"})


def _non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def packaged_skill_json_is_valid(skill_name: str, payload: dict[str, Any]) -> bool:
    """Validate ``{skill}.json`` beyond a forged shell (source + schema_version).

    Official ``package_*.py`` scripts write non-empty ``generated_at``. Known
    article-body skills also require ``title`` + ``content_html``; review needs
    ``review.status``. Unknown skill names only get the common handshake.
    """
    if payload.get("source") != skill_name:
        return False
    if not _non_empty_str(payload.get("schema_version")):
        return False
    if not _non_empty_str(payload.get("generated_at")):
        return False

    if skill_name in _ARTICLE_HTML_SKILLS:
        if not _non_empty_str(payload.get("title")):
            return False
        if not _non_empty_str(payload.get("content_html")):
            return False
        if skill_name == "content-article-review":
            review = payload.get("review")
            if not isinstance(review, dict) or not _non_empty_str(review.get("status")):
                return False
        return True

    if skill_name in _RESEARCH_SKILLS:
        return isinstance(payload.get("sources"), list)

    if skill_name in _COVER_SKILLS:
        if not _non_empty_str(payload.get("title")):
            return False
        return isinstance(payload.get("cover"), dict)

    return True


def _recovery_prompt(skill_name: str, filenames: tuple[str, ...]) -> str:
    listed = ", ".join(f"`/mnt/user-data/outputs/{name}`" for name in filenames)
    return (
        "<system_reminder>\n"
        f"This turn activated `/{skill_name}` which declares `required-outputs`, but "
        f"the required deliverable(s) are missing or invalid: {listed}.\n"
        "Before finishing, run the skill's official `package_*.py` script so it writes "
        "those files (must include packager fields such as `generated_at`; article steps "
        "also need `title`/`content_html`). Do not hand-write JSON via inline python / "
        "`json.dump`. Do not claim the task is complete until every required output is a "
        "valid packaged file.\n"
        "</system_reminder>"
    )


def _fallback_content(skill_name: str, filenames: tuple[str, ...]) -> str:
    listed = ", ".join(f"`/mnt/user-data/outputs/{name}`" for name in filenames)
    return f"This `/{skill_name}` run finished without valid required output(s) after automatic recovery attempts: {listed}. The skill's declared `required-outputs` must be written before the run can succeed."


def _has_tool_call_intent(message: AIMessage) -> bool:
    if message.tool_calls or getattr(message, "invalid_tool_calls", None):
        return True
    additional_kwargs = message.additional_kwargs or {}
    if additional_kwargs.get("tool_calls") or additional_kwargs.get("function_call"):
        return True
    response_metadata = message.response_metadata or {}
    return response_metadata.get("finish_reason") in _TOOL_CALL_FINISH_REASONS


def _outputs_path(state: AgentState) -> Path | None:
    thread_data = state.get("thread_data")
    if not isinstance(thread_data, dict):
        return None
    raw = thread_data.get("outputs_path")
    if not isinstance(raw, str) or not raw.strip():
        return None
    return Path(raw)


def _latest_real_user_text(messages: list[Any]) -> str | None:
    for message in reversed(messages):
        if not is_real_user_message(message):
            continue
        content = getattr(message, "content", None)
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, str) and block.strip():
                    parts.append(block)
                elif isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append(text)
            if parts:
                return "\n".join(parts)
    return None


def _normalize_required_outputs(raw: Any) -> tuple[str, ...] | None:
    if not isinstance(raw, list):
        return None
    names: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            names.append(item.strip())
    return tuple(names)


def resolve_required_outputs(runtime: Runtime, messages: list[Any]) -> tuple[str, tuple[str, ...]] | None:
    """Return ``(skill_name, required_outputs)`` when a deliverable gate applies.

    Authoritative source is run context written by ``SkillActivationMiddleware``:
    ``__slash_skill_name`` + ``__slash_skill_required_outputs``. When the name key
    is present, message parsing is not used (avoids re-gating after a different
    skill). When both keys are absent, fall back to slash-parsing the latest user
    message and resolving the live skill registry for ``required_outputs``.
    """
    context = getattr(runtime, "context", None)
    if isinstance(context, dict) and _SLASH_SKILL_NAME_KEY in context:
        name = context.get(_SLASH_SKILL_NAME_KEY)
        if not isinstance(name, str) or not name.strip():
            return None
        outputs = _normalize_required_outputs(context.get(_SLASH_SKILL_REQUIRED_OUTPUTS_KEY))
        if outputs is None:
            # Name recorded but outputs key missing: look up live skill (upgrade path).
            outputs = _lookup_required_outputs(name)
        if not outputs:
            return None
        return name, outputs

    text = _latest_real_user_text(messages)
    if text is None:
        return None
    reference = parse_slash_skill_reference(text)
    if reference is None:
        return None
    outputs = _lookup_required_outputs(reference.name)
    if not outputs:
        return None
    return reference.name, outputs


def _lookup_required_outputs(skill_name: str) -> tuple[str, ...]:
    """Resolve ``required_outputs`` from the enabled skill registry (best-effort)."""
    try:
        from deerflow.skills.storage import get_or_new_skill_storage

        for skill in get_or_new_skill_storage().load_skills(enabled_only=True):
            if skill.name == skill_name:
                return tuple(skill.required_outputs or ())
    except Exception:
        logger.debug("SlashSkillDeliverableMiddleware: skill registry lookup failed", exc_info=True)
    return ()


def output_is_satisfied(outputs_path: Path, skill_name: str, filename: str) -> bool:
    """Return whether one required output basename is present and minimally valid."""
    if "/" in filename or "\\" in filename or Path(filename).name != filename:
        return False
    path = outputs_path / filename
    if not path.is_file():
        return False
    if not filename.endswith(".json"):
        return True
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    # Convention for packaged step JSON: basename ``{skill}.json`` must match
    # the official packager shape (not a hand-written shell).
    if filename == f"{skill_name}.json":
        return packaged_skill_json_is_valid(skill_name, payload)
    if "source" in payload and payload.get("source") != skill_name:
        return False
    return True


def missing_required_outputs(outputs_path: Path, skill_name: str, required: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(name for name in required if not output_is_satisfied(outputs_path, skill_name, name))


class SlashSkillDeliverableMiddleware(AgentMiddleware[AgentState]):
    """Enforce skill-declared ``required-outputs`` before slash turns can END."""

    def __init__(self, *, max_recovery_attempts: int = _DEFAULT_MAX_RECOVERY_ATTEMPTS) -> None:
        super().__init__()
        if max_recovery_attempts < 1:
            raise ValueError("max_recovery_attempts must be >= 1")
        self._max_recovery_attempts = max_recovery_attempts
        self._lock = threading.Lock()
        self._retry_counts: BoundedDict[tuple[str, str], int] = BoundedDict(1000)
        self._pending_prompts: BoundedDict[tuple[str, str], tuple[str, tuple[str, ...]]] = BoundedDict(1000)

    @staticmethod
    def _key(runtime: Runtime) -> tuple[str, str]:
        context = getattr(runtime, "context", None)
        if isinstance(context, dict):
            thread_id = str(context.get("thread_id") or "unknown-thread")
            run_id = str(context.get("run_id") or context.get("run_attempt_id") or id(runtime))
            return thread_id, run_id
        return "unknown-thread", str(id(runtime))

    def _clear(self, runtime: Runtime) -> None:
        key = self._key(runtime)
        with self._lock:
            self._retry_counts.pop(key, None)
            self._pending_prompts.pop(key, None)

    def _clear_other_runs(self, runtime: Runtime) -> None:
        thread_id, run_id = self._key(runtime)
        with self._lock:
            stale = [key for key in self._retry_counts if key[0] == thread_id and key[1] != run_id]
            for key in stale:
                self._retry_counts.pop(key, None)
                self._pending_prompts.pop(key, None)

    def _gate_context(
        self, state: AgentState, runtime: Runtime, *, allow_tool_intent: bool
    ) -> tuple[AIMessage, str, tuple[str, ...], Path, tuple[str, ...]] | None:
        messages = list(state.get("messages") or [])
        if not messages or not isinstance(messages[-1], AIMessage):
            return None

        last = messages[-1]
        if not allow_tool_intent and _has_tool_call_intent(last):
            return None
        if (last.additional_kwargs or {}).get("deerflow_error_fallback"):
            return None

        resolved = resolve_required_outputs(runtime, messages)
        if resolved is None:
            return None
        skill_name, required = resolved

        outputs_path = _outputs_path(state)
        if outputs_path is None:
            logger.warning(
                "SlashSkillDeliverableMiddleware: skill %s declares required-outputs but thread_data.outputs_path missing",
                skill_name,
            )
            return None

        missing = missing_required_outputs(outputs_path, skill_name, required)
        if not missing:
            return None
        return last, skill_name, required, outputs_path, missing

    def _error_fallback(self, last: AIMessage, skill_name: str, missing: tuple[str, ...]) -> dict[str, Any]:
        additional_kwargs = dict(last.additional_kwargs or {})
        additional_kwargs.update(
            {
                "deerflow_error_fallback": True,
                "error_reason": f"Missing required-outputs {list(missing)} for /{skill_name}",
            }
        )
        fallback = last.model_copy(
            update={
                "content": _fallback_content(skill_name, missing),
                "additional_kwargs": additional_kwargs,
            }
        )
        return {"messages": [fallback]}

    def _apply(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        messages = list(state.get("messages") or [])
        if not messages or not isinstance(messages[-1], AIMessage):
            return None

        last = messages[-1]
        if _has_tool_call_intent(last):
            return None
        if (last.additional_kwargs or {}).get("deerflow_error_fallback"):
            return None

        resolved = resolve_required_outputs(runtime, messages)
        if resolved is None:
            return None
        skill_name, required = resolved

        outputs_path = _outputs_path(state)
        if outputs_path is None:
            logger.warning(
                "SlashSkillDeliverableMiddleware: skill %s declares required-outputs but thread_data.outputs_path missing",
                skill_name,
            )
            return None

        missing = missing_required_outputs(outputs_path, skill_name, required)
        if not missing:
            self._clear(runtime)
            return None

        key = self._key(runtime)
        with self._lock:
            retry_count = self._retry_counts.get(key, 0)
            if retry_count < self._max_recovery_attempts:
                self._retry_counts[key] = retry_count + 1
                self._pending_prompts[key] = (skill_name, missing)

        if retry_count < self._max_recovery_attempts:
            logger.info(
                "SlashSkillDeliverableMiddleware: missing %s for /%s; recovery %s/%s",
                missing,
                skill_name,
                retry_count + 1,
                self._max_recovery_attempts,
            )
            message_updates = [RemoveMessage(id=last.id)] if last.id else []
            return {"messages": message_updates, "jump_to": "model"}

        logger.warning(
            "SlashSkillDeliverableMiddleware: giving up on /%s without %s after %s recoveries",
            skill_name,
            missing,
            self._max_recovery_attempts,
        )
        return self._error_fallback(last, skill_name, missing)

    def _finalize(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        """Last-chance denial if the turn ends without a valid packaged deliverable.

        Covers cases where recovery jumped to the model, the agent used more tools,
        then ended without another ``after_model`` rejection (or overwrote a valid
        file with a hand-written shell).
        """
        gated = self._gate_context(state, runtime, allow_tool_intent=True)
        if gated is None:
            self._clear(runtime)
            return None
        last, skill_name, _required, _outputs_path, missing = gated
        logger.warning(
            "SlashSkillDeliverableMiddleware: finalizing /%s without valid %s",
            skill_name,
            missing,
        )
        result = self._error_fallback(last, skill_name, missing)
        self._clear(runtime)
        return result

    def _augment_request(self, request: ModelRequest) -> ModelRequest:
        key = self._key(request.runtime)
        with self._lock:
            pending = self._pending_prompts.pop(key, None)
        if not pending:
            return request
        skill_name, filenames = pending
        reminder = HumanMessage(
            content=_recovery_prompt(skill_name, filenames),
            name="slash_skill_deliverable_recovery",
            additional_kwargs={"hide_from_ui": True},
        )
        return request.override(messages=[*request.messages, reminder])

    @override
    def before_agent(self, state: AgentState, runtime: Runtime) -> dict | None:
        self._clear_other_runs(runtime)
        self._clear(runtime)
        return None

    @override
    async def abefore_agent(self, state: AgentState, runtime: Runtime) -> dict | None:
        self._clear_other_runs(runtime)
        self._clear(runtime)
        return None

    @hook_config(can_jump_to=["model"])
    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        return self._apply(state, runtime)

    @hook_config(can_jump_to=["model"])
    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        return self._apply(state, runtime)

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        return handler(self._augment_request(request))

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        return await handler(self._augment_request(request))

    @override
    def after_agent(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._finalize(state, runtime)

    @override
    async def aafter_agent(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._finalize(state, runtime)
