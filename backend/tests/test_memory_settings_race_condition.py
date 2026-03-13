"""Tests for the race-condition fix in _save_memory_to_file.

The fix ensures that a background LLM-driven memory update cannot silently
overwrite settings (e.g. injection_enabled) that were persisted to the file by
the Gateway API process between the time the update read the file and the time
it writes back to it.
"""

import json
from unittest.mock import patch

from src.agents.memory.updater import _save_memory_to_file

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _empty_memory() -> dict:
    return {
        "version": "1.0",
        "lastUpdated": "2026-01-01T00:00:00Z",
        "user": {
            "workContext": {"summary": "", "updatedAt": ""},
            "personalContext": {"summary": "", "updatedAt": ""},
            "topOfMind": {"summary": "", "updatedAt": ""},
        },
        "history": {
            "recentMonths": {"summary": "", "updatedAt": ""},
            "earlierContext": {"summary": "", "updatedAt": ""},
            "longTermBackground": {"summary": "", "updatedAt": ""},
        },
        "facts": [],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSaveMemoryPreservesSettings:
    """Verify that _save_memory_to_file preserves on-disk settings."""

    def test_settings_preserved_when_not_in_memory_data(self, tmp_path):
        """When memory_data has no 'settings' key but the file on disk does,
        the on-disk settings must be carried over (race-condition fix)."""
        memory_file = tmp_path / "memory.json"

        # Write initial file WITH settings (simulates Gateway having already saved them)
        initial = _empty_memory()
        initial["settings"] = {"injection_enabled": False}
        memory_file.write_text(json.dumps(initial))

        # Simulate background update data that was loaded BEFORE the settings were written
        # (so it has no "settings" key)
        update_data = _empty_memory()
        update_data["user"]["workContext"]["summary"] = "Updated by background thread"
        assert "settings" not in update_data

        with patch("src.agents.memory.updater._get_memory_file_path", return_value=memory_file):
            _save_memory_to_file(update_data)

        saved = json.loads(memory_file.read_text())
        assert "settings" in saved, "settings key must be preserved from on-disk file"
        assert saved["settings"]["injection_enabled"] is False

    def test_explicit_settings_not_overwritten(self, tmp_path):
        """When memory_data already has a 'settings' key (set_memory_settings path),
        it must NOT be overwritten by on-disk values."""
        memory_file = tmp_path / "memory.json"

        # File on disk has injection_enabled = True (old value)
        initial = _empty_memory()
        initial["settings"] = {"injection_enabled": True}
        memory_file.write_text(json.dumps(initial))

        # Caller explicitly sets injection_enabled = False
        update_data = _empty_memory()
        update_data["settings"] = {"injection_enabled": False}

        with patch("src.agents.memory.updater._get_memory_file_path", return_value=memory_file):
            _save_memory_to_file(update_data)

        saved = json.loads(memory_file.read_text())
        assert saved["settings"]["injection_enabled"] is False, (
            "explicit settings in memory_data must take precedence over on-disk value"
        )

    def test_no_settings_in_file_no_settings_added(self, tmp_path):
        """If neither memory_data nor the on-disk file has 'settings',
        the saved file should not have 'settings' either."""
        memory_file = tmp_path / "memory.json"
        initial = _empty_memory()
        memory_file.write_text(json.dumps(initial))

        update_data = _empty_memory()
        assert "settings" not in update_data

        with patch("src.agents.memory.updater._get_memory_file_path", return_value=memory_file):
            _save_memory_to_file(update_data)

        saved = json.loads(memory_file.read_text())
        assert "settings" not in saved

    def test_settings_preserved_when_file_does_not_exist_yet(self, tmp_path):
        """When the file does not exist yet (first save), no error and no settings added."""
        memory_file = tmp_path / "new_memory.json"
        assert not memory_file.exists()

        update_data = _empty_memory()

        with patch("src.agents.memory.updater._get_memory_file_path", return_value=memory_file):
            result = _save_memory_to_file(update_data)

        assert result is True
        saved = json.loads(memory_file.read_text())
        assert "settings" not in saved

    def test_race_condition_scenario(self, tmp_path):
        """Full race-condition simulation:
        1. Background thread reads memory at T0 (no settings).
        2. Gateway writes injection_enabled=False at T1.
        3. Background thread saves at T2.
        The saved file at T2 must still carry injection_enabled=False.
        """
        memory_file = tmp_path / "memory.json"

        # T0: initial file has no settings
        initial = _empty_memory()
        memory_file.write_text(json.dumps(initial))

        # Simulate background thread reading memory at T0
        memory_at_t0 = _empty_memory()
        memory_at_t0["user"]["workContext"]["summary"] = "work in progress"
        assert "settings" not in memory_at_t0

        # T1: Gateway writes injection_enabled=False to file
        gateway_update = _empty_memory()
        gateway_update["user"]["workContext"]["summary"] = "work in progress"
        gateway_update["settings"] = {"injection_enabled": False}
        memory_file.write_text(json.dumps(gateway_update))

        # T2: Background thread saves its (T0) version back
        with patch("src.agents.memory.updater._get_memory_file_path", return_value=memory_file):
            _save_memory_to_file(memory_at_t0)

        saved = json.loads(memory_file.read_text())
        assert "settings" in saved, "settings must survive the background-thread save"
        assert saved["settings"]["injection_enabled"] is False
