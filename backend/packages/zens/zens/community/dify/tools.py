"""Dify chat tool for DeerFlow agent."""

import logging
from typing import Annotated

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg
from zens.community.dify.dify_client import DifyAPIError, DifyClient

from deerflow.config import get_app_config
from deerflow.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)

# Per-(user_id, thread_id) → Dify conversation_id
_conversation_ids: dict[str, str] = {}


def _get_dify_client() -> DifyClient:
    config = get_app_config().get_tool_config("dify_chat")
    api_key: str | None = None
    if config is not None and "api_key" in config.model_extra:
        api_key = config.model_extra.get("api_key")

    base_url = (config.model_extra.get("base_url") if config else None) or "http://localhost:8000"

    if not api_key:
        raise DifyAPIError(0, "Dify api_key is not configured. Set 'api_key' in the dify_chat tool config or DIFY_API_KEY env var.")

    return DifyClient(api_key=api_key, base_url=base_url)


def _get_thread_id(config: RunnableConfig | None) -> str:
    """Extract thread_id from RunnableConfig, or return 'default'."""
    if config is None:
        return "default"
    configurable = config.get("configurable") or {}
    thread_id = configurable.get("thread_id")
    if thread_id is None:
        return "default"
    return str(thread_id)


@tool("dify_chat", parse_docstring=True)
def dify_chat_tool(
    query: str,
    config: Annotated[RunnableConfig, InjectedToolArg] = None,
) -> str:
    """Ask a Dify chatflow agent.

    Delegates the user's question to a Dify chatflow application and returns
    the agent's text response. Maintains conversation context within the same
    DeerFlow thread.

    Args:
        query: The question to ask the Dify agent.
    """
    user_id = get_effective_user_id()
    thread_id = _get_thread_id(config)
    cache_key = f"{user_id}:{thread_id}"

    conversation_id = _conversation_ids.get(cache_key, "")
    user = f"deerflow_{user_id}"

    client = _get_dify_client()

    try:
        response = client.chat(query=query, conversation_id=conversation_id, user=user)
    except DifyAPIError:
        raise
    except Exception as exc:
        raise DifyAPIError(0, f"Unexpected error: {exc}") from exc

    # Cache conversation_id for next call in same thread
    if response.conversation_id:
        _conversation_ids[cache_key] = response.conversation_id

    return response.answer
