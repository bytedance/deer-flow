"""Loopback-only team UI preview: real plugin routes, SQLite and graph checkpoints.

Identity and AgentRuns admission are synthetic. This is a browser fixture, not
production authentication or a substitute for Gateway run-control tests.
"""

import asyncio
import base64
import json
import os
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
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

from app.gateway.extension_artifacts import read_output_snapshot, write_import_snapshot
from app.gateway.routers.plugins import router
from deerflow.agents.middlewares.clarification_middleware import ClarificationMiddleware
from deerflow.config.paths import get_paths
from deerflow.extensions.loader import ExtensionSpec, load_extensions
from deerflow.tools.builtins.clarification_tool import ask_clarification_tool


class PreviewModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        latest = next(m for m in reversed(messages) if m.type == "human")
        response = latest.additional_kwargs.get("human_input_response")
        try:
            current_request = json.loads(latest.content.split("\n", 1)[1]).get("request", "")
        except (ValueError, IndexError):
            current_request = latest.content
        if response:
            answer = AIMessage(content=f"Clarification accepted: {response['value']}.")
        elif "Clarification fixture" in current_request:
            answer = AIMessage(content="", tool_calls=[{"name": "ask_clarification", "id": "clarify-environment", "args": {"question": "Which environment should I check?", "clarification_type": "missing_info"}, "type": "tool_call"}])
        else:
            answer = AIMessage(content="Release evidence verified. See the shared team record.")
        return ChatResult(generations=[ChatGeneration(message=answer)])


class PreviewRuns:
    def __init__(self):
        self.threads = {}
        self.runs = {}
        self.tasks = set()
        self.artifact_gate = asyncio.Event()
        self.graph = create_agent(PreviewModel(responses=[]), tools=[ask_clarification_tool], middleware=[ClarificationMiddleware()], checkpointer=InMemorySaver())

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
                return {"values": {"messages": [m.model_dump() for m in state.values["messages"]]}, "next": list(state.next), "checkpoint_id": state.config["configurable"]["checkpoint_id"]}

            async def validate_artifact_source(self, *, thread_id, run_id, idempotency_key):
                self.check(thread_id)
                run = host.runs.get(run_id)
                if run is None or run.thread_id != thread_id or run.status != "running" or run_id != idempotency_key:
                    raise AgentRunError(422, "Producing run is not executing")

            async def read_artifact(self, *, thread_id, path, expected_checkpoint_id=None):
                self.check(thread_id)
                if expected_checkpoint_id is not None and (await self.get_state(thread_id=thread_id))["checkpoint_id"] != expected_checkpoint_id:
                    raise AgentRunError(412, "Producing checkpoint changed")
                return await asyncio.to_thread(read_output_snapshot, owner, thread_id, path)

            async def import_artifact(self, *, thread_id, filename, content):
                self.check(thread_id)
                return await asyncio.to_thread(write_import_snapshot, owner, thread_id, "community.agent-teams", filename, content)

            async def start(self, *, thread_id, input, idempotency_key, artifact_imports=None):
                self.check(thread_id)
                if idempotency_key in host.runs:
                    return host.runs[idempotency_key]
                if any(r.thread_id == thread_id and r.status == "running" for r in host.runs.values()):
                    raise AgentRunError(409, "Busy")
                run = AgentRun(thread_id, idempotency_key, "running", host.threads[thread_id]["assistant_id"])
                host.runs[idempotency_key] = run

                async def execute():
                    if "Artifact fixture" in input["messages"][0]["content"]:
                        await host.artifact_gate.wait()
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
    os.environ["DEER_FLOW_HOME"] = str(directory)
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

    @app.post("/preview/state")
    async def public_state(payload: dict, request: Request):
        handlers = {"publish": service.publish_state, "read": service.read_state, "update": service.update_state}
        return await handlers[payload["operation"]](payload["input"], ToolContext(ExtensionPrincipal(request.state.user.id), {"enabled": True}, payload["source_thread"], agent_runs=runs.bound(request.state.user.id)))

    @app.post("/preview/artifact")
    async def artifact(payload: dict, request: Request):
        from deerflow_extension_api.plugins import ActionContext

        owner = request.state.user.id
        bound = runs.bound(owner)
        ctx = ActionContext(ExtensionPrincipal(owner), {"enabled": True}, agent_runs=bound)
        team = await service.get({"team_id": payload["team_id"]}, ctx)
        member = team["members"][0]
        runs.artifact_gate.clear()
        try:
            await service.send({"team_id": team["id"], "member_id": member["id"], "request_id": payload["request_id"], "text": "Artifact fixture: produce a release report"}, ctx)
            await service.tick()
            path = get_paths().sandbox_outputs_dir(member["thread_id"], user_id=owner) / "report.bin"

            def write():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(base64.b64decode(payload["content_base64"], validate=True))

            await asyncio.to_thread(write)
            return await service.register_artifact(
                {"team_id": team["id"], "request_id": payload["request_id"], "name": payload["name"], "path": "/mnt/user-data/outputs/report.bin", **({"artifact_id": payload["artifact_id"]} if "artifact_id" in payload else {})},
                ToolContext(ExtensionPrincipal(owner), {"enabled": True}, member["thread_id"], agent_runs=bound, run_id=next(r.run_id for r in runs.runs.values() if r.thread_id == member["thread_id"] and r.status == "running")),
            )
        finally:
            runs.artifact_gate.set()

    @app.get("/preview/imported")
    async def imported(team_id: str, member_id: str, request: Request):
        team = await service.db("get", request.state.user.id, team_id)
        member = next(member for member in team["members"] if member["id"] == member_id)
        directory = get_paths().sandbox_uploads_dir(member["thread_id"], user_id=request.state.user.id)
        return await asyncio.to_thread(lambda: [{"filename": file.name, "content_base64": base64.b64encode(file.read_bytes()).decode()} for file in directory.glob("artifact-*")])

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
<style>:root{--destructive:oklch(0.577 0.245 27.325)}
body{font:14px system-ui;background:#faf9f3;color:#252722;margin:0}
nav{height:56px;border-bottom:1px solid #e5e5de;padding:0 32px;display:flex;align-items:center;color:#777a72;font-size:12px}
main{max-width:1152px;margin:auto;padding:32px 40px;box-sizing:border-box}
h1{font-size:24px;font-weight:600;margin:0 0 24px}
@media(max-width:720px){main{padding:24px 20px}}
html.dark{--card:#24251f;--foreground:#eeeee8;--muted-foreground:#a2a49a;--border:#414239;--muted:#303128;--primary:#dbe4d6;--primary-foreground:#242d22;--destructive:oklch(0.704 0.191 22.216)}
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
