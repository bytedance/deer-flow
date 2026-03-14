from typing import Annotated, NotRequired

from langchain.agents import AgentState
from pydantic import ConfigDict
from typing_extensions import TypedDict


class SandboxState(TypedDict):
    sandbox_id: NotRequired[str | None]


class ThreadDataState(TypedDict):
    workspace_path: NotRequired[str | None]
    uploads_path: NotRequired[str | None]
    outputs_path: NotRequired[str | None]


class ViewedImageData(TypedDict):
    base64: str
    mime_type: str


class AgentContext(TypedDict, total=False):
    """Runtime context passed to the LangGraph assistant."""

    __pydantic_config__ = ConfigDict(extra="allow")

    thread_id: str
    sandbox_id: NotRequired[str | None]
    agent_name: NotRequired[str | None]
    channel_name: NotRequired[str | None]
    chat_id: NotRequired[str | None]
    user_id: NotRequired[str | None]
    thread_ts: NotRequired[str | None]
    topic_id: NotRequired[str | None]
    is_cron: NotRequired[bool]
    cron_job_id: NotRequired[str]
    cron_job_name: NotRequired[str]
    is_plan_mode: NotRequired[bool]
    thinking_enabled: NotRequired[bool]
    subagent_enabled: NotRequired[bool]


def merge_artifacts(existing: list[str] | None, new: list[str] | None) -> list[str]:
    """Reducer for artifacts list - merges and deduplicates artifacts."""
    if existing is None:
        return new or []
    if new is None:
        return existing
    # Use dict.fromkeys to deduplicate while preserving order
    return list(dict.fromkeys(existing + new))


def merge_viewed_images(existing: dict[str, ViewedImageData] | None, new: dict[str, ViewedImageData] | None) -> dict[str, ViewedImageData]:
    """Reducer for viewed_images dict - merges image dictionaries.

    Special case: If new is an empty dict {}, it clears the existing images.
    This allows middlewares to clear the viewed_images state after processing.
    """
    if existing is None:
        return new or {}
    if new is None:
        return existing
    # Special case: empty dict means clear all viewed images
    if len(new) == 0:
        return {}
    # Merge dictionaries, new values override existing ones for same keys
    return {**existing, **new}


class ThreadState(AgentState):
    sandbox: NotRequired[SandboxState | None]
    thread_data: NotRequired[ThreadDataState | None]
    title: NotRequired[str | None]
    artifacts: Annotated[list[str], merge_artifacts]
    todos: NotRequired[list | None]
    uploaded_files: NotRequired[list[dict] | None]
    viewed_images: Annotated[dict[str, ViewedImageData], merge_viewed_images]  # image_path -> {base64, mime_type}
