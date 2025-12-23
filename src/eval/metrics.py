# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Automated metrics for report quality evaluation.

These metrics can be computed without LLM calls, providing fast and
deterministic quality assessment.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from urllib.parse import urlparse


@dataclass
class ReportMetrics:
    """Container for computed report metrics."""

    word_count: int = 0
    citation_count: int = 0
    unique_sources: int = 0
    image_count: int = 0
    section_count: int = 0
    sections_found: List[str] = field(default_factory=list)
    sections_missing: List[str] = field(default_factory=list)
    section_coverage_score: float = 0.0
    has_title: bool = False
    has_key_points: bool = False
    has_overview: bool = False
    has_citations_section: bool = False

    def to_dict(self) -> Dict:
        """Convert metrics to dictionary."""
        return {
            "word_count": self.word_count,
            "citation_count": self.citation_count,
            "unique_sources": self.unique_sources,
            "image_count": self.image_count,
            "section_count": self.section_count,
            "sections_found": self.sections_found,
            "sections_missing": self.sections_missing,
            "section_coverage_score": self.section_coverage_score,
            "has_title": self.has_title,
            "has_key_points": self.has_key_points,
            "has_overview": self.has_overview,
            "has_citations_section": self.has_citations_section,
        }


# Required sections for different report styles
REPORT_STYLE_SECTIONS = {
    "default": [
        "title",
        "key_points",
        "overview",
        "detailed_analysis",
        "key_citations",
    ],
    "academic": [
        "title",
        "key_points",
        "overview",
        "detailed_analysis",
        "literature_review",
        "methodology",
        "key_citations",
    ],
    "news": [
        "title",
        "key_points",
        "overview",
        "detailed_analysis",
        "key_citations",
    ],
    "popular_science": [
        "title",
        "key_points",
        "overview",
        "detailed_analysis",
        "key_citations",
    ],
    "social_media": [
        "title",
        "key_points",
        "overview",
        "key_citations",
    ],
    "strategic_investment": [
        "title",
        "key_points",
        "overview",
        "detailed_analysis",
        "executive_summary",
        "market_analysis",
        "technology_analysis",
        "investment_recommendations",
        "key_citations",
    ],
}

# Section name patterns for detection (supports both English and Chinese)
SECTION_PATTERNS = {
    "title": r"^#\s+.+",
    "key_points": r"(?:key\s*points|要点|关键发现|核心观点)",
    "overview": r"(?:overview|概述|简介|背景)",
    "detailed_analysis": r"(?:detailed\s*analysis|详细分析|深度分析|分析)",
    "key_citations": r"(?:key\s*citations|references|参考文献|引用|来源)",
    "literature_review": r"(?:literature\s*review|文献综述|研究回顾)",
    "methodology": r"(?:methodology|方法论|研究方法)",
    "executive_summary": r"(?:executive\s*summary|执行摘要|投资建议)",
    "market_analysis": r"(?:market\s*analysis|市场分析|产业分析)",
    "technology_analysis": r"(?:technology|技术.*(?:分析|解析|深度))",
    "investment_recommendations": r"(?:investment.*recommend|投资建议|投资评级)",
}


def count_words(text: str) -> int:
    """Count words in text, handling both English and Chinese."""
    english_words = len(re.findall(r"\b[a-zA-Z]+\b", text))
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    return english_words + chinese_chars


def count_citations(text: str) -> int:
    """Count markdown-style citations [text](url)."""
    pattern = r"\[.+?\]\(https?://[^\s\)]+\)"
    return len(re.findall(pattern, text))


def extract_domains(text: str) -> List[str]:
    """Extract unique domains from URLs in the text."""
    url_pattern = r"https?://([^\s\)\]]+)"
    urls = re.findall(url_pattern, text)
    domains = set()
    for url in urls:
        try:
            parsed = urlparse(f"http://{url}")
            domain = parsed.netloc or url.split("/")[0]
            domain = domain.lower().replace("www.", "")
            if domain:
                domains.add(domain)
        except Exception:
            continue
    return list(domains)


def count_images(text: str) -> int:
    """Count markdown images ![alt](url)."""
    pattern = r"!\[.*?\]\(.+?\)"
    return len(re.findall(pattern, text))


def detect_sections(text: str, report_style: str = "default") -> Dict[str, bool]:
    """Detect which sections are present in the report."""
    required_sections = REPORT_STYLE_SECTIONS.get(
        report_style, REPORT_STYLE_SECTIONS["default"]
    )
    detected = {}

    text_lower = text.lower()

    for section in required_sections:
        pattern = SECTION_PATTERNS.get(section, section.replace("_", r"\s*"))
        if section == "title":
            detected[section] = bool(re.search(pattern, text, re.MULTILINE))
        else:
            detected[section] = bool(
                re.search(pattern, text_lower, re.IGNORECASE | re.MULTILINE)
            )

    return detected


def compute_metrics(
    report: str, report_style: str = "default", target_word_count: Optional[int] = None
) -> ReportMetrics:
    """
    Compute automated metrics for a report.

    Args:
        report: The report text in markdown format
        report_style: The style of report (academic, news, etc.)
        target_word_count: Optional target word count for compliance check

    Returns:
        ReportMetrics object with computed values
    """
    metrics = ReportMetrics()

    metrics.word_count = count_words(report)
    metrics.citation_count = count_citations(report)

    domains = extract_domains(report)
    metrics.unique_sources = len(domains)

    metrics.image_count = count_images(report)

    sections_detected = detect_sections(report, report_style)
    metrics.sections_found = [s for s, found in sections_detected.items() if found]
    metrics.sections_missing = [
        s for s, found in sections_detected.items() if not found
    ]
    metrics.section_count = len(metrics.sections_found)

    total_sections = len(sections_detected)
    if total_sections > 0:
        metrics.section_coverage_score = len(metrics.sections_found) / total_sections

    metrics.has_title = sections_detected.get("title", False)
    metrics.has_key_points = sections_detected.get("key_points", False)
    metrics.has_overview = sections_detected.get("overview", False)
    metrics.has_citations_section = sections_detected.get("key_citations", False)

    return metrics


def get_word_count_target(report_style: str) -> Optional[Dict[str, int]]:
    """Get target word count range for a report style."""
    targets = {
        "strategic_investment": {"min": 10000, "max": 15000},
        "academic": {"min": 3000, "max": 8000},
        "news": {"min": 800, "max": 2000},
        "popular_science": {"min": 1500, "max": 4000},
        "social_media": {"min": 500, "max": 1500},
        "default": {"min": 1000, "max": 5000},
    }
    return targets.get(report_style, targets["default"])
