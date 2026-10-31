"""Middleware contributing the ``skill_manage`` tool and the evolution policy.

Two contribution mechanics, both through the host's existing extension
contracts:

* **Tool** — the middleware declares the host's ``skill_manage`` tool through
  its ``tools`` instance attribute. The host folds middleware-declared tools
  into the bound toolset *after* Layer-1 authorization, so a deployment that
  denies ``skill_manage`` keeps it denied.

* **Prompt** — the host has no prompt-contribution contract yet (the
  observational ``IsolatedMiddleware`` wrapper deliberately drops request
  overrides, so ``wrap_model_call`` cannot append system text; RFC 6954's
  ``PromptContributor`` remains a proposal). Until that contract lands, the
  policy rides ``before_agent`` state injection: one hidden,
  provenance-stamped ``SystemMessage`` with a stable ID, which the messages
  reducer upserts — re-injection is idempotent and never accumulates
  duplicates.

Known limitation of this interim wiring: the injected policy does not react
to a build in which Layer-1 narrowing removed ``skill_manage`` (the isolation
wrapper narrows its own ``tools`` copy; the inner middleware cannot observe
it). Authorization still blocks the call — the prompt simply cannot
selectively disappear for denied deployments until the host ships a real
prompt-contribution point.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from deerflow_extension_api import (
    AgentBuildContext,
    AgentScope,
    ContentKind,
    ExtensionData,
    MiddlewarePlacement,
    Placement,
    provenance_kwargs,
)
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import SystemMessage

from deerflow_extension_skill_evolution.config import SkillEvolutionSettings
from deerflow_extension_skill_evolution.prompt import build_evolution_prompt

logger = logging.getLogger(__name__)

#: Stable message ID of the injected policy. The messages reducer replaces a
#: same-ID message in place, so re-running ``before_agent`` refreshes the
#: policy without appending a second copy.
POLICY_MESSAGE_ID = "extension-skill-evolution-policy"

_PRODUCER_KIND = "skill_evolution_extension"

_legacy_switch_warned = False


def _legacy_core_switch_enabled() -> bool:
    """Best-effort probe for the deprecated core ``skill_evolution.enabled`` switch.

    Fails open to ``False``: a config-read problem must never disable the
    extension, and the import failure simply means a host without the legacy
    switch at all.
    """
    try:
        from deerflow.config import get_app_config
    except ImportError:
        return False
    try:
        return bool(getattr(get_app_config().skill_evolution, "enabled", False))
    except Exception:
        logger.warning("skill-evolution: could not read the legacy core skill_evolution switch; assuming it is disabled", exc_info=True)
        return False


class SkillEvolutionMiddleware(AgentMiddleware):
    """Declares ``skill_manage`` (and, in agent feedback mode, the read-only
    ``skill_feedback`` tool) and injects the evolution policy once per run.

    ``tools`` is a plain instance attribute holding a tuple — the exact shape
    the host's declaration-narrowing expects: it copies the middleware and
    rewrites ``tools`` to the authorized subset, so this class must never
    derive the attribute lazily or rebuild it from constructor arguments.
    """

    def __init__(self, *, tools: Sequence[Any], settings: SkillEvolutionSettings, prompt_enabled: bool = True) -> None:
        super().__init__()
        self.tools = tuple(tools)
        self._settings = settings
        self._prompt_enabled = prompt_enabled
        # The policy may only advertise tools this build actually declares:
        # the skill_feedback guidance (Plan B) is gated on the tool being in
        # ``tools`` — the single truth the host's declaration-narrowing sees.
        self._policy_text = build_evolution_prompt(settings, feedback_tool_declared=any(getattr(tool, "name", None) == "skill_feedback" for tool in self.tools))

    def release_policy_parameters(self) -> dict[str, object]:
        """The model-visible policy identity, for the agent assembly descriptor."""
        return {
            "skill_manage_tool_declared": any(getattr(tool, "name", None) == "skill_manage" for tool in self.tools),
            "skill_feedback_tool_declared": any(getattr(tool, "name", None) == "skill_feedback" for tool in self.tools),
            "feedback_mode": self._settings.feedback_mode,
            "prompt_enabled": self._prompt_enabled,
            "min_tool_calls_hint": self._settings.min_tool_calls_hint,
            "prefer_patch": self._settings.prefer_patch,
            "confirm_before_create": self._settings.confirm_before_create,
        }

    def _build_policy_message(self) -> SystemMessage:
        return SystemMessage(
            content=self._policy_text,
            id=POLICY_MESSAGE_ID,
            additional_kwargs={
                "hide_from_ui": True,
                **provenance_kwargs(ContentKind.MIDDLEWARE_INJECTION, _PRODUCER_KIND),
            },
        )

    def _inject(self, state: Any) -> dict[str, list[SystemMessage]] | None:
        if not self._prompt_enabled:
            return None
        messages = state.get("messages") if isinstance(state, dict) else None
        if messages and any(getattr(message, "id", None) == POLICY_MESSAGE_ID for message in messages):
            return None
        return {"messages": [self._build_policy_message()]}

    def before_agent(self, state: Any, runtime: Any) -> dict[str, list[SystemMessage]] | None:
        return self._inject(state)

    async def abefore_agent(self, state: Any, runtime: Any) -> dict[str, list[SystemMessage]] | None:
        return self._inject(state)


class SkillEvolutionContributor:
    """Decides per agent build what this extension contributes.

    Lead builds always receive the middleware. Subagent builds only when the
    operator opted in via ``scope: lead_and_subagent`` — the deliberate
    default is lead-only because a subagent does not need an active evolution
    prompt (RFC 6954 leaves widening as an explicit, visible decision).

    When the deprecated core ``skill_evolution.enabled`` switch is still on,
    the core already renders its own copy of this policy into the system
    prompt; the extension keeps contributing the tool but suppresses its
    duplicate prompt and warns once per process, so migrations are observable
    instead of silent.
    """

    def __init__(self, *, settings: SkillEvolutionSettings, tools: Sequence[Any]) -> None:
        self._settings = settings
        self._tools = tuple(tools)

    def contribute_middlewares(self, app_store: ExtensionData, ctx: AgentBuildContext) -> Sequence[MiddlewarePlacement]:
        scope = AgentScope.BOTH if self._settings.includes_subagents else AgentScope.LEAD
        prompt_enabled = True
        if _legacy_core_switch_enabled():
            prompt_enabled = False
            global _legacy_switch_warned
            if not _legacy_switch_warned:
                _legacy_switch_warned = True
                logger.warning(
                    "skill-evolution: the deprecated core `skill_evolution.enabled` switch is also on. "
                    "This extension is now the evolution entry point, so its duplicate policy prompt is suppressed; "
                    "set `skill_evolution.enabled: false` in config.yaml to complete the migration."
                )
        return (
            MiddlewarePlacement(
                SkillEvolutionMiddleware(tools=self._tools, settings=self._settings, prompt_enabled=prompt_enabled),
                Placement.STANDARD,
                scope,
            ),
        )
