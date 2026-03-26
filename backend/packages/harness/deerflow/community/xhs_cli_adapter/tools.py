import json

from langchain.tools import tool

from deerflow.config import get_app_config

from .xhs_cli import XhsCliAdapter, XhsCliError


def _resolve_search_config() -> tuple[str, int]:
    config = get_app_config().get_tool_config("xhs_search")
    executable = "xhs"
    default_pages = 1

    if config is not None:
        if "executable" in config.model_extra:
            executable = str(config.model_extra.get("executable") or "xhs")
        if "default_pages" in config.model_extra:
            try:
                default_pages = int(config.model_extra.get("default_pages"))
            except (TypeError, ValueError):
                default_pages = 1

    return executable, max(1, default_pages)


def _resolve_read_config() -> str:
    config = get_app_config().get_tool_config("xhs_read")
    if config is not None and "executable" in config.model_extra:
        return str(config.model_extra.get("executable") or "xhs")
    return "xhs"


@tool("xhs_search", parse_docstring=True)
def xhs_search_tool(query: str, pages: int | None = None) -> str:
    """Search Xiaohongshu (XHS) notes via the installed xhs CLI.

    Use this tool when users ask for Xiaohongshu renting/living/sharing posts,
    including trends, examples, and creator content discovery.

    Tool usage guidance:
    - Keep query concise, include city/community keywords when possible.
    - Start with 1 page; increase pages only when recall is insufficient.
    - This tool returns summaries only, not full post details.

    Args:
        query: Search keywords for Xiaohongshu.
        pages: Optional page count to fetch. If omitted, uses config default.
    """
    executable, default_pages = _resolve_search_config()
    resolved_pages = default_pages if pages is None else max(1, pages)
    adapter = XhsCliAdapter(executable=executable)

    try:
        result = adapter.search_posts(query=query, pages=resolved_pages)
    except XhsCliError as exc:
        return f"Error: XHS search failed: {exc}"

    payload = {
        "query": result.query,
        "page_count": result.page_count,
        "posts": [
            {
                "post_id": post.post_id,
                "title": post.title,
                "author_id": post.author_id,
                "author_nickname": post.author_nickname,
            }
            for post in result.posts
        ],
        "recommended_queries": result.recommended_queries,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


@tool("xhs_read", parse_docstring=True)
def xhs_read_tool(post_id: str, xsec_token: str | None = None) -> str:
    """Fetch Xiaohongshu (XHS) post detail by post id.

    Use this tool after xhs_search when you need full content, tags, and comments.

    Tool usage guidance:
    - Prefer calling xhs_search first to obtain valid post_id (and xsec_token if present).
    - If xsec_token is available from search results, pass it to improve detail retrieval success.

    Args:
        post_id: XHS note/post id.
        xsec_token: Optional xsec token associated with the post.
    """
    executable = _resolve_read_config()
    adapter = XhsCliAdapter(executable=executable)

    try:
        result = adapter.fetch_post_detail(post_id=post_id, xsec_token=xsec_token)
    except XhsCliError as exc:
        return f"Error: XHS read failed: {exc}"

    payload = {
        "post_id": result.post_id,
        "title": result.title,
        "content": result.content,
        "published_at": result.published_at,
        "updated_at": result.updated_at,
        "xsec_token": result.xsec_token,
        "tags": result.tags,
        "comments": [
            {
                "comment_id": comment.comment_id,
                "author_id": comment.author_id,
                "author_nickname": comment.author_nickname,
                "content": comment.content,
                "created_at": comment.created_at,
            }
            for comment in result.comments
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
