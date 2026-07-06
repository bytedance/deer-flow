"""Tool for searching memory during conversation.

Lets the agent proactively look up relevant facts from long-term memory,
using both keyword matching and semantic (vector) search when embeddings
are available.
"""

from __future__ import annotations

import logging

from langchain.tools import tool

from deerflow.agents.memory.search import rank_facts, format_fact_list
from deerflow.agents.memory.updater import get_memory_data
from deerflow.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)


@tool("search_memory", parse_docstring=True)
def search_memory_tool(
    query: str,
    max_results: int = 10,
) -> str:
    """Search your long-term memory for information related to a query.

    Use this when you need to recall something the user told you in a previous
    conversation — preferences, past project context, technical stack details,
    or any other fact stored in memory.

    This searches both by keyword and by semantic similarity, so you can find
    information even when the exact wording differs.

    Do NOT use this for:
    - Information already visible in the current conversation
    - Information you just learned in this turn (it may not be saved yet)
    - General knowledge (use your own training data instead)

    Args:
        query: What to search for. Be specific — "what Python version does the user prefer"
               works better than "user info".
        max_results: Maximum number of matching memories to return (1-50). Default 10.
    """
    query = query.strip()
    if not query:
        return "Error: Provide a search query."

    if max_results < 1:
        max_results = 1
    elif max_results > 50:
        max_results = 50

    try:
        user_id = get_effective_user_id()
        memory_data = get_memory_data(user_id=user_id)
        facts = memory_data.get("facts", [])

        if not facts:
            return "Memory is empty — there is nothing to search yet."

        # Rank using combined keyword + vector scoring
        results = rank_facts(
            facts,
            query,
            max_results=max_results,
            keyword_weight=0.3,
            vector_weight=0.7,
        )

        if not results:
            return f"No matching memories found for '{query}'."

        return format_fact_list(results, title="Search results")

    except OSError as e:
        logger.exception("Failed to search memory")
        return f"Error: Could not search memory - {e}"
    except Exception as e:
        logger.exception("Unexpected error in search_memory tool")
        return f"Error: {e}"
