"""Opt-in read-only WeKnora v0.8.3 integration; needs existing indexed evidence."""

import json
import os
from pathlib import Path

import pytest


@pytest.mark.live
@pytest.mark.asyncio
async def test_weknora_live_selected_document_evidence(monkeypatch):
    if os.getenv("DEER_FLOW_RUN_LIVE_TESTS") != "1":
        pytest.skip("live knowledge checks are opt-in")
    names = ["WEKNORA_BASE_URL", "WEKNORA_TENANT_ID", "WEKNORA_KNOWLEDGE_BASE_ID", "WEKNORA_DOCUMENT_ID", "WEKNORA_EVIDENCE_QUERY", "WEKNORA_API_KEY"]
    if any(not os.getenv(name) for name in names):
        pytest.fail("Set all documented WEKNORA_* variables for live verification")
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "examples/deerflow-extension-weknora"))
    from deerflow_extension_weknora import WeKnoraProvider

    from deerflow.knowledge import KnowledgeRequestContext, format_result, sources_from_messages

    provider = WeKnoraProvider(
        {"spaces": [{"base_url": os.environ["WEKNORA_BASE_URL"], "tenant_id": os.environ["WEKNORA_TENANT_ID"], "api_key_env": "WEKNORA_API_KEY", "user_ids": ["live-probe"], "knowledge_base_ids": [os.environ["WEKNORA_KNOWLEDGE_BASE_ID"]]}]}
    )
    context = KnowledgeRequestContext("live-probe", "lead_agent")
    catalog = await provider.catalog(context=context, page=1, page_size=100, search="")
    assert len(catalog.items) == 1, "Configured base must be visible"
    dataset_id = catalog.items[0].id
    document_id = os.environ["WEKNORA_DOCUMENT_ID"]
    # Traverse actual catalog pagination, not a guessed first-page selection.
    page = 1
    while True:
        documents = await provider.documents(dataset_id, context=context, page=page, page_size=100, search="")
        match = next((item for item in documents.items if item.id == document_id), None)
        if match:
            assert match.selectable, "Configured document must be searchable"
            break
        assert documents.items and page * 100 < documents.total and page < 100, "Configured document not found within the bounded live scan"
        page += 1
    scope = {"version": 1, "mode": "selected", "dataset_ids": [dataset_id], "document_filters": [{"dataset_id": dataset_id, "document_ids": [document_id]}]}
    result = await provider.search_scoped(os.environ["WEKNORA_EVIDENCE_QUERY"], context=KnowledgeRequestContext("live-probe", "lead_agent", scope))
    content, artifact = format_result(result)
    persisted = json.loads(json.dumps({"type": "tool", "content": content, "artifact": artifact}))
    sources = sources_from_messages([persisted])
    assert sources, "Live query must retrieve attributable document evidence"
    for source in sources:
        assert source.provider == "weknora" and source.page is None and source.url is None
        assert any(hit.source and hit.source.title == source.title and source.excerpt.rstrip("…") in hit.content for hit in result.hits)

    # Exercise the host's actual tool/artifact path with the live provider.
    # The AIMessage is deterministic: this checks tool execution, not LLM quality.
    from types import SimpleNamespace

    from langchain_core.messages import AIMessage
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langgraph.prebuilt import ToolNode

    from deerflow.extensions import EXTENSION_SNAPSHOT_CONTEXT_KEY, ExtensionRegistry
    from deerflow.knowledge import tools
    from deerflow.knowledge.sources import prune_sources
    from deerflow.runtime.serialization import serialize_channel_values_for_api
    from deerflow.tools.builtins.task_tool import _task_result_command

    registry = ExtensionRegistry()
    with registry.attributed_to("deerflow_extension_weknora:install"):
        registry.knowledge_provider("weknora", provider)
    config = SimpleNamespace(get_tool_config=lambda _: SimpleNamespace(use="deerflow.knowledge.tools:knowledge_search_tool", model_extra={"provider": "weknora"}))
    monkeypatch.setattr(tools, "get_app_config", lambda: config)
    builder = StateGraph(MessagesState, context_schema=dict)
    builder.add_node("tools", ToolNode([tools.knowledge_search_tool]))
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    state = await builder.compile().ainvoke(
        {"messages": [AIMessage(content="", tool_calls=[{"id": "live-search", "name": "knowledge_search", "args": {"query": os.environ["WEKNORA_EVIDENCE_QUERY"]}}])]},
        context={"user_id": "live-probe", "is_subagent": True, "agent_id": "researcher", "__knowledge_scope_execution": scope, EXTENSION_SNAPSHOT_CONTEXT_KEY: registry.build()},
    )
    message = state["messages"][-1]
    tool_sources = sources_from_messages([message])
    assert tool_sources and all(source.provider == "weknora" for source in tool_sources)
    history = json.loads(json.dumps(serialize_channel_values_for_api({"messages": [message]})))
    assert sources_from_messages(history["messages"]) == tool_sources
    forwarded = _task_result_command(tool_call_id="live-task", status="completed", result=message.content, knowledge_sources=[source.model_dump(mode="json", exclude_none=True) for source in tool_sources])
    assert sources_from_messages(forwarded.update["messages"]) == tool_sources
    _, pruned = prune_sources("removed by budget", message.artifact)
    assert pruned["knowledge_sources"] == []
    with pytest.raises(PermissionError):
        await provider.search_scoped("test", context=KnowledgeRequestContext("unbound-live-user", "lead_agent", scope))
