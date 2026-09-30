"""Middleware for skill activation: explicit slash + in-context secret binding."""

from __future__ import annotations

import asyncio
import hashlib
import html
import json
import logging
import posixpath
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, override

from deerflow_extension_api import ContentKind, provenance_kwargs
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.middlewares.skill_usage import SKILL_USAGE_KEY, SKILL_USAGES_KEY, build_skill_usage, record_skill_usage
from deerflow.runtime.events.catalog import (
    MIDDLEWARE_SKILL_ACTIVATION_TAG,
    MIDDLEWARE_SKILL_SECRETS_TAG,
)
from deerflow.runtime.secret_context import (
    _SECRETS_BINDING_AUDIT_KEY,
    _SLASH_SKILL_ACTIVATION_RUN_KEY,
    ACTIVE_SECRETS_CONTEXT_KEY,
    extract_request_secrets,
    read_slash_skill_source_paths,
    write_slash_skill_source_paths,
)
from deerflow.skills.slash import parse_slash_skill_reference, resolve_slash_skill
from deerflow.skills.storage import get_or_new_skill_storage, get_or_new_user_skill_storage
from deerflow.skills.storage.skill_storage import SkillStorage
from deerflow.skills.types import SKILL_MD_FILE, SecretRequirement, Skill, SkillCategory
from deerflow.utils.messages import get_original_user_content_text, is_real_user_message

if TYPE_CHECKING:
    from deerflow.authz.skill_filter import ResolvedSkillAuthorization
    from deerflow.config.app_config import AppConfig

logger = logging.getLogger(__name__)

_SLASH_SKILL_ACTIVATION_KEY = "slash_skill_activation"
_SLASH_SKILL_ACTIVATION_TARGET_ID_KEY = "slash_skill_activation_target_id"

# Async-prepass registry load already attempted and failed. Handed down so
# the secret-binding resolution does not silently recover with a fresh load:
# entry names resolved from a recovered registry would miss the (empty)
# decision map and fall back to the synchronous provider API from the worker
# thread — for a loop-affine provider a denial becomes a fail-open allow.
# Entries bind nothing for that call instead (fail closed by construction).
# Same marker pattern as SkillToolPolicyMiddleware._REGISTRY_LOAD_FAILED.
_REGISTRY_LOAD_FAILED = object()

# _SECRETS_BINDING_AUDIT_KEY: last audited binding (skill and secret names only,
# never values) so unchanged bindings are not re-recorded each call.
# The shared slash-source context contract holds the latest slash activation,
# ONLY the activated skill's canonical container path (never its declared
# secrets — those are read from the live registry on each call, #3938). The
# injection set is recomputed every model call, but a slash-activated skill must
# stay bound for the rest of the run — the model's tool loop issues many model
# calls after the single activation call (#3861 semantics).
# _SLASH_SKILL_ACTIVATION_RUN_KEY: identity of the slash message already activated
# in this run, so the reminder injection + skill disk read + "activate" audit event
# fire once per user slash command instead of on every model call. The reminder is
# added via request.override(messages=...) for a single model call and never
# persisted to graph state, so the 2nd..Nth model call of a turn rebuilds
# request.messages from state without it — the run context is the only signal that
# survives the tool loop. All three live in secret_context so they are covered by
# REDACTED_CONTEXT_KEYS in one place.


@dataclass(frozen=True, slots=True)
class _Activation:
    skill_name: str
    category: str
    container_file_path: str
    skill_content: str
    content_hash: str
    remaining_text: str
    editable: bool
    required_secrets: tuple[SecretRequirement, ...] = ()
    additional_activations: tuple[_Activation, ...] = ()


@dataclass(frozen=True, slots=True)
class _ActivationResolution:
    activation: _Activation | None = None
    failure_message: str | None = None


def is_slash_skill_activation_reminder(message: object) -> bool:
    """Return whether a message is hidden slash-skill activation context."""
    return isinstance(message, HumanMessage) and bool(message.additional_kwargs.get(_SLASH_SKILL_ACTIVATION_KEY))


def _is_user_activation_target(message: object) -> bool:
    return is_real_user_message(message)


class SkillActivationMiddleware(AgentMiddleware):
    """Inject full SKILL.md content when the user explicitly types /skill-name."""

    def __init__(
        self,
        *,
        available_skills: set[str] | None = None,
        app_config: AppConfig | None = None,
        user_id: str | None = None,
        slash_source_owner_token: str,
        skill_authorization: ResolvedSkillAuthorization | None = None,
    ) -> None:
        super().__init__()
        if not isinstance(slash_source_owner_token, str) or not slash_source_owner_token:
            raise ValueError("slash_source_owner_token must be a non-empty string")
        self._available_skills = set(available_skills) if available_skills is not None else None
        self._app_config = app_config
        self._user_id = user_id
        self._slash_source_owner_token = slash_source_owner_token
        self._skill_authorization = skill_authorization

    def _activation_allowed(self, skill_name: str, *, activation_decisions: dict[str, bool] | None = None) -> bool:
        """Action-scoped ``skill:activate`` check for explicit slash activation.

        ``_available_skills`` is the Layer 1 *visibility* set (filter_resources,
        action-agnostic); an action-aware custom provider may expose a skill
        there while denying its activation. Mirrors ``_authorize_model_name``'s
        second ``authorize("model", "use")`` check. Provider errors follow the
        configured fail-closed / fail-open policy. ``None`` (authorization
        disabled) allows — membership in the visibility set already decided.
        Delegates to the shared ``skill_activation_allowed`` so the slash path,
        ``describe_skill``, and the skill-file-load path cannot drift.

        *activation_decisions* carries decisions precomputed on the event loop
        via ``aauthorize()`` by ``awrap_model_call``: the threaded handler then
        consults them instead of calling the synchronous ``authorize()`` (wrong
        API for loop-affine providers). Names absent from the map fall back to
        the synchronous check, which is the correct API for the sync
        ``wrap_model_call`` path.
        """
        if activation_decisions is not None and skill_name in activation_decisions:
            return activation_decisions[skill_name]
        from deerflow.authz.skill_filter import skill_activation_allowed

        return skill_activation_allowed(self._skill_authorization, skill_name)

    async def _collect_activation_decisions(self, names) -> dict[str, bool] | None:
        """Precompute ``skill:activate`` decisions on the event loop.

        Async middleware paths offload the blocking handler (skill-tree reads)
        to a worker thread, but the provider decision belongs on the loop with
        ``aauthorize()``. Collects every candidate name the handler may need —
        the slash target and the persisted ``skill_context`` entries — so one
        batch of awaits covers both the activation and secret-binding gates.
        ``None`` means authorization is disabled (nothing to precompute).
        """
        if self._skill_authorization is None:
            return None
        candidates = {name for name in names if isinstance(name, str) and name}
        if not candidates:
            return None
        from deerflow.authz.skill_filter import skill_activation_allowed_async

        decisions: dict[str, bool] = {}
        for name in sorted(candidates):
            decisions[name] = await skill_activation_allowed_async(self._skill_authorization, name)
        return decisions

    def _candidate_activation_targets(self, request: ModelRequest) -> tuple[list[str], list[str]]:
        """Split the activation candidates into (names, entry_paths).

        Loop-safe (no storage I/O): the slash reference is parsed straight
        from the latest real user message — its name is already canonical,
        because ``_resolve_activation`` matches it against the registry's
        ``Skill.name`` set. The persisted ``skill_context`` entries contribute
        their *paths*: the stamped ``entry["name"]`` is path-derived (the
        directory name) and can differ from the declared ``Skill.name``, so
        the consumer (``_in_context_secret_sources``) resolves the path
        through the live registry — the decision map must be keyed by the
        same canonical names, resolved off-loop by the caller.
        """
        names: list[str] = []
        entry_paths: list[str] = []
        messages = list(request.messages)
        for index in range(len(messages) - 1, -1, -1):
            if _is_user_activation_target(messages[index]):
                content = get_original_user_content_text(messages[index].content, messages[index].additional_kwargs)
                explicit_names = messages[index].additional_kwargs.get("skill_references")
                if explicit_names is not None and explicit_names != []:
                    if isinstance(explicit_names, list) and 1 <= len(explicit_names) <= 16:
                        for name in explicit_names:
                            reference = parse_slash_skill_reference(f"/{name}") if isinstance(name, str) else None
                            if reference is not None and reference.name == name:
                                names.append(name)
                else:
                    reference = parse_slash_skill_reference(content)
                    if reference is not None:
                        names.append(reference.name)
                break
        state = getattr(request, "state", None) or {}
        try:
            entries = state.get("skill_context") or []
        except AttributeError:
            entries = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            path = entry.get("path")
            if isinstance(path, str) and path:
                entry_paths.append(path)
        return names, entry_paths

    def _canonical_names_for_paths(self, paths: list[str]) -> tuple[list[str], dict[str, Skill] | object]:
        """Canonical ``Skill.name`` for the entry paths plus the registry they
        came from (thread-only; disk I/O).

        Returns ``(names, registry)`` where *registry* is the snapshot the
        names were resolved from — the async caller hands it to the secret
        binding resolution so entries are resolved against the SAME snapshot
        the decision map was keyed by (a map miss is then impossible by
        construction, closing the sync-API fallback divergence). On storage
        failure returns ``([], _REGISTRY_LOAD_FAILED)``: entries must bind
        nothing rather than be re-resolved from a silently recovered fresh
        load. Returns immediately for an empty list: this helper runs on
        every authorization-enabled async model step, and an ordinary request
        (no slash reference, no persisted entries, no supplied secrets) must
        not pay a full skill-tree scan per LLM call.
        """
        if not paths:
            return [], None
        try:
            from deerflow.skills.container_registry import build_container_path_registry, canonical_skill_name

            registry = build_container_path_registry(self._storage())
        except Exception:
            logger.exception("Failed to load skills while collecting activation candidates")
            return [], _REGISTRY_LOAD_FAILED
        return [name for name in (canonical_skill_name(registry, path) for path in paths) if name is not None], registry

    def release_policy_parameters(self) -> dict[str, object]:
        return {
            # None means "any enabled, runtime-allowed skill may be activated";
            # a concrete list narrows that to a fixed set.
            "available_skills": sorted(self._available_skills) if self._available_skills is not None else None,
            "max_explicit_skill_references": 16,
        }

    def _storage(self) -> SkillStorage:
        if self._user_id is not None:
            return get_or_new_user_skill_storage(self._user_id, app_config=self._app_config)
        if self._app_config is not None:
            return get_or_new_skill_storage(app_config=self._app_config)
        return get_or_new_skill_storage()

    @staticmethod
    def _read_skill_content(skill_file: Path, skills_root: Path, *, storage: SkillStorage | None = None) -> str:
        from deerflow.skills.mutations.guard import managed_read

        with managed_read(storage):
            return SkillActivationMiddleware._read_skill_content_unlocked(skill_file, skills_root, storage=storage)

    @staticmethod
    def _read_skill_content_unlocked(skill_file: Path, skills_root: Path, *, storage: SkillStorage | None = None) -> str:
        if skill_file.name != SKILL_MD_FILE:
            raise ValueError(f"Expected {SKILL_MD_FILE}, got {skill_file.name}")
        # Use the storage's path validation if available — UserScopedSkillStorage
        # stores custom skills in a per-user directory that is not a sub-path of
        # the global skills root, so the simple relative_to check would reject them.
        # Fall back to the relative_to check when the storage is a mock (e.g. tests)
        # that doesn't implement validate_skill_file_path.
        if storage is not None and hasattr(storage, "validate_skill_file_path"):
            resolved_file = storage.validate_skill_file_path(skill_file)
        else:
            resolved_file = skill_file.resolve()
            resolved_root = skills_root.resolve()
            try:
                resolved_file.relative_to(resolved_root)
            except ValueError as exc:
                raise ValueError("Resolved skill file must stay within the configured skills root.") from exc
        if not resolved_file.is_file():
            raise FileNotFoundError(resolved_file)
        return resolved_file.read_text(encoding="utf-8")

    def _resolve_activation(self, text: str, *, activation_decisions: dict[str, bool] | None = None) -> _ActivationResolution | None:
        reference = parse_slash_skill_reference(text)
        if reference is None:
            return None

        storage = self._storage()
        skills = storage.load_skills(enabled_only=False)
        skill = next((candidate for candidate in skills if candidate.name == reference.name), None)
        if skill is None:
            return _ActivationResolution(failure_message=f"Skill `/{reference.name}` is not installed.")
        if not skill.enabled:
            return _ActivationResolution(failure_message=f"Skill `/{reference.name}` is installed but disabled. Enable it before using slash activation.")
        if self._available_skills is not None and reference.name not in self._available_skills:
            return _ActivationResolution(failure_message=f"Skill `/{reference.name}` is not available for this agent.")
        if not self._activation_allowed(reference.name, activation_decisions=activation_decisions):
            # Visible in the Layer 1 set but denied by the action-scoped
            # skill:activate policy — same user-facing message as the
            # membership denial so the reason is not leaked.
            return _ActivationResolution(failure_message=f"Skill `/{reference.name}` is not available for this agent.")

        resolved = resolve_slash_skill(
            text,
            skills,
            available_skills=self._available_skills,
            container_base_path=storage.get_container_root(),
        )
        if resolved is None:
            return _ActivationResolution(failure_message=f"Skill `/{reference.name}` could not be resolved.")

        try:
            skill_content = self._read_skill_content(resolved.skill.skill_file, storage.get_skills_root_path(), storage=storage)
        except (OSError, ValueError):
            logger.exception("Failed to read slash-activated skill %s", resolved.skill.name)
            return _ActivationResolution(failure_message=f"Skill `/{reference.name}` could not be loaded safely. Please check the skill installation.")

        content_hash = hashlib.sha256(skill_content.encode("utf-8")).hexdigest()
        # CUSTOM skills are editable; PUBLIC and LEGACY are read-only
        editable = resolved.skill.category == SkillCategory.CUSTOM
        return _ActivationResolution(
            activation=_Activation(
                skill_name=resolved.skill.name,
                category=str(resolved.skill.category),
                container_file_path=resolved.container_file_path,
                skill_content=skill_content,
                content_hash=content_hash,
                remaining_text=resolved.remaining_text,
                editable=editable,
                required_secrets=tuple(resolved.skill.required_secrets or ()),
            )
        )

    @staticmethod
    def _build_activation_reminder(activation: _Activation, *, include_user_request: bool = True) -> str:
        user_request = activation.remaining_text or ("No additional task text was provided after the slash skill command. Ask the user what they want to do with this skill if the next step is unclear.")
        escaped_user_request = html.escape(user_request, quote=False)
        request_block = f"Treat the task text as:\n<user_request>\n{escaped_user_request}\n</user_request>\n" if include_user_request else ""
        escaped_skill_content = html.escape(activation.skill_content, quote=False)
        escaped_skill_name = html.escape(activation.skill_name, quote=True)
        escaped_category = html.escape(activation.category, quote=True)
        escaped_path = html.escape(activation.container_file_path, quote=True)
        escaped_content_hash = html.escape(activation.content_hash, quote=True)
        editable_str = "true" if activation.editable else "false"
        return f"""<slash_skill_activation>
The user explicitly activated the `{escaped_skill_name}` skill for this turn.
{request_block}
Follow this skill before choosing a general workflow. Load supporting resources from the same skill directory only when needed.

<skill name="{escaped_skill_name}" category="{escaped_category}" path="{escaped_path}" sha256="{escaped_content_hash}" editable="{editable_str}">
<skill_content encoding="xml-escaped">
{escaped_skill_content}
</skill_content>
</skill>
</slash_skill_activation>"""

    @staticmethod
    def _has_existing_activation_for_target(messages: list, target_index: int, target: HumanMessage) -> bool:
        if target_index <= 0:
            return False

        if target.id:
            for previous in messages[:target_index]:
                if not is_slash_skill_activation_reminder(previous):
                    continue
                target_id = previous.additional_kwargs.get(_SLASH_SKILL_ACTIVATION_TARGET_ID_KEY)
                if target_id == target.id or previous.id == f"{target.id}__slash_activation":
                    return True

        previous = messages[target_index - 1]
        return is_slash_skill_activation_reminder(previous)

    @staticmethod
    def _activation_run_key(target: HumanMessage) -> str:
        """Stable identity for a user slash message, used to activate once per run.

        Prefers the message id (LangGraph assigns and preserves a stable id once a
        message is in graph state); falls back to a digest of the genuine user text
        so an id-less message still dedupes within a run. A new user slash message
        (new id / new text) yields a new key, so it is not suppressed.
        """
        if target.id:
            return target.id
        content = get_original_user_content_text(target.content, target.additional_kwargs)
        references = target.additional_kwargs.get("skill_references")
        if references is not None:
            content += "\n" + json.dumps(references, sort_keys=True, default=str)
        return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _run_context(request: ModelRequest) -> dict | None:
        runtime = getattr(request, "runtime", None)
        context = getattr(runtime, "context", None)
        return context if isinstance(context, dict) else None

    @staticmethod
    def _already_activated(run_context: dict | None, run_key: str) -> bool:
        """Whether ``run_key`` was already recorded as activated earlier in this run.

        Sibling to ``_has_existing_activation_for_target``: that helper catches an
        activation reminder still present in the scanned ``messages`` window; this
        one catches a prior activation recorded on ``run_context`` whose reminder
        already fell out of that window (the tool-loop case — see
        ``_SLASH_SKILL_ACTIVATION_RUN_KEY``). ``run_key`` is computed once by the
        caller (``_find_activation_target``) and reused as-is at the write site in
        ``_prepare_model_request``, so the same key is always used to check and to
        record — this helper only ever checks membership, never computes the key.
        """
        return isinstance(run_context, dict) and run_context.get(_SLASH_SKILL_ACTIVATION_RUN_KEY) == run_key

    def _find_activation_target(self, messages: list, *, run_context: dict | None = None, activation_decisions: dict[str, bool] | None = None) -> tuple[int, HumanMessage, _ActivationResolution, str] | None:
        if not messages:
            return None

        target_index = next((idx for idx in range(len(messages) - 1, -1, -1) if _is_user_activation_target(messages[idx])), None)
        if target_index is None:
            return None

        target = messages[target_index]
        if target is None:
            return None
        if self._has_existing_activation_for_target(messages, target_index, target):
            return None
        # This exact slash message may have already activated earlier in the run.
        # The message scan above cannot catch it because the reminder lives only in
        # a per-call request override, never in state — the run context is the
        # durable signal (see _already_activated / _SLASH_SKILL_ACTIVATION_RUN_KEY).
        # Skipping here avoids the redundant skill disk read, reminder re-injection,
        # and duplicate "activate" audit. run_key is computed once here and threaded
        # through to the write site in _prepare_model_request.
        run_key = self._activation_run_key(target)
        if self._already_activated(run_context, run_key):
            return None

        content = get_original_user_content_text(target.content, target.additional_kwargs)
        names = target.additional_kwargs.get("skill_references")
        if names is not None and names != []:
            if not isinstance(names, list) or not 1 <= len(names) <= 16:
                resolution = _ActivationResolution(failure_message="Select between 1 and 16 skills.")
            else:
                activations: list[_Activation] = []
                resolution = None
                for name in names:
                    reference = parse_slash_skill_reference(f"/{name}") if isinstance(name, str) else None
                    if reference is None or reference.name != name:
                        resolution = _ActivationResolution(failure_message="Invalid skill reference.")
                        break
                    if any(item.skill_name == name for item in activations):
                        continue
                    resolved = self._resolve_activation(f"/{name} {content}", activation_decisions=activation_decisions)
                    if resolved is None or resolved.failure_message or resolved.activation is None:
                        resolution = resolved or _ActivationResolution(failure_message="Invalid skill reference.")
                        break
                    activations.append(resolved.activation)
                if resolution is None and activations:
                    resolution = _ActivationResolution(activation=replace(activations[0], additional_activations=tuple(activations[1:])))
        else:
            resolution = self._resolve_activation(content, activation_decisions=activation_decisions)
        if resolution is None:
            return None
        return target_index, target, resolution, run_key

    @staticmethod
    def _record_activation(request: ModelRequest, activation: _Activation, *, hook: str) -> None:
        runtime = getattr(request, "runtime", None)
        context = getattr(runtime, "context", None)
        journal = context.get("__run_journal") if isinstance(context, dict) else None
        if journal is None:
            return
        try:
            journal.record_middleware(
                MIDDLEWARE_SKILL_ACTIVATION_TAG,
                name="SkillActivationMiddleware",
                hook=hook,
                action="activate",
                changes={
                    "skill_name": activation.skill_name,
                    "category": activation.category,
                    "path": activation.container_file_path,
                    "content_hash": activation.content_hash,
                },
            )
        except Exception:
            logger.warning("Failed to record slash skill activation audit event", exc_info=True)

    def _prepare_model_request(self, request: ModelRequest, *, hook: str, activation_decisions: dict[str, bool] | None = None) -> tuple[ModelRequest | AIMessage | None, _Activation | None]:
        run_context = self._run_context(request)
        target_and_resolution = self._find_activation_target(list(request.messages), run_context=run_context, activation_decisions=activation_decisions)
        if target_and_resolution is None:
            return None, None

        target_index, target, resolution, run_key = target_and_resolution
        if resolution.failure_message:
            return AIMessage(content=resolution.failure_message), None

        activation = resolution.activation
        if activation is None:
            return None, None

        logger.info(
            "SkillActivationMiddleware: activating slash skill %s category=%s path=%s hash=%s",
            activation.skill_name,
            activation.category,
            activation.container_file_path,
            activation.content_hash,
        )
        for item in (activation, *activation.additional_activations):
            self._record_activation(request, item, hook=hook)
        # Mark this slash message as activated for the run so the tool loop's later
        # model calls skip the redundant re-activation (#3861: one activation call,
        # many follow-up model calls). A new user slash message keys differently and
        # still activates. Overwrite (`=`), not append/accumulate, is intentional:
        # _find_activation_target only ever considers the latest real user message as
        # an activation target, so there is nothing earlier in the run worth
        # remembering once a new activation replaces it — do not "fix" this into a
        # set. run_key is the same value already checked in _find_activation_target
        # (computed once there, threaded through here) rather than recomputed.
        if run_context is not None:
            run_context[_SLASH_SKILL_ACTIVATION_RUN_KEY] = run_key
        activation_msg = self._make_activation_message(target, "\n\n".join(self._build_activation_reminder(item, include_user_request=index == 0) for index, item in enumerate((activation, *activation.additional_activations))))
        messages = list(request.messages)
        messages.insert(target_index, activation_msg)
        return request.override(messages=messages), activation

    def _handle_model_request(
        self,
        request: ModelRequest,
        *,
        hook: str,
        activation_decisions: dict[str, bool] | None = None,
        entry_registry: dict[str, Skill] | object | None = None,
    ) -> tuple[ModelRequest | AIMessage, _Activation | None]:
        prepared, activation = self._prepare_model_request(request, hook=hook, activation_decisions=activation_decisions)
        if isinstance(prepared, AIMessage):
            return prepared, None
        effective = prepared if prepared is not None else request
        self._resolve_secret_bindings(effective, activation, hook=hook, activation_decisions=activation_decisions, entry_registry=entry_registry)
        if activation is not None:
            for item in (activation, *activation.additional_activations):
                record_skill_usage(getattr(request, "runtime", None), self._usage_snapshot(item))
        return effective, activation

    @staticmethod
    def _usage_snapshot(activation: _Activation) -> dict | None:
        return build_skill_usage(
            activation.container_file_path,
            activation.skill_content,
            skills_root=posixpath.dirname(activation.container_file_path),
            activation="slash",
            name=activation.skill_name,
            category=activation.category,
        )

    @staticmethod
    def _stamp_usage(response: ModelResponse | AIMessage, activation: _Activation | None) -> ModelResponse | AIMessage:
        if activation is None:
            return response
        # Embedded/checkpoint clients also keep evidence on the first response.
        # The journal independently attaches a run aggregate before serialization.
        usage = SkillActivationMiddleware._usage_snapshot(activation)
        if usage is not None:
            messages = [response] if isinstance(response, AIMessage) else getattr(response, "result", [])
            for message in messages:
                if isinstance(message, AIMessage):
                    if activation.additional_activations:
                        usages = [snapshot for item in (activation, *activation.additional_activations) if (snapshot := SkillActivationMiddleware._usage_snapshot(item)) is not None]
                        message.additional_kwargs = {**message.additional_kwargs, SKILL_USAGES_KEY: usages}
                    else:
                        message.additional_kwargs = {**message.additional_kwargs, SKILL_USAGE_KEY: usage}
                    break
        return response

    def _resolve_secret_bindings(
        self,
        request: ModelRequest,
        activation: _Activation | None,
        *,
        hook: str,
        activation_decisions: dict[str, bool] | None = None,
        entry_registry: dict[str, Skill] | object | None = None,
    ) -> None:
        """Recompute the per-run secret injection set (binding point A+, #3861/#3914).

        Sources, unioned on every model call:

        - the most recent slash activation of this run (persisted as a source on
          the run context so the whole tool loop after the activation call keeps
          the binding — a new slash activation replaces it). The slash source is
          validated once, at activation (enabled + allowlist checks in
          ``_resolve_activation``), and deliberately NOT re-validated per call:
          slash is a run-scoped commitment made by the user, and it dies with
          the run anyway;
        - skills the model loaded earlier in the thread (``ThreadState.skill_context``),
          re-validated against the live registry on each call: enabled,
          runtime-allowed for this agent, and not opted out via
          ``secrets-autonomous: false``. Slash activation is exempt from the
          opt-out — it is the explicit-ceremony path.

        The set is recomputed and REPLACED each call, so a skill evicted from
        skill_context, or a caller that stops supplying a value, loses its
        injection on the next call automatically. Injected values always come
        from the caller's request (``context.secrets``) — never the host
        environment, which ``env_policy.build_sandbox_env`` scrubs before
        injection — so a skill can never harvest a host platform credential.
        Secret *values* are never logged; the audit journal records names only.
        """
        runtime = getattr(request, "runtime", None)
        context = getattr(runtime, "context", None)
        if not isinstance(context, dict):
            return

        # The slash source records the canonical container path plus a
        # middleware-chain-local owner token — never declared secrets. Both
        # consumers authenticate the source and resolve the live registry skill
        # by path, so caller-mergeable context cannot forge an activation.
        if activation is not None:
            write_slash_skill_source_paths(
                context,
                tuple(item.container_file_path for item in (activation, *activation.additional_activations)),
                owner_token=self._slash_source_owner_token,
            )

        request_secrets = extract_request_secrets(context)
        sources: list[tuple[str, tuple[SecretRequirement, ...]]] = []
        if request_secrets:
            # Two secret sources, two deliberately DIFFERENT registry
            # reference points:
            #
            # Slash source — always a fresh, post-activation registry. Its
            # binding must match the skill content the activation just read;
            # the prepass snapshot is taken BEFORE the aauthorize awaits, so
            # resolving the slash source from it would activate NEW_KEY
            # content while binding OLD_KEY when a skill's declared secrets
            # change in that window (review: keep the fresh slash lookup
            # separate from the entry snapshot). The slash source never
            # consults the decision map, so snapshot consistency buys nothing
            # here.
            slash_registry = self._load_skill_registry_by_path()
            # Entry sources — the snapshot the decision map was keyed by
            # (a map miss is impossible by construction), or an empty
            # registry after a failed prepass (bind nothing rather than
            # silently recover with a fresh load whose names would miss the
            # map and fall back to the sync provider API). ``None`` (sync
            # chain / prepass not run) falls back to the same fresh registry
            # the slash source uses — on the sync chain the synchronous
            # authorize() is the correct API, so no divergence exists there.
            if entry_registry is _REGISTRY_LOAD_FAILED:
                entry_registry_effective: dict[str, Skill] = {}
            elif entry_registry is not None:
                entry_registry_effective = entry_registry
            else:
                entry_registry_effective = slash_registry if slash_registry is not None else {}
            # The two sources resolve independently — a transient failure of
            # the fresh slash lookup must not zero the entry sources (they
            # have their own snapshot and never consult that registry).
            slash_paths = read_slash_skill_source_paths(context, owner_token=self._slash_source_owner_token)
            if slash_registry is not None:
                # Slash source: exempt from the ``secrets-autonomous`` opt-out
                # (explicit ceremony), but still enabled + allowlist checked.
                for slash_path in slash_paths:
                    slash_skill = self._resolve_registry_skill(slash_registry, slash_path, require_autonomous=False)
                    if slash_skill is not None:
                        sources.append((slash_skill.name, tuple(slash_skill.required_secrets)))
            # Entry sources resolve independently. The same-skill exclusion is
            # anchored on the AUTHENTICATED slash activation identity — not on
            # binding success, and not on the declared name alone: a
            # slash-activated skill whose current version declares no secrets
            # binds nothing itself, yet must still suppress its stale entry
            # view, and a mid-run rename (same path, new declared name) would
            # otherwise slip a name-anchored exclusion. The PATH is the stable
            # identity shared by the activation and every earlier read, so the
            # identity path always excludes; the resolved names (fresh registry
            # first, then the entry snapshot) additionally cover the cross-path
            # same-name shadowing case.
            slash_bound = {name for name, _ in sources}
            identity_paths = frozenset(posixpath.normpath(path) for path in slash_paths)
            for normalized_identity in identity_paths:
                for registry in (slash_registry, entry_registry_effective):
                    identity = registry.get(normalized_identity) if isinstance(registry, dict) else None
                    if identity is not None:
                        slash_bound.add(identity.name)
                        break
            sources.extend(self._in_context_secret_sources(request, entry_registry_effective, activation_decisions=activation_decisions, exclude_names=frozenset(slash_bound), exclude_paths=identity_paths))

        injected: dict[str, str] = {}
        bound_skills: set[str] = set()
        missing: dict[str, list[str]] = {}
        for skill_name, requirements in sources:
            for req in requirements:
                if req.name in request_secrets:
                    injected[req.name] = request_secrets[req.name]
                    bound_skills.add(skill_name)
                elif not req.optional:
                    missing.setdefault(skill_name, []).append(req.name)

        if injected:
            context[ACTIVE_SECRETS_CONTEXT_KEY] = injected
        else:
            context.pop(ACTIVE_SECRETS_CONTEXT_KEY, None)

        audit_state = {
            "skills": sorted(bound_skills),
            "secrets": sorted(injected),
            "missing": {name: sorted(values) for name, values in sorted(missing.items())},
        }
        previous = context.get(_SECRETS_BINDING_AUDIT_KEY)
        if previous == audit_state:
            return
        if previous is None and not injected and not missing:
            return
        context[_SECRETS_BINDING_AUDIT_KEY] = audit_state
        for skill_name, names in sorted(missing.items()):
            logger.warning(
                "Skill %s is active but required secrets are missing from the request context: %s",
                skill_name,
                ", ".join(names),
            )
        self._record_secret_binding(context, audit_state, hook=hook)

    def _load_skill_registry_by_path(self) -> dict[str, Skill] | None:
        """Load the live skill registry keyed by normalized container file path.

        Reloaded every call on purpose (not cached): load_skills re-reads the
        enabled state from extensions_config so an operator disabling a skill
        revokes its secret binding on the very next model call. A cache keyed on
        file mtimes would miss enable/disable toggles (which do not touch
        SKILL.md) and keep injecting after a disable — trading the
        immediate-revocation security property for speed. The cost is gated: the
        only caller runs this only when the caller supplied secrets.

        Paths are normalized so a non-canonical ``container_path`` config (e.g. a
        trailing slash) still matches the canonical path captured in
        ``skill_context`` (#3938). Returns ``None`` if the registry can't load —
        both the slash and in-context sources then bind nothing for that call
        (fail closed). This is a deliberate availability-for-security trade-off:
        a transient registry read failure mid-run drops the injection for that
        call rather than trusting stale caller-supplied data.
        """
        try:
            from deerflow.skills.container_registry import build_container_path_registry

            return build_container_path_registry(self._storage())
        except Exception:
            logger.exception("Failed to load skills while resolving secret bindings")
            return None

    def _resolve_registry_skill(self, registry: dict[str, Skill], path: object, *, require_autonomous: bool) -> Skill | None:
        """Resolve a container path to a live registry skill eligible for secret
        binding, or ``None``.

        Match strictly by normalized container file path — never by name. A
        by-name fallback would be a confused deputy: DeerFlow lets a custom skill
        shadow a same-named public/legacy one (load_skills de-dupes by name,
        custom wins), so a reference to public/foo could bind the custom foo's
        secrets. A path that does not resolve simply binds nothing (the safe
        direction), which also fails closed on a caller-forged path (#3938).

        Gates: the skill must be enabled, declare secrets, and be allowlisted for
        this agent. ``require_autonomous`` additionally enforces the
        ``secrets-autonomous`` opt-out for the in-context path; the slash path
        passes ``False`` because explicit activation is the ceremony that opt-out
        is meant to preserve.
        """
        if not isinstance(path, str) or not path:
            return None
        skill = registry.get(posixpath.normpath(path))
        if skill is None or not skill.enabled or not skill.required_secrets:
            return None
        if require_autonomous and not skill.secrets_autonomous:
            return None
        if self._available_skills is not None and skill.name not in self._available_skills:
            return None
        return skill

    def _in_context_secret_sources(
        self,
        request: ModelRequest,
        registry: dict[str, Skill],
        *,
        activation_decisions: dict[str, bool] | None = None,
        exclude_names: frozenset[str] = frozenset(),
        exclude_paths: frozenset[str] = frozenset(),
    ) -> list[tuple[str, tuple[SecretRequirement, ...]]]:
        """Map ``ThreadState.skill_context`` entries to declared-secret sources.

        Entries are references to skills the model actually loaded in this
        thread. Each is re-validated against the live registry so a skill that
        was disabled, uninstalled, opted out, or removed from the agent's
        allowlist after being read stops binding immediately. The
        ``skill:activate`` decision is re-checked here as well: ``skill_context``
        persists across runs, and an entry stamped under an earlier policy must
        not keep binding secrets after the provider starts denying activation.

        *exclude_names* carries the slash-activated skill names: explicit slash
        activation dominates for the rest of the run (the same rule the
        tool-policy middleware applies), and the slash source is resolved from
        a fresher registry than the entry snapshot — letting the same skill
        contribute both sources would bind two eras of its declarations when
        they change across the prepass→activation window. *exclude_paths*
        carries the authenticated slash identity's container path — the stable
        identity across mid-run renames, where the same path's old and new
        versions carry different declared names and a name-anchored exclusion
        alone would slip.
        """
        state = getattr(request, "state", None) or {}
        try:
            entries = state.get("skill_context") or []
        except AttributeError:
            return []

        sources: list[tuple[str, tuple[SecretRequirement, ...]]] = []
        seen: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            entry_path = entry.get("path")
            normalized_entry_path = posixpath.normpath(entry_path) if isinstance(entry_path, str) and entry_path else None
            if normalized_entry_path is not None and normalized_entry_path in exclude_paths:
                # The slash-activated identity owns this path; its entry view
                # must not widen or stale it under any declared name.
                continue
            skill = self._resolve_registry_skill(registry, entry_path, require_autonomous=True)
            if skill is None or skill.name in seen:
                continue
            if skill.name in exclude_names:
                # The slash source already binds this skill's activation-era
                # declaration; its entry view must not widen or stale it.
                continue
            if not self._activation_allowed(skill.name, activation_decisions=activation_decisions):
                continue
            seen.add(skill.name)
            sources.append((skill.name, tuple(skill.required_secrets)))
        return sources

    @staticmethod
    def _record_secret_binding(context: dict, audit_state: dict, *, hook: str) -> None:
        journal = context.get("__run_journal")
        if journal is None:
            return
        try:
            journal.record_middleware(
                MIDDLEWARE_SKILL_SECRETS_TAG,
                name="SkillActivationMiddleware",
                hook=hook,
                action="bind_secrets",
                changes=audit_state,
            )
        except Exception:
            logger.warning("Failed to record skill secret binding audit event", exc_info=True)

    @staticmethod
    def _make_activation_message(target: HumanMessage, activation_content: str) -> HumanMessage:
        stable_id = target.id or str(uuid.uuid4())
        additional_kwargs = {
            "hide_from_ui": True,
            _SLASH_SKILL_ACTIVATION_KEY: True,
            **provenance_kwargs(ContentKind.SKILL_BODY, "skill_activation"),
        }
        if target.id:
            additional_kwargs[_SLASH_SKILL_ACTIVATION_TARGET_ID_KEY] = target.id
        return HumanMessage(
            content=activation_content,
            id=f"{stable_id}__slash_activation",
            additional_kwargs=additional_kwargs,
        )

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse | AIMessage:
        # Sync-chain twin of the async publication: when authorization is
        # enabled and persisted entries exist, resolve one registry snapshot
        # plus the synchronous authorize() decisions and publish the path-keyed
        # map for the durable renderer. Passive steps (no entries) publish
        # nothing and pay no I/O, mirroring the async empty-paths guard.
        if self._skill_authorization is not None:
            _, entry_paths = self._candidate_activation_targets(request)
            if entry_paths:
                names, registry = self._canonical_names_for_paths(entry_paths)
                decisions = self._collect_sync_activation_decisions(names)
                self._publish_entry_decisions(request, entry_paths, registry, decisions)
        prepared, activation = self._handle_model_request(request, hook="wrap_model_call")
        if isinstance(prepared, AIMessage):
            return prepared
        return self._stamp_usage(handler(prepared), activation)

    def _publish_entry_decisions(
        self,
        request: ModelRequest,
        entry_paths: list[str],
        entry_registry: dict[str, Skill] | object | None,
        activation_decisions: dict[str, bool] | None,
    ) -> None:
        """Publish per-step ``skill:activate`` decisions keyed by entry path.

        The durable-context renderer consumes this map so the model-visible
        "Active skills" reminder stops advertising skills the provider now
        denies. Keyed by normalized container path (the renderer's entry
        identity); a prepass registry failure, an unresolvable path, or a
        missing decision all publish ``False`` — hide rather than advertise.
        """
        run_context = self._run_context(request)
        if run_context is None:
            return
        from deerflow.runtime.secret_context import write_skill_entry_decisions

        decisions: dict[str, bool] = {}
        registry = entry_registry if isinstance(entry_registry, dict) else {}
        collected = activation_decisions or {}
        for path in entry_paths:
            normalized = posixpath.normpath(path)
            skill = registry.get(normalized)
            decisions[normalized] = collected.get(skill.name, False) if skill is not None else False
        write_skill_entry_decisions(run_context, decisions, owner_token=self._slash_source_owner_token)

    def _collect_sync_activation_decisions(self, names: list[str]) -> dict[str, bool] | None:
        """Synchronous authorize() decisions for *names* (sync chain only)."""
        if self._skill_authorization is None or not names:
            return None
        from deerflow.authz.skill_filter import skill_activation_allowed

        return {name: skill_activation_allowed(self._skill_authorization, name) for name in names}

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse | AIMessage:
        # Resolve the skill:activate decisions on the event loop with the
        # provider's async API, then hand them to the worker thread: the
        # blocking handler (skill-tree reads) keeps its to_thread offload while
        # loop-affine providers still receive aauthorize() — a synchronous
        # authorize() from the thread is the wrong API for them. Entry paths
        # are canonicalized through the registry in a worker thread first so
        # the decision map is keyed by declared Skill.name (the same names the
        # threaded handler's registry lookups produce), not directory names.
        # The snapshot those names came from travels with the decisions: the
        # secret-binding resolution reuses it for the entry sources, so a map
        # miss is impossible by construction (and a failed load means entries
        # bind nothing — no silent fresh-load recovery).
        entry_registry: dict[str, Skill] | object | None = None
        if self._skill_authorization is not None:
            slash_names, entry_paths = self._candidate_activation_targets(request)
            canonical_names, entry_registry = await asyncio.to_thread(self._canonical_names_for_paths, entry_paths)
            activation_decisions = await self._collect_activation_decisions([*slash_names, *canonical_names])
            self._publish_entry_decisions(request, entry_paths, entry_registry, activation_decisions)
        else:
            activation_decisions = None
        prepared, activation = await asyncio.to_thread(
            self._handle_model_request,
            request,
            hook="awrap_model_call",
            activation_decisions=activation_decisions,
            entry_registry=entry_registry,
        )
        if isinstance(prepared, AIMessage):
            return prepared
        return self._stamp_usage(await handler(prepared), activation)
