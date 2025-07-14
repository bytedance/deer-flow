# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import json
from src.utils.json_utils import repair_json_output


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
