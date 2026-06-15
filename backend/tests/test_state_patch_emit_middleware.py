"""Tests for StatePatchEmitMiddleware."""

from unittest.mock import MagicMock, patch

import pytest

from deerflow.agents.middlewares.state_patch_emit_middleware import (
    _TRACKED_FIELDS,
    StatePatchEmitMiddleware,
)


@pytest.fixture
def middleware() -> StatePatchEmitMiddleware:
    return StatePatchEmitMiddleware()


def _mock_writer() -> MagicMock:
    writer = MagicMock()
    return writer


_WRITER_PATCH = "langgraph.config.get_stream_writer"


class TestStatePatchEmitMiddleware:
    def test_tracked_fields_are_correct(self):
        assert _TRACKED_FIELDS == ("title", "todos", "artifacts")

    def test_emits_patch_when_title_changes(self, middleware: StatePatchEmitMiddleware):
        writer = _mock_writer()
        state = {"title": "New Title"}

        with patch(_WRITER_PATCH, return_value=writer):
            result = middleware.after_model(state, MagicMock())

        assert result is None
        writer.assert_called_once_with({"type": "state_patch", "patch": {"title": "New Title"}})

    def test_emits_patch_when_todos_changes(self, middleware: StatePatchEmitMiddleware):
        writer = _mock_writer()
        state = {"todos": [{"content": "Task 1", "status": "pending"}]}

        with patch(_WRITER_PATCH, return_value=writer):
            middleware.after_model(state, MagicMock())

        writer.assert_called_once_with({"type": "state_patch", "patch": {"todos": [{"content": "Task 1", "status": "pending"}]}})

    def test_emits_patch_when_artifacts_changes(self, middleware: StatePatchEmitMiddleware):
        writer = _mock_writer()
        state = {"artifacts": ["file1.md"]}

        with patch(_WRITER_PATCH, return_value=writer):
            middleware.after_model(state, MagicMock())

        writer.assert_called_once_with({"type": "state_patch", "patch": {"artifacts": ["file1.md"]}})

    def test_no_emit_when_no_tracked_fields_change(self, middleware: StatePatchEmitMiddleware):
        writer = _mock_writer()
        middleware._last_emitted = {"title": "Same Title"}
        state = {"title": "Same Title", "messages": []}

        with patch(_WRITER_PATCH, return_value=writer):
            middleware.after_model(state, MagicMock())

        writer.assert_not_called()

    def test_no_emit_when_state_unchanged_between_calls(self, middleware: StatePatchEmitMiddleware):
        writer = _mock_writer()
        state = {"title": "Same Title", "todos": [{"content": "Task 1", "status": "done"}]}

        with patch(_WRITER_PATCH, return_value=writer):
            middleware.after_model(state, MagicMock())

        assert writer.call_count == 2

        writer.reset_mock()
        with patch(_WRITER_PATCH, return_value=writer):
            middleware.after_model(state, MagicMock())

        writer.assert_not_called()

    def test_emits_multiple_patches_for_multiple_field_changes(self, middleware: StatePatchEmitMiddleware):
        writer = _mock_writer()
        state = {"title": "New Title", "todos": [{"content": "Task 1", "status": "pending"}]}

        with patch(_WRITER_PATCH, return_value=writer):
            middleware.after_model(state, MagicMock())

        assert writer.call_count == 2
        calls = [call.args[0] for call in writer.call_args_list]
        assert {"type": "state_patch", "patch": {"title": "New Title"}} in calls
        assert {"type": "state_patch", "patch": {"todos": [{"content": "Task 1", "status": "pending"}]}} in calls

    def test_returns_none_never_modifies_state(self, middleware: StatePatchEmitMiddleware):
        writer = _mock_writer()
        state = {"title": "New Title"}

        with patch(_WRITER_PATCH, return_value=writer):
            result = middleware.after_model(state, MagicMock())

        assert result is None

    def test_handles_missing_stream_writer_gracefully(self, middleware: StatePatchEmitMiddleware):
        state = {"title": "New Title"}

        with patch(_WRITER_PATCH, side_effect=RuntimeError("no writer")):
            result = middleware.after_model(state, MagicMock())

        assert result is None

    @pytest.mark.anyio
    async def test_async_after_model_emits_patches(self, middleware: StatePatchEmitMiddleware):
        writer = _mock_writer()
        state = {"title": "Async Title"}

        with patch(_WRITER_PATCH, return_value=writer):
            result = await middleware.aafter_model(state, MagicMock())

        assert result is None
        writer.assert_called_once_with({"type": "state_patch", "patch": {"title": "Async Title"}})
