"""Opt-in new Phase 1 checks using existing Wiki and indexed graph data.

No ingestion or resource mutations. Credentials are supplied by environment;
fixtures must contain attributable published entries and graph evidence.
"""

import json
import os
from pathlib import Path

import pytest

pytestmark = [pytest.mark.live, pytest.mark.asyncio]


def _required(*names):
    if os.getenv("DEER_FLOW_RUN_LIVE_TESTS") != "1":
        pytest.skip("live knowledge checks are opt-in")
    if any(not os.getenv(name) for name in names):
        pytest.fail("Set all documented live provider environment variables")
    return {name: os.environ[name] for name in names}


def _evidence(result):
    from deerflow.knowledge import format_result, sources_from_messages
    from deerflow.knowledge.sources import forward_sources, prune_sources

    content, artifact = format_result(result)
    message = json.loads(json.dumps({"type": "tool", "content": content, "artifact": artifact}))
    sources = sources_from_messages([message])
    assert sources, "Live fixture must return attributable evidence"
    for source in sources:
        assert source.page is None and source.url is None
        assert any(hit.source and source.title == hit.source.title and source.excerpt.rstrip("…") in hit.content for hit in result.hits)
    forwarded, envelope = forward_sources(content, [source.model_dump(mode="json") for source in sources])
    assert sources_from_messages([{"type": "tool", "content": forwarded, "artifact": envelope}]) == sources
    assert prune_sources("removed", artifact)[1]["knowledge_sources"] == []
    return sources


async def test_weknora_live_published_entries(monkeypatch):
    env = _required("WEKNORA_BASE_URL", "WEKNORA_TENANT_ID", "WEKNORA_WIKI_BASE_ID", "WEKNORA_API_KEY", "WEKNORA_WIKI_QUERY")
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "examples/deerflow-extension-weknora"))
    from deerflow_extension_weknora import WeKnoraProvider

    from deerflow.knowledge import KnowledgeRequestContext

    provider = WeKnoraProvider({"spaces": [{"base_url": env["WEKNORA_BASE_URL"], "tenant_id": env["WEKNORA_TENANT_ID"], "api_key_env": "WEKNORA_API_KEY", "user_ids": ["live-probe"], "knowledge_base_ids": [env["WEKNORA_WIKI_BASE_ID"]]}]})
    page = await provider.catalog(context=KnowledgeRequestContext("live-probe", "researcher"), page=1, page_size=100, search="")
    assert len(page.items) == 1
    scope = {"version": 1, "mode": "selected", "dataset_ids": [page.items[0].id]}
    result = await provider.entries_search(env["WEKNORA_WIKI_QUERY"], context=KnowledgeRequestContext("live-probe", "researcher", scope))
    assert all(source.provider == "weknora" for source in _evidence(result))
    with pytest.raises(PermissionError):
        await provider.entries_search(env["WEKNORA_WIKI_QUERY"], context=KnowledgeRequestContext("unbound", "researcher", scope))
    with pytest.raises(ValueError, match="document"):
        await provider.entries_search(env["WEKNORA_WIKI_QUERY"], context=KnowledgeRequestContext("live-probe", "researcher", {**scope, "document_filters": [{"dataset_id": page.items[0].id, "document_ids": ["unsupported"]}]}))


async def test_lightrag_live_relation_evidence(monkeypatch):
    env = _required("LIGHTRAG_BASE_URL", "LIGHTRAG_API_KEY", "LIGHTRAG_RELATION_QUERY")
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "examples/deerflow-extension-lightrag"))
    from deerflow_extension_lightrag import LightRAGProvider

    from deerflow.knowledge import KnowledgeRequestContext

    provider = LightRAGProvider({"base_url": env["LIGHTRAG_BASE_URL"], "api_key_env": "LIGHTRAG_API_KEY", "user_ids": ["live-probe"], "timeout": 120})
    result = await provider.relations_search(env["LIGHTRAG_RELATION_QUERY"], context=KnowledgeRequestContext("live-probe", "researcher"))
    assert any("Upstream relation (one edge):" in hit.content for hit in result.hits), "Live fixture must have actual relations"
    assert all(source.provider == "lightrag" for source in _evidence(result))
    for scope in ({"version": 1, "mode": "disabled"}, {"version": 1, "mode": "selected", "dataset_ids": ["unsupported"]}):
        with pytest.raises(ValueError):
            await provider.relations_search(env["LIGHTRAG_RELATION_QUERY"], context=KnowledgeRequestContext("live-probe", "researcher", scope))
    with pytest.raises(PermissionError):
        await provider.relations_search(env["LIGHTRAG_RELATION_QUERY"], context=KnowledgeRequestContext("unbound", "researcher"))


async def test_live_glm_three_tools_and_citations(monkeypatch):
    if os.getenv("KNOWLEDGE_RUN_MODEL_TEST") != "1":
        pytest.skip("generative model validation requires a separate opt-in")
    env = _required(
        "E2E_LLM_MODEL",
        "E2E_LLM_BASE_URL",
        "E2E_LLM_API_KEY",
        "KNOWLEDGE_MODEL_QUESTION",
        "WEKNORA_BASE_URL",
        "WEKNORA_TENANT_ID",
        "WEKNORA_WIKI_BASE_ID",
        "WEKNORA_KNOWLEDGE_BASE_ID",
        "WEKNORA_API_KEY",
        "LIGHTRAG_BASE_URL",
        "LIGHTRAG_API_KEY",
    )
    import re

    from langchain.agents import create_agent
    from langchain_core.messages import HumanMessage, ToolMessage
    from langchain_openai import ChatOpenAI

    for package in ("weknora", "lightrag"):
        monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / f"examples/deerflow-extension-{package}"))
    from deerflow_extension_lightrag import LightRAGProvider
    from deerflow_extension_weknora import WeKnoraProvider

    from deerflow.agents.middlewares.knowledge_scope_middleware import KnowledgeScopeMiddleware
    from deerflow.config.app_config import AppConfig
    from deerflow.config.sandbox_config import SandboxConfig
    from deerflow.config.tool_config import ToolConfig
    from deerflow.extensions import EXTENSION_SNAPSHOT_CONTEXT_KEY, ExtensionRegistry
    from deerflow.knowledge import sources_from_messages, tools
    from deerflow.knowledge.sources import forward_sources, prune_sources
    from deerflow.runtime.serialization import serialize_channel_values_for_api

    wiki = WeKnoraProvider(
        {
            "spaces": [
                {
                    "base_url": env["WEKNORA_BASE_URL"],
                    "tenant_id": env["WEKNORA_TENANT_ID"],
                    "api_key_env": "WEKNORA_API_KEY",
                    "user_ids": ["live-probe"],
                    "knowledge_base_ids": [env["WEKNORA_WIKI_BASE_ID"], env["WEKNORA_KNOWLEDGE_BASE_ID"]],
                }
            ]
        }
    )
    graph = LightRAGProvider({"base_url": env["LIGHTRAG_BASE_URL"], "api_key_env": "LIGHTRAG_API_KEY", "user_ids": ["live-probe"], "timeout": 120})
    registry = ExtensionRegistry()
    with registry.attributed_to("live:providers"):
        registry.knowledge_provider("weknora", wiki)
        registry.knowledge_provider("lightrag-relations", graph)
    mapping = {"knowledge_search": "weknora", "knowledge_entries_search": "weknora", "entity_relations_search": "lightrag-relations"}
    config = AppConfig(sandbox=SandboxConfig(use="example.remote:Sandbox"), tools=[ToolConfig(name=name, group="knowledge", use=f"deerflow.knowledge.tools:{name}_tool", provider=provider) for name, provider in mapping.items()])
    model = ChatOpenAI(model=env["E2E_LLM_MODEL"], base_url=env["E2E_LLM_BASE_URL"], api_key=env["E2E_LLM_API_KEY"], timeout=240, max_retries=0, extra_body=json.loads(os.getenv("E2E_LLM_EXTRA_BODY", "{}")))
    agent = create_agent(
        model,
        tools=[getattr(tools, name + "_tool") for name in mapping],
        middleware=[KnowledgeScopeMiddleware()],
        context_schema=dict,
        system_prompt="Use all three knowledge retrieval tools to answer the user's question from real evidence. Copy citation links exactly from tool output. Never invent locators or relations. State any tool failures.",
    )
    state = await agent.ainvoke(
        {"messages": [HumanMessage(content=env["KNOWLEDGE_MODEL_QUESTION"])]},
        context={"app_config": config, "user_id": "live-probe", "__knowledge_scope_execution": {"version": 1, "mode": "all"}, EXTENSION_SNAPSHOT_CONTEXT_KEY: registry.build()},
        config={"recursion_limit": 16},
    )
    messages = state["messages"]
    results = [message for message in messages if isinstance(message, ToolMessage)]
    assert set(mapping) <= {message.name for message in results}
    assert all(isinstance(message.content, str) and not message.content.startswith("Error:") for message in results)
    for name in mapping:
        assert sources_from_messages([message for message in results if message.name == name]), f"{name} must supply actual evidence"
    answer = messages[-1].content
    assert isinstance(answer, str)
    if os.getenv("KNOWLEDGE_EXPECT_CLEAN_ANSWER") == "1":
        for message in messages:
            if message.type == "ai" and isinstance(message.content, str):
                assert "<think>" not in message.content and "</think>" not in message.content
    cited = set(re.findall(r"#knowledge-source-([a-f0-9]{32})", answer))
    sources = sources_from_messages(messages)
    assert cited and cited <= {source.id for source in sources}
    history = json.loads(json.dumps(serialize_channel_values_for_api({"messages": messages})))
    assert sources_from_messages(history["messages"]) == sources
    report, envelope = forward_sources(answer, [source.model_dump(mode="json") for source in sources])
    assert {source.id for source in sources_from_messages([{"type": "tool", "content": report, "artifact": envelope}])} == cited
    assert prune_sources("removed", envelope)[1]["knowledge_sources"] == []
