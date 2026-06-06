"""Tests for router.invoke_workflow's dify_* event emission in streaming mode."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from zens.community.dify.dify_client import DifyAPIError, DifyChunk

# ── helpers ──────────────────────────────────────────────────────────────


def _patch_router_dependencies(
    *,
    response_mode: str = "streaming",
    astream_chat_chunks: list[DifyChunk] | None = None,
    astream_chat_raises: Exception | None = None,
    blocking_answer: str = "blocking answer",
):
    """Build a stack of patches to isolate invoke_workflow from real Dify + config.

    Returns a list of patch objects the caller must use as a context manager.
    """
    tool_cfg = MagicMock()
    tool_cfg.api_key = "k"
    tool_cfg.base_url = "http://x"
    tool_cfg.response_mode = response_mode

    class FakeStreamingClient:
        def __init__(self, api_key, base_url):
            pass

        async def astream_chat(self, query, conversation_id, user, timeout=60.0):
            if astream_chat_raises is not None:
                raise astream_chat_raises
            for chunk in astream_chat_chunks or []:
                yield chunk

    class FakeBlockingClient:
        def __init__(self, api_key, base_url):
            pass

        def chat(self, query, conversation_id, user, timeout=60.0):
            from zens.community.dify.dify_client import DifyResponse

            return DifyResponse(answer=blocking_answer, conversation_id="cb", message_id="mb")

    mock_writer = MagicMock()
    mock_logger = MagicMock()
    mock_cache = MagicMock()

    fake_client_cls = FakeBlockingClient if response_mode == "blocking" else FakeStreamingClient

    patches = [
        patch("zens.community.dify.router.DifyClient", fake_client_cls),
        patch("zens.community.dify.router.get_stream_writer", return_value=mock_writer),
        patch("zens.community.dify.router._get_tool_config", return_value=tool_cfg),
        patch("zens.community.dify.router._get_cached_conversation", return_value="conv-prev"),
        patch("zens.community.dify.router._cache_conversation", mock_cache),
        patch("zens.community.dify.router._get_workflow_logger", return_value=mock_logger),
        patch("zens.community.dify.router.get_effective_user_id", return_value="u1"),
        patch("zens.community.dify.router.get_current_user", return_value=None),
    ]
    return patches, mock_writer, mock_cache


def _run(coro):
    return asyncio.run(coro)


# ── tests ────────────────────────────────────────────────────────────────


def test_invoke_workflow_streaming_emits_started_chunk_completed():
    """Streaming path pushes dify_started → dify_chunk (per chunk) → dify_completed."""
    from zens.community.dify import router

    chunks = [
        DifyChunk(answer="Hel", conversation_id="conv-z", message_id="m1"),
        DifyChunk(answer="lo", conversation_id="conv-z", message_id="m2"),
    ]
    patches, mock_writer, mock_cache = _patch_router_dependencies(response_mode="streaming", astream_chat_chunks=chunks)

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
        result = _run(
            router.invoke_workflow(
                tool_name="dify_test",
                query="hello",
                config={"configurable": {"thread_id": "t1"}},
            )
        )

    assert result == "Hello"
    events = [c.args[0] for c in mock_writer.call_args_list]
    types = [e["type"] for e in events]
    assert types == ["dify_started", "dify_chunk", "dify_chunk", "dify_completed"]
    assert events[0] == {"type": "dify_started", "tool": "dify_test", "query_len": 5}
    assert events[1] == {"type": "dify_chunk", "tool": "dify_test", "delta": "Hel", "index": 0}
    assert events[2] == {"type": "dify_chunk", "tool": "dify_test", "delta": "lo", "index": 1}
    assert events[3] == {
        "type": "dify_completed",
        "tool": "dify_test",
        "total_len": 5,
        "conversation_id": "conv-z",
    }
    mock_cache.assert_called_once_with("u1:t1:dify_test", "conv-z")


def test_invoke_workflow_streaming_emits_failed_and_reraises():
    """astream_chat raising DifyAPIError → dify_failed event + re-raise."""
    from zens.community.dify import router

    patches, mock_writer, _ = _patch_router_dependencies(response_mode="streaming", astream_chat_raises=DifyAPIError(401, "Unauthorized"))

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
        with pytest.raises(DifyAPIError) as exc_info:
            _run(
                router.invoke_workflow(
                    tool_name="dify_test",
                    query="hi",
                    config=None,
                )
            )
    assert exc_info.value.status_code == 401

    events = [c.args[0] for c in mock_writer.call_args_list]
    types = [e["type"] for e in events]
    assert "dify_started" in types
    assert "dify_failed" in types
    failed = next(e for e in events if e["type"] == "dify_failed")
    assert failed == {
        "type": "dify_failed",
        "tool": "dify_test",
        "status_code": 401,
        "message": "Unauthorized",
    }
    # No dify_completed when an error happened
    assert "dify_completed" not in types


def test_invoke_workflow_blocking_emits_no_events():
    """Blocking path returns full answer with zero get_stream_writer calls."""
    from zens.community.dify import router

    patches, mock_writer, _ = _patch_router_dependencies(response_mode="blocking", blocking_answer="blocking answer")

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
        result = _run(
            router.invoke_workflow(
                tool_name="dify_test",
                query="q",
                config=None,
            )
        )

    assert result == "blocking answer"
    mock_writer.assert_not_called()


def test_invoke_workflow_streaming_omits_completed_when_no_chunks():
    """If astream_chat yields nothing, we still emit dify_completed with total_len=0."""
    from zens.community.dify import router

    patches, mock_writer, _ = _patch_router_dependencies(response_mode="streaming", astream_chat_chunks=[])

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
        result = _run(
            router.invoke_workflow(
                tool_name="dify_test",
                query="q",
                config=None,
            )
        )

    assert result == ""
    events = [c.args[0] for c in mock_writer.call_args_list]
    types = [e["type"] for e in events]
    assert types == ["dify_started", "dify_completed"]
    completed = next(e for e in events if e["type"] == "dify_completed")
    assert completed["total_len"] == 0
    assert completed["conversation_id"] == ""
