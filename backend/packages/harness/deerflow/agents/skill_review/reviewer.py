"""Background skill reviewer that analyzes conversations and creates/updates skills."""

import logging
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from deerflow.agents.skill_review.prompt import SKILL_REVIEW_SYSTEM_PROMPT, SKILL_REVIEW_USER_PROMPT
from deerflow.agents.thread_state import ThreadState
from deerflow.config.app_config import AppConfig
from deerflow.models import create_chat_model

logger = logging.getLogger(__name__)

_REVIEW_RECURSION_LIMIT = 8


class SkillReviewer:
    """Creates and runs a lightweight background agent to review conversations for skill extraction.

    The review agent is created with no middlewares (anti-recursion) and only
    gets the ``skill_manage`` tool. It cannot trigger another skill review.
    """

    def __init__(self, config: AppConfig, model_name: str | None = None):
        self._config = config
        self._model_name = model_name

    def _get_model_name(self) -> str | None:
        """Resolve the model name for the review agent."""
        # Use moderation_model_name from skill_evolution config if set, otherwise use provided or default
        if self._config.skill_evolution.moderation_model_name:
            return self._config.skill_evolution.moderation_model_name
        if self._model_name:
            return self._model_name
        # Fall back to the first configured model
        if self._config.models:
            return self._config.models[0].name
        return None

    def _create_review_agent(self):
        """Create a minimal agent with only skill_manage tool, no middlewares (anti-recursion)."""
        from deerflow.tools.skill_manage_tool import skill_manage_tool

        model_name = self._get_model_name()
        model = create_chat_model(name=model_name, thinking_enabled=False)

        return create_agent(
            model=model,
            tools=[skill_manage_tool],
            middleware=[],
            system_prompt=SKILL_REVIEW_SYSTEM_PROMPT,
            state_schema=ThreadState,
        )

    def _build_existing_skills_section(self) -> str:
        """Build a section listing existing skills for the review prompt."""
        try:
            from deerflow.skills import load_skills

            skills = list(load_skills(enabled_only=False))
            if not skills:
                return ""
            lines = ['\n\n## Existing Skills\n\nThe following skills already exist. Update them with `skill_manage` action="patch" if they need new learnings, rather than creating duplicates.\n']
            for skill in skills:
                mutability = "editable" if skill.category == "custom" else "built-in"
                lines.append(f"- **{skill.name}** ({mutability}): {skill.description}")
            return "\n".join(lines)
        except Exception:
            logger.debug("Failed to load existing skills for review prompt", exc_info=True)
            return ""

    async def review(self, thread_id: str, messages: list[Any]) -> None:
        """Run a background skill review on the conversation.

        Best-effort: all exceptions are caught and logged, never propagated.

        Args:
            thread_id: The thread ID for tool execution context.
            messages: List of conversation messages to review.
        """
        try:
            agent = self._create_review_agent()

            # Build the review prompt, including a list of existing skills
            existing_skills_section = self._build_existing_skills_section()
            review_content = SKILL_REVIEW_USER_PROMPT + existing_skills_section
            review_message = HumanMessage(content=review_content)

            # Initial state: conversation messages + review prompt
            state: dict[str, Any] = {
                "messages": messages + [review_message],
            }

            # Build config with thread_id for skill_manage tool context
            run_config: RunnableConfig = {
                "recursion_limit": _REVIEW_RECURSION_LIMIT,
                "configurable": {"thread_id": thread_id},
            }
            context = {"thread_id": thread_id}

            logger.info("Skill review started for thread %s", thread_id)

            result = await agent.ainvoke(state, config=run_config, context=context)  # type: ignore[arg-type]

            # Log a summary of what happened
            # Only look at messages added by the review agent itself (after the review prompt).
            # The initial state includes conversation messages + review prompt, so we
            # skip everything before and including the review prompt to avoid logging
            # old tool results from the main conversation.
            result_messages = result.get("messages", []) if isinstance(result, dict) else []
            input_count = len(messages) + 1  # original messages + review prompt
            new_messages = result_messages[input_count:] if len(result_messages) > input_count else []

            review_tool_messages = [m for m in new_messages if getattr(m, "type", None) == "tool"]
            review_ai_messages = [m for m in new_messages if getattr(m, "type", None) == "ai"]

            if review_tool_messages:
                actions = []
                for msg in review_tool_messages:
                    content = getattr(msg, "content", "")
                    if isinstance(content, str):
                        content_lower = content.lower()
                        if "created" in content_lower or "updated" in content_lower or "patched" in content_lower:
                            actions.append(content)
                if actions:
                    summary = " | ".join(dict.fromkeys(actions))
                    logger.info("Skill review completed for thread %s: %s", thread_id, summary)
                else:
                    # Log the actual tool call content for debugging (truncated)
                    for msg in review_tool_messages:
                        content = getattr(msg, "content", "")
                        if isinstance(content, str) and len(content) > 200:
                            content = content[:200] + "..."
                        logger.info("Skill review tool result for thread %s: %s", thread_id, content)
                    logger.info("Skill review completed for thread %s (no skill changes)", thread_id)
            elif review_ai_messages:
                # Review agent responded with text only (e.g. "Nothing to save.")
                last_ai = review_ai_messages[-1]
                text = getattr(last_ai, "content", "")
                if isinstance(text, str):
                    logger.info("Skill review completed for thread %s: %s", thread_id, text[:200])
                else:
                    logger.info("Skill review completed for thread %s (no tool calls)", thread_id)
            else:
                logger.info("Skill review completed for thread %s (no new messages)", thread_id)

        except Exception:
            logger.warning("Skill review failed for thread %s", thread_id, exc_info=True)
