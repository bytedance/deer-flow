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
    upload_responses: dict | None = None,
    fake_client_cls: type | None = None,
):
    """Build a stack of patches to isolate invoke_workflow from real Dify + config.

    Returns a tuple of (patches, mock_writer, mock_cache, captured) where
    ``captured`` is a dict with ``"uploads"`` (list of upload_file invocations)
    and ``"chat_calls"`` (list of chat-call kwargs) populated by the fake clients.

    Args:
        response_mode: "streaming" or "blocking" — selects the default fake client class.
        upload_responses: Optional mapping of ``file_path -> DifyFileUpload`` that
            ``upload_file`` should return for tests that care about the chat payload.
        fake_client_cls: Optional override for the DifyClient class the router sees
            (e.g. a subclass that raises on upload).
    """
    tool_cfg = MagicMock()
    tool_cfg.api_key = "k"
    tool_cfg.base_url = "http://x"
    tool_cfg.response_mode = response_mode

    captured: dict = {"uploads": [], "chat_calls": []}

    class FakeStreamingClient:
        def __init__(self, api_key, base_url):
            pass

        async def astream_chat(self, query, conversation_id, user, timeout=60.0, inputs=None, files=None):
            captured["chat_calls"].append(
                {
                    "query": query,
                    "conversation_id": conversation_id,
                    "user": user,
                    "inputs": inputs,
                    "files": files,
                }
            )
            if astream_chat_raises is not None:
                raise astream_chat_raises
            for chunk in astream_chat_chunks or []:
                yield chunk

        async def upload_file(self, file_path, user, timeout=60.0):
            captured["uploads"].append({"path": file_path, "user": user})
            from zens.community.dify.dify_client import DifyFileUpload

            if upload_responses and file_path in upload_responses:
                return upload_responses[file_path]
            return DifyFileUpload(id=f"fake-{file_path}", name=file_path, mime_type="application/octet-stream")

    class FakeBlockingClient:
        def __init__(self, api_key, base_url):
            pass

        def chat(self, query, conversation_id, user, timeout=60.0, inputs=None, files=None):
            captured["chat_calls"].append(
                {
                    "query": query,
                    "conversation_id": conversation_id,
                    "user": user,
                    "inputs": inputs,
                    "files": files,
                }
            )
            from zens.community.dify.dify_client import DifyResponse

            return DifyResponse(answer=blocking_answer, conversation_id="cb", message_id="mb")

        async def upload_file(self, file_path, user, timeout=60.0):
            captured["uploads"].append({"path": file_path, "user": user})
            from zens.community.dify.dify_client import DifyFileUpload

            if upload_responses and file_path in upload_responses:
                return upload_responses[file_path]
            return DifyFileUpload(id=f"fake-{file_path}", name=file_path, mime_type="application/octet-stream")

    mock_writer = MagicMock()
    mock_logger = MagicMock()
    mock_cache = MagicMock()

    chosen_cls = fake_client_cls if fake_client_cls is not None else (FakeBlockingClient if response_mode == "blocking" else FakeStreamingClient)

    patches = [
        patch("zens.community.dify.router.DifyClient", chosen_cls),
        patch("zens.community.dify.router.get_stream_writer", return_value=mock_writer),
        patch("zens.community.dify.router._get_tool_config", return_value=tool_cfg),
        patch("zens.community.dify.router._get_cached_conversation", return_value="conv-prev"),
        patch("zens.community.dify.router._cache_conversation", mock_cache),
        patch("zens.community.dify.router._get_workflow_logger", return_value=mock_logger),
        patch("zens.community.dify.router.get_effective_user_id", return_value="u1"),
        patch("zens.community.dify.router.get_current_user", return_value=None),
    ]
    return patches, mock_writer, mock_cache, captured


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
    patches, mock_writer, mock_cache, _ = _patch_router_dependencies(response_mode="streaming", astream_chat_chunks=chunks)

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

    patches, mock_writer, _, _ = _patch_router_dependencies(response_mode="streaming", astream_chat_raises=DifyAPIError(401, "Unauthorized"))

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

    patches, mock_writer, _, _ = _patch_router_dependencies(response_mode="blocking", blocking_answer="blocking answer")

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

    patches, mock_writer, _, _ = _patch_router_dependencies(response_mode="streaming", astream_chat_chunks=[])

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


def test_dify_file_type_mapping():
    """_dify_file_type maps MIME prefixes to Dify file-ref ``type`` values."""
    from zens.community.dify.router import _dify_file_type

    assert _dify_file_type("image/png") == "image"
    assert _dify_file_type("image/jpeg") == "image"
    assert _dify_file_type("audio/mp3") == "audio"
    assert _dify_file_type("audio/ogg") == "audio"
    assert _dify_file_type("video/mp4") == "video"
    assert _dify_file_type("video/quicktime") == "video"
    assert _dify_file_type("application/pdf") == "document"
    assert _dify_file_type("text/plain") == "document"
    assert _dify_file_type("") == "document"
    # case-insensitive
    assert _dify_file_type("IMAGE/PNG") == "image"


def test_invoke_workflow_uploads_and_forwards_files_streaming():
    """files= triggers uploads, then chat payload receives file refs keyed off mime_type."""
    from zens.community.dify import router
    from zens.community.dify.dify_client import DifyFileUpload

    chunks = [DifyChunk(answer="ok", conversation_id="c", message_id="m")]
    upload_responses = {
        "/tmp/a.png": DifyFileUpload(id="id-png", name="a.png", mime_type="image/png"),
        "/tmp/b.pdf": DifyFileUpload(id="id-pdf", name="b.pdf", mime_type="application/pdf"),
    }
    patches, _, _, captured = _patch_router_dependencies(
        response_mode="streaming",
        astream_chat_chunks=chunks,
        upload_responses=upload_responses,
    )

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
        result = _run(
            router.invoke_workflow(
                tool_name="dify_test",
                query="describe",
                config=None,
                files=["/tmp/a.png", "/tmp/b.pdf"],
            )
        )

    assert result == "ok"
    assert [u["path"] for u in captured["uploads"]] == ["/tmp/a.png", "/tmp/b.pdf"]
    assert len(captured["chat_calls"]) == 1
    chat_call = captured["chat_calls"][0]
    assert chat_call["files"] == [
        {"type": "image", "transfer_method": "local_file", "upload_file_id": "id-png"},
        {"type": "document", "transfer_method": "local_file", "upload_file_id": "id-pdf"},
    ]


def test_invoke_workflow_emits_dify_failed_on_upload_error():
    """Upload failure in streaming path emits dify_started + dify_failed and re-raises."""
    from zens.community.dify import router

    class FailingUploadClient:
        def __init__(self, api_key, base_url):
            pass

        async def upload_file(self, file_path, user, timeout=60.0):
            raise DifyAPIError(413, "File too large")

        async def astream_chat(self, query, conversation_id, user, timeout=60.0, inputs=None, files=None):
            # Unreachable — upload raises before chat is called.
            if False:
                yield DifyChunk(answer="", conversation_id="", message_id="")

    patches, mock_writer, _, _ = _patch_router_dependencies(
        response_mode="streaming",
        fake_client_cls=FailingUploadClient,
    )

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
        with pytest.raises(DifyAPIError) as exc_info:
            _run(
                router.invoke_workflow(
                    tool_name="dify_test",
                    query="q",
                    config=None,
                    files=["/tmp/a.png"],
                )
            )

    assert exc_info.value.status_code == 413
    events = [c.args[0] for c in mock_writer.call_args_list]
    types = [e["type"] for e in events]
    # Upload failure still emits the started/failed pair so the UI can render
    # a meaningful failure state instead of a silent exception.
    assert "dify_started" in types
    assert "dify_failed" in types
    failed = next(e for e in events if e["type"] == "dify_failed")
    assert failed == {
        "type": "dify_failed",
        "tool": "dify_test",
        "status_code": 413,
        "message": "File too large",
    }
    assert "dify_completed" not in types
