"""Tests for global variables prompt injection."""

from unittest.mock import patch

from deerflow.config.global_variables_config import GlobalVariablesConfig
from deerflow.global_variables.prompt_injector import (
    build_prompt_section,
    get_merged_variables,
    replace_template_variables,
)


class TestGetMergedVariables:
    def test_no_variables(self):
        with patch("deerflow.global_variables.prompt_injector.get_storage") as mock_storage:
            mock_storage.return_value.load.side_effect = lambda s, **kw: {"variables": {}}
            result = get_merged_variables()
            assert result == {}

    def test_project_only(self):
        def mock_load(scope, thread_id=None):
            if scope == "project":
                return {"variables": {"mode": {"value": "writing", "description": "Work mode"}}}
            return {"variables": {}}

        with patch("deerflow.global_variables.prompt_injector.get_storage") as mock_storage:
            mock_storage.return_value.load = mock_load
            result = get_merged_variables()
            assert "mode" in result
            assert result["mode"]["value"] == "writing"

    def test_thread_overrides_project(self):
        def mock_load(scope, thread_id=None):
            if scope == "project":
                return {"variables": {"mode": {"value": "writing", "description": "Work mode"}, "lang": {"value": "en"}}}
            if scope == "thread" and thread_id == "t1":
                return {"variables": {"mode": {"value": "reviewing"}}}
            return {"variables": {}}

        with patch("deerflow.global_variables.prompt_injector.get_storage") as mock_storage:
            mock_storage.return_value.load = mock_load
            result = get_merged_variables(thread_id="t1")
            assert result["mode"]["value"] == "reviewing"
            assert result["lang"]["value"] == "en"

    def test_no_thread_id(self):
        def mock_load(scope, thread_id=None):
            if scope == "project":
                return {"variables": {"mode": {"value": "writing"}}}
            return {"variables": {}}

        with patch("deerflow.global_variables.prompt_injector.get_storage") as mock_storage:
            mock_storage.return_value.load = mock_load
            result = get_merged_variables(thread_id=None)
            assert result["mode"]["value"] == "writing"


class TestBuildPromptSection:
    def test_disabled_returns_empty(self):
        config = GlobalVariablesConfig(enabled=False)
        with patch("deerflow.global_variables.prompt_injector.get_global_variables_config", return_value=config):
            result = build_prompt_section()
            assert result == ""

    def test_no_variables_returns_empty(self):
        config = GlobalVariablesConfig(enabled=True, injection_enabled=True)
        with patch("deerflow.global_variables.prompt_injector.get_global_variables_config", return_value=config):
            with patch("deerflow.global_variables.prompt_injector.get_merged_variables", return_value={}):
                result = build_prompt_section()
                assert result == ""

    def test_builds_section(self):
        config = GlobalVariablesConfig(enabled=True, injection_enabled=True)
        merged = {
            "mode": {"value": "writing", "description": "Current work mode"},
            "chapter": {"value": "5", "description": "Current chapter"},
        }
        with patch("deerflow.global_variables.prompt_injector.get_global_variables_config", return_value=config):
            with patch("deerflow.global_variables.prompt_injector.get_merged_variables", return_value=merged):
                result = build_prompt_section()
                assert "<global_variables>" in result
                assert "mode = writing" in result
                assert "chapter = 5" in result
                assert "# Current work mode" in result
                assert "# Current chapter" in result
                assert "</global_variables>" in result

    def test_truncates_when_too_long(self):
        config = GlobalVariablesConfig(
            enabled=True,
            injection_enabled=True,
            max_total_prompt_length=100,
        )
        merged = {
            "key1": {"value": "a" * 30, "description": "long1"},
            "key2": {"value": "b" * 30, "description": "long2"},
            "key3": {"value": "c" * 30, "description": "long3"},
        }
        with patch("deerflow.global_variables.prompt_injector.get_global_variables_config", return_value=config):
            with patch("deerflow.global_variables.prompt_injector.get_merged_variables", return_value=merged):
                result = build_prompt_section()
                assert len(result) < 200
                assert "<global_variables>" in result


class TestReplaceTemplateVariables:
    def test_replaces_variable(self):
        merged = {"role": {"value": "写作助手"}, "chapter": {"value": "5"}}
        with patch("deerflow.global_variables.prompt_injector.get_merged_variables", return_value=merged):
            result = replace_template_variables("你是{{role}}，处理第{{chapter}}章")
            assert result == "你是写作助手，处理第5章"

    def test_keeps_missing_variable(self):
        merged = {"role": {"value": "写作助手"}}
        with patch("deerflow.global_variables.prompt_injector.get_merged_variables", return_value=merged):
            result = replace_template_variables("你是{{role}}，{{unknown}}")
            assert result == "你是写作助手，{{unknown}}"

    def test_thread_overrides_project(self):
        def mock_load(scope, thread_id=None):
            if scope == "project":
                return {"variables": {"role": {"value": "默认角色"}, "chapter": {"value": "1"}}}
            if scope == "thread" and thread_id == "t1":
                return {"variables": {"role": {"value": "自定义角色"}}}
            return {"variables": {}}

        with patch("deerflow.global_variables.prompt_injector.get_storage") as mock_storage:
            mock_storage.return_value.load = mock_load
            result = replace_template_variables("你是{{role}}，第{{chapter}}章", thread_id="t1")
            assert result == "你是自定义角色，第1章"

    def test_no_variables_no_change(self):
        with patch("deerflow.global_variables.prompt_injector.get_merged_variables", return_value={}):
            result = replace_template_variables("没有变量{{x}}")
            assert result == "没有变量{{x}}"

    def test_plain_text_no_change(self):
        with patch("deerflow.global_variables.prompt_injector.get_merged_variables", return_value={"role": {"value": "x"}}):
            result = replace_template_variables("This is plain text with no variables")
            assert result == "This is plain text with no variables"

    def test_non_dict_variable(self):
        merged = {"name": "simple_value"}
        with patch("deerflow.global_variables.prompt_injector.get_merged_variables", return_value=merged):
            result = replace_template_variables("Hello {{name}}")
            assert result == "Hello simple_value"
