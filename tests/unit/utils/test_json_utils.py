# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import json

from src.utils.json_utils import (
    _extract_json_from_content,
    repair_json_output,
    sanitize_args,
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

    def test_json_with_code_block_uppercase_json(self):
        """Test JSON wrapped in ```JSON (uppercase) code block"""
        content = '```JSON\n{"key": "value"}\n```'
        result = repair_json_output(content)
        expected = json.dumps({"key": "value"}, ensure_ascii=False)
        assert result == expected

    def test_json_with_code_block_uppercase_ts(self):
        """Test JSON wrapped in ```TS (uppercase) code block"""
        content = '```TS\n{"key": "value"}\n```'
        result = repair_json_output(content)
        expected = json.dumps({"key": "value"}, ensure_ascii=False)
        assert result == expected

    def test_json_with_code_block_mixed_case_json(self):
        """Test JSON wrapped in ```Json (mixed case) code block"""
        content = '```Json\n{"key": "value"}\n```'
        result = repair_json_output(content)
        expected = json.dumps({"key": "value"}, ensure_ascii=False)
        assert result == expected

    def test_json_with_code_block_uppercase_ts_with_prefix(self):
        """Test JSON wrapped in ```TS code block with prefix text"""
        content = 'some prefix ```TS\n{"key": "value"}\n```'
        result = repair_json_output(content)
        expected = json.dumps({"key": "value"}, ensure_ascii=False)
        assert result == expected

    def test_json_with_code_block_uppercase_json_with_prefix(self):
        """Test JSON wrapped in ```JSON code block with prefix text - case sensitive fix"""
        # This tests the fix for case-insensitive guard when fence is not at start
        content = 'prefix ```JSON\n{"key": "value"}\n```'
        result = repair_json_output(content)
        expected = json.dumps({"key": "value"}, ensure_ascii=False)
        assert result == expected

    def test_json_with_plain_code_block_uppercase(self):
        """Test JSON wrapped in plain ``` code block (case insensitive)"""
        content = '```\n{"key": "value"}\n```'
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


class TestSanitizeArgs:
    def test_sanitize_special_characters(self):
        """Test sanitization of special characters"""
        args = '{"key": "value", "array": [1, 2, 3]}'
        result = sanitize_args(args)
        assert result == '&#123;"key": "value", "array": &#91;1, 2, 3&#93;&#125;'

    def test_sanitize_square_brackets(self):
        """Test sanitization of square brackets"""
        args = '[1, 2, 3]'
        result = sanitize_args(args)
        assert result == '&#91;1, 2, 3&#93;'

    def test_sanitize_curly_braces(self):
        """Test sanitization of curly braces"""
        args = '{key: value}'
        result = sanitize_args(args)
        assert result == '&#123;key: value&#125;'

    def test_sanitize_mixed_brackets(self):
        """Test sanitization of mixed bracket types"""
        args = '{[test]}'
        result = sanitize_args(args)
        assert result == '&#123;&#91;test&#93;&#125;'

    def test_sanitize_non_string_input(self):
        """Test sanitization of non-string input returns empty string"""
        assert sanitize_args(None) == ""
        assert sanitize_args(123) == ""
        assert sanitize_args([1, 2, 3]) == ""
        assert sanitize_args({"key": "value"}) == ""

    def test_sanitize_empty_string(self):
        """Test sanitization of empty string"""
        result = sanitize_args("")
        assert result == ""

    def test_sanitize_plain_text(self):
        """Test sanitization of plain text without special characters"""
        args = "plain text without brackets or braces"
        result = sanitize_args(args)
        assert result == "plain text without brackets or braces"

    def test_sanitize_nested_structures(self):
        """Test sanitization of deeply nested structures"""
        args = '{"outer": {"inner": [1, [2, 3]]}}'
        result = sanitize_args(args)
        assert result == '&#123;"outer": &#123;"inner": &#91;1, &#91;2, 3&#93;&#93;&#125;&#125;'


class TestRepairJsonOutputEdgeCases:
    def test_code_block_with_leading_spaces(self):
        """Test code block with leading spaces"""
        content = '   ```json\n{"key": "value"}\n```'
        result = repair_json_output(content)
        expected = json.dumps({"key": "value"}, ensure_ascii=False)
        assert result == expected

    def test_code_block_with_tabs(self):
        """Test code block with tabs"""
        content = '\t```json\n{"key": "value"}\n```'
        result = repair_json_output(content)
        expected = json.dumps({"key": "value"}, ensure_ascii=False)
        assert result == expected

    def test_code_block_with_multiple_newlines(self):
        """Test code block with multiple newlines after opening fence"""
        content = '```json\n\n\n{"key": "value"}\n```'
        result = repair_json_output(content)
        expected = json.dumps({"key": "value"}, ensure_ascii=False)
        assert result == expected

    def test_code_block_with_spaces_before_closing(self):
        """Test code block with spaces before closing fence"""
        content = '```json\n{"key": "value"}\n  ```'
        result = repair_json_output(content)
        expected = json.dumps({"key": "value"}, ensure_ascii=False)
        assert result == expected

    def test_json_with_newlines_in_values(self):
        """Test JSON with newlines in string values"""
        content = '{"text": "line1\\nline2\\nline3"}'
        result = repair_json_output(content)
        expected = json.dumps({"text": "line1\nline2\nline3"}, ensure_ascii=False)
        assert result == expected

    def test_json_with_special_unicode(self):
        """Test JSON with special unicode characters"""
        content = '{"emoji": "🔥💯", "chinese": "中文测试", "math": "∑∫"}'
        result = repair_json_output(content)
        expected = json.dumps({"emoji": "🔥💯", "chinese": "中文测试", "math": "∑∫"}, ensure_ascii=False)
        assert result == expected

    def test_json_boolean_values(self):
        """Test JSON with boolean values"""
        content = '{"active": true, "disabled": false, "nullable": null}'
        result = repair_json_output(content)
        expected = json.dumps({"active": True, "disabled": False, "nullable": None}, ensure_ascii=False)
        assert result == expected

    def test_json_numeric_values(self):
        """Test JSON with various numeric values"""
        content = '{"int": 42, "float": 3.14159, "negative": -123, "scientific": 1.23e10}'
        result = repair_json_output(content)
        parsed = json.loads(result)
        assert parsed["int"] == 42
        assert parsed["float"] == 3.14159
        assert parsed["negative"] == -123

    def test_plain_code_block_marker(self):
        """Test plain ``` code block without language specifier"""
        content = '```\n{"key": "value"}\n```'
        result = repair_json_output(content)
        expected = json.dumps({"key": "value"}, ensure_ascii=False)
        assert result == expected

    def test_multiple_json_objects_takes_first_complete(self):
        """Test that multiple JSON objects are properly extracted"""
        content = '{"first": "object"} {"second": "object"}'
        result = repair_json_output(content)
        # json_repair will combine multiple objects into an array
        expected = json.dumps([{"first": "object"}, {"second": "object"}], ensure_ascii=False)
        assert result == expected

    def test_chinese_json_with_code_block(self):
        """Test JSON with Chinese content wrapped in markdown code block"""
        content = '''```json
{
  "locale": "en-US",
  "has_enough_context": true,
  "thought": "测试中文内容",
  "title": "地月距离小报告",
  "steps": []
}
```'''
        result = repair_json_output(content)
        parsed = json.loads(result)
        assert parsed["locale"] == "en-US"
        assert parsed["title"] == "地月距离小报告"
        assert parsed["thought"] == "测试中文内容"
        assert isinstance(parsed["steps"], list)

    def test_code_block_uppercase_json_with_leading_spaces(self):
        """Test uppercase JSON code block with leading spaces"""
        content = '   ```JSON\n{"key": "value"}\n```'
        result = repair_json_output(content)
        expected = json.dumps({"key": "value"}, ensure_ascii=False)
        assert result == expected

    def test_code_block_uppercase_json_with_tabs(self):
        """Test uppercase JSON code block with tabs"""
        content = '\t```JSON\n{"key": "value"}\n```'
        result = repair_json_output(content)
        expected = json.dumps({"key": "value"}, ensure_ascii=False)
        assert result == expected

    def test_code_block_mixed_case_with_multiple_newlines(self):
        """Test mixed case code block with multiple newlines"""
        content = '```JsOn\n\n\n{"key": "value"}\n```'
        result = repair_json_output(content)
        expected = json.dumps({"key": "value"}, ensure_ascii=False)
        assert result == expected

    def test_code_block_uppercase_with_spaces_before_closing(self):
        """Test uppercase code block with spaces before closing fence"""
        content = '```TYPESCRIPT\n{"key": "value"}\n  ```'
        result = repair_json_output(content)
        expected = json.dumps({"key": "value"}, ensure_ascii=False)
        assert result == expected

    def test_code_block_case_insensitive_various_languages(self):
        """Test code blocks with various language specifiers in different cases"""
        test_cases = [
            ('```Python\n{"key": "value"}\n```', '{"key": "value"}'),
            ('```PYTHON\n{"key": "value"}\n```', '{"key": "value"}'),
            ('```pYtHoN\n{"key": "value"}\n```', '{"key": "value"}'),
            ('```sql\n{"key": "value"}\n```', '{"key": "value"}'),
            ('```SQL\n{"key": "value"}\n```', '{"key": "value"}'),
        ]
        for content, expected_json_str in test_cases:
            result = repair_json_output(content)
            # Verify it's valid JSON
            parsed = json.loads(result)
            assert parsed["key"] == "value"


class TestExtractJsonFromContentEdgeCases:
    def test_deeply_nested_json(self):
        """Test extraction of deeply nested JSON"""
        content = '{"l1": {"l2": {"l3": {"l4": {"l5": "deep"}}}}} garbage'
        result = _extract_json_from_content(content)
        assert result == '{"l1": {"l2": {"l3": {"l4": {"l5": "deep"}}}}}'

    def test_json_array_of_arrays(self):
        """Test extraction of nested arrays"""
        content = '[[1, 2], [3, 4], [5, 6]] extra'
        result = _extract_json_from_content(content)
        assert result == '[[1, 2], [3, 4], [5, 6]]'

    def test_json_with_backslashes_in_string(self):
        """Test JSON with backslashes in string values"""
        content = r'{"path": "C:\\Users\\test\\file.txt"} garbage'
        result = _extract_json_from_content(content)
        assert result == r'{"path": "C:\\Users\\test\\file.txt"}'

    def test_json_with_forward_slashes(self):
        """Test JSON with forward slashes in string values"""
        content = '{"url": "https://example.com/path/to/resource"} extra'
        result = _extract_json_from_content(content)
        assert result == '{"url": "https://example.com/path/to/resource"}'

    def test_mixed_object_and_array(self):
        """Test JSON with mixed objects and arrays"""
        content = '{"items": [{"id": 1}, {"id": 2}], "count": 2} tail'
        result = _extract_json_from_content(content)
        assert result == '{"items": [{"id": 1}, {"id": 2}], "count": 2}'

    def test_json_with_unicode_escape_sequences(self):
        """Test JSON with unicode escape sequences"""
        content = r'{"text": "\u4E2D\u6587"} junk'
        result = _extract_json_from_content(content)
        assert result == r'{"text": "\u4E2D\u6587"}'

    def test_no_json_structure(self):
        """Test content without JSON structure"""
        content = 'just plain text without brackets'
        result = _extract_json_from_content(content)
        assert result == content

    def test_unbalanced_braces_in_middle(self):
        """Test content with unbalanced braces doesn't extract invalid JSON"""
        content = '{"incomplete": {"nested": } text'
        result = _extract_json_from_content(content)
        # Should not mark as valid end since braces are unbalanced
        assert result == content

    def test_json_with_comma_separated_values(self):
        """Test JSON object with multiple comma-separated values"""
        content = '{"a": 1, "b": 2, "c": 3, "d": 4, "e": 5} more text'
        result = _extract_json_from_content(content)
        assert result == '{"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}'


class TestSanitizeToolResponseEdgeCases:
    def test_json_object_with_extra_tokens(self):
        """Test sanitizing JSON object with trailing tokens"""
        content = '{"status": "success", "data": {"id": 123}} trailing garbage'
        result = sanitize_tool_response(content)
        assert result == '{"status": "success", "data": {"id": 123}}'

    def test_truncation_at_exact_boundary(self):
        """Test truncation behavior at exact max_length boundary"""
        content = "x" * 50000
        result = sanitize_tool_response(content, max_length=50000)
        assert len(result) == 50000
        assert not result.endswith("...")

    def test_truncation_one_over_boundary(self):
        """Test truncation when content is one char over limit"""
        content = "x" * 50001
        result = sanitize_tool_response(content, max_length=50000)
        assert len(result) <= 50003
        assert result.endswith("...")

    def test_multiple_control_characters(self):
        """Test removal of multiple types of control characters"""
        content = "text\x00with\x01various\x02control\x1Fchars\x7F"
        result = sanitize_tool_response(content)
        # All control characters should be removed
        assert "\x00" not in result
        assert "\x01" not in result
        assert "\x02" not in result
        assert "\x1F" not in result
        assert "\x7F" not in result
        assert "textwithvariouscontrolchars" == result

    def test_newline_and_tab_preservation(self):
        """Test that newlines and tabs are preserved (they are valid)"""
        content = "line1\nline2\tindented"
        result = sanitize_tool_response(content)
        assert "\n" in result
        assert "\t" in result
        assert result == "line1\nline2\tindented"

    def test_non_json_content_unchanged(self):
        """Test that non-JSON content is not modified"""
        content = "This is plain text without any JSON structure"
        result = sanitize_tool_response(content)
        assert result == content

    def test_json_array_at_start(self):
        """Test extraction of JSON array at start of content"""
        content = '[1, 2, 3, 4, 5] followed by text'
        result = sanitize_tool_response(content)
        assert result == '[1, 2, 3, 4, 5]'

    def test_empty_json_structures_preserved(self):
        """Test that empty JSON structures are preserved"""
        content = '{"empty_obj": {}, "empty_arr": []} extra'
        result = sanitize_tool_response(content)
        assert result == '{"empty_obj": {}, "empty_arr": []}'

    def test_whitespace_variations(self):
        """Test handling of various whitespace patterns"""
        content = "  \n\t  content with spaces  \t\n  "
        result = sanitize_tool_response(content)
        assert result == "content with spaces"
