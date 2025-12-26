# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import json
from unittest.mock import MagicMock, patch

import openai
import pytest

from src.podcast.graph.script_writer_node import script_writer_node
from src.podcast.types import Script, ScriptLine


class TestScriptWriterNode:
    """Tests for script_writer_node function."""

    @pytest.fixture
    def sample_state(self):
        """Create a sample podcast state."""
        return {"input": "Test content for podcast generation"}

    @pytest.fixture
    def sample_script(self):
        """Create a sample Script object."""
        return Script(
            locale="en",
            lines=[
                ScriptLine(speaker="male", paragraph="Hello, welcome to our podcast."),
                ScriptLine(speaker="female", paragraph="Today we discuss testing."),
            ],
        )

    @pytest.fixture
    def sample_script_json(self, sample_script):
        """Create JSON representation of sample script."""
        return sample_script.model_dump_json()

    @patch("src.podcast.graph.script_writer_node.get_prompt_template")
    @patch("src.podcast.graph.script_writer_node.get_llm_by_type")
    def test_script_writer_with_json_mode_success(
        self, mock_get_llm, mock_get_template, sample_state, sample_script
    ):
        """Test successful script generation using json_mode."""
        mock_get_template.return_value = "Generate a podcast script."

        mock_model = MagicMock()
        mock_structured_model = MagicMock()
        mock_model.with_structured_output.return_value = mock_structured_model
        mock_structured_model.invoke.return_value = sample_script
        mock_get_llm.return_value = mock_model

        result = script_writer_node(sample_state)

        assert result["script"] == sample_script
        assert result["audio_chunks"] == []
        mock_model.with_structured_output.assert_called_once_with(
            Script, method="json_mode"
        )

    @patch("src.podcast.graph.script_writer_node.get_prompt_template")
    @patch("src.podcast.graph.script_writer_node.get_llm_by_type")
    def test_script_writer_fallback_on_json_object_not_supported(
        self, mock_get_llm, mock_get_template, sample_state, sample_script_json
    ):
        """Test fallback to prompting when model doesn't support json_object."""
        mock_get_template.return_value = "Generate a podcast script."

        mock_model = MagicMock()
        mock_structured_model = MagicMock()
        mock_model.with_structured_output.return_value = mock_structured_model

        # Simulate json_object not supported error
        mock_structured_model.invoke.side_effect = openai.BadRequestError(
            message="json_object is not supported by this model",
            response=MagicMock(status_code=400),
            body={"error": {"message": "json_object is not supported"}},
        )

        # Mock the fallback response
        mock_response = MagicMock()
        mock_response.content = sample_script_json
        mock_model.invoke.return_value = mock_response

        mock_get_llm.return_value = mock_model

        result = script_writer_node(sample_state)

        assert result["script"].locale == "en"
        assert len(result["script"].lines) == 2
        assert result["audio_chunks"] == []
        # Verify fallback was used
        mock_model.invoke.assert_called_once()

    @patch("src.podcast.graph.script_writer_node.get_prompt_template")
    @patch("src.podcast.graph.script_writer_node.get_llm_by_type")
    def test_script_writer_reraises_other_bad_request_errors(
        self, mock_get_llm, mock_get_template, sample_state
    ):
        """Test that other BadRequestError types are re-raised."""
        mock_get_template.return_value = "Generate a podcast script."

        mock_model = MagicMock()
        mock_structured_model = MagicMock()
        mock_model.with_structured_output.return_value = mock_structured_model

        # Simulate a different BadRequestError (not json_object related)
        mock_structured_model.invoke.side_effect = openai.BadRequestError(
            message="Invalid model parameter",
            response=MagicMock(status_code=400),
            body={"error": {"message": "Invalid model parameter"}},
        )

        mock_get_llm.return_value = mock_model

        with pytest.raises(openai.BadRequestError) as exc_info:
            script_writer_node(sample_state)

        assert "Invalid model parameter" in str(exc_info.value)

    @patch("src.podcast.graph.script_writer_node.get_prompt_template")
    @patch("src.podcast.graph.script_writer_node.get_llm_by_type")
    def test_script_writer_fallback_with_markdown_wrapped_json(
        self, mock_get_llm, mock_get_template, sample_state
    ):
        """Test fallback handles JSON wrapped in markdown code blocks."""
        mock_get_template.return_value = "Generate a podcast script."

        mock_model = MagicMock()
        mock_structured_model = MagicMock()
        mock_model.with_structured_output.return_value = mock_structured_model

        mock_structured_model.invoke.side_effect = openai.BadRequestError(
            message="json_object is not supported",
            response=MagicMock(status_code=400),
            body={},
        )

        # Mock response with markdown-wrapped JSON (common LLM output)
        mock_response = MagicMock()
        mock_response.content = """```json
{
    "locale": "zh",
    "lines": [
        {"speaker": "male", "paragraph": "欢迎收听播客。"}
    ]
}
```"""
        mock_model.invoke.return_value = mock_response

        mock_get_llm.return_value = mock_model

        result = script_writer_node(sample_state)

        assert result["script"].locale == "zh"
        assert len(result["script"].lines) == 1
        assert result["script"].lines[0].speaker == "male"

    @patch("src.podcast.graph.script_writer_node.get_prompt_template")
    @patch("src.podcast.graph.script_writer_node.get_llm_by_type")
    def test_script_writer_fallback_raises_on_invalid_json(
        self, mock_get_llm, mock_get_template, sample_state
    ):
        """Test that fallback raises JSONDecodeError when response is not valid JSON."""
        mock_get_template.return_value = "Generate a podcast script."

        mock_model = MagicMock()
        mock_structured_model = MagicMock()
        mock_model.with_structured_output.return_value = mock_structured_model

        mock_structured_model.invoke.side_effect = openai.BadRequestError(
            message="json_object is not supported",
            response=MagicMock(status_code=400),
            body={},
        )

        # Mock response with completely invalid JSON
        mock_response = MagicMock()
        mock_response.content = "This is not JSON at all, just plain text response."
        mock_model.invoke.return_value = mock_response

        mock_get_llm.return_value = mock_model

        with pytest.raises(json.JSONDecodeError):
            script_writer_node(sample_state)

    @patch("src.podcast.graph.script_writer_node.get_prompt_template")
    @patch("src.podcast.graph.script_writer_node.get_llm_by_type")
    def test_script_writer_fallback_raises_on_invalid_schema(
        self, mock_get_llm, mock_get_template, sample_state
    ):
        """Test that fallback raises ValidationError when JSON doesn't match Script schema."""
        mock_get_template.return_value = "Generate a podcast script."

        mock_model = MagicMock()
        mock_structured_model = MagicMock()
        mock_model.with_structured_output.return_value = mock_structured_model

        mock_structured_model.invoke.side_effect = openai.BadRequestError(
            message="json_object is not supported",
            response=MagicMock(status_code=400),
            body={},
        )

        # Mock response with valid JSON but invalid schema (missing required fields, wrong types)
        mock_response = MagicMock()
        mock_response.content = '{"locale": "invalid_locale", "lines": "not_a_list"}'
        mock_model.invoke.return_value = mock_response

        mock_get_llm.return_value = mock_model

        # Pydantic ValidationError is raised when schema validation fails
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            script_writer_node(sample_state)
