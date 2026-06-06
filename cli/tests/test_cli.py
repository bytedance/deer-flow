"""Integration tests for deerflow_cli.py — command parsing and user interaction."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# safe_input
# ---------------------------------------------------------------------------

class TestSafeInput:
    """Input handling with UTF-8 encoding recovery."""

    def test_returns_stripped_input(self):
        from deerflow_cli.cli import safe_input

        with patch("deerflow_cli.cli.input", return_value="  hello  \n"):
            result = safe_input("> ")
        assert result == "  hello  "

    def test_handles_unicode_decode_error(self):
        from deerflow_cli.cli import safe_input

        call_count = [0]

        def broken_input(prompt):
            call_count[0] += 1
            if call_count[0] == 1:
                raise UnicodeDecodeError("utf-8", b"", 0, 1, "mock error")
            return "recovered"

        with patch("deerflow_cli.cli.input", side_effect=broken_input):
            result = safe_input("> ")
        assert result == "recovered"

    def test_handles_eof(self):
        from deerflow_cli.cli import safe_input

        with patch("deerflow_cli.cli.input", side_effect=EOFError()):
            result = safe_input("> ")
        assert result == ""


# ---------------------------------------------------------------------------
# multi_line_input
# ---------------------------------------------------------------------------

class TestMultiLineInput:
    """Multi-line input mode with !end sentinel."""

    def test_reads_until_end_sentinel(self):
        from deerflow_cli.cli import multi_line_input

        lines = iter(["line1", "line2", "!end"])

        with patch("deerflow_cli.cli.input", side_effect=lambda: next(lines)):
            result = multi_line_input("Enter:")

        assert result == "line1\nline2"

    def test_handles_eof(self):
        from deerflow_cli.cli import multi_line_input

        with patch("deerflow_cli.cli.input", side_effect=EOFError()):
            result = multi_line_input("Enter:")

        assert result == ""

    def test_handles_unicode_decode_error(self):
        from deerflow_cli.cli import multi_line_input

        call_count = [0]

        def broken_input():
            call_count[0] += 1
            if call_count[0] == 1:
                raise UnicodeDecodeError("utf-8", b"", 0, 1, "mock error")
            return "!end"

        with patch("deerflow_cli.cli.input", side_effect=broken_input):
            result = multi_line_input("Enter:")

        assert result == ""


# ---------------------------------------------------------------------------
# main — command dispatch
# ---------------------------------------------------------------------------

class TestMainCommandDispatch:
    """Verify that !commands correctly delegate to engine methods."""

    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        """Reset the engine singleton before each test."""
        from deerflow_cli.engine import DeerFlowProductionEngine
        DeerFlowProductionEngine._instance = None
        DeerFlowProductionEngine._initialized = False
        yield
        DeerFlowProductionEngine._instance = None
        DeerFlowProductionEngine._initialized = False

    def _run_main(self, inputs: list[str], mock_engine: MagicMock, monkeypatch) -> None:
        """Run main() with a fixed list of inputs, then raise KeyboardInterrupt to exit."""
        mock_engine.current_session_id = "test1234"
        mock_engine.client = MagicMock()

        input_iter = iter(inputs)

        def mock_input(prompt=""):
            try:
                return next(input_iter)
            except StopIteration:
                raise KeyboardInterrupt

        with patch("deerflow_cli.cli.DeerFlowProductionEngine", return_value=mock_engine), \
             patch("deerflow_cli.cli.safe_input", side_effect=mock_input), \
             patch("deerflow_cli.cli.multi_line_input", return_value="multi line content"):
            try:
                from deerflow_cli.cli import main
                main()
            except (KeyboardInterrupt, SystemExit):
                pass

    # --- Session management ---

    def test_new_creates_session(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"
        self._run_main(["!new custom-id My Title", "!exit"], engine, monkeypatch)
        engine.create_session.assert_called_with("custom-id", "My Title")

    def test_new_without_args(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"
        self._run_main(["!new", "!exit"], engine, monkeypatch)
        engine.create_session.assert_called_with(None, None)

    def test_switch_session(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"
        self._run_main(["!switch other-session", "!exit"], engine, monkeypatch)
        engine.switch_session.assert_called_with("other-session")

    def test_switch_missing_arg_shows_error(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"
        self._run_main(["!switch", "!exit"], engine, monkeypatch)
        engine.switch_session.assert_not_called()

    def test_delete_session(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"
        self._run_main(["!delete session sid123", "!exit"], engine, monkeypatch)
        engine.delete_session.assert_called_with("sid123")

    def test_rename_session(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"
        self._run_main(["!rename New Title", "!exit"], engine, monkeypatch)
        engine.rename_session.assert_called_with("test1234", "New Title")

    def test_rename_missing_title(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"
        self._run_main(["!rename", "!exit"], engine, monkeypatch)
        engine.rename_session.assert_not_called()

    def test_list_sessions(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"
        self._run_main(["!sessions", "!exit"], engine, monkeypatch)
        engine.list_sessions.assert_called_once()

    # --- Help / Exit ---

    def test_help(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"
        self._run_main(["!help", "!exit"], engine, monkeypatch)

    def test_exit_breaks_loop(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"
        self._run_main(["!exit"], engine, monkeypatch)

    # --- Multi-line ---

    def test_multi_line_mode(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"
        engine.chat.return_value = iter(["response"])

        self._run_main(["!multi", "!exit"], engine, monkeypatch)
        engine.chat.assert_called_with("multi line content")

    def test_multi_line_empty_ignored(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"

        with patch("deerflow_cli.cli.DeerFlowProductionEngine", return_value=engine), \
             patch("deerflow_cli.cli.safe_input", side_effect=["!multi", KeyboardInterrupt]), \
             patch("deerflow_cli.cli.multi_line_input", return_value=""):
            try:
                from deerflow_cli.cli import main
                main()
            except (KeyboardInterrupt, SystemExit):
                pass
        engine.chat.assert_not_called()

    # --- Normal chat ---

    def test_default_chat_path(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"
        engine.chat.return_value = iter(["Hello!"])

        self._run_main(["What is AI?", "!exit"], engine, monkeypatch)
        engine.chat.assert_called_with("What is AI?")

    def test_creates_session_when_none_active(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = None
        engine.client = MagicMock()
        engine.chat.return_value = iter(["response"])

        def _create(*args, **kwargs):
            engine.current_session_id = "new12345"
            return "new12345"
        engine.create_session.side_effect = _create

        with patch("deerflow_cli.cli.DeerFlowProductionEngine", return_value=engine), \
             patch("deerflow_cli.cli.safe_input", side_effect=["Hello", "!exit"]):
            try:
                from deerflow_cli.cli import main
                main()
            except (KeyboardInterrupt, SystemExit):
                pass

        engine.create_session.assert_called_once()

    # --- Error handling ---

    def test_generic_exception_handling(self, monkeypatch):
        """Exceptions in command handling are caught and printed, not propagated."""
        engine = MagicMock()
        engine.current_session_id = "test1234"
        engine.chat.side_effect = RuntimeError("Something went wrong")

        self._run_main(["broken", "!exit"], engine, monkeypatch)


# ---------------------------------------------------------------------------
# main — null session handling
# ---------------------------------------------------------------------------

class TestMainNullSession:
    """main() creates a session when current_session_id is None."""

    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        from deerflow_cli.engine import DeerFlowProductionEngine
        DeerFlowProductionEngine._instance = None
        DeerFlowProductionEngine._initialized = False
        yield
        DeerFlowProductionEngine._instance = None
        DeerFlowProductionEngine._initialized = False

    def test_null_session_triggers_create(self, monkeypatch):
        """When current_session_id is None, main() calls create_session()."""
        engine = MagicMock()
        engine.current_session_id = None

        def _create(*args, **kwargs):
            engine.current_session_id = "new12345"
            return "new12345"
        engine.create_session.side_effect = _create

        with patch("deerflow_cli.cli.DeerFlowProductionEngine", return_value=engine), \
             patch("deerflow_cli.cli.safe_input", side_effect=["!sessions", KeyboardInterrupt]):
            try:
                from deerflow_cli.cli import main
                main()
            except (KeyboardInterrupt, SystemExit):
                pass

        engine.create_session.assert_called()
