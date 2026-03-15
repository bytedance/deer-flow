"""Unit tests for the start_langgraph.py entrypoint script."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# The script lives outside the backend package, so add its directory to sys.path
SCRIPTS_DIR = str(Path(__file__).resolve().parent.parent.parent / "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import start_langgraph  # noqa: E402


class TestStartLanggraphScript:
    """Verify the entrypoint builds the correct run_server arguments."""

    def test_reads_langgraph_json_and_passes_checkpointer(self, tmp_path):
        """run_server receives the checkpointer config from langgraph.json."""
        config_file = tmp_path / "langgraph.json"
        config_file.write_text(
            json.dumps(
                {
                    "graphs": {"agent": "my_module:agent"},
                    "checkpointer": {
                        "path": "./checkpointer.py:make_checkpointer"
                    },
                }
            )
        )

        captured = {}

        def fake_run_server(**kwargs):
            captured.update(kwargs)

        with (
            patch("start_langgraph.run_server", fake_run_server, create=True),
            patch(
                "sys.argv",
                [
                    "start_langgraph.py",
                    "--config",
                    str(config_file),
                    "--no-browser",
                    "--no-reload",
                    "--allow-blocking",
                ],
            ),
        ):
            # Patch the import inside main()
            mock_module = MagicMock()
            mock_module.run_server = fake_run_server
            with patch.dict(sys.modules, {"langgraph_api.cli": mock_module}):
                # Re-import to get the patched version
                import importlib

                importlib.reload(start_langgraph)
                start_langgraph.main()

        assert captured["checkpointer"] == {
            "path": "./checkpointer.py:make_checkpointer"
        }
        assert captured["graphs"] == {"agent": "my_module:agent"}
        assert captured["reload"] is False
        assert "sqlite" in captured["__database_uri__"]

    def test_database_uri_uses_deer_flow_home(self, tmp_path):
        """The SQLite database is placed under DEER_FLOW_HOME."""
        config_file = tmp_path / "langgraph.json"
        config_file.write_text(json.dumps({"graphs": {}}))

        deer_flow_home = str(tmp_path / "deerflow-data")

        captured = {}

        def fake_run_server(**kwargs):
            captured.update(kwargs)

        with (
            patch.dict(os.environ, {"DEER_FLOW_HOME": deer_flow_home}),
            patch(
                "sys.argv",
                ["start_langgraph.py", "--config", str(config_file), "--no-browser"],
            ),
        ):
            mock_module = MagicMock()
            mock_module.run_server = fake_run_server
            with patch.dict(sys.modules, {"langgraph_api.cli": mock_module}):
                import importlib

                importlib.reload(start_langgraph)
                start_langgraph.main()

        expected_db = os.path.join(deer_flow_home, "langgraph_api.db")
        assert captured["__database_uri__"] == f"sqlite:///{expected_db}"
        assert os.path.isdir(deer_flow_home)

    def test_no_checkpointer_passes_none(self, tmp_path):
        """When langgraph.json has no checkpointer key, None is passed."""
        config_file = tmp_path / "langgraph.json"
        config_file.write_text(json.dumps({"graphs": {"g": "m:g"}}))

        captured = {}

        def fake_run_server(**kwargs):
            captured.update(kwargs)

        with patch(
            "sys.argv",
            ["start_langgraph.py", "--config", str(config_file), "--no-browser"],
        ):
            mock_module = MagicMock()
            mock_module.run_server = fake_run_server
            with patch.dict(sys.modules, {"langgraph_api.cli": mock_module}):
                import importlib

                importlib.reload(start_langgraph)
                start_langgraph.main()

        assert captured["checkpointer"] is None
