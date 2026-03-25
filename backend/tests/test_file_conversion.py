"""Tests for file conversion utilities."""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from deerflow.utils.file_conversion import (
    convert_file_to_markdown,
    CONVERTIBLE_EXTENSIONS,
)


class TestConvertFileToMarkdown:
    """Tests for convert_file_to_markdown function."""

    @pytest.fixture
    def temp_pdf_file(self, tmp_path):
        """Create a temporary PDF file for testing."""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake pdf content")
        return pdf_file

    @pytest.mark.asyncio
    async def test_returns_none_for_unsupported_extension(self, tmp_path):
        """Should return None for unsupported file extensions."""
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("Plain text content")
        
        # txt is not in CONVERTIBLE_EXTENSIONS
        result = await convert_file_to_markdown(txt_file)
        
        # Function doesn't check extension, it tries to convert anyway
        # But markitdown will fail and return None
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_markitdown_fails(self, tmp_path):
        """Should return None when markitdown conversion fails."""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_text("Not a real PDF")
        
        result = await convert_file_to_markdown(pdf_file)
        
        assert result is None

    @pytest.mark.asyncio
    async def test_converts_pdf_to_markdown(self, tmp_path):
        """Should convert PDF file to markdown."""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake pdf content")
        
        # Mock MarkItDown to avoid actual conversion
        mock_result = Mock()
        mock_result.text_content = "# Converted Content\n\nThis is the converted markdown."
        
        with patch("deerflow.utils.file_conversion.MarkItDown") as MockMarkItDown:
            MockMarkItDown.return_value.convert.return_value = mock_result
            
            result = await convert_file_to_markdown(pdf_file)
            
            assert result is not None
            assert result.suffix == ".md"
            assert result.name == "test.md"
            assert result.parent == tmp_path
            
            # Verify the markdown content was written
            assert result.read_text(encoding="utf-8") == "# Converted Content\n\nThis is the converted markdown."

    @pytest.mark.asyncio
    async def test_converts_docx_to_markdown(self, tmp_path):
        """Should convert DOCX file to markdown."""
        docx_file = tmp_path / "document.docx"
        docx_file.write_bytes(b"fake docx content")
        
        mock_result = Mock()
        mock_result.text_content = "Document content"
        
        with patch("deerflow.utils.file_conversion.MarkItDown") as MockMarkItDown:
            MockMarkItDown.return_value.convert.return_value = mock_result
            
            result = await convert_file_to_markdown(docx_file)
            
            assert result is not None
            assert result.name == "document.md"

    @pytest.mark.asyncio
    async def test_handles_conversion_exception(self, tmp_path):
        """Should handle exceptions during conversion gracefully."""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 content")
        
        with patch("deerflow.utils.file_conversion.MarkItDown") as MockMarkItDown:
            MockMarkItDown.return_value.convert.side_effect = Exception("Conversion failed")
            
            result = await convert_file_to_markdown(pdf_file)
            
            assert result is None

    def test_convertible_extensions_defined(self):
        """CONVERTIBLE_EXTENSIONS should contain expected file types."""
        expected_extensions = {
            ".pdf",
            ".ppt",
            ".pptx",
            ".xls",
            ".xlsx",
            ".doc",
            ".docx",
        }
        assert CONVERTIBLE_EXTENSIONS == expected_extensions

    @pytest.mark.asyncio
    async def test_preserves_original_file(self, tmp_path):
        """Original file should not be modified during conversion."""
        pdf_file = tmp_path / "original.pdf"
        original_content = b"%PDF-1.4 original content"
        pdf_file.write_bytes(original_content)
        
        mock_result = Mock()
        mock_result.text_content = "Converted"
        
        with patch("deerflow.utils.file_conversion.MarkItDown") as MockMarkItDown:
            MockMarkItDown.return_value.convert.return_value = mock_result
            await convert_file_to_markdown(pdf_file)
        
        # Original file should be unchanged
        assert pdf_file.read_bytes() == original_content

    @pytest.mark.asyncio
    async def test_nonexistent_file_returns_none(self, tmp_path):
        """Should return None when file doesn't exist."""
        nonexistent = tmp_path / "does_not_exist.pdf"
        
        result = await convert_file_to_markdown(nonexistent)
        
        assert result is None
