from typing import Annotated, Any, NotRequired, TypedDict

from langchain.agents import AgentState


class SandboxState(TypedDict):
    sandbox_id: NotRequired[str | None]


class ThreadDataState(TypedDict):
    workspace_path: NotRequired[str | None]
    uploads_path: NotRequired[str | None]
    outputs_path: NotRequired[str | None]


class ViewedImageData(TypedDict):
    base64: str
    mime_type: str


class TokenUsageState(TypedDict):
    input_tokens: int
    output_tokens: int


class SubagentTrajectoryState(TypedDict, total=False):
    task_id: str
    subagent_type: str
    description: str
    prompt: str
    status: str
    result: str | None
    error: str | None
    started_at: str | None
    completed_at: str | None
    token_usage: TokenUsageState
    messages: list[dict[str, Any]]


def merge_token_usage(existing: TokenUsageState | None, new: TokenUsageState | None) -> TokenUsageState:
    """Accumulates token counts across model calls and turns."""
    if existing is None:
        return new or {"input_tokens": 0, "output_tokens": 0}
    if new is None:
        return existing
    return {
        "input_tokens": existing.get("input_tokens", 0) + new.get("input_tokens", 0),
        "output_tokens": existing.get("output_tokens", 0) + new.get("output_tokens", 0),
    }


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


def merge_subagent_trajectories(
    existing: dict[str, SubagentTrajectoryState] | None,
    new: dict[str, SubagentTrajectoryState] | None,
) -> dict[str, SubagentTrajectoryState]:
    """Reducer for subagent trajectories keyed by task_id.

    New entries overwrite existing task IDs and preserve all other records.
    """
    if existing is None:
        return new or {}
    if new is None:
        return existing
    return {**existing, **new}


class ThreadState(AgentState):
    sandbox: NotRequired[SandboxState | None]
    thread_data: NotRequired[ThreadDataState | None]
    title: NotRequired[str | None]
    artifacts: Annotated[list[str], merge_artifacts]
    todos: NotRequired[list | None]
    uploaded_files: NotRequired[list[dict] | None]
    viewed_images: Annotated[dict[str, ViewedImageData], merge_viewed_images]  # image_path -> {base64, mime_type}
    token_usage: Annotated[TokenUsageState, merge_token_usage]
    subagent_trajectories: Annotated[dict[str, SubagentTrajectoryState], merge_subagent_trajectories]
