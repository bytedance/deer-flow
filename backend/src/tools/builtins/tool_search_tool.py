"""Tool search tool for dynamic tool discovery.

The function body is a fallback — actual execution is intercepted by
ToolSearchMiddleware.wrap_tool_call() which has access to the ToolCatalog.
This follows the same pattern as ask_clarification being intercepted by
ClarificationMiddleware.
"""

from langchain.tools import tool


@tool("tool_search", parse_docstring=True)
def tool_search_tool(
    query: str,
    mode: str = "auto",
    max_results: int = 5,
) -> str:
    """Search for specialized tools not currently loaded.

    Use this tool when your current tools are insufficient for the task at hand.
    After discovering tools, they will be automatically available for your next action.

    Search modes:
    - "auto": Automatically chooses the best search method (recommended)
    - "regex": Search by pattern matching on tool names and descriptions
    - "bm25": Search by natural language description

    Examples:
        tool_search(query="database SQL query")
        tool_search(query="clinical trials research")
        tool_search(query="stock price financial data")
        tool_search(query="worldbank.*indicator", mode="regex")

    Args:
        query: Search query - natural language description or regex pattern.
        mode: Search mode: "auto", "regex", or "bm25".
        max_results: Maximum number of results to return (1-10).

    Returns:
        List of matching tools with descriptions, or a message if no tools found.
    """
    # Fallback body: only runs if ToolSearchMiddleware is not active
    return "Tool search is not available. All tools are already loaded."
