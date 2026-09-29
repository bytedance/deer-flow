"""Standalone Pi-inspired plugin: persistence, ownership and real tool dispatch."""

import asyncio
import json
from pathlib import Path

import pytest
from deerflow_extension_api.auth import ExtensionPrincipal
from deerflow_extension_api.plugins import ActionContext
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from deerflow.extensions.loader import ExtensionSpec, load_extensions
from deerflow.extensions.plugin_tools import build_plugin_tools


@pytest.fixture
def bookmarks(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "examples/deerflow-extension-bookmarks"))

    def load():
        loaded, diagnostics = load_extensions([ExtensionSpec(use="deerflow_extension_bookmarks:install", config={"enabled": True, "storage_path": str(tmp_path / "bookmarks.sqlite")})])
        assert not diagnostics
        return loaded

    loaded = load()
    ((_, plugin),) = loaded.plugins
    actions = {action.name: action.handler for action in plugin.backend}
    return loaded, actions, load


def user(name):
    return ActionContext(ExtensionPrincipal(name), {"enabled": True})


@pytest.mark.asyncio
async def test_save_search_rename_delete_are_owner_scoped_and_persisted(bookmarks):
    _, actions, reload_plugin = bookmarks
    payload = {"thread_id": "thread-1", "message_id": "answer-1", "label": "Release notes", "text": "ORCHID launches on Friday."}
    saved = await actions["save"](payload, user("alice"))
    # Retrying save does not create duplicate bookmarks.
    assert (await actions["save"](payload, user("alice")))["id"] == saved["id"]
    assert (await actions["search"]({"query": "orchid"}, user("alice")))["items"][0]["text"] == payload["text"]
    assert (await actions["search"]({"query": ""}, user("bob")))["items"] == []
    for action, args in [("rename", {"id": saved["id"], "label": "Stolen"}), ("delete", {"id": saved["id"]})]:
        with pytest.raises(ValueError):
            await actions[action](args, user("bob"))
    await actions["rename"]({"id": saved["id"], "label": "Launch plan"}, user("alice"))
    ((_, plugin),) = reload_plugin().plugins
    search = next(a.handler for a in plugin.backend if a.name == "search")
    assert (await search({"query": "Launch plan"}, user("alice")))["items"][0]["label"] == "Launch plan"
    await actions["delete"]({"id": saved["id"]}, user("alice"))
    assert (await search({"query": ""}, user("alice")))["items"] == []


@pytest.mark.asyncio
async def test_concurrent_duplicate_save_and_payload_identity_rejection(bookmarks):
    _, actions, _ = bookmarks
    payload = {"thread_id": "t", "message_id": "m", "label": "One", "text": "Hello"}
    values = await asyncio.gather(*(actions["save"](payload, user("alice")) for _ in range(6)))
    assert len({v["id"] for v in values}) == 1
    with pytest.raises(ValueError):
        await actions["save"]({**payload, "user_id": "bob"}, user("alice"))
    with pytest.raises(ValueError):
        await actions["save"]({**payload, "text": "x" * 12001}, user("alice"))
    # Query is literal text, not SQL wildcard syntax.
    assert (await actions["search"]({"query": "%"}, user("alice")))["items"] == []


@pytest.mark.asyncio
async def test_model_tool_reads_only_authenticated_users_bookmarks(bookmarks):
    loaded, actions, _ = bookmarks
    await actions["save"]({"thread_id": "t", "message_id": "m", "label": "Release", "text": "ORCHID Friday"}, user("alice"))
    (tool,) = build_plugin_tools(loaded)
    assert "user_id" not in tool.tool_call_schema.get("properties", {})
    graph = StateGraph(MessagesState)
    graph.add_node("tools", ToolNode([tool]))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    runtime = graph.compile()
    for owner, count in [("alice", 1), ("bob", 0)]:
        result = await runtime.ainvoke({"messages": [AIMessage(content="", tool_calls=[{"name": tool.name, "args": {"query": "ORCHID"}, "id": "c"}])]}, context={"user_id": owner})
        assert len(json.loads(result["messages"][-1].content)["items"]) == count
