"""Tests for Phase 1: Literature Ingestion.

Covers:
- URL normalization (arxiv_url.py):
    - arXiv prefix notation (arxiv:XXXX.XXXXX)
    - arXiv abs/pdf URL forms → canonical abs URL
    - DOI prefix notation and doi.org URLs
    - PubMed pmid: prefix and pubmed.ncbi.nlm.nih.gov URLs
    - Plain URLs pass through unchanged
    - Version suffixes preserved (e.g., 2310.06825v2)
    - Batch splitting respects OV concurrency limit (≤3)
- SKILL.md completeness:
    - Phase 1 sections 1A through 1E all present
    - URL normalization table documented
    - Bulk ingestion batching described
    - Verification query step documented
    - Acceptance criteria present
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from deerflow.utils.arxiv_url import (
    NormalizedURL,
    batch_urls,
    normalize_literature_url,
    normalize_literature_urls,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SKILL_MD = Path(__file__).parent.parent.parent / "skills" / "custom" / "sci-research" / "SKILL.md"


# ---------------------------------------------------------------------------
# arXiv normalization
# ---------------------------------------------------------------------------


class TestArxivNormalization:
    def test_prefix_notation(self):
        result = normalize_literature_url("arxiv:2310.06825")
        assert result.url == "https://arxiv.org/abs/2310.06825"
        assert result.source_type == "arxiv"
        assert result.identifier == "2310.06825"

    def test_prefix_notation_case_insensitive(self):
        result = normalize_literature_url("arXiv:2310.06825")
        assert result.url == "https://arxiv.org/abs/2310.06825"
        assert result.source_type == "arxiv"

    def test_abs_url(self):
        result = normalize_literature_url("https://arxiv.org/abs/2310.06825")
        assert result.url == "https://arxiv.org/abs/2310.06825"
        assert result.source_type == "arxiv"
        assert result.identifier == "2310.06825"

    def test_pdf_url_normalized_to_abs(self):
        """PDF URLs must be normalized to abs page (per SKILL.md URL normalization table)."""
        result = normalize_literature_url("https://arxiv.org/pdf/2310.06825")
        assert result.url == "https://arxiv.org/abs/2310.06825"
        assert result.source_type == "arxiv"

    def test_pdf_url_with_extension(self):
        result = normalize_literature_url("https://arxiv.org/pdf/2310.06825.pdf")
        assert result.url == "https://arxiv.org/abs/2310.06825"
        assert result.source_type == "arxiv"

    def test_version_suffix_preserved(self):
        result = normalize_literature_url("arxiv:2310.06825v2")
        assert result.url == "https://arxiv.org/abs/2310.06825v2"
        assert result.identifier == "2310.06825v2"

    def test_version_suffix_in_abs_url(self):
        result = normalize_literature_url("https://arxiv.org/abs/2406.12345v3")
        assert result.url == "https://arxiv.org/abs/2406.12345v3"
        assert result.identifier == "2406.12345v3"

    def test_html_url_normalized_to_abs(self):
        result = normalize_literature_url("https://arxiv.org/html/2310.06825")
        assert result.url == "https://arxiv.org/abs/2310.06825"
        assert result.source_type == "arxiv"


# ---------------------------------------------------------------------------
# DOI normalization
# ---------------------------------------------------------------------------


class TestDOINormalization:
    def test_prefix_notation(self):
        result = normalize_literature_url("doi:10.1038/s41586-021-03828-1")
        assert result.url == "https://doi.org/10.1038/s41586-021-03828-1"
        assert result.source_type == "doi"
        assert result.identifier == "10.1038/s41586-021-03828-1"

    def test_prefix_notation_case_insensitive(self):
        result = normalize_literature_url("DOI:10.1038/s41586-021-03828-1")
        assert result.source_type == "doi"

    def test_doi_org_url(self):
        result = normalize_literature_url("https://doi.org/10.1038/s41586-021-03828-1")
        assert result.url == "https://doi.org/10.1038/s41586-021-03828-1"
        assert result.source_type == "doi"
        assert result.identifier == "10.1038/s41586-021-03828-1"

    def test_dx_doi_org_url(self):
        result = normalize_literature_url("https://dx.doi.org/10.1038/s41586-021-03828-1")
        assert result.url == "https://doi.org/10.1038/s41586-021-03828-1"
        assert result.source_type == "doi"

    def test_http_doi_url(self):
        result = normalize_literature_url("http://doi.org/10.1016/j.cell.2021.01.001")
        assert result.url == "https://doi.org/10.1016/j.cell.2021.01.001"
        assert result.source_type == "doi"


# ---------------------------------------------------------------------------
# PubMed normalization
# ---------------------------------------------------------------------------


class TestPubMedNormalization:
    def test_pmid_prefix(self):
        result = normalize_literature_url("pmid:12345678")
        assert result.url == "https://pubmed.ncbi.nlm.nih.gov/12345678/"
        assert result.source_type == "pubmed"
        assert result.identifier == "12345678"

    def test_pmid_prefix_case_insensitive(self):
        result = normalize_literature_url("PMID:12345678")
        assert result.source_type == "pubmed"

    def test_pubmed_url(self):
        result = normalize_literature_url("https://pubmed.ncbi.nlm.nih.gov/12345678/")
        assert result.url == "https://pubmed.ncbi.nlm.nih.gov/12345678/"
        assert result.source_type == "pubmed"
        assert result.identifier == "12345678"

    def test_pubmed_url_without_trailing_slash(self):
        result = normalize_literature_url("https://pubmed.ncbi.nlm.nih.gov/12345678")
        assert result.url == "https://pubmed.ncbi.nlm.nih.gov/12345678/"
        assert result.source_type == "pubmed"


# ---------------------------------------------------------------------------
# Plain URL pass-through
# ---------------------------------------------------------------------------


class TestPlainURLPassThrough:
    def test_plain_https_url(self):
        url = "https://www.nature.com/articles/s41586-021-03828-1"
        result = normalize_literature_url(url)
        assert result.url == url
        assert result.source_type == "url"
        assert result.identifier == url

    def test_plain_http_url(self):
        url = "http://example.com/paper.pdf"
        result = normalize_literature_url(url)
        assert result.url == url
        assert result.source_type == "url"

    def test_whitespace_stripped(self):
        result = normalize_literature_url("  arxiv:2310.06825  ")
        assert result.url == "https://arxiv.org/abs/2310.06825"


# ---------------------------------------------------------------------------
# batch_urls
# ---------------------------------------------------------------------------


class TestBatchUrls:
    def _make_urls(self, n: int) -> list[NormalizedURL]:
        return [normalize_literature_url(f"arxiv:23{i:02d}.0{i:04d}") for i in range(1, n + 1)]

    def test_exact_batch_size(self):
        urls = self._make_urls(3)
        batches = batch_urls(urls, batch_size=3)
        assert len(batches) == 1
        assert len(batches[0]) == 3

    def test_splits_into_batches_of_3(self):
        """Default batch_size=3 matches OV concurrency limit."""
        urls = self._make_urls(7)
        batches = batch_urls(urls)
        assert len(batches) == 3  # 3, 3, 1
        assert len(batches[0]) == 3
        assert len(batches[1]) == 3
        assert len(batches[2]) == 1

    def test_single_url(self):
        urls = self._make_urls(1)
        batches = batch_urls(urls)
        assert len(batches) == 1
        assert len(batches[0]) == 1

    def test_empty_list(self):
        batches = batch_urls([])
        assert batches == []

    def test_invalid_batch_size_raises(self):
        with pytest.raises(ValueError, match="batch_size must be >= 1"):
            batch_urls(self._make_urls(3), batch_size=0)

    def test_custom_batch_size(self):
        urls = self._make_urls(10)
        batches = batch_urls(urls, batch_size=5)
        assert len(batches) == 2
        assert all(len(b) == 5 for b in batches)


# ---------------------------------------------------------------------------
# normalize_literature_urls (list variant)
# ---------------------------------------------------------------------------


class TestNormalizeList:
    def test_mixed_sources(self):
        raws = [
            "arxiv:2310.06825",
            "doi:10.1038/s41586-021-03828-1",
            "pmid:12345678",
            "https://example.com/paper",
        ]
        results = normalize_literature_urls(raws)
        assert len(results) == 4
        assert results[0].source_type == "arxiv"
        assert results[1].source_type == "doi"
        assert results[2].source_type == "pubmed"
        assert results[3].source_type == "url"

    def test_empty_strings_skipped(self):
        results = normalize_literature_urls(["arxiv:2310.06825", "", "   ", "pmid:111"])
        assert len(results) == 2

    def test_empty_list(self):
        assert normalize_literature_urls([]) == []


# ---------------------------------------------------------------------------
# NormalizedURL result type
# ---------------------------------------------------------------------------


class TestNormalizedURLType:
    def test_is_named_tuple(self):
        result = normalize_literature_url("arxiv:2310.06825")
        assert isinstance(result, tuple)
        assert hasattr(result, "url")
        assert hasattr(result, "source_type")
        assert hasattr(result, "identifier")

    def test_unpacking(self):
        url, source_type, identifier = normalize_literature_url("arxiv:2310.06825")
        assert url == "https://arxiv.org/abs/2310.06825"
        assert source_type == "arxiv"
        assert identifier == "2310.06825"


# ---------------------------------------------------------------------------
# SKILL.md completeness checks
# ---------------------------------------------------------------------------


class TestSkillMDCompleteness:
    @pytest.fixture(scope="class")
    def skill_content(self):
        assert SKILL_MD.exists(), f"SKILL.md not found at {SKILL_MD}"
        return SKILL_MD.read_text(encoding="utf-8")

    def test_phase1_section_exists(self, skill_content):
        assert "Phase 1" in skill_content or "Phase 1:" in skill_content

    def test_section_1a_namespace_setup(self, skill_content):
        """1A: Namespace setup must be documented."""
        assert "1A" in skill_content or "Namespace" in skill_content

    def test_section_1b_local_file_indexing(self, skill_content):
        """1B: Local file indexing via ov add-resource must be documented."""
        assert "1B" in skill_content or "ov add-resource" in skill_content

    def test_section_1c_url_ingestion(self, skill_content):
        """1C: URL ingestion (arXiv/DOI/PubMed) must be documented."""
        assert "1C" in skill_content or ("arXiv" in skill_content and "DOI" in skill_content and "PubMed" in skill_content)

    def test_section_1d_verification(self, skill_content):
        """1D: Verification step must be documented."""
        assert "1D" in skill_content or "Verification" in skill_content or "ov find" in skill_content

    def test_section_1e_ingestion_summary(self, skill_content):
        """1E: Ingestion summary report must be documented."""
        assert "1E" in skill_content or "Ingestion Summary" in skill_content or "Ingestion Complete" in skill_content

    def test_url_normalization_table_documented(self, skill_content):
        """SKILL.md must document the URL normalization table."""
        # All three source formats must be mentioned
        assert "arxiv" in skill_content.lower()
        assert "doi" in skill_content.lower()
        assert "pubmed" in skill_content.lower() or "pmid" in skill_content.lower()

    def test_bulk_ingestion_batching_documented(self, skill_content):
        """Batching strategy for ≥3 URLs must be mentioned."""
        assert "batch" in skill_content.lower() or "Batch" in skill_content

    def test_ov_add_resource_command_present(self, skill_content):
        assert "ov add-resource" in skill_content

    def test_acceptance_criteria_present(self, skill_content):
        assert "Acceptance" in skill_content or "acceptance" in skill_content or "score" in skill_content

    def test_error_handling_documented(self, skill_content):
        """Error/failure path (error_count > 0 or failed indexing) must be covered."""
        assert "error" in skill_content.lower() or "fail" in skill_content.lower()

    def test_ov_retriever_subagent_referenced(self, skill_content):
        assert "ov-retriever" in skill_content
