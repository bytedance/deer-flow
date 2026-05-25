"""Unit tests for index_error_classifier."""

import pytest

from deerflow.knowledge_base.index_error_classifier import (
    classify_failures,
    classify_index_error,
)


class TestClassifyIndexError:
    def test_empty_result_variants(self):
        assert classify_index_error("empty_result: no text extracted") == "EMPTY_RESULT"
        assert classify_index_error("no text found in document") == "EMPTY_RESULT"
        assert classify_index_error("the file contains no content") == "EMPTY_RESULT"

    def test_encrypted_pdf_variants(self):
        assert classify_index_error("encrypted_pdf: cannot read") == "ENCRYPTED_PDF"
        assert classify_index_error("file is encrypted") == "ENCRYPTED_PDF"

    def test_unsupported_format_variants(self):
        assert classify_index_error("unsupported_format: .exe") == "UNSUPPORTED_FORMAT"
        assert classify_index_error("unsupported file type") == "UNSUPPORTED_FORMAT"

    def test_markitdown_unavailable(self):
        assert classify_index_error("markitdown_unavailable") == "MARKITDOWN_UNAVAILABLE"

    def test_dimension_mismatch_variants(self):
        assert classify_index_error("dimension mismatch: expected 1536 got 768") == "DIMENSION_MISMATCH"
        assert classify_index_error("embedding dimension mismatch") == "DIMENSION_MISMATCH"

    def test_internal_error(self):
        assert classify_index_error("internal_error: something went wrong") == "INTERNAL_ERROR"

    def test_none_returns_other(self):
        assert classify_index_error(None) == "OTHER"

    def test_unknown_error_returns_other(self):
        assert classify_index_error("some random unknown error message") == "OTHER"

    def test_empty_string_returns_other(self):
        assert classify_index_error("") == "OTHER"


class TestClassifyFailures:
    def test_empty_list(self):
        assert classify_failures([]) == {}

    def test_mixed_categories(self):
        jobs = [
            {"error": "empty_result: nothing there"},
            {"error": "empty_result: no text"},
            {"error": "encrypted_pdf: locked"},
            {"error": "some unknown issue"},
            {"error": "dimension mismatch: 1536 vs 768"},
        ]
        result = classify_failures(jobs)
        assert result == {
            "EMPTY_RESULT": 2,
            "ENCRYPTED_PDF": 1,
            "OTHER": 1,
            "DIMENSION_MISMATCH": 1,
        }

    def test_missing_error_key(self):
        jobs = [{"no_error_field": "whatever"}, {"error": "encrypted_pdf"}]
        result = classify_failures(jobs)
        assert result == {"OTHER": 1, "ENCRYPTED_PDF": 1}

    def test_case_insensitive(self):
        assert classify_index_error("Dimension Mismatch: expected 1536") == "DIMENSION_MISMATCH"
        assert classify_index_error("Encrypted_PDF: cannot open") == "ENCRYPTED_PDF"
