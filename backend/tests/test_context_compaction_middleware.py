from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from deerflow.agents.middlewares.context_compaction_middleware import (
    ContextCompactionMiddleware,
    build_compacted_messages,
)
from deerflow.config.context_management_config import (
    ContextManagementConfig,
    MicrocompactConfig,
    SessionStateConfig,
    SnipConfig,
    set_context_management_config,
)


@pytest.fixture(autouse=True)
def _reset_context_management_config():
    set_context_management_config(ContextManagementConfig())
    yield
    set_context_management_config(ContextManagementConfig())


def test_build_compacted_messages_strips_old_uploaded_files_block_only():
    messages = [
        HumanMessage(
            content="<uploaded_files>\n- file.txt\n</uploaded_files>\n\nPlease inspect this file."
        ),
        AIMessage(content="I will inspect it."),
        HumanMessage(content="<uploaded_files>\n- newer.txt\n</uploaded_files>\n\nUse the latest upload."),
    ]

    patched = build_compacted_messages(messages)

    assert patched is not None
    assert patched[0].content == "Please inspect this file."
    assert patched[2].content.startswith("<uploaded_files>")


def test_build_compacted_messages_replaces_upload_only_turn_with_placeholder():
    messages = [
        HumanMessage(content="<uploaded_files>\n- file.txt\n</uploaded_files>\n"),
        AIMessage(content="Received."),
        HumanMessage(content="Work on the latest file."),
    ]

    patched = build_compacted_messages(messages)

    assert patched is not None
    assert "Earlier uploaded file listing omitted" in patched[0].content


def test_build_compacted_messages_microcompacts_old_large_tool_results():
    set_context_management_config(
        ContextManagementConfig(
            microcompact=MicrocompactConfig(
                enabled=True,
                compactable_tools=["bash", "read_file"],
                keep_recent_tool_results=1,
                min_content_chars=10,
            )
        )
    )
    messages = [
        AIMessage(content="", tool_calls=[{"name": "bash", "id": "call-1", "args": {}}]),
        ToolMessage(content="x" * 100, tool_call_id="call-1", name="bash"),
        AIMessage(content="", tool_calls=[{"name": "bash", "id": "call-2", "args": {}}]),
        ToolMessage(content="y" * 100, tool_call_id="call-2", name="bash"),
    ]

    patched = build_compacted_messages(messages)

    assert patched is not None
    assert "Older bash result omitted" in patched[1].content
    assert patched[3].content == "y" * 100


def test_build_compacted_messages_microcompacts_old_x_reader_results():
    set_context_management_config(
        ContextManagementConfig(
            microcompact=MicrocompactConfig(
                enabled=True,
                compactable_tools=["x-reader_read_url"],
                keep_recent_tool_results=1,
                min_content_chars=10,
            )
        )
    )
    messages = [
        AIMessage(content="", tool_calls=[{"name": "x-reader_read_url", "id": "call-1", "args": {}}]),
        ToolMessage(content="a" * 120, tool_call_id="call-1", name="x-reader_read_url"),
        AIMessage(content="", tool_calls=[{"name": "x-reader_read_url", "id": "call-2", "args": {}}]),
        ToolMessage(content="b" * 120, tool_call_id="call-2", name="x-reader_read_url"),
    ]

    patched = build_compacted_messages(messages)

    assert patched is not None
    assert "Older x-reader_read_url result omitted" in patched[1].content
    assert patched[3].content == "b" * 120


def test_build_compacted_messages_leaves_recent_or_small_results_untouched():
    set_context_management_config(
        ContextManagementConfig(
            microcompact=MicrocompactConfig(
                enabled=True,
                compactable_tools=["bash"],
                keep_recent_tool_results=2,
                min_content_chars=50,
            )
        )
    )
    messages = [
        ToolMessage(content="small", tool_call_id="call-1", name="bash"),
        ToolMessage(content="still small", tool_call_id="call-2", name="bash"),
    ]

    assert build_compacted_messages(messages) is None


def test_build_compacted_messages_collapses_older_session_history():
    set_context_management_config(
        ContextManagementConfig(
            snip=SnipConfig(enabled=False),
            microcompact=MicrocompactConfig(enabled=False),
            session_state=SessionStateConfig(
                enabled=True,
                collapse_enabled=True,
                collapse_when_message_count_at_least=8,
                keep_recent_messages=4,
                max_tool_observations=2,
                max_tool_observation_chars=80,
            ),
        )
    )
    messages = [
        HumanMessage(content="Investigate the parser failure in the imported repo."),
        AIMessage(content="Starting investigation."),
        AIMessage(content="", tool_calls=[{"name": "web_search", "id": "ws-1", "args": {}}]),
        ToolMessage(content="Result one " * 20, tool_call_id="ws-1", name="web_search"),
        AIMessage(content="The issue may be in parser.py."),
        AIMessage(content="", tool_calls=[{"name": "web_fetch", "id": "wf-1", "args": {}}]),
        ToolMessage(content="Fetched article " * 20, tool_call_id="wf-1", name="web_fetch"),
        HumanMessage(content="Continue and prepare the fix."),
        AIMessage(content="I am narrowing the fallback branch."),
    ]

    patched = build_compacted_messages(messages)

    assert patched is not None
    assert isinstance(patched[0], HumanMessage)
    assert "<session_history_summary>" in patched[0].content
    assert "web_search" in patched[0].content
    assert patched[-1].content == "I am narrowing the fallback branch."


def test_build_compacted_messages_keeps_tool_pair_boundary_when_collapsing():
    set_context_management_config(
        ContextManagementConfig(
            snip=SnipConfig(enabled=False),
            microcompact=MicrocompactConfig(enabled=False),
            session_state=SessionStateConfig(
                enabled=True,
                collapse_enabled=True,
                collapse_when_message_count_at_least=7,
                keep_recent_messages=4,
            ),
        )
    )
    messages = [
        HumanMessage(content="Start"),
        AIMessage(content="Middle"),
        HumanMessage(content="Need more info"),
        AIMessage(content="", tool_calls=[{"name": "web_search", "id": "ws-1", "args": {}}]),
        ToolMessage(content="search result body " * 10, tool_call_id="ws-1", name="web_search"),
        AIMessage(content="Post tool reasoning"),
        HumanMessage(content="Latest request"),
    ]

    patched = build_compacted_messages(messages)

    assert patched is not None
    tool_call_message = next(msg for msg in patched if isinstance(msg, AIMessage) and msg.tool_calls)
    assert tool_call_message.tool_calls[0]["id"] == "ws-1"
    tool_result = next(msg for msg in patched if isinstance(msg, ToolMessage))
    assert tool_result.tool_call_id == "ws-1"


def test_wrap_model_call_forwards_patched_messages():
    set_context_management_config(
        ContextManagementConfig(
            snip=SnipConfig(enabled=True, strip_historical_upload_blocks=True),
            microcompact=MicrocompactConfig(enabled=False),
        )
    )
    middleware = ContextCompactionMiddleware()
    request = MagicMock()
    request.messages = [
        HumanMessage(content="<uploaded_files>\n- file.txt\n</uploaded_files>\n\nInspect."),
        AIMessage(content="ok"),
        HumanMessage(content="latest"),
    ]
    patched_request = MagicMock()
    request.override.return_value = patched_request
    handler = MagicMock(return_value="response")

    result = middleware.wrap_model_call(request, handler)

    request.override.assert_called_once()
    passed_messages = request.override.call_args.kwargs["messages"]
    assert passed_messages[0].content == "Inspect."
    handler.assert_called_once_with(patched_request)
    assert result == "response"


@pytest.mark.anyio
async def test_awrap_model_call_passthrough_when_no_changes():
    set_context_management_config(
        ContextManagementConfig(
            snip=SnipConfig(enabled=False),
            microcompact=MicrocompactConfig(enabled=False),
        )
    )
    middleware = ContextCompactionMiddleware()
    request = MagicMock()
    request.messages = [HumanMessage(content="plain message")]
    handler = AsyncMock(return_value="response")

    result = await middleware.awrap_model_call(request, handler)

    request.override.assert_not_called()
    handler.assert_called_once_with(request)
    assert result == "response"
