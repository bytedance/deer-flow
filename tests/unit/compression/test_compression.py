# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Tests for the tool result compression system."""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from langchain_core.messages import AIMessage

from src.compression import (
    ArtifactMetadata,
    ArtifactStorageManager,
    CompressionInput,
    CompressionService,
    ToolResultCompression,
)


class TestToolResultCompression:
    """Test the ToolResultCompression Pydantic model."""

    def test_valid_compression_model(self):
        """Test creating a valid ToolResultCompression model."""
        model = ToolResultCompression(
            summary_title="Search Results for AI Market Trends",
            summary="The search returned 5 articles about AI market trends in 2024. Key findings include a 25% growth in enterprise AI adoption and increased investment in generative AI tools.",
            extraction=[
                "Enterprise AI adoption grew 25% in 2024",
                "Investment in generative AI tools increased by 40%",
                "Healthcare and finance sectors leading adoption",
            ],
            is_useful=True,
        )
        assert model.summary_title == "Search Results for AI Market Trends"
        assert len(model.extraction) == 3
        assert model.is_useful is True

    def test_compression_model_not_useful(self):
        """Test creating a compression model with is_useful=False."""
        model = ToolResultCompression(
            summary_title="Empty Search Results",
            summary="No results found for the given query.",
            extraction=[],
            is_useful=False,
        )
        assert model.is_useful is False
        assert len(model.extraction) == 0

    def test_summary_title_min_length_validation(self):
        """Test that summary_title has minimum length validation."""
        with pytest.raises(Exception):
            ToolResultCompression(
                summary_title="Hi",  # Too short
                summary="Valid summary content.",
                extraction=[],
                is_useful=True,
            )


class TestArtifactStorageManager:
    """Test the ArtifactStorageManager class."""

    def test_init(self):
        """Test initializing the storage manager."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ArtifactStorageManager(base_path=tmpdir)
            assert manager.base_path == Path(tmpdir)

    def test_sanitize_filename_component(self):
        """Test filename sanitization."""
        manager = ArtifactStorageManager()

        # Test basic sanitization
        assert manager._sanitize_filename_component("Test Plan") == "test_plan"
        assert manager._sanitize_filename_component("Test-Plan") == "test_plan"
        assert manager._sanitize_filename_component("Test@Plan!") == "testplan"

        # Test special characters
        assert manager._sanitize_filename_component("Test Plan 2024") == "test_plan_2024"
        assert manager._sanitize_filename_component("  Test  Plan  ") == "test_plan"

    def test_generate_filename(self):
        """Test deterministic filename generation."""
        manager = ArtifactStorageManager()

        filename = manager._generate_filename(
            plan_title="Test Research Plan",
            step_id="1",
            step_title="Initial Search",
            tool_name="web_search",
            extension="json",
        )

        assert filename == "test_research_plan__step1_initial_search__web_search.json"

    def test_get_plan_directory(self):
        """Test plan directory creation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ArtifactStorageManager(base_path=tmpdir)

            plan_dir = manager._get_plan_directory("Test Plan")
            assert plan_dir.exists()
            assert plan_dir.name == "test_plan"

    def test_save_raw_output_json(self):
        """Test saving raw JSON output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ArtifactStorageManager(base_path=tmpdir)

            input_data = CompressionInput(
                plan_title="Test Plan",
                step_id="1",
                step_title="Search Step",
                step_description="Search for information",
                tool_name="web_search",
                raw_output='{"results": [{"title": "Test"}]}',
            )

            artifact_file = manager.save_raw_output(input_data, input_data.raw_output)

            # Verify file was created
            file_path = Path(tmpdir) / artifact_file
            assert file_path.exists()

            # Verify content
            with open(file_path, "r") as f:
                content = json.load(f)
            assert content["results"][0]["title"] == "Test"

    def test_save_raw_output_text(self):
        """Test saving raw text output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ArtifactStorageManager(base_path=tmpdir)

            input_data = CompressionInput(
                plan_title="Test Plan",
                step_id="1",
                step_title="Analysis Step",
                step_description="Analyze data",
                tool_name="python_repl",
                raw_output="The analysis is complete.",
            )

            artifact_file = manager.save_raw_output(input_data, input_data.raw_output)

            # Verify file was created with .txt extension
            file_path = Path(tmpdir) / artifact_file
            assert file_path.exists()
            assert file_path.suffix == ".txt"

    def test_save_compression_metadata(self):
        """Test saving compression metadata."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ArtifactStorageManager(base_path=tmpdir)

            input_data = CompressionInput(
                plan_title="Test Plan",
                step_id="1",
                step_title="Search Step",
                step_description="Search for information",
                tool_name="web_search",
                raw_output='{"results": []}',
            )

            compression = ToolResultCompression(
                summary_title="Test Summary",
                summary="Test summary content",
                extraction=["Point 1", "Point 2"],
                is_useful=True,
            )

            manager.save_compression_metadata(input_data, compression, "test_file.json")

            # Verify metadata file was created
            metadata_files = list(Path(tmpdir).glob("*/*.meta.json"))
            assert len(metadata_files) == 1

            with open(metadata_files[0], "r") as f:
                metadata = json.load(f)

            assert metadata["summary_title"] == "Test Summary"
            assert metadata["is_useful"] is True
            assert metadata["artifact_file"] == "test_file.json"


class TestArtifactMetadata:
    """Test the ArtifactMetadata model."""

    def test_artifact_metadata_creation(self):
        """Test creating ArtifactMetadata."""
        metadata = ArtifactMetadata(
            summary_title="Test Summary",
            summary="Test summary content",
            extraction=["Point 1"],
            artifact_file="test_file.json",
        )
        assert metadata.artifact_file == "test_file.json"
        assert len(metadata.extraction) == 1


class TestCompressionInput:
    """Test the CompressionInput model."""

    def test_compression_input_creation(self):
        """Test creating CompressionInput."""
        input_data = CompressionInput(
            plan_title="Test Plan",
            step_id="1",
            step_title="Search Step",
            step_description="Search for information",
            tool_name="web_search",
            raw_output='{"results": []}',
        )
        assert input_data.plan_title == "Test Plan"
        assert input_data.tool_name == "web_search"


class TestCompressionService:
    """Test the CompressionService class."""

    @pytest.mark.asyncio
    async def test_compress_tool_result_useful(self):
        """Test compressing a useful tool result."""
        # Create mock LLM
        mock_llm = AsyncMock()
        mock_response = Mock()
        mock_response.content = json.dumps({
            "summary_title": "Search Results",
            "summary": "Found 5 relevant articles.",
            "extraction": ["Article 1", "Article 2"],
            "is_useful": True,
        })
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with tempfile.TemporaryDirectory() as tmpdir:
            storage_manager = ArtifactStorageManager(base_path=tmpdir)
            service = CompressionService(llm=mock_llm, storage_manager=storage_manager)

            input_data = CompressionInput(
                plan_title="Test Plan",
                step_id="1",
                step_title="Search Step",
                step_description="Search for information",
                tool_name="web_search",
                raw_output='{"results": [{"title": "Test"}]}',
            )

            result = await service.compress_tool_result(input_data)

            assert result is not None
            assert isinstance(result, ArtifactMetadata)
            assert result.summary_title == "Search Results"
            assert result.is_useful is True

            # Verify raw file was saved
            artifact_files = list(Path(tmpdir).glob("*/*.json"))
            assert len(artifact_files) >= 1

    @pytest.mark.asyncio
    async def test_compress_tool_result_not_useful(self):
        """Test compressing a non-useful tool result."""
        # Create mock LLM
        mock_llm = AsyncMock()
        mock_response = Mock()
        mock_response.content = json.dumps({
            "summary_title": "No Results",
            "summary": "No relevant information found.",
            "extraction": [],
            "is_useful": False,
        })
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with tempfile.TemporaryDirectory() as tmpdir:
            storage_manager = ArtifactStorageManager(base_path=tmpdir)
            service = CompressionService(llm=mock_llm, storage_manager=storage_manager)

            input_data = CompressionInput(
                plan_title="Test Plan",
                step_id="1",
                step_title="Search Step",
                step_description="Search for information",
                tool_name="web_search",
                raw_output='{"results": []}',
            )

            result = await service.compress_tool_result(input_data)

            # Should return None for non-useful results
            assert result is None

            # But raw file should still be saved
            artifact_files = list(Path(tmpdir).glob("*/*.json"))
            assert len(artifact_files) >= 1

    @pytest.mark.asyncio
    async def test_compress_tool_result_disabled(self):
        """Test that compression is skipped when disabled."""
        mock_llm = AsyncMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            storage_manager = ArtifactStorageManager(base_path=tmpdir)
            service = CompressionService(llm=mock_llm, storage_manager=storage_manager, enabled=False)

            input_data = CompressionInput(
                plan_title="Test Plan",
                step_id="1",
                step_title="Search Step",
                step_description="Search for information",
                tool_name="web_search",
                raw_output='{"results": []}',
            )

            result = await service.compress_tool_result(input_data)

            # Should return None when disabled
            assert result is None

            # LLM should not have been called
            assert not mock_llm.ainvoke.called

    def test_set_enabled(self):
        """Test enabling/disabling compression service."""
        mock_llm = Mock()
        service = CompressionService(llm=mock_llm)

        assert service.enabled is True

        service.set_enabled(False)
        assert service.enabled is False

        service.set_enabled(True)
        assert service.enabled is True

    @pytest.mark.asyncio
    async def test_invoke_compression_llm_with_json_code_block(self):
        """Test compression LLM invocation with JSON in code block."""
        mock_llm = AsyncMock()
        mock_response = Mock()
        mock_response.content = '''```json
        {
            "summary_title": "Test",
            "summary": "Test summary",
            "extraction": [],
            "is_useful": true
        }
        ```'''
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with tempfile.TemporaryDirectory() as tmpdir:
            storage_manager = ArtifactStorageManager(base_path=tmpdir)
            service = CompressionService(llm=mock_llm, storage_manager=storage_manager)

            input_data = CompressionInput(
                plan_title="Test Plan",
                step_id="1",
                step_title="Search Step",
                step_description="Search for information",
                tool_name="web_search",
                raw_output='{"results": []}',
            )

            result = await service.compress_tool_result(input_data)

            assert result is not None
            assert result.summary_title == "Test"

    @pytest.mark.asyncio
    async def test_invoke_compression_llm_with_invalid_json(self):
        """Test compression LLM invocation with invalid JSON."""
        mock_llm = AsyncMock()
        mock_response = Mock()
        mock_response.content = "This is not valid JSON"
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with tempfile.TemporaryDirectory() as tmpdir:
            storage_manager = ArtifactStorageManager(base_path=tmpdir)
            service = CompressionService(llm=mock_llm, storage_manager=storage_manager)

            input_data = CompressionInput(
                plan_title="Test Plan",
                step_id="1",
                step_title="Search Step",
                step_description="Search for information",
                tool_name="web_search",
                raw_output='{"results": []}',
            )

            # Should return None on JSON parse error
            result = await service.compress_tool_result(input_data)
            assert result is None
