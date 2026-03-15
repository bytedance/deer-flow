from typing import Annotated, NotRequired, TypedDict

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


class ModelUsageState(TypedDict):
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class UsageSummaryState(TypedDict):
    models: list[ModelUsageState]
    tool_calls: dict[str, int]


class UsageDetailsState(TypedDict):
    lead: UsageSummaryState
    subagent: UsageSummaryState


def _empty_usage_summary() -> UsageSummaryState:
    return {"models": [], "tool_calls": {}}


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


def merge_usage(existing: UsageSummaryState | None, new: UsageSummaryState | None) -> UsageSummaryState:
    """Reducer for usage summary.

    - Aggregates model token usage by model name.
    - Aggregates tool call counters by tool name.
    """
    if existing is None:
        return new or {"models": [], "tool_calls": {}}
    if new is None:
        return existing

    merged_models: dict[str, ModelUsageState] = {}

    for item in existing.get("models", []):
        model_name = str(item.get("model", "unknown"))
        merged_models[model_name] = {
            "model": model_name,
            "prompt_tokens": int(item.get("prompt_tokens", 0)),
            "completion_tokens": int(item.get("completion_tokens", 0)),
            "total_tokens": int(item.get("total_tokens", 0)),
        }

    for item in new.get("models", []):
        model_name = str(item.get("model", "unknown"))
        if model_name not in merged_models:
            merged_models[model_name] = {
                "model": model_name,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            }

        merged_models[model_name]["prompt_tokens"] += int(item.get("prompt_tokens", 0))
        merged_models[model_name]["completion_tokens"] += int(item.get("completion_tokens", 0))
        merged_models[model_name]["total_tokens"] += int(item.get("total_tokens", 0))

    merged_tool_calls: dict[str, int] = {}
    for name, count in existing.get("tool_calls", {}).items():
        merged_tool_calls[str(name)] = int(count)
    for name, count in new.get("tool_calls", {}).items():
        merged_tool_calls[str(name)] = merged_tool_calls.get(str(name), 0) + int(count)

    return {
        "models": sorted(merged_models.values(), key=lambda x: x["model"]),
        "tool_calls": merged_tool_calls,
    }


def merge_usage_details(existing: UsageDetailsState | None, new: UsageDetailsState | None) -> UsageDetailsState:
    """Reducer for usage details split by execution source.

    Aggregates lead and subagent usage independently, each using merge_usage.
    """
    if existing is None:
        existing = {
            "lead": _empty_usage_summary(),
            "subagent": _empty_usage_summary(),
        }
    if new is None:
        return existing

    return {
        "lead": merge_usage(existing.get("lead"), new.get("lead")),
        "subagent": merge_usage(existing.get("subagent"), new.get("subagent")),
    }


class ThreadState(AgentState):
    sandbox: NotRequired[SandboxState | None]
    thread_data: NotRequired[ThreadDataState | None]
    title: NotRequired[str | None]
    artifacts: Annotated[list[str], merge_artifacts]
    todos: NotRequired[list | None]
    uploaded_files: NotRequired[list[dict] | None]
    viewed_images: Annotated[dict[str, ViewedImageData], merge_viewed_images]  # image_path -> {base64, mime_type}
    usage: Annotated[UsageSummaryState, merge_usage]
    usage_details: Annotated[UsageDetailsState, merge_usage_details]
