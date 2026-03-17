from typing import Annotated

from langchain.tools import InjectedToolCallId, ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.config import get_config
from langgraph.types import Command
from langgraph.typing import ContextT

from src.agents.thread_state import ThreadState
from src.research_writing.fulltext_ingest import LiteratureSource
from src.research_writing.runtime_service import ingest_fulltext_evidence


def _resolve_thread_id(runtime: ToolRuntime[ContextT, ThreadState]) -> str | None:
    ctx = runtime.context
    thread_id = ctx.get("thread_id") if (ctx is not None and hasattr(ctx, "get")) else None
    if thread_id:
        return thread_id
    try:
        return get_config().get("configurable", {}).get("thread_id")
    except RuntimeError:
        return None


@tool("research_fulltext_ingest", parse_docstring=True)
def research_fulltext_ingest_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    source: LiteratureSource,
    external_id: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
    persist: bool = True,
) -> Command:
    """Ingest fulltext/abstract literature and extract structured evidence units.

    Besides passage-level evidence, this tool also produces dynamic citation-graph RAG
    signals (co-citation edges + timeline narrative threads) for richer literature synthesis.

    Supports biomed and AI/CS sources:
    - pubmed
    - europe_pmc
    - openalex
    - dblp
    - arxiv

    Args:
        source: Literature source name.
        external_id: Source-specific id (e.g., PMID, PMCID, OpenAlex work id, DBLP key, arXiv id).
        persist: If true, persist extracted evidence/citation into thread research stores.
    """
    thread_id = _resolve_thread_id(runtime)
    if not thread_id:
        return Command(update={"messages": [ToolMessage("Error: thread_id is not available in runtime context", tool_call_id=tool_call_id)]})

    try:
        result = ingest_fulltext_evidence(
            thread_id=thread_id,
            source=source,
            external_id=external_id,
            persist=persist,
        )
    except Exception as exc:
        return Command(update={"messages": [ToolMessage(f"Error: research_fulltext_ingest failed: {exc}", tool_call_id=tool_call_id)]})

    narrative_threads = result.get("narrative_threads") or []
    thread_hint = "; ".join(str(item) for item in narrative_threads[:2]) if isinstance(narrative_threads, list) else ""
    msg = (
        "research_fulltext_ingest completed: "
        f"source={source}, external_id={external_id}, "
        f"evidence_count={result.get('evidence_count')}, "
        f"graph_evidence_count={len(result.get('graph_evidence_ids') or [])}, "
        f"citation_graph_nodes={result.get('citation_graph_node_count', 0)}, "
        f"co_citation_edges={result.get('co_citation_edge_count', 0)}, "
        f"literature_claims={result.get('literature_graph_claim_count', 0)}, "
        f"literature_edges={result.get('literature_graph_edge_count', 0)}"
    )
    if thread_hint:
        msg = f"{msg}, narrative_threads={thread_hint}"
    return Command(update={"artifacts": [result["artifact_path"]], "messages": [ToolMessage(msg, tool_call_id=tool_call_id)]})
