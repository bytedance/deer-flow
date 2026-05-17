"""Middleware for explicit slash skill activation."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, override

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime

from deerflow.skills.slash import parse_slash_skill_reference, resolve_slash_skill
from deerflow.skills.storage import get_or_new_skill_storage
from deerflow.skills.types import SKILL_MD_FILE

if TYPE_CHECKING:
    from deerflow.config.app_config import AppConfig

logger = logging.getLogger(__name__)

_SLASH_SKILL_ACTIVATION_KEY = "slash_skill_activation"
_SLASH_SKILL_PROCESSED_KEY = "slash_skill_activation_processed"
_SUMMARY_MESSAGE_NAME = "summary"


@dataclass(frozen=True, slots=True)
class _Activation:
    skill_name: str
    category: str
    container_file_path: str
    skill_content: str
    content_hash: str
    remaining_text: str


def is_slash_skill_activation_reminder(message: object) -> bool:
    return isinstance(message, HumanMessage) and bool(message.additional_kwargs.get(_SLASH_SKILL_ACTIVATION_KEY))


def _is_user_activation_target(message: object) -> bool:
    if not isinstance(message, HumanMessage):
        return False
    if message.name == _SUMMARY_MESSAGE_NAME:
        return False
    if message.additional_kwargs.get("hide_from_ui"):
        return False
    return not bool(message.additional_kwargs.get(_SLASH_SKILL_PROCESSED_KEY))


class SkillActivationMiddleware(AgentMiddleware):
    """Inject full SKILL.md content when the user explicitly types /skill-name."""

    def __init__(
        self,
        *,
        available_skills: set[str] | None = None,
        app_config: AppConfig | None = None,
    ) -> None:
        super().__init__()
        self._available_skills = set(available_skills) if available_skills is not None else None
        self._app_config = app_config

    def _storage(self):
        if self._app_config is not None:
            return get_or_new_skill_storage(app_config=self._app_config)
        return get_or_new_skill_storage()

    @staticmethod
    def _read_skill_content(skill_file: Path) -> str:
        if skill_file.name != SKILL_MD_FILE:
            raise ValueError(f"Expected {SKILL_MD_FILE}, got {skill_file.name}")
        return skill_file.read_text(encoding="utf-8")

    def _resolve_activation(self, text: str) -> _Activation | None:
        if parse_slash_skill_reference(text) is None:
            return None

        storage = self._storage()
        skills = storage.load_skills(enabled_only=True)
        resolved = resolve_slash_skill(
            text,
            skills,
            available_skills=self._available_skills,
            container_base_path=storage.get_container_root(),
        )
        if resolved is None:
            return None

        try:
            skill_content = self._read_skill_content(resolved.skill.skill_file)
        except OSError:
            logger.exception("Failed to read slash-activated skill %s", resolved.skill.name)
            return None

        content_hash = hashlib.sha256(skill_content.encode("utf-8")).hexdigest()
        return _Activation(
            skill_name=resolved.skill.name,
            category=str(resolved.skill.category),
            container_file_path=resolved.container_file_path,
            skill_content=skill_content,
            content_hash=content_hash,
            remaining_text=resolved.remaining_text,
        )

    @staticmethod
    def _build_activation_reminder(activation: _Activation) -> str:
        user_request = activation.remaining_text or ("No additional task text was provided after the slash skill command. Ask the user what they want to do with this skill if the next step is unclear.")
        return f"""<slash_skill_activation>
The user explicitly activated the `{activation.skill_name}` skill for this turn.
Treat the task text as:
<user_request>
{user_request}
</user_request>

Follow this skill before choosing a general workflow. Load supporting resources from the same skill directory only when needed.

<skill name="{activation.skill_name}" category="{activation.category}" path="{activation.container_file_path}" sha256="{activation.content_hash}">
----- BEGIN SKILL.md -----
{activation.skill_content}
----- END SKILL.md -----
</skill>
</slash_skill_activation>"""

    @staticmethod
    def _make_activation_and_user_messages(original: HumanMessage, activation_content: str) -> tuple[HumanMessage, HumanMessage]:
        stable_id = original.id or str(uuid.uuid4())
        activation_msg = HumanMessage(
            content=activation_content,
            id=stable_id,
            additional_kwargs={
                "hide_from_ui": True,
                _SLASH_SKILL_ACTIVATION_KEY: True,
            },
        )
        user_kwargs = dict(original.additional_kwargs)
        user_kwargs[_SLASH_SKILL_PROCESSED_KEY] = True
        user_msg = HumanMessage(
            content=original.content,
            id=f"{stable_id}__slash_user",
            name=original.name,
            additional_kwargs=user_kwargs,
        )
        return activation_msg, user_msg

    def _inject(self, state) -> dict | None:
        messages = list(state.get("messages", []))
        if not messages:
            return None

        target = next((msg for msg in reversed(messages) if _is_user_activation_target(msg)), None)
        if target is None:
            return None

        content = target.content if isinstance(target.content, str) else str(target.content)
        activation = self._resolve_activation(content)
        if activation is None:
            return None

        logger.info(
            "SkillActivationMiddleware: activating slash skill %s category=%s hash=%s",
            activation.skill_name,
            activation.category,
            activation.content_hash[:12],
        )
        activation_msg, user_msg = self._make_activation_and_user_messages(target, self._build_activation_reminder(activation))
        return {"messages": [activation_msg, user_msg]}

    @override
    def before_agent(self, state, runtime: Runtime) -> dict | None:
        return self._inject(state)

    @override
    async def abefore_agent(self, state, runtime: Runtime) -> dict | None:
        return await asyncio.to_thread(self._inject, state)
