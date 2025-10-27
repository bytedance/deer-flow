# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Keywords that indicate report editing intent
EDIT_KEYWORDS = [
    "modify",
    "edit",
    "change",
    "revise",
    "update",
    "improve",
    "enhance",
    "add section",
    "add chapter",
    "add content",
    "rewrite",
    "focus more",
    "more details",
    "expand",
    "detail",
    "clarify",
    "correct",
    "fix",
    "replace",
    "remove",
    "delete",
    "i'm not satisfied",
    "i don't like",
    "not happy with",
    "doesn't cover",
    "missing",
    "inadequate",
]


def detect_edit_intent(message: str, has_previous_report: bool = False) -> bool:
    """
    Detect if the user is trying to edit/modify a report.
    
    Args:
        message: The user's message
        has_previous_report: Whether there's a previous report in context
    
    Returns:
        True if edit intent is detected, False otherwise
    """
    if not has_previous_report:
        return False
    
    message_lower = message.lower().strip()
    
    # Check for explicit edit keywords
    for keyword in EDIT_KEYWORDS:
        if keyword in message_lower:
            logger.info(f"Edit intent detected with keyword: '{keyword}'")
            return True
    
    # Check for patterns like "section X", "part Y", "about Z" combined with action words
    if re.search(r'\b(section|part|chapter|area|topic|point|part|aspect)\b.*\b(more|better|different|changed|updated|improved)\b', message_lower):
        logger.info("Edit intent detected via section reference pattern")
        return True
    
    # Check for "I want the report to..." patterns
    if re.search(r"i\s+(want|need|would\s+like|prefer).*report.*\b(to|be|have|include)\b", message_lower):
        logger.info("Edit intent detected via 'I want the report' pattern")
        return True
    
    return False


def extract_edit_context(message: str, report: str) -> dict:
    """
    Extract which sections need to be edited and what feedback the user has.
    
    Args:
        message: The user's feedback message
        report: The current report content
    
    Returns:
        Dictionary with extracted context:
        {
            "sections": ["section_name1", "section_name2"],
            "feedback": "extracted user feedback",
            "action": "modify|add|enhance|replace"
        }
    """
    sections = []
    action = "modify"
    
    # Try to identify which sections are mentioned
    section_keywords = ["section", "part", "chapter", "point", "area", "topic", "paragraph"]
    message_lower = message.lower()
    
    for keyword in section_keywords:
        pattern = rf"{keyword}\s+(?:number\s+)?(\d+|about|on|covering|titled|called|named|\"[^\"]+\"|'[^']+'|[\w\s]+)"
        matches = re.findall(pattern, message_lower)
        if matches:
            logger.debug(f"Found section references using keyword '{keyword}': {matches}")
            sections.extend(matches)
    
    # Determine action type
    if any(word in message_lower for word in ["add", "include", "insert", "append"]):
        action = "add"
    elif any(word in message_lower for word in ["remove", "delete", "exclude"]):
        action = "remove"
    elif any(word in message_lower for word in ["improve", "enhance", "expand", "detail", "clarify"]):
        action = "enhance"
    elif any(word in message_lower for word in ["replace", "rewrite", "reword", "change"]):
        action = "replace"
    
    logger.info(f"Extracted edit context: action={action}, sections={len(sections)}, feedback_len={len(message)}")
    
    return {
        "sections": sections,
        "feedback": message,
        "action": action,
    }


def parse_report_sections(report: str) -> dict[str, str]:
    """
    Parse a report into its major sections.
    
    Tries to identify standard report sections based on markdown headers:
    - Title (# or ##)
    - Key Points
    - Overview
    - Detailed Analysis
    - Survey Note
    - Key Citations
    
    Args:
        report: The full report content
    
    Returns:
        Dictionary mapping section names to their content
        {
            "title": "...",
            "key_points": "...",
            "overview": "...",
            "detailed_analysis": "...",
            "survey_note": "...",
            "key_citations": "..."
        }
    """
    sections = {}
    
    # Split by markdown headers (# or ##)
    # Pattern: lines starting with # or ##, followed by section title
    header_pattern = r'^#{1,2}\s+(.+?)$'
    
    lines = report.split('\n')
    current_section = "header"
    current_content = []
    
    for line in lines:
        header_match = re.match(header_pattern, line)
        
        if header_match:
            # Save previous section before starting new one
            if current_content and current_section != "header":
                sections[current_section] = '\n'.join(current_content).strip()
            
            # Start new section
            section_title = header_match.group(1).strip().lower()
            # Normalize section names
            if "key point" in section_title:
                current_section = "key_points"
            elif "overview" in section_title:
                current_section = "overview"
            elif "detailed analysis" in section_title or "analysis" in section_title:
                current_section = "detailed_analysis"
            elif "survey" in section_title:
                current_section = "survey_note"
            elif "citation" in section_title or "reference" in section_title or "source" in section_title:
                current_section = "key_citations"
            else:
                current_section = section_title.replace(" ", "_").lower()
            
            current_content = [line]
        else:
            current_content.append(line)
    
    # Save last section
    if current_content and current_section:
        sections[current_section] = '\n'.join(current_content).strip()
    
    logger.info(f"Parsed report into {len(sections)} sections: {list(sections.keys())}")
    return sections


def merge_reports(
    original_report: str,
    new_findings: str,
    edit_context: dict,
    report_style: str = "academic",
    locale: str = "en-US"
) -> dict:
    """
    Prepare data for merging findings into existing report.
    
    This function processes the merge context to be passed to the reporter LLM.
    The actual merging is done by the reporter LLM using the report_editor prompt.
    
    Args:
        original_report: The existing report
        new_findings: Newly researched content
        edit_context: Context about what sections to modify
        report_style: Style of the report (academic, news, etc.)
        locale: Language locale
    
    Returns:
        Dictionary with merge context for reporter LLM
        {
            "original_report": "...",
            "new_findings": "...",
            "edit_action": "...",
            "target_sections": [...],
            "merge_instructions": "..."
        }
    """
    
    # Parse original report to understand structure
    original_sections = parse_report_sections(original_report)
    
    logger.info(
        f"Preparing merge context: action={edit_context.get('action')}, "
        f"sections={len(edit_context.get('sections', []))}"
    )
    
    merge_instructions = (
        f"Merge the new findings into the original report. "
        f"Action: {edit_context.get('action', 'modify')}. "
        f"User feedback: {edit_context.get('feedback', 'Improve and enhance the report.')}"
    )
    
    return {
        "original_report": original_report,
        "new_findings": new_findings,
        "edit_action": edit_context.get("action", "modify"),
        "target_sections": edit_context.get("sections", []),
        "merge_instructions": merge_instructions,
        "original_sections_count": len(original_sections),
        "report_style": report_style,
        "locale": locale,
    }
