# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Citation management module for DeerFlow.

This module provides structured citation/source metadata handling
for research reports, enabling proper attribution and inline citations.
"""

from .collector import CitationCollector
from .extractor import (
    citations_to_markdown_references,
    extract_citations_from_messages,
    merge_citations,
)
from .formatter import CitationFormatter
from .models import Citation, CitationMetadata

__all__ = [
    "Citation",
    "CitationMetadata",
    "CitationCollector",
    "CitationFormatter",
    "extract_citations_from_messages",
    "merge_citations",
    "citations_to_markdown_references",
]
