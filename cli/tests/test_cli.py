"""Integration tests for cli.py — command parsing and user interaction."""

from __future__ import annotations

import io
import sys
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# safe_input
# ---------------------------------------------------------------------------

class TestSafeInput:
    """Input handling with UTF-8 encoding recovery."""

    def test_returns_stripped_input(self):
        from cli.cli import safe_input

        with patch("cli.cli.input", return_value="  hello  \n"):
            result = safe_input("> ")
        assert result == "  hello  "

    def test_handles_unicode_decode_error(self):
        from cli.cli import safe_input

        call_count = [0]

        def broken_input(prompt):
            call_count[0] += 1
            if call_count[0] == 1:
                raise UnicodeDecodeError("utf-8", b"", 0, 1, "mock error")
            return "recovered"

        with patch("cli.cli.input", side_effect=broken_input):
            result = safe_input("> ")
        assert result == "recovered"

    def test_handles_eof(self):
        from cli.cli import safe_input

        with patch("cli.cli.input", side_effect=EOFError()):
            result = safe_input("> ")
        assert result == ""


# ---------------------------------------------------------------------------
# multi_line_input
# ---------------------------------------------------------------------------

class TestMultiLineInput:
    """Multi-line input mode with !end sentinel."""

    def test_reads_until_end_sentinel(self):
        from cli.cli import multi_line_input

        lines = iter(["line1", "line2", "!end"])

        with patch("cli.cli.input", side_effect=lambda: next(lines)):
            result = multi_line_input("Enter:")

        assert result == "line1\nline2"

    def test_handles_eof(self):
        from cli.cli import multi_line_input

        with patch("cli.cli.input", side_effect=EOFError()):
            result = multi_line_input("Enter:")

        assert result == ""

    def test_handles_unicode_decode_error(self):
        from cli.cli import multi_line_input

        call_count = [0]

        def broken_input():
            call_count[0] += 1
            if call_count[0] == 1:
                raise UnicodeDecodeError("utf-8", b"", 0, 1, "mock error")
            return "!end"

        with patch("cli.cli.input", side_effect=broken_input):
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
        from engine import DeerFlowProductionEngine
        DeerFlowProductionEngine._instance = None
        DeerFlowProductionEngine._initialized = False
        yield
        DeerFlowProductionEngine._instance = None
        DeerFlowProductionEngine._initialized = False

    def _run_main(self, inputs: list[str], mock_engine: MagicMock, monkeypatch) -> None:
        """Run main() with a fixed list of inputs, then raise KeyboardInterrupt to exit."""
        mock_engine.current_session_id = "test1234"
        mock_engine.client = MagicMock()
        mock_engine.client._model_name = "opus"
        mock_engine.client.list_models.return_value = {"models": [{"name": "opus", "display_name": "Opus", "supports_thinking": True}]}
        mock_engine.client.list_skills.return_value = {"skills": [{"name": "coding", "category": "dev", "enabled": True}]}
        mock_engine.client.get_memory.return_value = {"facts": []}
        mock_engine.list_uploads.return_value = {"count": 0, "files": []}

        input_iter = iter(inputs)

        def mock_input(prompt=""):
            try:
                return next(input_iter)
            except StopIteration:
                raise KeyboardInterrupt

        with patch("cli.cli.DeerFlowProductionEngine", return_value=mock_engine), \
             patch("cli.cli.safe_input", side_effect=mock_input), \
             patch("cli.cli.multi_line_input", return_value="multi line content"):
            try:
                from cli.cli import main
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

    def test_archive_session(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"
        self._run_main(["!archive sid123", "!exit"], engine, monkeypatch)
        engine.archive_session.assert_called_with("sid123")

    def test_list_archives(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"
        self._run_main(["!archives", "!exit"], engine, monkeypatch)
        engine.list_archives.assert_called_once()

    def test_restore_archive(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"
        self._run_main(["!restore sid123", "!exit"], engine, monkeypatch)
        engine.restore_archive.assert_called_with("sid123")

    def test_list_sessions(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"
        self._run_main(["!sessions", "!exit"], engine, monkeypatch)
        engine.list_sessions.assert_called_once()

    # --- Export ---

    def test_export_session(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"
        self._run_main(["!export", "!exit"], engine, monkeypatch)
        engine.export_session_markdown.assert_called_once()

    def test_export_all_checkpoints(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"
        self._run_main(["!export_all", "!exit"], engine, monkeypatch)
        engine.export_all_checkpoints.assert_called_once()

    # --- Search ---

    def test_search(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"
        self._run_main(["!search keyword", "!exit"], engine, monkeypatch)
        engine.search_sessions.assert_called_with("keyword")

    def test_search_missing_keyword(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"
        self._run_main(["!search", "!exit"], engine, monkeypatch)
        engine.search_sessions.assert_not_called()

    # --- Debugging ---

    def test_steps(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"
        engine.get_session_steps.return_value = [
            {"step": 1, "user_input": "Hello world this is a longer message for truncation test"},
        ]
        self._run_main(["!steps", "!exit"], engine, monkeypatch)
        engine.get_session_steps.assert_called_once()

    def test_steps_all(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"
        engine.get_all_checkpoint_steps.return_value = [
            {"checkpoint_id": "abc12345xx", "ts": "2024-01-01", "has_new_content": True},
        ]
        self._run_main(["!steps_all", "!exit"], engine, monkeypatch)
        engine.get_all_checkpoint_steps.assert_called_once()

    # --- File management ---

    def test_upload_file(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"
        self._run_main(["!upload /path/to/file.txt", "!exit"], engine, monkeypatch)
        engine.upload_file.assert_called_with("/path/to/file.txt")

    def test_list_files(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"
        self._run_main(["!files", "!exit"], engine, monkeypatch)
        engine.list_uploads.assert_called_once()

    def test_delete_file(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"
        self._run_main(["!delete myfile.txt", "!exit"], engine, monkeypatch)
        engine.delete_upload.assert_called_with("myfile.txt")

    # --- Models & skills ---

    def test_list_models(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"
        self._run_main(["!models", "!exit"], engine, monkeypatch)
        engine.client.list_models.assert_called_once()

    def test_use_model(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"
        self._run_main(["!use sonnet", "!exit"], engine, monkeypatch)
        engine.switch_model.assert_called_with("sonnet")

    def test_list_skills(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"
        self._run_main(["!skills", "!exit"], engine, monkeypatch)
        engine.client.list_skills.assert_called_once()

    def test_enable_skill(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"
        self._run_main(["!enable coding", "!exit"], engine, monkeypatch)
        engine.enable_skill.assert_called_with("coding")

    def test_disable_skill(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"
        self._run_main(["!disable coding", "!exit"], engine, monkeypatch)
        engine.disable_skill.assert_called_with("coding")

    # --- Runtime modes ---

    def test_plan_on(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"
        self._run_main(["!plan on", "!exit"], engine, monkeypatch)
        engine.enable_plan_mode.assert_called_once()

    def test_plan_off(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"
        self._run_main(["!plan off", "!exit"], engine, monkeypatch)
        engine.disable_plan_mode.assert_called_once()

    def test_plan_invalid(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"
        self._run_main(["!plan invalid", "!exit"], engine, monkeypatch)
        engine.enable_plan_mode.assert_not_called()
        engine.disable_plan_mode.assert_not_called()

    def test_subagent_on(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"
        self._run_main(["!subagent on", "!exit"], engine, monkeypatch)
        engine.enable_subagent.assert_called_once()

    def test_subagent_off(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"
        self._run_main(["!subagent off", "!exit"], engine, monkeypatch)
        engine.disable_subagent.assert_called_once()

    def test_subagent_invalid(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"
        self._run_main(["!subagent invalid", "!exit"], engine, monkeypatch)
        engine.enable_subagent.assert_not_called()
        engine.disable_subagent.assert_not_called()

    # --- Memory ---

    def test_memory(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"
        self._run_main(["!memory", "!exit"], engine, monkeypatch)
        engine.client.get_memory.assert_called_once()

    def test_clear_memory(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"
        self._run_main(["!clear", "!exit"], engine, monkeypatch)
        engine.client.clear_memory.assert_called_once()

    # --- Help / Exit ---

    def test_help(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"
        # help prints but does not delegate to any engine method
        self._run_main(["!help", "!exit"], engine, monkeypatch)
        # No engine methods should be called (just printing)

    def test_exit_breaks_loop(self, monkeypatch):
        engine = MagicMock()
        engine.current_session_id = "test1234"
        self._run_main(["!exit"], engine, monkeypatch)
        # !exit causes main() to break out of the loop — no exception

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

        with patch("cli.cli.DeerFlowProductionEngine", return_value=engine), \
             patch("cli.cli.safe_input", side_effect=["!multi", KeyboardInterrupt]), \
             patch("cli.cli.multi_line_input", return_value=""):
            try:
                from cli.cli import main
                main()
            except (KeyboardInterrupt, SystemExit):
                pass
        # Empty multi-line input should not call chat
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
        engine.client._model_name = "opus"
        engine.client.list_models.return_value = {"models": [{"name": "opus", "display_name": "Opus", "supports_thinking": True}]}
        engine.client.list_skills.return_value = {"skills": []}
        engine.client.get_memory.return_value = {"facts": []}
        engine.list_uploads.return_value = {"count": 0, "files": []}
        engine.chat.return_value = iter(["response"])

        # create_session must set current_session_id so the loop doesn't crash
        def _create(*args, **kwargs):
            engine.current_session_id = "new12345"
            return "new12345"
        engine.create_session.side_effect = _create

        with patch("cli.cli.DeerFlowProductionEngine", return_value=engine), \
             patch("cli.cli.safe_input", side_effect=["Hello", "!exit"]):
            try:
                from cli.cli import main
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
        # Exception is caught in the REPL loop — main() continues to !exit


# ---------------------------------------------------------------------------
# main — null session handling
# ---------------------------------------------------------------------------

class TestMainNullSession:
    """main() creates a session when current_session_id is None."""

    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        from engine import DeerFlowProductionEngine
        DeerFlowProductionEngine._instance = None
        DeerFlowProductionEngine._initialized = False
        yield
        DeerFlowProductionEngine._instance = None
        DeerFlowProductionEngine._initialized = False

    def test_null_session_triggers_create(self, monkeypatch):
        """When current_session_id is None, main() calls create_session()."""
        engine = MagicMock()
        engine.current_session_id = None

        # create_session must set current_session_id so the loop works
        def _create(*args, **kwargs):
            engine.current_session_id = "new12345"
            return "new12345"
        engine.create_session.side_effect = _create

        with patch("cli.cli.DeerFlowProductionEngine", return_value=engine), \
             patch("cli.cli.safe_input", side_effect=["!sessions", KeyboardInterrupt]):
            try:
                from cli.cli import main
                main()
            except (KeyboardInterrupt, SystemExit):
                pass

        engine.create_session.assert_called()
