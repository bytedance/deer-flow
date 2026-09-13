"""Apply skill ``allowed-tools`` only to skills active in lead-agent context."""

from __future__ import annotations

import asyncio
import json
import logging
import posixpath
import secrets
from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from deerflow.runtime.secret_context import SKILL_TOOL_POLICY_DECISION_CONTEXT_KEY, read_slash_skill_source_path
from deerflow.skills.storage import get_or_new_skill_storage, get_or_new_user_skill_storage
from deerflow.skills.tool_policy import ALWAYS_AVAILABLE_BUILTIN_TOOL_NAMES, allowed_tool_names_for_skills
from deerflow.skills.types import Skill

if TYPE_CHECKING:
    from deerflow.config.app_config import AppConfig
    from deerflow.skills.storage.skill_storage import SkillStorage

logger = logging.getLogger(__name__)

_POLICY_DECISION_VERSION = 2
_POLICY_SOURCE_PASSIVE = "passive"
_POLICY_SOURCE_SLASH = "slash"
_POLICY_SOURCE_SKILL_CONTEXT = "skill_context"
_POLICY_SOURCES = frozenset({_POLICY_SOURCE_PASSIVE, _POLICY_SOURCE_SLASH, _POLICY_SOURCE_SKILL_CONTEXT})
_MISSING_POLICY_DECISION = object()
_TOOL_SEARCH_NAME = "tool_search"

type _PolicySignature = tuple[str, tuple[str, ...]]


class SkillToolPolicyMiddleware(AgentMiddleware[AgentState]):
    """Restrict agent tools to declarations from slash/in-context skills.

    Merely enabling a skill makes it discoverable; it does not activate its
    authority policy. A skill becomes policy-active when the user slash-activates
    it for the run or after the model loads it into ``skill_context``. Explicit
    slash activation dominates for the rest of that run: passively reading a
    second skill cannot widen the slash skill's authority.
    """

    def __init__(
        self,
        *,
        available_skills: set[str] | None = None,
        app_config: AppConfig | None = None,
        user_id: str | None = None,
        slash_source_owner_token: str,
        skill_authorization=None,
    ) -> None:
        super().__init__()
        if not isinstance(slash_source_owner_token, str) or not slash_source_owner_token:
            raise ValueError("slash_source_owner_token must be a non-empty string")
        self._available_skills = set(available_skills) if available_skills is not None else None
        self._app_config = app_config
        self._user_id = user_id
        self._slash_source_owner_token = slash_source_owner_token
        self._skill_authorization = skill_authorization
        self._decision_owner_token = secrets.token_urlsafe(24)

    def _activation_allowed(self, skill_name: str, *, activation_decisions: dict[str, bool] | None = None) -> bool:
        """Action-scoped ``skill:activate`` decision for one skill name.

        Persisted ``skill_context`` entries were authorized when they were
        stamped, but the policy may have changed since — every entry is
        re-authorized before its allowed-tools declaration is applied.
        *activation_decisions* carries decisions precomputed on the event loop
        via ``aauthorize()`` (async hooks); names absent from the map fall back
        to the synchronous check, which is the correct API for the sync hooks.
        """
        if self._skill_authorization is None:
            return True
        if activation_decisions is not None and skill_name in activation_decisions:
            return activation_decisions[skill_name]
        from deerflow.authz.skill_filter import skill_activation_allowed

        return skill_activation_allowed(self._skill_authorization, skill_name)

    async def _collect_activation_decisions(self, request: ModelRequest | ToolCallRequest) -> dict[str, bool] | None:
        """Precompute ``skill:activate`` decisions on the event loop (async hooks).

        The policy resolution itself runs in a worker thread (storage reads),
        but the provider decision belongs on the loop with ``aauthorize()``.
        Candidates are the persisted ``skill_context`` entry names — the same
        entries ``_active_skills_for_paths`` will re-authorize.
        """
        if self._skill_authorization is None:
            return None
        names = {name for name in self._entry_names(request) if isinstance(name, str) and name}
        # The slash source (when present) is the policy's dominant path — its
        # skill goes through the same re-authorization, so precompute its name
        # too; otherwise the async path would fall back to the sync provider
        # call from the worker thread.
        context = getattr(getattr(request, "runtime", None), "context", None)
        slash_path = read_slash_skill_source_path(context, owner_token=self._slash_source_owner_token)
        if isinstance(slash_path, str) and slash_path:
            names.add(posixpath.basename(posixpath.dirname(slash_path)))
        if not names:
            return None
        from deerflow.authz.skill_filter import skill_activation_allowed_async

        decisions: dict[str, bool] = {}
        for name in sorted(names):
            decisions[name] = await skill_activation_allowed_async(self._skill_authorization, name)
        return decisions

    def _storage(self) -> SkillStorage:
        if self._user_id is not None:
            return get_or_new_user_skill_storage(self._user_id, app_config=self._app_config)
        if self._app_config is not None:
            return get_or_new_skill_storage(app_config=self._app_config)
        return get_or_new_skill_storage()

    @staticmethod
    def _skill_context_entries(request: ModelRequest | ToolCallRequest) -> list:
        """Persisted ``skill_context`` entries from agent state (possibly empty)."""
        state = getattr(request, "state", None)
        if state is None:
            state = {}
        if isinstance(state, Mapping):
            entries = state.get("skill_context") or []
        elif hasattr(state, "skill_context"):
            entries = getattr(state, "skill_context") or []
        else:
            logger.warning("Unsupported agent state shape for skill tool policy: %s", type(state).__name__)
            entries = []
        if not isinstance(entries, (list, tuple)):
            logger.warning("Invalid skill_context shape for skill tool policy: %s", type(entries).__name__)
            entries = []
        return list(entries)

    @classmethod
    def _entry_names(cls, request: ModelRequest | ToolCallRequest) -> list[str]:
        """Skill names of the persisted entries (stamped name, else path-derived)."""
        names: list[str] = []
        for entry in cls._skill_context_entries(request):
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if isinstance(name, str) and name:
                names.append(name)
            else:
                path = entry.get("path")
                if isinstance(path, str) and path:
                    names.append(posixpath.basename(posixpath.dirname(path)))
        return names

    def _active_policy(self, request: ModelRequest | ToolCallRequest) -> _PolicySignature:
        context = getattr(getattr(request, "runtime", None), "context", None)
        slash_path = read_slash_skill_source_path(context, owner_token=self._slash_source_owner_token)
        if slash_path is not None:
            return _POLICY_SOURCE_SLASH, (slash_path,)

        paths: list[str] = []
        for entry in self._skill_context_entries(request):
            if isinstance(entry, dict) and isinstance(entry.get("path"), str):
                paths.append(entry["path"])
        if paths:
            return _POLICY_SOURCE_SKILL_CONTEXT, tuple(paths)
        return _POLICY_SOURCE_PASSIVE, ()

    def _active_skills_for_paths(self, paths: tuple[str, ...], *, activation_decisions: dict[str, bool] | None = None) -> tuple[list[Skill], bool]:
        if not paths:
            return [], False

        try:
            storage = self._storage()
            skills = storage.load_skills(enabled_only=False)
            container_root = storage.get_container_root()
        except Exception:
            logger.exception("Failed to load active skills for allowed-tools policy")
            # A real active reference exists but cannot be authorized. Signal a
            # policy failure so callers retain only framework-safe tools.
            return [], True

        registry = {posixpath.normpath(skill.get_container_file_path(container_root)): skill for skill in skills}
        active: list[Skill] = []
        seen: set[str] = set()
        for path in paths:
            skill = registry.get(posixpath.normpath(path))
            if skill is None:
                logger.warning("Active skill path could not be resolved for allowed-tools policy: %s", path)
                continue
            if not skill.enabled:
                logger.warning("Active skill is disabled for allowed-tools policy: %s", path)
                continue
            if self._available_skills is not None and skill.name not in self._available_skills:
                logger.warning("Active skill is outside the agent allowlist for allowed-tools policy: %s", path)
                continue
            # Phase 3: skill_context persists across runs — an entry stamped
            # under an earlier policy must not keep applying its allowed-tools
            # declaration after the provider starts denying activation (same
            # skip-and-continue treatment as a disabled or unallowlisted skill).
            if not self._activation_allowed(skill.name, activation_decisions=activation_decisions):
                logger.info("Active skill is denied by the skill:activate policy for allowed-tools policy: %s", path)
                continue
            if skill.name in seen:
                continue
            seen.add(skill.name)
            active.append(skill)
        if not active:
            logger.warning("No active skill references could be authorized for allowed-tools policy; failing closed")
            return [], True
        return active, False

    def _allowed_names_for_paths(self, paths: tuple[str, ...], *, activation_decisions: dict[str, bool] | None = None) -> set[str] | None:
        active_skills, policy_failed = self._active_skills_for_paths(paths, activation_decisions=activation_decisions)
        if policy_failed:
            return set(ALWAYS_AVAILABLE_BUILTIN_TOOL_NAMES)
        allowed = allowed_tool_names_for_skills(active_skills)
        if allowed is None:
            return None
        return allowed | set(ALWAYS_AVAILABLE_BUILTIN_TOOL_NAMES)

    @staticmethod
    def _runtime_context(request: ModelRequest | ToolCallRequest) -> dict | None:
        context = getattr(getattr(request, "runtime", None), "context", None)
        return context if isinstance(context, dict) else None

    def _store_policy_decision(self, request: ModelRequest, policy: _PolicySignature, allowed: set[str] | None) -> None:
        context = self._runtime_context(request)
        if context is not None:
            source, paths = policy
            context[SKILL_TOOL_POLICY_DECISION_CONTEXT_KEY] = {
                "version": _POLICY_DECISION_VERSION,
                "owner_token": self._decision_owner_token,
                "source": source,
                "active_paths": list(paths),
                "allowed_names": None if allowed is None else sorted(allowed),
            }

    def _read_policy_decision(self, context: dict | None, policy: _PolicySignature) -> set[str] | None | object:
        if context is None:
            return _MISSING_POLICY_DECISION
        decision = context.get(SKILL_TOOL_POLICY_DECISION_CONTEXT_KEY)
        if not isinstance(decision, dict):
            return _MISSING_POLICY_DECISION
        if type(decision.get("version")) is not int or decision["version"] != _POLICY_DECISION_VERSION:
            return _MISSING_POLICY_DECISION
        if not isinstance(decision.get("owner_token"), str) or decision["owner_token"] != self._decision_owner_token:
            return _MISSING_POLICY_DECISION
        source, paths = policy
        stored_source = decision.get("source")
        if not isinstance(stored_source, str) or stored_source not in _POLICY_SOURCES or stored_source != source:
            return _MISSING_POLICY_DECISION
        stored_paths = decision.get("active_paths")
        if not isinstance(stored_paths, list) or not all(isinstance(path, str) for path in stored_paths) or tuple(stored_paths) != paths:
            return _MISSING_POLICY_DECISION
        allowed = decision.get("allowed_names")
        if allowed is None:
            return None
        if not isinstance(allowed, list) or not all(isinstance(name, str) for name in allowed):
            return _MISSING_POLICY_DECISION
        return set(allowed)

    def _allowed_names(
        self,
        request: ModelRequest | ToolCallRequest,
        *,
        policy: _PolicySignature | None = None,
        activation_decisions: dict[str, bool] | None = None,
    ) -> set[str] | None:
        resolved_policy = self._active_policy(request) if policy is None else policy
        _, paths = resolved_policy
        context = self._runtime_context(request)
        decision = self._read_policy_decision(context, resolved_policy)
        if decision is not _MISSING_POLICY_DECISION:
            return decision
        return self._allowed_names_for_paths(paths, activation_decisions=activation_decisions)

    def _filter_model_request(
        self,
        request: ModelRequest,
        *,
        policy: _PolicySignature | None = None,
        refresh_decision: bool = False,
        activation_decisions: dict[str, bool] | None = None,
    ) -> ModelRequest:
        resolved_policy = self._active_policy(request) if policy is None else policy
        _, paths = resolved_policy
        if refresh_decision:
            allowed = self._allowed_names_for_paths(paths, activation_decisions=activation_decisions)
        else:
            allowed = self._allowed_names(request, policy=resolved_policy, activation_decisions=activation_decisions)
        if refresh_decision:
            self._store_policy_decision(request, resolved_policy, allowed)
        if allowed is None:
            return request
        tools = [tool for tool in request.tools if getattr(tool, "name", None) in allowed]
        if len(tools) < len(request.tools):
            logger.debug("Skill policy filtered %d lead tool schema(s)", len(request.tools) - len(tools))
        return request.override(tools=tools)

    def _blocked_tool_message(
        self,
        request: ToolCallRequest,
        *,
        allowed: set[str] | None,
    ) -> ToolMessage | None:
        name = str(request.tool_call.get("name") or "")
        if allowed is None or not name or name in allowed:
            return None
        return ToolMessage(
            content=f"Error: Tool '{name}' is not allowed by the active skill policy.",
            tool_call_id=str(request.tool_call.get("id") or "missing_tool_call_id"),
            name=name,
            status="error",
        )

    @staticmethod
    def _tool_search_policy_error(request: ToolCallRequest) -> ToolMessage:
        return ToolMessage(
            content="Error: tool_search returned a result that could not be validated against the active skill policy.",
            tool_call_id=str(request.tool_call.get("id") or "missing_tool_call_id"),
            name=_TOOL_SEARCH_NAME,
            status="error",
        )

    def _filter_tool_search_result(
        self,
        request: ToolCallRequest,
        result: ToolMessage | Command,
        *,
        allowed: set[str] | None,
    ) -> ToolMessage | Command:
        """Remove denied schemas and promotions from tool_search output.

        Keeping tool_search available is safe only if it cannot return a full
        schema for a tool removed by the active policy. Deferred filtering still
        controls when an allowed schema becomes model-visible; this method keeps
        the discovery result itself within the same authorization boundary.
        """
        name = str(request.tool_call.get("name") or "")
        if name != _TOOL_SEARCH_NAME or allowed is None:
            return result
        if not isinstance(result, Command) or not isinstance(result.update, dict):
            logger.warning("Active-policy tool_search returned an unsupported result shape")
            return self._tool_search_policy_error(request)

        promoted = result.update.get("promoted")
        messages = result.update.get("messages")
        if not isinstance(promoted, dict) or not isinstance(messages, list) or len(messages) != 1:
            logger.warning("Active-policy tool_search command omitted promoted/messages updates")
            return self._tool_search_policy_error(request)
        raw_names = promoted.get("names")
        if not isinstance(raw_names, list) or not all(isinstance(item, str) for item in raw_names):
            logger.warning("Active-policy tool_search returned malformed promoted names")
            return self._tool_search_policy_error(request)

        permitted_names = [item for item in raw_names if item in allowed]
        sanitized_messages: list[ToolMessage] = []
        for message in messages:
            if not isinstance(message, ToolMessage) or message.name != _TOOL_SEARCH_NAME:
                logger.warning("Active-policy tool_search returned an unexpected message shape")
                return self._tool_search_policy_error(request)
            content = message.content
            if raw_names:
                try:
                    schemas = json.loads(content) if isinstance(content, str) else None
                except json.JSONDecodeError:
                    schemas = None
                if not isinstance(schemas, list):
                    logger.warning("Active-policy tool_search returned schemas that could not be filtered")
                    return self._tool_search_policy_error(request)
                filtered_schemas = [schema for schema in schemas if isinstance(schema, dict) and (schema.get("name") in permitted_names or (isinstance(schema.get("function"), dict) and schema["function"].get("name") in permitted_names))]
                content = json.dumps(filtered_schemas, indent=2, ensure_ascii=False) if filtered_schemas else "No tools found matching the active skill policy."
            sanitized_messages.append(message.model_copy(update={"content": content}))

        sanitized_update = dict(result.update)
        sanitized_update["promoted"] = {**promoted, "names": permitted_names}
        sanitized_update["messages"] = sanitized_messages
        return Command(
            graph=result.graph,
            update=sanitized_update,
            resume=result.resume,
            goto=result.goto,
        )

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        policy = self._active_policy(request)
        return handler(self._filter_model_request(request, policy=policy, refresh_decision=True))

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        policy = self._active_policy(request)
        _, paths = policy
        if not paths:
            self._store_policy_decision(request, policy, None)
            return await handler(request)
        # Resolve the skill:activate re-authorization decisions on the event
        # loop (aauthorize) and hand them to the worker thread below — the
        # blocking policy resolution keeps its to_thread offload while
        # loop-affine providers still receive the async API.
        activation_decisions = await self._collect_activation_decisions(request)
        filtered = await asyncio.to_thread(
            self._filter_model_request,
            request,
            policy=policy,
            refresh_decision=True,
            activation_decisions=activation_decisions,
        )
        return await handler(filtered)

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        policy = self._active_policy(request)
        if not policy[1]:
            return handler(request)
        allowed = self._allowed_names(request, policy=policy)
        blocked = self._blocked_tool_message(request, allowed=allowed)
        if blocked is not None:
            return blocked
        return self._filter_tool_search_result(request, handler(request), allowed=allowed)

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        policy = self._active_policy(request)
        if not policy[1]:
            return await handler(request)
        activation_decisions = await self._collect_activation_decisions(request)
        allowed = await asyncio.to_thread(self._allowed_names, request, policy=policy, activation_decisions=activation_decisions)
        blocked = self._blocked_tool_message(request, allowed=allowed)
        if blocked is not None:
            return blocked
        return self._filter_tool_search_result(request, await handler(request), allowed=allowed)
