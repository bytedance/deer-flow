"""Tests for global variables storage."""

import json
from unittest.mock import MagicMock, patch

import pytest

from deerflow.global_variables.storage import (
    GlobalVariablesStorage,
    create_empty_variables,
    get_storage,
    reset_storage,
    utc_now_iso_z,
)


class TestUtcNowIsoZ:
    def test_returns_iso_string_with_z(self):
        result = utc_now_iso_z()
        assert isinstance(result, str)
        assert result.endswith("Z")


class TestCreateEmptyVariables:
    def test_returns_valid_structure(self):
        data = create_empty_variables()
        assert isinstance(data, dict)
        assert "variables" in data
        assert isinstance(data["variables"], dict)
        assert len(data["variables"]) == 0


class TestGlobalVariablesStorage:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.tmp_path = tmp_path
        self.base_dir = tmp_path / "deer_flow_home"
        self.base_dir.mkdir()
        reset_storage()

    def _mock_paths(self):
        mock_paths = MagicMock()
        mock_paths.base_dir = self.base_dir
        mock_paths.thread_dir = lambda tid: self.base_dir / "threads" / tid
        return mock_paths

    def test_project_save_and_load(self):
        with patch("deerflow.global_variables.storage.get_paths", side_effect=lambda: self._mock_paths()):
            storage = GlobalVariablesStorage()
            data = {"variables": {"mode": {"value": "writing", "description": "Work mode"}}}
            assert storage.save(data, scope="project")

            loaded = storage.load("project")
            assert "variables" in loaded
            assert "mode" in loaded["variables"]
            assert loaded["variables"]["mode"]["value"] == "writing"

    def test_thread_save_and_load(self):
        with patch("deerflow.global_variables.storage.get_paths", side_effect=lambda: self._mock_paths()):
            storage = GlobalVariablesStorage()
            thread_id = "test-thread-1"
            data = {"variables": {"chapter": {"value": "5", "description": "Current chapter"}}}
            assert storage.save(data, scope="thread", thread_id=thread_id)

            loaded = storage.load("thread", thread_id=thread_id)
            assert "chapter" in loaded["variables"]
            assert loaded["variables"]["chapter"]["value"] == "5"

    def test_load_nonexistent_returns_system_variables(self):
        with patch("deerflow.global_variables.storage.get_paths", side_effect=lambda: self._mock_paths()):
            storage = GlobalVariablesStorage()
            data = storage.load("project")
            assert "workdir" in data["variables"]
            assert data["variables"]["workdir"]["is_system"] is True
            assert data["is_custom"] is True
            assert "lastUpdated" in data

    def test_cache_invalidated_on_file_change(self, tmp_path):
        with patch("deerflow.global_variables.storage.get_paths", side_effect=lambda: self._mock_paths()):
            storage = GlobalVariablesStorage()
            data = {"variables": {"key1": {"value": "v1"}}}
            storage.save(data, scope="project")

            loaded1 = storage.load("project")
            assert loaded1["variables"]["key1"]["value"] == "v1"

            file_path = self.base_dir / "global_variables.json"
            new_data = {"variables": {"key1": {"value": "v2"}}}
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(new_data, f)

            import time

            time.sleep(0.01)
            loaded2 = storage.load("project")
            assert loaded2["variables"]["key1"]["value"] == "v2"

    def test_reload_forces_cache_refresh(self):
        with patch("deerflow.global_variables.storage.get_paths", side_effect=lambda: self._mock_paths()):
            storage = GlobalVariablesStorage()
            data = {"variables": {"key1": {"value": "v1"}}}
            storage.save(data, scope="project")

            file_path = self.base_dir / "global_variables.json"
            new_data = {"variables": {"key1": {"value": "v2"}}}
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(new_data, f)

            reloaded = storage.reload("project")
            assert reloaded["variables"]["key1"]["value"] == "v2"

    def test_delete_variable(self):
        with patch("deerflow.global_variables.storage.get_paths", side_effect=lambda: self._mock_paths()):
            storage = GlobalVariablesStorage()
            data = {"variables": {"key1": {"value": "v1"}, "key2": {"value": "v2"}}}
            storage.save(data, scope="project")

            loaded = storage.load("project")
            del loaded["variables"]["key1"]
            storage.save(loaded, scope="project")

            final = storage.load("project")
            assert "key1" not in final["variables"]
            assert "key2" in final["variables"]

    def test_isolation_between_scopes(self):
        with patch("deerflow.global_variables.storage.get_paths", side_effect=lambda: self._mock_paths()):
            storage = GlobalVariablesStorage()
            project_data = {"variables": {"shared": {"value": "project_val"}}}
            thread_data = {"variables": {"shared": {"value": "thread_val"}}}
            storage.save(project_data, scope="project")
            storage.save(thread_data, scope="thread", thread_id="t1")

            p = storage.load("project")
            t = storage.load("thread", thread_id="t1")
            assert p["variables"]["shared"]["value"] == "project_val"
            assert t["variables"]["shared"]["value"] == "thread_val"


class TestGetStorage:
    def test_returns_singleton(self):
        reset_storage()
        s1 = get_storage()
        s2 = get_storage()
        assert s1 is s2

    def test_reset_clears_singleton(self):
        reset_storage()
        s1 = get_storage()
        reset_storage()
        s2 = get_storage()
        assert s1 is not s2
