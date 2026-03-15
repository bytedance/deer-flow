"""Tool catalog with BM25 and regex search for dynamic tool discovery.

Indexes all available tools and provides search capabilities for the
ToolSearchMiddleware to use when the agent needs to discover deferred tools.
"""

import logging
import math
import re
from collections import Counter
from dataclasses import dataclass, field

from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)


def _tokenize(text: str) -> list[str]:
    """Tokenize text by splitting on whitespace, underscores, and hyphens."""
    return [t for t in re.split(r"[\s_\-/.,;:()]+", text.lower()) if t]


# ---------------------------------------------------------------------------
# JSON Schema → Python type hint mapping
# ---------------------------------------------------------------------------

_JSON_TYPE_MAP: dict[str, str] = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "null": "None",
}


def _json_type_to_python(schema: dict) -> str:
    """Map a JSON Schema property to a Python type hint string.

    Handles primitives, arrays (with item types), objects, anyOf/oneOf unions,
    and nested references.

    Args:
        schema: A JSON Schema property descriptor.

    Returns:
        Python type hint as a string (e.g. ``"str"``, ``"list[int]"``, ``"dict"``).
    """
    # anyOf / oneOf → Union-style
    for key in ("anyOf", "oneOf"):
        if key in schema:
            variants = schema[key]
            parts = []
            for v in variants:
                vtype = v.get("type")
                if vtype == "null":
                    continue  # skip null from Optional
                parts.append(_json_type_to_python(v))
            if not parts:
                return "Any"
            return parts[0] if len(parts) == 1 else f"{' | '.join(parts)}"

    json_type = schema.get("type")
    if json_type is None:
        return "Any"

    if json_type == "array":
        items_schema = schema.get("items", {})
        item_type = _json_type_to_python(items_schema)
        return f"list[{item_type}]"

    if json_type == "object":
        return "dict"

    return _JSON_TYPE_MAP.get(json_type, "Any")


# ---------------------------------------------------------------------------
# Parameter schema
# ---------------------------------------------------------------------------


@dataclass
class ToolParameterSchema:
    """Full schema for a single tool parameter.

    Used by the PTC code generator to produce typed wrapper functions.
    """

    name: str
    type_hint: str  # Python type string (e.g. "str", "int", "list[str]")
    description: str
    required: bool
    default: str | None = None  # repr string of default value, or None


# ---------------------------------------------------------------------------
# Tool entry
# ---------------------------------------------------------------------------


@dataclass
class ToolEntry:
    """Indexed metadata for a single tool."""

    name: str
    description: str
    parameter_names: list[str]
    parameters: list[ToolParameterSchema] = field(default_factory=list)
    server_name: str | None = None  # MCP server origin, or None for config/builtin
    is_core: bool = False  # True if tool should always be loaded
    tokens: list[str] = field(default_factory=list)  # pre-tokenized for BM25

    def __post_init__(self):
        if not self.tokens:
            # Tokenize name + description + parameter names for search
            text = f"{self.name} {self.description} {' '.join(self.parameter_names)}"
            self.tokens = _tokenize(text)


@dataclass
class ToolCatalog:
    """Indexes tools for search-based discovery.

    Supports two search modes:
    - regex: Match tool name or description against a Python regex pattern
    - bm25: Natural language search using BM25 ranking
    """

    entries: dict[str, ToolEntry] = field(default_factory=dict)
    _idf: dict[str, float] = field(default_factory=dict)
    _avg_dl: float = 0.0

    @classmethod
    def from_tools(
        cls,
        tools: list[BaseTool],
        core_tool_names: set[str],
        mcp_server_map: dict[str, str] | None = None,
    ) -> "ToolCatalog":
        """Build a catalog from a list of tools.

        Args:
            tools: All available tools.
            core_tool_names: Names of tools that should always be loaded.
            mcp_server_map: Optional mapping of tool_name -> MCP server_name.

        Returns:
            Populated ToolCatalog instance.
        """
        mcp_server_map = mcp_server_map or {}
        entries: dict[str, ToolEntry] = {}

        for tool in tools:
            if not isinstance(tool, BaseTool):
                continue

            # Extract parameter names and full schemas
            param_names: list[str] = []
            param_schemas: list[ToolParameterSchema] = []
            if hasattr(tool, "args_schema") and tool.args_schema is not None:
                try:
                    schema = tool.args_schema.model_json_schema()
                    properties = schema.get("properties", {})
                    required_set = set(schema.get("required", []))
                    param_names = list(properties.keys())

                    for pname, pschema in properties.items():
                        type_hint = _json_type_to_python(pschema)
                        desc = pschema.get("description", "")
                        is_required = pname in required_set
                        default_val = repr(pschema["default"]) if "default" in pschema else None
                        param_schemas.append(
                            ToolParameterSchema(
                                name=pname,
                                type_hint=type_hint,
                                description=desc,
                                required=is_required,
                                default=default_val,
                            )
                        )
                except Exception:
                    pass

            entry = ToolEntry(
                name=tool.name,
                description=tool.description or "",
                parameter_names=param_names,
                parameters=param_schemas,
                server_name=mcp_server_map.get(tool.name),
                is_core=tool.name in core_tool_names,
            )
            entries[tool.name] = entry

        catalog = cls(entries=entries)
        catalog._build_bm25_index()
        return catalog

    def _build_bm25_index(self) -> None:
        """Build IDF scores and average document length for BM25."""
        if not self.entries:
            return

        n = len(self.entries)
        df: Counter[str] = Counter()

        total_dl = 0
        for entry in self.entries.values():
            total_dl += len(entry.tokens)
            # Count unique terms per document for DF
            for term in set(entry.tokens):
                df[term] += 1

        self._avg_dl = total_dl / n if n > 0 else 0.0

        # IDF with smoothing: log((N - df + 0.5) / (df + 0.5) + 1)
        self._idf = {}
        for term, freq in df.items():
            self._idf[term] = math.log((n - freq + 0.5) / (freq + 0.5) + 1.0)

    def _bm25_score(self, query_tokens: list[str], entry: ToolEntry, k1: float = 1.5, b: float = 0.75) -> float:
        """Compute BM25 score for a single entry against query tokens."""
        dl = len(entry.tokens)
        tf: Counter[str] = Counter(entry.tokens)
        score = 0.0

        for qt in query_tokens:
            if qt not in self._idf:
                continue
            idf = self._idf[qt]
            term_freq = tf.get(qt, 0)
            numerator = term_freq * (k1 + 1)
            denominator = term_freq + k1 * (1 - b + b * dl / self._avg_dl) if self._avg_dl > 0 else term_freq + k1
            score += idf * (numerator / denominator)

        return score

    def search_regex(self, pattern: str, max_results: int = 10) -> list[ToolEntry]:
        """Search tools by regex pattern against name and description.

        Args:
            pattern: Python regex pattern.
            max_results: Maximum results to return.

        Returns:
            List of matching ToolEntry objects.
        """
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            logger.warning("Invalid regex pattern %r: %s", pattern, e)
            return []

        results: list[ToolEntry] = []
        for entry in self.entries.values():
            searchable = f"{entry.name} {entry.description}"
            if compiled.search(searchable):
                results.append(entry)
                if len(results) >= max_results:
                    break

        return results

    def search_bm25(self, query: str, max_results: int = 10) -> list[ToolEntry]:
        """Search tools by natural language query using BM25 ranking.

        Args:
            query: Natural language search query.
            max_results: Maximum results to return.

        Returns:
            List of ToolEntry objects ranked by relevance.
        """
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        scored: list[tuple[float, ToolEntry]] = []
        for entry in self.entries.values():
            score = self._bm25_score(query_tokens, entry)
            if score > 0:
                scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in scored[:max_results]]

    def search(
        self,
        query: str,
        mode: str = "auto",
        max_results: int = 10,
    ) -> list[ToolEntry]:
        """Unified search entry point.

        In 'auto' mode, uses regex if query contains regex special characters,
        otherwise uses BM25.

        Args:
            query: Search query string.
            mode: Search mode - "auto", "regex", or "bm25".
            max_results: Maximum results to return.

        Returns:
            List of matching ToolEntry objects.
        """
        if mode == "regex":
            return self.search_regex(query, max_results)
        elif mode == "bm25":
            return self.search_bm25(query, max_results)
        else:
            # Auto: use regex if query looks like a pattern
            if any(c in query for c in r".*+?[](){}|\\^$"):
                return self.search_regex(query, max_results)
            return self.search_bm25(query, max_results)

    def get_deferred_entries(self) -> list[ToolEntry]:
        """Return all non-core tool entries (the deferrable tools)."""
        return [e for e in self.entries.values() if not e.is_core]

    def get_tools_by_server(self) -> dict[str | None, list[ToolEntry]]:
        """Group all tool entries by their MCP server origin.

        Returns:
            Dict mapping server_name (or None for non-MCP tools) to list of entries.
        """
        by_server: dict[str | None, list[ToolEntry]] = {}
        for entry in self.entries.values():
            by_server.setdefault(entry.server_name, []).append(entry)
        return by_server

    def format_catalog_summary(self) -> str:
        """Format a brief summary of deferred tools for the system prompt.

        Groups deferred tools by MCP server origin and lists tool counts.

        Returns:
            Formatted string suitable for injection into the system prompt.
        """
        deferred = self.get_deferred_entries()
        if not deferred:
            return ""

        # Group by server name
        by_server: dict[str | None, list[ToolEntry]] = {}
        for entry in deferred:
            by_server.setdefault(entry.server_name, []).append(entry)

        lines: list[str] = []
        for server_name, entries in sorted(by_server.items(), key=lambda x: x[0] or ""):
            tool_names = ", ".join(e.name for e in entries)
            if server_name:
                lines.append(f"- {server_name} ({len(entries)} tools): {tool_names}")
            else:
                lines.append(f"- Uncategorized ({len(entries)} tools): {tool_names}")

        return (
            "<tool_search_system>\n"
            "You have access to additional specialized tools beyond those currently loaded.\n"
            "Use the `tool_search` tool to discover and activate them when needed.\n\n"
            "**Available tool categories (not yet loaded):**\n"
            + "\n".join(lines)
            + "\n\n"
            "**When to use `tool_search`:**\n"
            "- When you need capabilities not available in your current tools\n"
            "- When the user asks about domains covered by specialized tools (databases, financial data, biomedical, etc.)\n\n"
            "**How it works:**\n"
            "1. Call `tool_search(query=\"your search terms\")` to find relevant tools\n"
            "2. Found tools are automatically activated for your next action\n"
            "3. You do not need to search again for already-discovered tools\n"
            "</tool_search_system>"
        )
