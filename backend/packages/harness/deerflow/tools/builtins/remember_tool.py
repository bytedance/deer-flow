"""Tool for explicitly remembering information during conversation.

Lets the user say "remember this" in natural language and have the agent
immediately persist a fact, bypassing the 30-second debounce queue that
the passive MemoryMiddleware uses.
"""

from __future__ import annotations

import logging
from typing import Literal

from langchain.tools import tool

from deerflow.agents.memory.updater import create_memory_fact, get_memory_data
from deerflow.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)


@tool("remember", parse_docstring=True)
def remember_tool(
    content: str,
    category: Literal["preference", "knowledge", "context", "behavior", "goal"] = "preference",
    confidence: float | None = None,
) -> str:
    """Remember an important piece of information about the user.

    Use this when the user explicitly says something they want you to remember,
    such as "remember that I use X", "note that I prefer Y", or "keep in mind that Z".

    This persists the information immediately into long-term memory so it is
    available in future conversations. Only use it for information the user
    explicitly asks you to remember or that is clearly important for future
    interactions.

    Do NOT use this for:
    - Session-specific details (current file paths, temporary tasks)
    - Information already captured by normal conversation flow
    - Trivial or obvious facts

    Args:
        content: The specific fact or information to remember. Be precise and self-contained.
        category: The type of information. Defaults to "preference".
            - preference: Tools, styles, approaches the user prefers
            - knowledge: Specific expertise, technologies, domain knowledge
            - context: Background facts (job, projects, languages)
            - behavior: Working patterns, communication habits
            - goal: Stated objectives, learning targets
        confidence: Optional confidence score 0-1. Defaults to 0.95 for explicit requests.
    """
    normalized = content.strip()
    if not normalized:
        return "Error: Cannot remember empty content."

    try:
        user_id = get_effective_user_id()
        effective_confidence = confidence if confidence is not None else 0.95

        create_memory_fact(
            content=normalized,
            category=category,
            confidence=effective_confidence,
            user_id=user_id,
        )

        logger.info("Memory fact created (user=%s, category=%s): %.60s", user_id, category, normalized)
        return f"I've remembered: {normalized}"
    except ValueError as e:
        return f"Error: Invalid fact - {e}"
    except OSError as e:
        logger.exception("Failed to save memory fact")
        return f"Error: Could not save memory - {e}"
    except Exception as e:
        logger.exception("Unexpected error in remember tool")
        return f"Error: {e}"
