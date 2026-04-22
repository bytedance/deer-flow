"""App-owned request adapter for runs entrypoints."""

from __future__ import annotations

from dataclasses import dataclass

from deerflow.runtime.stream_bridge import JSONValue
from deerflow.runtime.runs.types import RunIntent

type RequestBody = dict[str, JSONValue]
type RequestQuery = dict[str, str]


@dataclass(frozen=True)
class AdaptedRunRequest:
    """
    统一的内部请求 DTO.

    路由层只负责提取 path/query/body，适配器负责转成稳定内部结构。
    """

    intent: RunIntent
    thread_id: str | None
    run_id: str | None
    body: RequestBody
    headers: dict[str, str]
    query: RequestQuery

    @property
    def last_event_id(self) -> str | None:
        """Extract Last-Event-ID from headers."""
        return self.headers.get("last-event-id") or self.headers.get("Last-Event-ID")

    @property
    def is_stateless(self) -> bool:
        """Check if this is a stateless request."""
        return self.thread_id is None


def adapt_create_run_request(
    *,
    thread_id: str | None,
    body: RequestBody,
    headers: dict[str, str] | None = None,
    query: RequestQuery | None = None,
) -> AdaptedRunRequest:
    """Adapt POST /threads/{thread_id}/runs or POST /runs."""
    return AdaptedRunRequest(
        intent="create_background",
        thread_id=thread_id,
        run_id=None,
        body=body,
        headers=headers or {},
        query=query or {},
    )


def adapt_create_stream_request(
    *,
    thread_id: str | None,
    body: RequestBody,
    headers: dict[str, str] | None = None,
    query: RequestQuery | None = None,
) -> AdaptedRunRequest:
    """Adapt POST /threads/{thread_id}/runs/stream or POST /runs/stream."""
    return AdaptedRunRequest(
        intent="create_and_stream",
        thread_id=thread_id,
        run_id=None,
        body=body,
        headers=headers or {},
        query=query or {},
    )


def adapt_create_wait_request(
    *,
    thread_id: str | None,
    body: RequestBody,
    headers: dict[str, str] | None = None,
    query: RequestQuery | None = None,
) -> AdaptedRunRequest:
    """Adapt POST /threads/{thread_id}/runs/wait or POST /runs/wait."""
    return AdaptedRunRequest(
        intent="create_and_wait",
        thread_id=thread_id,
        run_id=None,
        body=body,
        headers=headers or {},
        query=query or {},
    )


def adapt_join_stream_request(
    *,
    thread_id: str,
    run_id: str,
    headers: dict[str, str] | None = None,
    query: RequestQuery | None = None,
) -> AdaptedRunRequest:
    """Adapt GET /threads/{thread_id}/runs/{run_id}/stream."""
    return AdaptedRunRequest(
        intent="join_stream",
        thread_id=thread_id,
        run_id=run_id,
        body={},
        headers=headers or {},
        query=query or {},
    )


def adapt_join_wait_request(
    *,
    thread_id: str,
    run_id: str,
    headers: dict[str, str] | None = None,
    query: RequestQuery | None = None,
) -> AdaptedRunRequest:
    """Adapt GET /threads/{thread_id}/runs/{run_id}/join."""
    return AdaptedRunRequest(
        intent="join_wait",
        thread_id=thread_id,
        run_id=run_id,
        body={},
        headers=headers or {},
        query=query or {},
    )
