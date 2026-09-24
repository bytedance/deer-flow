"""Loopback-only example preview: real plugin/router/SQLite, synthetic identity.

The tool-dispatch endpoint uses real LangGraph ToolNode with a deterministic
tool call, not an external language model or the full production Gateway.
"""

import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import uvicorn
from deerflow_extension_api.auth import EXTENSION_PRINCIPAL_RESOLVER_KEY, ExtensionPrincipal
from fastapi import FastAPI, Request
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from app.gateway.routers.plugins import router
from deerflow.extensions.loader import ExtensionSpec, load_extensions
from deerflow.extensions.plugin_tools import build_plugin_tools


def create_app(directory):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "examples/deerflow-extension-bookmarks"))
    extensions, diagnostics = load_extensions([ExtensionSpec(use="deerflow_extension_bookmarks:install", config={"enabled": True, "storage_path": str(Path(directory) / "bookmarks.sqlite")}, required=True)])
    assert not diagnostics
    app = FastAPI()
    app.state.extensions = extensions

    @app.middleware("http")
    async def identity(request, call_next):
        request.state.user = SimpleNamespace(id=request.headers.get("x-test-user", "alice"), system_role="admin" if request.headers.get("x-test-role") == "admin" else "user")
        request.state.auth_source = "session"
        return await call_next(request)

    setattr(app.state, EXTENSION_PRINCIPAL_RESOLVER_KEY, lambda request: ExtensionPrincipal(request.state.user.id, is_admin=request.state.user.system_role == "admin"))
    app.include_router(router)

    @app.post("/test/model-search")
    async def model_search(request: Request):
        (tool,) = build_plugin_tools(extensions)
        graph = StateGraph(MessagesState)
        graph.add_node("tools", ToolNode([tool]))
        graph.add_edge(START, "tools")
        graph.add_edge("tools", END)
        body = await request.json()
        result = await graph.compile().ainvoke({"messages": [AIMessage(content="", tool_calls=[{"id": "example", "name": tool.name, "args": {"query": body["query"]}}])]}, context={"user_id": request.state.user.id})
        return {"tool": tool.name, "content": result["messages"][-1].content}

    return app


if __name__ == "__main__":
    with TemporaryDirectory(prefix="deerflow-bookmark-preview-") as directory:
        uvicorn.run(create_app(directory), host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
