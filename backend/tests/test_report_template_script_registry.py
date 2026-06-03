"""Unit tests for report_templates.script_registry.

We avoid touching the real skill loader: instead the tests inject a synthetic
``[(skill_name, skill_dir, enabled)]`` list into the internal builder.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from deerflow.report_templates.script_registry import (
    REPORT_SCRIPTS_FILE,
    RegistryConflictError,
    RegistryLoadError,
    ScriptRegistry,
    UnknownScriptError,
    _build_registry_from_skills,
    load_registry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


VALID_MANIFEST = {
    "schema_version": "1",
    "scripts": {
        "list_equipment": {
            "entry": "scripts/list_equipment.py",
            "kind": ["form_options"],
            "description": "Query equipment catalogue",
            "args_schema": {
                "type": {"type": "enum", "values": ["all", "pump"], "required": True},
                "limit": {"type": "integer", "min": 1, "max": 100, "default": 50},
            },
            "outputs_schema": {"equipment": {"type": "array"}},
            "timeout_seconds": 30,
            "max_output_bytes": 1048576,
        },
        "query_daily": {
            "entry": "scripts/query_daily.py",
            "kind": ["data_step"],
            "description": "Daily data",
            "args_schema": {"date": {"type": "date", "required": True}},
            "output_files": [{"id": "daily_data", "path": "{run_output_dir}/data/daily_data.json"}],
            "timeout_seconds": 120,
            "max_output_bytes": 52428800,
        },
    },
}


def _write_skill(tmp_path: Path, skill_name: str, manifest: dict | None) -> Path:
    skill_dir = tmp_path / skill_name
    skill_dir.mkdir()
    if manifest is not None:
        (skill_dir / REPORT_SCRIPTS_FILE).write_text(
            yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
        )
    return skill_dir


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestLoadRegistry:
    def test_loads_valid_manifest(self, tmp_path: Path):
        skill_dir = _write_skill(tmp_path, "daily-report", VALID_MANIFEST)
        reg = _build_registry_from_skills([("daily-report", skill_dir, True)])
        assert sorted(reg.scripts.keys()) == [
            "daily-report/list_equipment",
            "daily-report/query_daily",
        ]

    def test_descriptor_fields_populated(self, tmp_path: Path):
        skill_dir = _write_skill(tmp_path, "daily-report", VALID_MANIFEST)
        reg = _build_registry_from_skills([("daily-report", skill_dir, True)])
        d = reg.scripts["daily-report/query_daily"]
        assert d.skill_name == "daily-report"
        assert d.script_name == "query_daily"
        assert d.entry == "scripts/query_daily.py"
        assert d.kinds == ("data_step",)
        assert d.timeout_seconds == 120
        assert d.output_files[0].id == "daily_data"
        assert "{run_output_dir}/data/daily_data.json" in d.output_files[0].path

    def test_skill_without_manifest_is_silently_skipped(self, tmp_path: Path):
        skill_dir = _write_skill(tmp_path, "boring-skill", None)
        reg = _build_registry_from_skills([("boring-skill", skill_dir, True)])
        assert reg.scripts == {}

    def test_multiple_skills_aggregated(self, tmp_path: Path):
        a_dir = _write_skill(
            tmp_path,
            "skill-a",
            {"schema_version": "1", "scripts": {"foo": {"entry": "x.py", "kind": ["data_step"]}}},
        )
        b_dir = _write_skill(
            tmp_path,
            "skill-b",
            {"schema_version": "1", "scripts": {"bar": {"entry": "y.py", "kind": ["transform"]}}},
        )
        reg = _build_registry_from_skills(
            [("skill-a", a_dir, True), ("skill-b", b_dir, True)]
        )
        assert "skill-a/foo" in reg.scripts
        assert "skill-b/bar" in reg.scripts

    def test_same_script_name_in_different_skills_does_not_conflict(self, tmp_path: Path):
        manifest = {
            "schema_version": "1",
            "scripts": {"shared": {"entry": "x.py", "kind": ["data_step"]}},
        }
        a_dir = _write_skill(tmp_path, "skill-a", manifest)
        b_dir = _write_skill(tmp_path, "skill-b", manifest)
        reg = _build_registry_from_skills(
            [("skill-a", a_dir, True), ("skill-b", b_dir, True)]
        )
        assert "skill-a/shared" in reg.scripts
        assert "skill-b/shared" in reg.scripts


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestRegistryErrors:
    def test_invalid_yaml_raises(self, tmp_path: Path):
        skill_dir = tmp_path / "skill-a"
        skill_dir.mkdir()
        (skill_dir / REPORT_SCRIPTS_FILE).write_text("not: valid: yaml: [", encoding="utf-8")
        with pytest.raises(RegistryLoadError, match="cannot read"):
            _build_registry_from_skills([("skill-a", skill_dir, True)])

    def test_wrong_schema_version_raises(self, tmp_path: Path):
        skill_dir = _write_skill(
            tmp_path,
            "skill-a",
            {
                "schema_version": "999",
                "scripts": {"foo": {"entry": "x.py", "kind": ["data_step"]}},
            },
        )
        with pytest.raises(RegistryLoadError, match="schema_version"):
            _build_registry_from_skills([("skill-a", skill_dir, True)])

    def test_extra_top_level_keys_rejected(self, tmp_path: Path):
        skill_dir = _write_skill(
            tmp_path,
            "skill-a",
            {
                "schema_version": "1",
                "extra_root_key": True,
                "scripts": {"foo": {"entry": "x.py", "kind": ["data_step"]}},
            },
        )
        with pytest.raises(RegistryLoadError, match="invalid"):
            _build_registry_from_skills([("skill-a", skill_dir, True)])

    def test_invalid_script_kind_rejected(self, tmp_path: Path):
        skill_dir = _write_skill(
            tmp_path,
            "skill-a",
            {
                "schema_version": "1",
                "scripts": {
                    "foo": {"entry": "x.py", "kind": ["NOT_A_KIND"]},
                },
            },
        )
        with pytest.raises(RegistryLoadError):
            _build_registry_from_skills([("skill-a", skill_dir, True)])

    def test_qualified_name_collision_rejected(self, tmp_path: Path):
        # If somehow two skills end up with the same name (e.g. duplicate
        # registration through a programmatic path), the loader rejects it.
        a_dir = _write_skill(
            tmp_path,
            "same-name",
            {"schema_version": "1", "scripts": {"foo": {"entry": "x.py", "kind": ["data_step"]}}},
        )
        b_dir = tmp_path / "same-name-2"
        b_dir.mkdir()
        (b_dir / REPORT_SCRIPTS_FILE).write_text(
            yaml.safe_dump(
                {"schema_version": "1", "scripts": {"foo": {"entry": "y.py", "kind": ["data_step"]}}},
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        # Pretend both directories register under the same skill name to force the conflict.
        with pytest.raises(RegistryConflictError, match="duplicate script"):
            _build_registry_from_skills(
                [("same-name", a_dir, True), ("same-name", b_dir, True)]
            )


# ---------------------------------------------------------------------------
# Snapshot helpers
# ---------------------------------------------------------------------------


class TestRegistryAccessors:
    def test_require_raises_for_unknown(self, tmp_path: Path):
        reg = _build_registry_from_skills([])
        with pytest.raises(UnknownScriptError):
            reg.require("nonexistent/script")

    def test_list_by_skill_filters_correctly(self, tmp_path: Path):
        a_dir = _write_skill(
            tmp_path,
            "skill-a",
            {
                "schema_version": "1",
                "scripts": {
                    "a1": {"entry": "x.py", "kind": ["data_step"]},
                    "a2": {"entry": "y.py", "kind": ["transform"]},
                },
            },
        )
        b_dir = _write_skill(
            tmp_path,
            "skill-b",
            {"schema_version": "1", "scripts": {"b1": {"entry": "z.py", "kind": ["data_step"]}}},
        )
        reg = _build_registry_from_skills(
            [("skill-a", a_dir, True), ("skill-b", b_dir, True)]
        )
        assert {d.script_name for d in reg.list_by_skill("skill-a")} == {"a1", "a2"}
        assert {d.script_name for d in reg.list_by_skill("skill-b")} == {"b1"}

    def test_empty_registry(self):
        reg = ScriptRegistry()
        assert reg.scripts == {}
        with pytest.raises(UnknownScriptError):
            reg.require("any/thing")


# ---------------------------------------------------------------------------
# Cached load — sanity check that the public function delegates correctly
# ---------------------------------------------------------------------------


class TestCachedLoad:
    def test_load_registry_uses_skill_storage(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        skill_dir = _write_skill(tmp_path, "daily-report", VALID_MANIFEST)

        from deerflow.report_templates import script_registry as sr

        monkeypatch.setattr(
            sr,
            "_discover_skills",
            lambda *, enabled_only: [("daily-report", skill_dir, True)],
        )
        reg = load_registry()
        assert "daily-report/list_equipment" in reg.scripts

    def test_load_registry_handles_no_skills(self, monkeypatch: pytest.MonkeyPatch):
        from deerflow.report_templates import script_registry as sr

        monkeypatch.setattr(sr, "_discover_skills", lambda *, enabled_only: [])
        reg = load_registry()
        assert reg.scripts == {}
