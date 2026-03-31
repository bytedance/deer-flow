"""Unit tests for LayeredAppConfig and LayeredExtensionsConfig."""

import json
from pathlib import Path

import pytest
import yaml

from deerflow.identity.agent_identity import AgentIdentity


# ── Helpers ────────────────────────────────────────────────────────────────────

def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


# ── Deep-merge helpers ─────────────────────────────────────────────────────────

class TestDeepMerge:
    def test_scalar_override(self):
        from deerflow.config.layered_config import _deep_merge

        result = _deep_merge({"a": 1, "b": 2}, {"b": 99})
        assert result == {"a": 1, "b": 99}

    def test_nested_dict_recursive(self):
        from deerflow.config.layered_config import _deep_merge

        base = {"x": {"y": 1, "z": 2}}
        override = {"x": {"z": 99}}
        result = _deep_merge(base, override)
        assert result["x"]["y"] == 1
        assert result["x"]["z"] == 99

    def test_named_list_merge(self):
        from deerflow.config.layered_config import _deep_merge

        base = {"models": [{"name": "m1", "foo": "bar"}, {"name": "m2", "foo": "baz"}]}
        override = {"models": [{"name": "m1", "foo": "OVERRIDE"}]}
        result = _deep_merge(base, override)
        assert len(result["models"]) == 2
        m1 = next(m for m in result["models"] if m["name"] == "m1")
        assert m1["foo"] == "OVERRIDE"

    def test_unnamed_list_replaced(self):
        from deerflow.config.layered_config import _deep_merge

        base = {"items": [1, 2, 3]}
        override = {"items": [9]}
        result = _deep_merge(base, override)
        assert result["items"] == [9]

    def test_new_keys_added(self):
        from deerflow.config.layered_config import _deep_merge

        result = _deep_merge({"a": 1}, {"b": 2})
        assert result == {"a": 1, "b": 2}

    def test_base_not_mutated(self):
        from deerflow.config.layered_config import _deep_merge

        base = {"x": {"y": 1}}
        _deep_merge(base, {"x": {"y": 2}})
        assert base["x"]["y"] == 1


# ── load_layered_config_dict ───────────────────────────────────────────────────

class TestLoadLayeredConfigDict:
    def test_returns_empty_for_global_no_files(self, tmp_path):
        from deerflow.config.paths import Paths
        from deerflow.config.layered_config import load_layered_config_dict

        # Monkey-patch get_paths to use tmp_path
        import deerflow.config.layered_config as lc

        original = lc.__dict__.get("get_paths")
        try:
            lc_paths = Paths(tmp_path)

            def _fake_get_paths():
                return lc_paths

            # Patch inside the function via the paths module
            import deerflow.config.paths as paths_module
            orig_get_paths = paths_module.get_paths
            paths_module.get_paths = _fake_get_paths

            identity = AgentIdentity()
            result = load_layered_config_dict(identity)
            assert result == {}
        finally:
            paths_module.get_paths = orig_get_paths

    def test_dept_overrides_global(self, tmp_path):
        from deerflow.config.paths import Paths
        from deerflow.config.layered_config import load_layered_config_dict
        import deerflow.config.paths as paths_module

        paths_obj = Paths(tmp_path)
        orig = paths_module.get_paths

        try:
            paths_module.get_paths = lambda: paths_obj

            # Write global config
            _write_yaml(tmp_path / "config.yaml", {"memory": {"enabled": True, "max_facts": 50}})
            # Write dept override
            dept_cfg = paths_obj.dept_dir("research") / "config.yaml"
            _write_yaml(dept_cfg, {"memory": {"max_facts": 200}})

            identity = AgentIdentity(dept_id="research")
            merged = load_layered_config_dict(identity)
            assert merged["memory"]["enabled"] is True   # preserved from global
            assert merged["memory"]["max_facts"] == 200  # overridden by dept
        finally:
            paths_module.get_paths = orig

    def test_agent_overrides_all(self, tmp_path):
        from deerflow.config.paths import Paths
        from deerflow.config.layered_config import load_layered_config_dict
        import deerflow.config.paths as paths_module

        paths_obj = Paths(tmp_path)
        orig = paths_module.get_paths

        try:
            paths_module.get_paths = lambda: paths_obj

            identity = AgentIdentity(dept_id="d", user_id="u", agent_name="a")

            _write_yaml(tmp_path / "config.yaml", {"key": "global"})
            _write_yaml(paths_obj.dept_dir("d") / "config.yaml", {"key": "dept"})
            _write_yaml(paths_obj.dept_user_dir("d", "u") / "config.yaml", {"key": "user"})
            _write_yaml(paths_obj.identity_agent_dir(identity) / "config.yaml", {"key": "agent"})

            merged = load_layered_config_dict(identity)
            assert merged["key"] == "agent"
        finally:
            paths_module.get_paths = orig


# ── load_layered_extensions (skills intersection) ─────────────────────────────

class TestLoadLayeredExtensions:
    def _setup_paths(self, tmp_path):
        import deerflow.config.paths as paths_module
        from deerflow.config.paths import Paths

        paths_obj = Paths(tmp_path)
        return paths_obj, paths_module

    def test_global_only_returns_global_skills(self, tmp_path):
        from deerflow.config.layered_extensions import load_layered_extensions
        import deerflow.config.paths as paths_module
        from deerflow.config.paths import Paths

        paths_obj = Paths(tmp_path)
        orig = paths_module.get_paths

        try:
            paths_module.get_paths = lambda: paths_obj
            _write_json(tmp_path / "extensions_config.json", {
                "skills": {"my-skill": {"enabled": True}}
            })

            identity = AgentIdentity(dept_id="d", user_id="u")
            ext = load_layered_extensions(identity)
            # No dept/user extensions_config.json → inherits global
            assert ext.is_skill_enabled("my-skill", "custom") is True
        finally:
            paths_module.get_paths = orig

    def test_dept_disables_skill(self, tmp_path):
        from deerflow.config.layered_extensions import load_layered_extensions
        import deerflow.config.paths as paths_module
        from deerflow.config.paths import Paths

        paths_obj = Paths(tmp_path)
        orig = paths_module.get_paths

        try:
            paths_module.get_paths = lambda: paths_obj
            _write_json(tmp_path / "extensions_config.json", {
                "skills": {"skill-a": {"enabled": True}}
            })
            _write_json(paths_obj.dept_dir("d") / "extensions_config.json", {
                "skills": {"skill-a": {"enabled": False}}  # dept disables it
            })

            identity = AgentIdentity(dept_id="d", user_id="u")
            ext = load_layered_extensions(identity)
            # Once disabled at any layer → stays disabled (intersection)
            assert ext.is_skill_enabled("skill-a", "public") is False
        finally:
            paths_module.get_paths = orig

    def test_user_cannot_re_enable_dept_disabled_skill(self, tmp_path):
        from deerflow.config.layered_extensions import load_layered_extensions
        import deerflow.config.paths as paths_module
        from deerflow.config.paths import Paths

        paths_obj = Paths(tmp_path)
        orig = paths_module.get_paths

        try:
            paths_module.get_paths = lambda: paths_obj
            _write_json(tmp_path / "extensions_config.json", {
                "skills": {"restricted-skill": {"enabled": True}}
            })
            _write_json(paths_obj.dept_dir("d") / "extensions_config.json", {
                "skills": {"restricted-skill": {"enabled": False}}
            })
            _write_json(paths_obj.dept_user_dir("d", "u") / "extensions_config.json", {
                "skills": {"restricted-skill": {"enabled": True}}  # user tries to re-enable
            })

            identity = AgentIdentity(dept_id="d", user_id="u")
            ext = load_layered_extensions(identity)
            # Intersection: once False → stays False
            assert ext.is_skill_enabled("restricted-skill", "public") is False
        finally:
            paths_module.get_paths = orig

    def test_mcp_last_layer_wins(self, tmp_path):
        from deerflow.config.layered_extensions import load_layered_extensions
        import deerflow.config.paths as paths_module
        from deerflow.config.paths import Paths

        paths_obj = Paths(tmp_path)
        orig = paths_module.get_paths

        try:
            paths_module.get_paths = lambda: paths_obj
            _write_json(tmp_path / "extensions_config.json", {
                "mcpServers": {"my-mcp": {"enabled": True, "url": "http://global:8080"}}
            })
            _write_json(paths_obj.dept_dir("d") / "extensions_config.json", {
                "mcpServers": {"my-mcp": {"url": "http://dept:9090"}}
            })

            identity = AgentIdentity(dept_id="d", user_id="u")
            ext = load_layered_extensions(identity)
            servers = ext.get_enabled_mcp_servers()
            # URL should be the dept-level override
            assert servers["my-mcp"].url == "http://dept:9090"
        finally:
            paths_module.get_paths = orig
