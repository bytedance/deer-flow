# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import pytest
from src.prompts.template import get_prompt_template, apply_prompt_template


def test_get_prompt_template_success():
    """Test successful template loading"""
    template = get_prompt_template("coder")
    assert template is not None
    assert isinstance(template, str)
    assert len(template) > 0


def test_get_prompt_template_not_found():
    """Test handling of non-existent template"""
    with pytest.raises(ValueError) as exc_info:
        get_prompt_template("non_existent_template")
    assert "Error loading template" in str(exc_info.value)


def test_apply_prompt_template():
    """Test template variable substitution"""
    test_state = {
        "messages": [{"role": "user", "content": "test message"}],
        "task": "test task",
        "workspace_context": "test context",
    }

    messages = apply_prompt_template("coder", test_state)

    assert isinstance(messages, list)
    assert len(messages) > 1
    assert messages[0]["role"] == "system"
    assert "CURRENT_TIME" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "test message"


def test_apply_prompt_template_empty_messages():
    """Test template with empty messages list"""
    test_state = {
        "messages": [],
        "task": "test task",
        "workspace_context": "test context",
    }

    messages = apply_prompt_template("coder", test_state)
    assert len(messages) == 1  # Only system message
    assert messages[0]["role"] == "system"


def test_apply_prompt_template_multiple_messages():
    """Test template with multiple messages"""
    test_state = {
        "messages": [
            {"role": "user", "content": "first message"},
            {"role": "assistant", "content": "response"},
            {"role": "user", "content": "second message"},
        ],
        "task": "test task",
        "workspace_context": "test context",
    }

    messages = apply_prompt_template("coder", test_state)
    assert len(messages) == 4  # system + 3 messages
    assert messages[0]["role"] == "system"
    assert all(m["role"] in ["system", "user", "assistant"] for m in messages)


def test_apply_prompt_template_with_special_chars():
    """Test template with special characters in variables"""
    test_state = {
        "messages": [{"role": "user", "content": "test\nmessage\"with'special{chars}"}],
        "task": "task with $pecial ch@rs",
        "workspace_context": "<html>context</html>",
    }

    messages = apply_prompt_template("coder", test_state)
    assert messages[1]["content"] == "test\nmessage\"with'special{chars}"


@pytest.mark.parametrize("prompt_name", ["coder", "coder", "coordinator", "planner"])
def test_multiple_template_types(prompt_name):
    """Test loading different types of templates"""
    template = get_prompt_template(prompt_name)
    assert template is not None
    assert isinstance(template, str)
    assert len(template) > 0


def test_current_time_format():
    """Test the format of CURRENT_TIME in rendered template"""
    test_state = {
        "messages": [{"role": "user", "content": "test"}],
        "task": "test",
        "workspace_context": "test",
    }

    messages = apply_prompt_template("coder", test_state)
    system_content = messages[0]["content"]

    assert any(
        line.strip().startswith("CURRENT_TIME:") for line in system_content.split("\n")
    )


def test_apply_prompt_template_reporter():
    """Test reporter template rendering with different styles and locale"""

    test_state_news = {
        "messages": [],
        "task": "test reporter task",
        "workspace_context": "test reporter context",
        "report_style": "news",
        "locale": "en-US",
    }
    messages_news = apply_prompt_template("reporter", test_state_news)
    system_content_news = messages_news[0]["content"]
    assert "NBC News" in system_content_news

    test_state_social_media_en = {
        "messages": [],
        "task": "test reporter task",
        "workspace_context": "test reporter context",
        "report_style": "social_media",
        "locale": "en-US",
    }
    messages_default = apply_prompt_template("reporter", test_state_social_media_en)
    system_content_default = messages_default[0]["content"]
    assert "Twitter/X" in system_content_default

    test_state_social_media_cn = {
        "messages": [],
        "task": "test reporter task",
        "workspace_context": "test reporter context",
        "report_style": "social_media",
        "locale": "zh-CN",
    }
    messages_cn = apply_prompt_template("reporter", test_state_social_media_cn)
    system_content_cn = messages_cn[0]["content"]
    assert "小红书" in system_content_cn
