"""Tool policy follows producer evidence, never incidental prose."""

from types import SimpleNamespace

import pytest
from langchain_core.messages import ToolMessage

from deerflow.agents.middlewares.harness_guard_middleware import classify_tool_error
from deerflow.agents.middlewares.tool_progress_middleware import ToolPhaseState, ToolProgressMiddleware
from deerflow.agents.middlewares.tool_result_meta import TOOL_META_KEY, ToolResultMeta, normalize_tool_message, stamp_exception_meta


@pytest.mark.parametrize("text", ["missing required argument: query", "authentication succeeded; file not found", "internal error; retry after one second", "quoted: 401 unauthorized"])
def test_error_prose_cannot_determine_category_or_stop(text):
    msg = normalize_tool_message(ToolMessage(content=text, status="error", tool_call_id="1", name="search"))
    meta = msg.additional_kwargs[TOOL_META_KEY]
    assert meta["status"] == "error"
    assert meta["error_type"] == "unknown"
    assert meta["recoverable_by_model"] is True


@pytest.mark.parametrize(
    ("text", "producer_stamped"),
    [
        ("A guide to no results found", False),
        ("partial results are discussed here", False),
        ("Error: an example from a manual", True),
        ('{"error": {"code": 401}}', False),
    ],
)
def test_document_content_keeps_success(text, producer_stamped):
    kwargs = (
        {
            "additional_kwargs": {
                TOOL_META_KEY: {
                    "status": "success",
                    "error_type": None,
                    "recoverable_by_model": True,
                    "recommended_next_action": "continue",
                    "source": "tool_return",
                }
            }
        }
        if producer_stamped
        else {}
    )
    msg = normalize_tool_message(ToolMessage(content=text, tool_call_id="1", name="read_file", **kwargs))
    assert msg.additional_kwargs[TOOL_META_KEY]["status"] == "success"


def test_typed_exception_wins_over_misleading_description():
    msg = ToolMessage(content="display", tool_call_id="1")
    stamp_exception_meta(msg, TimeoutError("invalid api key in quoted request"))
    assert msg.additional_kwargs[TOOL_META_KEY]["error_type"] == "transient"


def test_http_exception_uses_actual_response_status():
    exc = RuntimeError("timeout")
    exc.response = SimpleNamespace(status_code=401)
    msg = stamp_exception_meta(ToolMessage(content="display", tool_call_id="1"), exc)
    assert msg.additional_kwargs[TOOL_META_KEY]["error_type"] == "auth"


def test_legacy_content_analysis_cannot_block_tool():
    meta = ToolResultMeta(status="error", error_type="auth", recoverable_by_model=False, recommended_next_action="stop", source="content_analysis")
    middleware = ToolProgressMiddleware()
    state = ToolPhaseState()
    for _ in range(12):
        state, _, _ = middleware._assess_and_transition(state, meta, "quoted auth failure")
        assert state.phase != "blocked"


@pytest.mark.parametrize("text", ["ModuleNotFoundError: No module named 'cv2'", "ImportError: cannot import name 'helper' from 'my_project'", "PermissionError: [Errno 13] Permission denied: '/tmp/a'"])
def test_error_observations_do_not_prescribe_mutation(text):
    signature = classify_tool_error(text)
    assert signature is not None
    assert "pip install" not in signature.targeted_hint
    assert "chmod" not in signature.targeted_hint
    assert "Action:" not in signature.targeted_hint
