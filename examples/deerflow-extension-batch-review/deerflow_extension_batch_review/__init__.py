"""Optional browser consumer; no private host imports, storage or provider calls."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from deerflow_extension_api import ExtensionRegistry, extension
from deerflow_extension_api.batch_results import BatchResultError, BatchResultReader
from deerflow_extension_api.plugins import (
    ActionContext,
    BackendAction,
    BrowserAssets,
    PluginContribution,
)


def _payload(payload: Mapping[str, Any], required: tuple[str, ...], optional: tuple[str, ...] = ()) -> None:
    if not isinstance(payload, dict) and not hasattr(payload, "keys"):
        raise ValueError("Expected a request object")
    if not set(required) <= set(payload) or set(payload) - set(required) - set(optional):
        raise ValueError("Unexpected result request fields")


def _reader(context: ActionContext) -> BatchResultReader:
    if context.batch_results is None:
        raise BatchResultError(503, "This host does not provide batch result inspection")
    return context.batch_results()


async def batches(payload: Mapping[str, Any], context: ActionContext) -> list[dict[str, Any]]:
    _payload(payload, ("thread_id",))
    return await _reader(context).list_batches(thread_id=payload["thread_id"])


async def items(payload: Mapping[str, Any], context: ActionContext) -> list[dict[str, Any]]:
    _payload(payload, ("thread_id", "batch_id"), ("offset",))
    rows = await _reader(context).list_items(
        thread_id=payload["thread_id"],
        batch_id=payload["batch_id"],
        offset=payload.get("offset", 0),
    )
    if rows is None:
        raise BatchResultError(404, "Batch results are unavailable")
    return rows


async def result(payload: Mapping[str, Any], context: ActionContext) -> dict[str, Any]:
    _payload(payload, ("thread_id", "batch_id", "position"))
    item = await _reader(context).read_item(
        thread_id=payload["thread_id"],
        batch_id=payload["batch_id"],
        position=payload["position"],
    )
    if item is None:
        raise BatchResultError(404, "Batch results are unavailable")
    return item


@extension(api="0.2.6", name="batch-review")
def install(registry: ExtensionRegistry, config: Mapping[str, Any]) -> None:
    enabled = config.get("enabled", False)
    if type(enabled) is not bool:
        raise ValueError("enabled must be a deployment-owned boolean")
    accepted = registry.plugin(
        PluginContribution(
            namespace="community.batch-review",
            title="批任务结果审阅 / Batch result review",
            description="Inspect saved reports, acceptance and original captured excerpts. Read-only; never refetches a provider.",
            enabled=enabled,
            frontend=BrowserAssets("batch-review.v1", Path(__file__).parent),
            backend=(
                BackendAction("batches", batches),
                BackendAction("items", items),
                BackendAction("result", result),
            ),
        )
    )
    if accepted is not True:
        raise RuntimeError("Batch review requires a full-stack plugin host")
