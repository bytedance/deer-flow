# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Citation extraction utilities for extracting citations from tool results.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from langchain_core.messages import ToolMessage, AIMessage

from .models import CitationMetadata

logger = logging.getLogger(__name__)


def extract_citations_from_messages(messages: List[Any]) -> List[Dict[str, Any]]:
    """
    Extract citation metadata from agent messages (tool calls/results).
    
    Args:
        messages: List of messages from agent execution
        
    Returns:
        List of citation dictionaries
    """
    citations = []
    seen_urls = set()
    
    logger.info(f"[Citations] Starting extraction from {len(messages)} messages")
    
    for message in messages:
        # Extract from ToolMessage results (web_search, crawl)
        if isinstance(message, ToolMessage):
            logger.info(f"[Citations] Found ToolMessage: name={getattr(message, 'name', 'unknown')}")
            tool_citations = _extract_from_tool_message(message)
            for citation in tool_citations:
                url = citation.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    citations.append(citation)
        
        # Also check AIMessage tool_calls for any embedded results
        if isinstance(message, AIMessage) and hasattr(message, "tool_calls"):
            for tool_call in (message.tool_calls or []):
                if tool_call.get("name") == "web_search":
                    # The query is in the args
                    query = tool_call.get("args", {}).get("query", "")
                    # Note: results come in subsequent ToolMessage
    
    logger.info(f"[Citations] Extracted {len(citations)} unique citations from {len(messages)} messages")
    return citations


def _extract_from_tool_message(message: ToolMessage) -> List[Dict[str, Any]]:
    """
    Extract citations from a tool message result.
    
    Args:
        message: ToolMessage with tool execution result
        
    Returns:
        List of citation dictionaries
    """
    citations = []
    tool_name = getattr(message, "name", "") or ""
    content = getattr(message, "content", "")
    
    logger.info(f"Processing tool message: tool_name='{tool_name}', content_len={len(str(content)) if content else 0}")
    
    if not content:
        return citations
    
    # Parse JSON content
    try:
        if isinstance(content, str):
            data = json.loads(content)
        else:
            data = content
    except (json.JSONDecodeError, TypeError):
        logger.debug(f"Could not parse tool message content as JSON: {str(content)[:100]}...")
        return citations
    
    logger.debug(f"Parsed tool message data type: {type(data).__name__}")
    
    # Try to detect content type by structure rather than just tool name
    tool_name_lower = tool_name.lower() if tool_name else ""
    
    # Handle web_search results (by name or by structure)
    if tool_name_lower in ("web_search", "tavily_search", "duckduckgo_search", "brave_search", "searx_search"):
        citations.extend(_extract_from_search_results(data))
        logger.debug(f"Extracted {len(citations)} citations from search tool '{tool_name}'")
    
    # Handle crawl results (by name or by structure)
    elif tool_name_lower in ("crawl_tool", "crawl", "jina_crawl"):
        citation = _extract_from_crawl_result(data)
        if citation:
            citations.append(citation)
            logger.debug(f"Extracted 1 citation from crawl tool '{tool_name}'")
    
    # Fallback: Try to detect by data structure
    else:
        # Check if it looks like search results (list of items with url)
        if isinstance(data, list) and len(data) > 0:
            first_item = data[0]
            if isinstance(first_item, dict) and "url" in first_item:
                logger.debug(f"Auto-detected search results format for tool '{tool_name}'")
                citations.extend(_extract_from_search_results(data))
        # Check if it looks like crawl result (dict with url and crawled_content)
        elif isinstance(data, dict) and "url" in data and ("crawled_content" in data or "content" in data):
            logger.debug(f"Auto-detected crawl result format for tool '{tool_name}'")
            citation = _extract_from_crawl_result(data)
            if citation:
                citations.append(citation)
    
    return citations


def _extract_from_search_results(data: Any) -> List[Dict[str, Any]]:
    """
    Extract citations from web search results.
    
    Args:
        data: Parsed JSON data from search tool
        
    Returns:
        List of citation dictionaries
    """
    citations = []
    
    # Handle list of results
    if isinstance(data, list):
        for result in data:
            if isinstance(result, dict) and result.get("type") != "image_url":
                citation = _result_to_citation(result)
                if citation:
                    citations.append(citation)
    
    # Handle dict with results key
    elif isinstance(data, dict):
        if "error" in data:
            logger.warning(f"Search error: {data.get('error')}")
            return citations
        
        results = data.get("results", [])
        for result in results:
            if isinstance(result, dict) and result.get("type") != "image_url":
                citation = _result_to_citation(result)
                if citation:
                    citations.append(citation)
    
    return citations


def _result_to_citation(result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Convert a search result to a citation dictionary.
    
    Args:
        result: Search result dictionary
        
    Returns:
        Citation dictionary or None
    """
    url = result.get("url", "")
    if not url:
        return None
    
    return {
        "url": url,
        "title": result.get("title", "Untitled"),
        "description": result.get("content", ""),
        "content_snippet": (result.get("content", "") or "")[:500],
        "relevance_score": result.get("score", 0.0),
        "domain": _extract_domain(url),
        "accessed_at": None,  # Will be filled by CitationMetadata
        "source_type": "web_search",
    }


def _extract_from_crawl_result(data: Any) -> Optional[Dict[str, Any]]:
    """
    Extract citation from crawl tool result.
    
    Args:
        data: Parsed JSON data from crawl tool
        
    Returns:
        Citation dictionary or None
    """
    if not isinstance(data, dict):
        return None
    
    url = data.get("url", "")
    if not url:
        return None
    
    content = data.get("crawled_content", "")
    
    # Try to extract title from content (first h1 or first line)
    title = "Untitled"
    if content:
        lines = content.strip().split("\n")
        for line in lines:
            line = line.strip()
            if line.startswith("# "):
                title = line[2:].strip()
                break
            elif line and not line.startswith("#"):
                title = line[:100]
                break
    
    return {
        "url": url,
        "title": title,
        "description": content[:300] if content else "",
        "content_snippet": content[:500] if content else "",
        "raw_content": content,
        "domain": _extract_domain(url),
        "source_type": "crawl",
    }


def _extract_domain(url: str) -> str:
    """Extract domain from URL."""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return parsed.netloc
    except Exception:
        return ""


def merge_citations(
    existing: List[Dict[str, Any]], 
    new: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Merge new citations into existing list, avoiding duplicates.
    
    Args:
        existing: Existing citations list
        new: New citations to add
        
    Returns:
        Merged list of citations
    """
    seen_urls = {c.get("url") for c in existing if c.get("url")}
    result = list(existing)
    
    for citation in new:
        url = citation.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            result.append(citation)
        elif url in seen_urls:
            # Update existing citation with potentially better data
            for i, existing_citation in enumerate(result):
                if existing_citation.get("url") == url:
                    # Prefer higher relevance score
                    if citation.get("relevance_score", 0) > existing_citation.get("relevance_score", 0):
                        result[i] = {**existing_citation, **citation}
                    break
    
    return result


def citations_to_markdown_references(citations: List[Dict[str, Any]]) -> str:
    """
    Convert citations list to markdown references section.
    
    Args:
        citations: List of citation dictionaries
        
    Returns:
        Markdown formatted references section
    """
    if not citations:
        return ""
    
    lines = ["## Key Citations", ""]
    
    for i, citation in enumerate(citations, 1):
        title = citation.get("title", "Untitled")
        url = citation.get("url", "")
        domain = citation.get("domain", "")
        description = citation.get("description", "")
        
        # Main reference link
        lines.append(f"- [{title}]({url})")
        
        # Add metadata as comment for parsing
        metadata_parts = []
        if domain:
            metadata_parts.append(f"domain: {domain}")
        if citation.get("relevance_score"):
            metadata_parts.append(f"score: {citation['relevance_score']:.2f}")
        
        if metadata_parts:
            lines.append(f"  <!-- {', '.join(metadata_parts)} -->")
        
        lines.append("")  # Empty line between citations
    
    return "\n".join(lines)
