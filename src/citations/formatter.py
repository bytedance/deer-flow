# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Citation formatter for generating citation sections and inline references.
"""

import re
from typing import List, Dict, Optional, Tuple
from .models import Citation, CitationMetadata


class CitationFormatter:
    """
    Formats citations for display in reports.
    
    Supports multiple citation styles:
    - numbered: [1], [2], etc.
    - superscript: ¹, ², etc.
    - footnote: [^1], [^2], etc.
    - inline: (Author, Year) or (Source)
    """
    
    SUPERSCRIPT_MAP = {
        '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
        '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹'
    }
    
    def __init__(self, style: str = "numbered"):
        """
        Initialize the formatter.
        
        Args:
            style: Citation style ('numbered', 'superscript', 'footnote', 'inline')
        """
        self.style = style
    
    def format_inline_marker(self, number: int) -> str:
        """
        Format an inline citation marker.
        
        Args:
            number: The citation number
            
        Returns:
            Formatted marker string
        """
        if self.style == "superscript":
            return ''.join(self.SUPERSCRIPT_MAP.get(c, c) for c in str(number))
        elif self.style == "footnote":
            return f"[^{number}]"
        else:  # numbered
            return f"[{number}]"
    
    def format_reference(self, citation: Citation) -> str:
        """
        Format a single reference for the citations section.
        
        Args:
            citation: The citation to format
            
        Returns:
            Formatted reference string
        """
        metadata = citation.metadata
        
        # Build reference with available metadata
        parts = []
        
        # Number and title
        parts.append(f"[{citation.number}] **{metadata.title}**")
        
        # Author if available
        if metadata.author:
            parts.append(f"   *{metadata.author}*")
        
        # Domain/source
        if metadata.domain:
            parts.append(f"   Source: {metadata.domain}")
        
        # Published date if available
        if metadata.published_date:
            parts.append(f"   Published: {metadata.published_date}")
        
        # URL
        parts.append(f"   URL: {metadata.url}")
        
        # Description/snippet
        if metadata.description:
            snippet = metadata.description[:200]
            if len(metadata.description) > 200:
                snippet += "..."
            parts.append(f"   > {snippet}")
        
        return "\n".join(parts)
    
    def format_simple_reference(self, citation: Citation) -> str:
        """
        Format a simple reference (title + URL).
        
        Args:
            citation: The citation to format
            
        Returns:
            Simple reference string
        """
        return f"- [{citation.metadata.title}]({citation.metadata.url})"
    
    def format_rich_reference(self, citation: Citation) -> str:
        """
        Format a rich reference with metadata as JSON-like annotation.
        
        Args:
            citation: The citation to format
            
        Returns:
            Rich reference string with metadata
        """
        metadata = citation.metadata
        parts = [f"- [{metadata.title}]({metadata.url})"]
        
        annotations = []
        if metadata.domain:
            annotations.append(f"domain: {metadata.domain}")
        if metadata.relevance_score > 0:
            annotations.append(f"relevance: {metadata.relevance_score:.2f}")
        if metadata.accessed_at:
            annotations.append(f"accessed: {metadata.accessed_at[:10]}")
        
        if annotations:
            parts.append(f"  <!-- {', '.join(annotations)} -->")
        
        return "\n".join(parts)
    
    def format_citations_section(
        self, 
        citations: List[Citation],
        include_metadata: bool = True
    ) -> str:
        """
        Format the full citations section for a report.
        
        Args:
            citations: List of citations to include
            include_metadata: Whether to include rich metadata
            
        Returns:
            Formatted citations section markdown
        """
        if not citations:
            return ""
        
        lines = ["## Key Citations", ""]
        
        for citation in citations:
            if include_metadata:
                lines.append(self.format_rich_reference(citation))
            else:
                lines.append(self.format_simple_reference(citation))
            lines.append("")  # Empty line between citations
        
        return "\n".join(lines)
    
    def format_footnotes_section(self, citations: List[Citation]) -> str:
        """
        Format citations as footnotes (for footnote style).
        
        Args:
            citations: List of citations
            
        Returns:
            Footnotes section markdown
        """
        if not citations:
            return ""
        
        lines = ["", "---", ""]
        for citation in citations:
            lines.append(f"[^{citation.number}]: {citation.metadata.title} - {citation.metadata.url}")
        
        return "\n".join(lines)
    
    def add_citation_markers_to_text(
        self,
        text: str,
        citations: List[Citation],
        url_to_number: Dict[str, int]
    ) -> str:
        """
        Add citation markers to text where URLs are referenced.
        
        Args:
            text: The text to process
            citations: Available citations
            url_to_number: Mapping from URL to citation number
            
        Returns:
            Text with citation markers added
        """
        # Find all markdown links and add citation numbers
        def replace_link(match):
            full_match = match.group(0)
            link_text = match.group(1)
            url = match.group(2)
            
            if url in url_to_number:
                number = url_to_number[url]
                marker = self.format_inline_marker(number)
                return f"{full_match}{marker}"
            return full_match
        
        pattern = r'\[([^\]]+)\]\(([^)]+)\)'
        return re.sub(pattern, replace_link, text)
    
    @staticmethod
    def build_citation_data_json(citations: List[Citation]) -> str:
        """
        Build a JSON block containing citation data for frontend use.
        
        Args:
            citations: List of citations
            
        Returns:
            JSON string with citation data
        """
        import json
        
        data = {
            "citations": [c.to_dict() for c in citations],
            "count": len(citations),
        }
        
        return json.dumps(data, ensure_ascii=False)


def parse_citations_from_report(report: str) -> List[Tuple[str, str]]:
    """
    Parse citation links from a report's Key Citations section.
    
    Args:
        report: The report markdown text
        
    Returns:
        List of (title, url) tuples
    """
    citations = []
    
    # Find the Key Citations section
    section_pattern = r'(?:##\s*Key Citations|##\s*References|##\s*Sources)\s*\n(.*?)(?=\n##|\Z)'
    section_match = re.search(section_pattern, report, re.IGNORECASE | re.DOTALL)
    
    if section_match:
        section = section_match.group(1)
        
        # Extract markdown links
        link_pattern = r'\[([^\]]+)\]\(([^)]+)\)'
        for match in re.finditer(link_pattern, section):
            title = match.group(1)
            url = match.group(2)
            if url.startswith(('http://', 'https://')):
                citations.append((title, url))
    
    return citations
