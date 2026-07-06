"""Tool for explicitly forgetting remembered information during conversation.

Lets the user say "forget that" in natural language and have the agent
immediately remove a fact from long-term memory.
"""

from __future__ import annotations

import logging

from langchain.tools import tool

from deerflow.agents.memory.search import find_facts_by_content, format_fact_list
from deerflow.agents.memory.updater import get_memory_data
from deerflow.agents.memory.storage import get_memory_storage
from deerflow.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)


@tool("forget", parse_docstring=True)
def forget_tool(
    query_or_id: str,
) -> str:
    """Forget a previously remembered piece of information.

    Use this when the user says something like "forget that", "never mind that fact",
    "remove that from memory", or when a previously remembered fact is no longer
    accurate.

    You can either:
    - Pass a fact_id directly (you can see fact IDs in the memory context)
    - Pass a search query and the tool will find the best matching facts to forget

    Always confirm with the user before forgetting if there are multiple matches.

    Args:
        query_or_id: Either a fact ID (e.g. "fact_abc12345") or a search phrase.
    """
    query = query_or_id.strip()
    if not query:
        return "Error: Provide a fact ID or search phrase."

    try:
        user_id = get_effective_user_id()
        memory_data = get_memory_data(user_id=user_id)
        facts = memory_data.get("facts", [])

        if not facts:
            return "Nothing to forget — memory is empty."

        # Check if it's a direct fact ID
        if query.startswith("fact_"):
            matching = [f for f in facts if f.get("id") == query]
            if matching:
                fact = matching[0]
                content = fact.get("content", "")
                storage = get_memory_storage()
                updated_facts = [f for f in facts if f.get("id") != query]
                memory_data["facts"] = updated_facts
                storage.save(memory_data, user_id=user_id)
                logger.info("Memory fact deleted by id (user=%s, fact=%s): %.60s", user_id, query, content)
                return f"I've forgotten: {content}"
            return f"Error: No fact found with id '{query}'."

        # Search by content (keyword-only, high precision for delete)
        matches = find_facts_by_content(facts, query, min_score=1.0)

        if not matches:
            return (
                f"I couldn't find anything matching '{query}' in memory. "
                "You can see all remembered facts in Settings > Memory."
            )

        if len(matches) == 1:
            fact, score = matches[0]
            fact_id = fact.get("id")
            content = fact.get("content", "")
            storage = get_memory_storage()
            updated_facts = [f for f in facts if f.get("id") != fact_id]
            memory_data["facts"] = updated_facts
            storage.save(memory_data, user_id=user_id)
            logger.info("Memory fact deleted by search (user=%s, score=%.2f): %.60s", user_id, score, content)
            return f"I've forgotten: {content}"

        # Multiple matches — return them so the agent can confirm
        return format_fact_list(matches, title="Matches") + '\nTell me the id or number, or say "forget all of them".'

    except OSError as e:
        logger.exception("Failed to save memory after forget")
        return f"Error: Could not update memory - {e}"
    except Exception as e:
        logger.exception("Unexpected error in forget tool")
        return f"Error: {e}"
