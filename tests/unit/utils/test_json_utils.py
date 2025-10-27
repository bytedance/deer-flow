# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import json

from src.utils.json_utils import (
    _extract_json_from_content,
    repair_json_output,
    sanitize_tool_response,
)


class TestRepairJsonOutput:
    def test_valid_json_object(self):
        """Test with valid JSON object"""
        content = '{"key": "value", "number": 123}'
        result = repair_json_output(content)
        expected = json.dumps({"key": "value", "number": 123}, ensure_ascii=False)
        assert result == expected

    def test_valid_json_array(self):
        """Test with valid JSON array"""
        content = '[1, 2, 3, "test"]'
        result = repair_json_output(content)
        expected = json.dumps([1, 2, 3, "test"], ensure_ascii=False)
        assert result == expected

    def test_json_with_code_block_json(self):
        """Test JSON wrapped in ```json code block"""
        content = '```json\n{"key": "value"}\n```'
        result = repair_json_output(content)
        expected = json.dumps({"key": "value"}, ensure_ascii=False)
        assert result == expected

    def test_json_with_code_block_ts(self):
        """Test JSON wrapped in ```ts code block"""
        content = '```ts\n{"key": "value"}\n```'
        result = repair_json_output(content)
        expected = json.dumps({"key": "value"}, ensure_ascii=False)
        assert result == expected

    def test_malformed_json_repair(self):
        """Test with malformed JSON that can be repaired"""
        content = '{"key": "value", "incomplete":'
        result = repair_json_output(content)
        # Should return repaired JSON
        assert result.startswith('{"key": "value"')

    def test_non_json_content(self):
        """Test with non-JSON content"""
        content = "This is just plain text"
        result = repair_json_output(content)
        assert result == content

    def test_empty_string(self):
        """Test with empty string"""
        content = ""
        result = repair_json_output(content)
        assert result == ""

    def test_whitespace_only(self):
        """Test with whitespace only"""
        content = "   \n\t  "
        result = repair_json_output(content)
        assert result == ""

    def test_json_with_unicode(self):
        """Test JSON with unicode characters"""
        content = '{"name": "测试", "emoji": "🎯"}'
        result = repair_json_output(content)
        expected = json.dumps({"name": "测试", "emoji": "🎯"}, ensure_ascii=False)
        assert result == expected

    def test_json_code_block_without_closing(self):
        """Test JSON code block without closing```"""
        content = '```json\n{"key": "value"}'
        result = repair_json_output(content)
        expected = json.dumps({"key": "value"}, ensure_ascii=False)
        assert result == expected

    def test_json_repair_broken_json(self):
        """Test exception handling when JSON repair fails"""
        content = '{"this": "is", "completely": broken and unparseable'
        expect = '{"this": "is", "completely": "broken and unparseable"}'
        result = repair_json_output(content)
        assert result == expect

    def test_nested_json_object(self):
        """Test with nested JSON object"""
        content = '{"outer": {"inner": {"deep": "value"}}}'
        result = repair_json_output(content)
        expected = json.dumps(
            {"outer": {"inner": {"deep": "value"}}}, ensure_ascii=False
        )
        assert result == expected

    def test_json_array_with_objects(self):
        """Test JSON array containing objects"""
        content = '[{"id": 1, "name": "test1"}, {"id": 2, "name": "test2"}]'
        result = repair_json_output(content)
        expected = json.dumps(
            [{"id": 1, "name": "test1"}, {"id": 2, "name": "test2"}], ensure_ascii=False
        )
        assert result == expected

    def test_content_with_json_in_middle(self):
        """Test content that contains ```json in the middle"""
        content = 'Some text before ```json {"key": "value"} and after'
        result = repair_json_output(content)
        # Should attempt to process as JSON since it contains ```json
        assert isinstance(result, str)
        assert result == '{"key": "value"}'


class TestExtractJsonFromContent:
    def test_json_with_extra_tokens_after_closing_brace(self):
        """Test extracting JSON with extra tokens after closing brace"""
        content = '{"key": "value"} extra tokens here'
        result = _extract_json_from_content(content)
        assert result == '{"key": "value"}'

    def test_json_with_extra_tokens_after_closing_bracket(self):
        """Test extracting JSON array with extra tokens"""
        content = '[1, 2, 3] garbage data'
        result = _extract_json_from_content(content)
        assert result == '[1, 2, 3]'

    def test_nested_json_with_extra_tokens(self):
        """Test nested JSON with extra tokens"""
        content = '{"nested": {"inner": [1, 2, 3]}} invalid text'
        result = _extract_json_from_content(content)
        assert result == '{"nested": {"inner": [1, 2, 3]}}'

    def test_json_with_string_containing_braces(self):
        """Test JSON with strings containing braces"""
        content = '{"text": "this has {braces} in it"} extra'
        result = _extract_json_from_content(content)
        assert result == '{"text": "this has {braces} in it"}'

    def test_json_with_escaped_quotes(self):
        """Test JSON with escaped quotes in strings"""
        content = '{"text": "quote \\"here\\""} junk'
        result = _extract_json_from_content(content)
        assert result == '{"text": "quote \\"here\\""}'

    def test_clean_json_no_extra_tokens(self):
        """Test clean JSON without extra tokens"""
        content = '{"key": "value"}'
        result = _extract_json_from_content(content)
        assert result == '{"key": "value"}'

    def test_empty_object(self):
        """Test empty object"""
        content = '{} extra'
        result = _extract_json_from_content(content)
        assert result == '{}'

    def test_empty_array(self):
        """Test empty array"""
        content = '[] more stuff'
        result = _extract_json_from_content(content)
        assert result == '[]'

    def test_extra_closing_brace_no_opening(self):
        """Test that extra closing brace without opening is not marked as valid end"""
        content = '} garbage data'
        result = _extract_json_from_content(content)
        # Should return original content since no opening brace was seen
        assert result == content

    def test_extra_closing_bracket_no_opening(self):
        """Test that extra closing bracket without opening is not marked as valid end"""
        content = '] garbage data'
        result = _extract_json_from_content(content)
        # Should return original content since no opening bracket was seen
        assert result == content


class TestSanitizeToolResponse:
    def test_basic_sanitization(self):
        """Test basic tool response sanitization"""
        content = "normal response"
        result = sanitize_tool_response(content)
        assert result == "normal response"

    def test_json_with_extra_tokens(self):
        """Test sanitizing JSON with extra tokens"""
        content = '{"data": "value"} some garbage'
        result = sanitize_tool_response(content)
        assert result == '{"data": "value"}'

    def test_very_long_response_truncation(self):
        """Test truncation of very long responses"""
        long_content = "a" * 60000  # Exceeds default max of 50000
        result = sanitize_tool_response(long_content)
        assert len(result) <= 50003  # 50000 + "..."
        assert result.endswith("...")

    def test_custom_max_length(self):
        """Test custom maximum length"""
        long_content = "a" * 1000
        result = sanitize_tool_response(long_content, max_length=100)
        assert len(result) <= 103  # 100 + "..."
        assert result.endswith("...")

    def test_control_character_removal(self):
        """Test removal of control characters"""
        content = "text with \x00 null \x01 chars"
        result = sanitize_tool_response(content)
        assert "\x00" not in result
        assert "\x01" not in result

    def test_none_content(self):
        """Test handling of None content"""
        result = sanitize_tool_response("")
        assert result == ""

    def test_whitespace_handling(self):
        """Test whitespace handling"""
        content = "  text with spaces  "
        result = sanitize_tool_response(content)
        assert result == "text with spaces"

    def test_json_array_with_extra_tokens(self):
        """Test JSON array with extra tokens"""
        content = '[{"id": 1}, {"id": 2}] invalid stuff'
        result = sanitize_tool_response(content)
        assert result == '[{"id": 1}, {"id": 2}]'
