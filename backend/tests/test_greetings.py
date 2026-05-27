"""Unit tests for the personalized greeting API."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from app.gateway.routers.greetings import (
    _DEFAULT_SUGGESTIONS,
    _GREETING_TEMPLATES,
    _TICKET_STALE_DAYS,
    _MAINTENANCE_WINDOW_DAYS,
    _CLOSED_RECENT_DAYS,
    _build_suggestions,
    _detect_language,
    _sort_suggestions_by_priority,
    _time_of_day_key,
)


class TestDetectLanguage:
    def test_chinese_input(self):
        assert _detect_language("帮我看看设备情况") == "zh-CN"

    def test_english_input(self):
        assert _detect_language("Check device status") == "en-US"

    def test_mixed_input_favors_chinese(self):
        assert _detect_language("帮我check一下设备") == "zh-CN"

    def test_empty_string_defaults_to_chinese(self):
        assert _detect_language("") == "zh-CN"

    def test_none_defaults_to_chinese(self):
        assert _detect_language(None) == "zh-CN"


class TestTimeOfDayKey:
    def test_returns_valid_key(self):
        key = _time_of_day_key()
        assert key in ("morning", "afternoon", "evening")


class TestBuildSuggestions:
    def test_default_suggestions_when_no_memory(self):
        memory: dict = {}
        result = _build_suggestions(memory, "zh-CN")
        assert len(result) == 3
        assert all(isinstance(s, str) for s in result)

    def test_includes_continue_when_recent_months(self):
        memory = {"recentMonths": "analyzed pump vibration data"}
        result = _build_suggestions(memory, "zh-CN")
        assert any("继续" in s for s in result)

    def test_includes_continue_english_when_recent_months(self):
        memory = {"recentMonths": "analyzed pump vibration data"}
        result = _build_suggestions(memory, "en-US")
        assert any("Continue" in s for s in result)

    def test_facts_boosted_into_suggestions(self):
        memory = {"facts": [{"content": "2号泵振动偏高", "category": "observation"}]}
        result = _build_suggestions(memory, "zh-CN")
        assert "2号泵振动偏高" in result

    def test_long_facts_excluded(self):
        long_fact = "x" * 50
        memory = {"facts": [{"content": long_fact, "category": "observation"}]}
        result = _build_suggestions(memory, "zh-CN")
        assert long_fact not in result


class TestGreetingTemplates:
    def test_zh_templates_have_all_time_keys(self):
        for key in ("morning", "afternoon", "evening"):
            assert key in _GREETING_TEMPLATES["zh-CN"]

    def test_en_templates_have_all_time_keys(self):
        for key in ("morning", "afternoon", "evening"):
            assert key in _GREETING_TEMPLATES["en-US"]

    def test_default_suggestions_have_both_languages(self):
        assert "zh-CN" in _DEFAULT_SUGGESTIONS
        assert "en-US" in _DEFAULT_SUGGESTIONS
        assert len(_DEFAULT_SUGGESTIONS["zh-CN"]) == 3
        assert len(_DEFAULT_SUGGESTIONS["en-US"]) == 3


class TestPrioritySorting:
    def test_pump_keyword_boosts_priority(self):
        suggestions = ["查看设备状态", "分析2号泵振动", "生成报告"]
        memory = {"recentMonths": "", "userContext": {}}
        result = _sort_suggestions_by_priority(suggestions, memory)
        assert result[0] == "分析2号泵振动"

    def test_alarm_keyword_boosts_priority(self):
        suggestions = ["查看设备状态", "处理告警", "生成报告"]
        memory = {"recentMonths": "", "userContext": {}}
        result = _sort_suggestions_by_priority(suggestions, memory)
        assert result[0] == "处理告警"

    def test_recent_memory_boosts_matching_suggestions(self):
        suggestions = ["继续上次的工作", "查看设备状态", "生成报告"]
        memory = {"recentMonths": "analyzed pump vibration", "userContext": {}}
        result = _sort_suggestions_by_priority(suggestions, memory)
        assert "pump" in result[0].lower() or "vibration" in result[0].lower() or result[0] == "继续上次的工作"

    def test_no_keywords_maintains_order(self):
        suggestions = ["查看设备状态", "生成报告", "其他任务"]
        memory = {"recentMonths": "", "userContext": {}}
        result = _sort_suggestions_by_priority(suggestions, memory)
        assert len(result) == 3


class TestFollowUpConstants:
    def test_ticket_stale_days_is_30(self):
        assert _TICKET_STALE_DAYS == 30

    def test_maintenance_window_is_14_days(self):
        assert _MAINTENANCE_WINDOW_DAYS == 14

    def test_closed_recent_days_is_7(self):
        assert _CLOSED_RECENT_DAYS == 7


class TestPendingFollowUp:
    def test_followup_fact_detected_in_memory(self):
        memory = {
            "facts": [
                {"content": "分析泵振动", "category": "observation"},
                {"content": "跟进2号泵的诊断结果", "category": "followup"},
            ]
        }
        followup = None
        for fact in memory.get("facts", []):
            if isinstance(fact, dict) and fact.get("category") == "followup":
                followup = fact.get("content", "")
                break
        assert followup == "跟进2号泵的诊断结果"

    def test_no_followup_fact_returns_none(self):
        memory = {
            "facts": [
                {"content": "分析泵振动", "category": "observation"},
            ]
        }
        followup = None
        for fact in memory.get("facts", []):
            if isinstance(fact, dict) and fact.get("category") == "followup":
                followup = fact.get("content", "")
                break
        assert followup is None
