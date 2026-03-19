"""工具 search — deferred 工具 discovery at runtime.

Contains:
- DeferredToolRegistry: stores deferred tools and handles regex search
- tool_search: the LangChain 工具 the 代理 calls to discover deferred tools

The 代理 sees deferred 工具 names in <可用的-deferred-tools> but cannot
call them until it fetches their full schema via the tool_search 工具.
Source-agnostic: no mention of MCP or 工具 origin.
"""

import json
import logging
import re
from dataclasses import dataclass

from langchain.tools import BaseTool
from langchain_core.tools import tool
from langchain_core.utils.function_calling import convert_to_openai_function

logger = logging.getLogger(__name__)

MAX_RESULTS = 5  #    Max tools returned per search




#    ── Registry ──




@dataclass
class DeferredToolEntry:
    """Lightweight metadata for a deferred 工具 (no full schema in context)."""

    name: str
    description: str
    tool: BaseTool  #    Full 工具 对象, returned only on search match




class DeferredToolRegistry:
    """Registry of deferred tools, searchable by regex pattern."""

    def __init__(self):
        self._entries: list[DeferredToolEntry] = []

    def register(self, tool: BaseTool) -> None:
        self._entries.append(
            DeferredToolEntry(
                name=tool.name,
                description=tool.description or "",
                tool=tool,
            )
        )

    def search(self, query: str) -> list[BaseTool]:
        """Search deferred tools by regex pattern against 名称 + 描述.

        Supports three query forms (aligned with Claude Code):
          - "select:name1,name2" — exact 名称 match
          - "+keyword rest" — 名称 must contain keyword, rank by rest
          - "keyword query" — regex match against 名称 + 描述

        Returns:
            List of matched BaseTool objects (上 to MAX_RESULTS).
        """
        if query.startswith("select:"):
            names = {n.strip() for n in query[7:].split(",")}
            return [e.tool for e in self._entries if e.name in names][:MAX_RESULTS]

        if query.startswith("+"):
            parts = query[1:].split(None, 1)
            required = parts[0].lower()
            candidates = [e for e in self._entries if required in e.name.lower()]
            if len(parts) > 1:
                candidates.sort(
                    key=lambda e: _regex_score(parts[1], e),
                    reverse=True,
                )
            return [e.tool for e in candidates][:MAX_RESULTS]

        #    General regex search


        try:
            regex = re.compile(query, re.IGNORECASE)
        except re.error:
            regex = re.compile(re.escape(query), re.IGNORECASE)

        scored = []
        for entry in self._entries:
            searchable = f"{entry.name} {entry.description}"
            if regex.search(searchable):
                score = 2 if regex.search(entry.name) else 1
                scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry.tool for _, entry in scored][:MAX_RESULTS]

    @property
    def entries(self) -> list[DeferredToolEntry]:
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)


def _regex_score(pattern: str, entry: DeferredToolEntry) -> int:
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error:
        regex = re.compile(re.escape(pattern), re.IGNORECASE)
    return len(regex.findall(f"{entry.name} {entry.description}"))


#    ── Singleton ──



_registry: DeferredToolRegistry | None = None


def get_deferred_registry() -> DeferredToolRegistry | None:
    return _registry


def set_deferred_registry(registry: DeferredToolRegistry) -> None:
    global _registry
    _registry = registry


def reset_deferred_registry() -> None:
    """Reset the deferred registry singleton. Useful for testing."""
    global _registry
    _registry = None


#    ── 工具 ──




@tool
def tool_search(query: str) -> str:
    """Fetches full schema definitions for deferred tools so they can be called.

    Deferred tools appear by 名称 in <可用的-deferred-tools> in the 系统
    提示词. Until fetched, only the 名称 is known — there is no 参数
    schema, so the 工具 cannot be invoked. This 工具 takes a query, matches
    it against the deferred 工具 列表, and returns the matched tools' complete
    definitions. Once a 工具's schema appears in that 结果, it is callable.

    Query forms:
      - "select:Read,Edit,Grep" — fetch these exact tools by 名称
      - "notebook jupyter" — keyword search, 上 to max_results best matches
      - "+slack send" — require "slack" in the 名称, rank by remaining terms

    Args:
        query: Query to find deferred tools. Use "select:<tool_name>" for
               direct selection, or keywords to search.

    Returns:
        Matched 工具 definitions as JSON 数组.
    """
    registry = get_deferred_registry()
    if registry is None:
        return "No deferred tools available."

    matched_tools = registry.search(query)
    if not matched_tools:
        return f"No tools found matching: {query}"

    #    Use LangChain's built-in serialization to produce OpenAI 函数 format.


    #    This is 模型-agnostic: all LLMs understand this standard schema.


    tool_defs = [convert_to_openai_function(t) for t in matched_tools[:MAX_RESULTS]]

    return json.dumps(tool_defs, indent=2, ensure_ascii=False)
