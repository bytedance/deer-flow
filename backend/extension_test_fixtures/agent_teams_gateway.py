"""Loopback-only team UI preview: real plugin routes, SQLite and graph checkpoints.

Identity and AgentRuns admission are synthetic. This is a browser fixture, not
production authentication or a substitute for Gateway run-control tests.
"""

import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import uvicorn
from deerflow_extension_api import AgentRun, AgentRunError
from deerflow_extension_api.agent_runs import AGENT_RUNS_RESOLVER_KEY
from deerflow_extension_api.auth import EXTENSION_PRINCIPAL_RESOLVER_KEY, ExtensionPrincipal
from deerflow_extension_api.plugins import ToolContext
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langgraph.checkpoint.memory import InMemorySaver

from app.gateway.routers.plugins import router
from deerflow.extensions.loader import ExtensionSpec, load_extensions


class PreviewRuns:
    def __init__(self):
        self.threads = {}
        self.runs = {}
        self.tasks = set()
        self.graph = create_agent(FakeListChatModel(responses=["Release evidence verified. See the shared team record."]), checkpointer=InMemorySaver())

    def bound(self, owner):
        host = self

        class Bound:
            def for_plugin(self, namespace):
                return self

            def check(self, thread_id):
                if host.threads.get(thread_id, {}).get("owner") != owner:
                    raise AgentRunError(404, "Thread unavailable")

            async def create_thread(self, *, assistant_id, thread_id, metadata):
                if thread_id in host.threads:
                    self.check(thread_id)
                host.threads.setdefault(thread_id, {"owner": owner, "assistant_id": assistant_id})
                return thread_id

            async def get_state(self, *, thread_id):
                self.check(thread_id)
                state = await host.graph.aget_state({"configurable": {"thread_id": thread_id}})
                if not state.values:
                    raise AgentRunError(404, "No checkpoint")
                return {"values": {"messages": [m.model_dump() for m in state.values["messages"]]}, "next": list(state.next)}

            async def start(self, *, thread_id, input, idempotency_key):
                self.check(thread_id)
                if idempotency_key in host.runs:
                    return host.runs[idempotency_key]
                if any(r.thread_id == thread_id and r.status == "running" for r in host.runs.values()):
                    raise AgentRunError(409, "Busy")
                run = AgentRun(thread_id, idempotency_key, "running", host.threads[thread_id]["assistant_id"])
                host.runs[idempotency_key] = run

                async def execute():
                    await host.graph.ainvoke(input, config={"configurable": {"thread_id": thread_id}})
                    host.runs[idempotency_key] = AgentRun(thread_id, idempotency_key, "success", run.assistant_id)

                task = asyncio.create_task(execute())
                host.tasks.add(task)
                task.add_done_callback(host.tasks.discard)
                return run

            async def get(self, *, thread_id, run_id):
                self.check(thread_id)
                return host.runs[run_id]

        return Bound()


def create_app(directory):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "examples/deerflow-extension-agent-teams"))
    extensions, diagnostics = load_extensions([ExtensionSpec(use="deerflow_extension_agent_teams:install", config={"enabled": True, "storage_path": str(Path(directory) / "teams.sqlite")}, required=True)])
    assert not diagnostics
    ((_, plugin),) = extensions.plugins
    service = plugin.backend[0].handler.__self__
    runs = PreviewRuns()

    @asynccontextmanager
    async def lifespan(app):
        await service.start(None)
        yield
        await service.stop()
        await asyncio.gather(*runs.tasks, return_exceptions=True)

    app = FastAPI(lifespan=lifespan)
    app.state.extensions = extensions

    @app.middleware("http")
    async def identity(request, call_next):
        request.state.user = SimpleNamespace(id=request.headers.get("x-test-user", "alice"), system_role="user")
        request.state.auth_source = "session"
        return await call_next(request)

    setattr(app.state, EXTENSION_PRINCIPAL_RESOLVER_KEY, lambda request: ExtensionPrincipal(request.state.user.id))
    setattr(app.state, AGENT_RUNS_RESOLVER_KEY, lambda request: runs.bound(request.state.user.id))
    app.include_router(router)

    @app.post("/preview/peer-request")
    async def peer_request(payload: dict, request: Request):
        owner = request.state.user.id
        return await service.send(
            {"team_id": payload["team_id"], "member_id": payload["member_id"], "text": payload["text"], "request_id": "browser-peer"},
            ToolContext(ExtensionPrincipal(owner), {"enabled": True}, payload["source_thread"], agent_runs=runs.bound(owner)),
        )

    @app.get("/api/agents")
    async def catalog():
        return {
            "agents": [
                {"name": "researcher", "display_name": "Research", "description": "Find and check source evidence"},
                {"name": "reviewer", "display_name": "Review", "description": "Independent quality review"},
                {"name": "writer", "display_name": "Writer", "description": "Write clear reports"},
            ]
        }

    @app.get("/", response_class=HTMLResponse)
    async def preview():
        return """<!doctype html><html lang="en"><meta charset="utf-8"><title>Agent teams preview</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{font:14px system-ui;background:#faf9f3;color:#252722;margin:0}
nav{height:56px;border-bottom:1px solid #e5e5de;padding:0 32px;display:flex;align-items:center;color:#777a72;font-size:12px}
main{max-width:1152px;margin:auto;padding:32px 40px;box-sizing:border-box}
h1{font-size:24px;font-weight:600;margin:0 0 24px}
@media(max-width:720px){main{padding:24px 20px}}
html.dark{--card:#24251f;--foreground:#eeeee8;--muted-foreground:#a2a49a;--border:#414239;--muted:#303128;--primary:#dbe4d6;--primary-foreground:#242d22}
html.dark body{background:#1c1d18;color:#eeeee8}</style>
<nav>Workspace　/　Agent teams</nav><main><h1>Agent teams</h1><div id="root"></div></main>
<script type="module">
const descriptors = await (await fetch('/api/plugins')).json();
const descriptor = descriptors.find(p => p.namespace === 'community.agent-teams');
const {default: plugin} = await import(descriptor.entry);
const context = {namespace: descriptor.namespace, locale: new URLSearchParams(location.search).get('locale') || 'en', settings: descriptor.settings,
signal: new AbortController().signal, openConversation: async id => {window.openedThread = id},
async callBackend(action,payload){
const response = await fetch(`/api/plugins/${descriptor.namespace}/actions/${action}`, {method:'POST',headers:{'Content-Type':'application/json','X-Deerflow-Plugin-Viewer':descriptor.viewer_id},body:JSON.stringify(payload)});
const result = await response.json(); if(!response.ok) throw new Error(result.detail); return result; }};
window.teamPlugin = plugin; window.teamContext = context;
const root = document.querySelector('#root').attachShadow({mode:'open'});
window.teamView = plugin.surfaces[0].mount(root, context);
</script></html>"""

    return app


if __name__ == "__main__":
    with TemporaryDirectory(prefix="deerflow-teams-preview-") as directory:
        uvicorn.run(create_app(directory), host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
