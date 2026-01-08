# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Citation management module for DeerFlow.

This module provides structured citation/source metadata handling
for research reports, enabling proper attribution and inline citations.
"""

from .models import Citation, CitationMetadata
from .collector import CitationCollector
from .formatter import CitationFormatter
from .extractor import (
    extract_citations_from_messages,
    merge_citations,
    citations_to_markdown_references,
)

__all__ = [
    "Citation",
    "CitationMetadata",
    "CitationCollector",
    "CitationFormatter",
    "extract_citations_from_messages",
    "merge_citations",
    "citations_to_markdown_references",
]
