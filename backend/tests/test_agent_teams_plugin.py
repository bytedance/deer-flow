"""Team extension contracts exercised through the installed contribution."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from deerflow_extension_api import AgentRun, AgentRunError, ExtensionPrincipal
from deerflow_extension_api.plugins import ActionContext, ToolContext

from deerflow.extensions.loader import ExtensionSpec, load_extensions


class Runs:
    """Controllable host: records real admissions and separate thread states."""

    def __init__(self):
        self.threads = {}
        self.runs = {}
        self.starts = []
        self.denied = False

    def for_plugin(self, namespace):
        return self

    async def create_thread(self, *, assistant_id, thread_id, metadata):
        self.threads.setdefault(thread_id, {"assistant": assistant_id, "values": {"messages": []}, "next": [], "interrupts": []})
        return thread_id

    async def get_state(self, *, thread_id):
        if self.denied or thread_id not in self.threads:
            raise AgentRunError(403, "unavailable")
        return self.threads[thread_id]

    async def start(self, *, thread_id, input, idempotency_key):
        if self.denied:
            raise AgentRunError(403, "revoked")
        if idempotency_key in self.runs:
            return self.runs[idempotency_key]
        if any(r.thread_id == thread_id and r.status == "running" for r in self.runs.values()):
            raise AgentRunError(409, "busy")
        self.starts.append((thread_id, input))
        self.threads[thread_id]["values"]["messages"].extend(input["messages"])
        run = AgentRun(thread_id, idempotency_key, "running")
        self.runs[run.run_id] = run
        return run

    async def get(self, *, thread_id, run_id):
        if self.denied:
            raise AgentRunError(403, "revoked")
        return self.runs[run_id]

    async def cancel(self, *, thread_id, run_id):
        self.runs[run_id] = AgentRun(thread_id, run_id, "interrupted")

    async def resume(self, *, thread_id, resume, idempotency_key):
        self.threads[thread_id]["next"] = []
        self.threads[thread_id]["interrupts"] = []
        run = AgentRun(thread_id, idempotency_key, "running")
        self.runs[run.run_id] = run
        return run

    def finish(self, run_id, answer="Evidence checked.", *, interrupted=False):
        old = self.runs[run_id]
        self.runs[run_id] = AgentRun(old.thread_id, run_id, "success")
        state = self.threads[old.thread_id]
        state["values"]["messages"].append({"type": "ai", "content": answer})
        state["next"] = ["tools"] if interrupted else []
        state["interrupts"] = [{"value": "Approve?"}] if interrupted else []


@pytest.fixture
def plugin(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "examples/deerflow-extension-agent-teams"))
    loaded, diagnostics = load_extensions([ExtensionSpec(use="deerflow_extension_agent_teams:install", config={"enabled": True, "storage_path": str(tmp_path / "teams.sqlite")})])
    assert not diagnostics
    ((_, declaration),) = loaded.plugins
    actions = {a.name: a.handler for a in declaration.backend}
    service = actions["list"].__self__
    service.available = True  # Explicit ticks keep lifecycle tests deterministic.
    return loaded, actions, service


def context(runs, owner="alice", thread=None):
    if thread:
        return ToolContext(ExtensionPrincipal(owner), {"enabled": True}, thread, agent_runs=runs)
    return ActionContext(ExtensionPrincipal(owner), {"enabled": True}, agent_runs=runs)


async def create(actions, runs):
    return await actions["create"]({"request_id": "team-one", "name": "Release", "goal": "Check release readiness", "members": [{"name": "Research", "agent": "researcher"}, {"name": "Review", "agent": "reviewer"}]}, context(runs))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "team_name,member_name,expected", [("Release", "Research", "Release / Research"), ("T" * 80, "M" * 37, "T" * 80 + " / " + "M" * 37), ("T" * 80, "M" * 38, "M" * 38), ("T" * 80, "M" * 80, "M" * 80), ("😀" * 40, "😀" * 40, "😀" * 40)]
)
async def test_native_mention_labels_fit_host_limit_without_changing_routing(plugin, team_name, member_name, expected):
    _, actions, service = plugin
    runs = Runs()
    team = await actions["create"]({"request_id": "long-name", "name": team_name, "goal": "Check mentions", "members": [{"name": member_name, "agent": "researcher"}, {"name": "Review", "agent": "reviewer"}]}, context(runs))
    # Search still matches the full team/member names, even if the label falls back.
    candidates = (await service.search({"query": team_name}, context(runs)))["items"]
    assert len(candidates) == 2
    assert candidates[0]["label"] == expected
    assert all(len(item["label"].encode("utf-16-le")) // 2 <= 120 for item in candidates)
    assert candidates[0]["id"] == f"{team['id']}/{team['members'][0]['id']}"


@pytest.mark.asyncio
async def test_members_are_full_agents_and_requests_are_deduplicated(plugin):
    _, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    assert len(runs.threads) == 2
    assert {t["assistant"] for t in runs.threads.values()} == {"researcher", "reviewer"}
    assert (await create(actions, runs))["id"] == team["id"]
    assert (await actions["list"]({}, context(runs, "bob")))["teams"] == []
    payload = {"team_id": team["id"], "member_id": team["members"][0]["id"], "text": "Check release", "request_id": "one"}
    with pytest.raises(ValueError):
        await actions["send"](payload, context(runs, "bob"))
    jobs = await asyncio.gather(*(actions["send"](payload, context(runs)) for _ in range(4)))
    assert len({j["id"] for j in jobs}) == 1
    await service.tick()
    assert len(runs.starts) == 1
    runs.finish(jobs[0]["id"])
    await service.tick()
    view = await actions["get"]({"team_id": team["id"]}, context(runs))
    assert view["jobs"][0]["status"] == "completed"
    assert view["messages"][-1]["text"] == "Evidence checked."
    assert view["messages"][-1]["member_id"] == payload["member_id"]


@pytest.mark.asyncio
async def test_serial_admission_parallel_members_and_explicit_approval(plugin):
    _, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    jobs = []
    for n, member in enumerate([team["members"][0], team["members"][0], team["members"][1]]):
        jobs.append(await actions["send"]({"team_id": team["id"], "member_id": member["id"], "text": "Check", "request_id": str(n)}, context(runs)))
    await service.tick()
    assert len(runs.starts) == 2
    runs.finish(jobs[0]["id"], interrupted=True)
    await service.tick()
    view = await actions["get"]({"team_id": team["id"]}, context(runs))
    assert view["jobs"][0]["status"] == "waiting_input"
    await service.tick()
    assert len(runs.starts) == 2
    await actions["resume"]({"team_id": team["id"], "job_id": jobs[0]["id"], "response": {"approved": False}, "request_id": "answer"}, context(runs))
    await service.tick()
    view = await actions["get"]({"team_id": team["id"]}, context(runs))
    runs.finish(view["jobs"][0]["run_id"])
    await service.tick()
    await service.tick()
    assert len(runs.starts) == 3


@pytest.mark.asyncio
async def test_peer_handoff_delivers_result_and_cannot_impersonate_member(plugin):
    loaded, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    sender, recipient = team["members"]
    tools = {tool.name: tool.handler for _, p in loaded.plugins for tool in p.tools}
    sent = await tools["send_member"]({"team_id": team["id"], "member_id": recipient["id"], "text": "Review this finding", "request_id": "review"}, context(runs, thread=sender["thread_id"]))
    await service.tick()
    runs.finish(sent["id"], "Verified finding")
    await service.tick()
    await service.tick()
    assert len(runs.starts) == 2
    assert runs.starts[-1][0] == sender["thread_id"]
    message = runs.starts[-1][1]["messages"][0]
    assert message["role"] == "user"
    assert "Verified finding" in message["content"]
    assert recipient["id"] in message["content"]
    with pytest.raises(ValueError):
        await tools["send_member"]({"team_id": team["id"], "member_id": recipient["id"], "text": "Spoof", "request_id": "bad"}, context(runs, thread="unrelated"))


@pytest.mark.asyncio
async def test_native_mentions_route_once_and_reject_foreign_access(plugin):
    from deerflow_extension_api.agent_runs import AGENT_RUNS_CONTEXT_KEY
    from langchain_core.messages import HumanMessage

    _, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    await runs.create_thread(assistant_id="lead_agent", thread_id="source", metadata={})
    member = team["members"][0]
    message = HumanMessage(id="m", content="@Research check this", additional_kwargs={"extension_mentions": [{"namespace": "community.agent-teams", "provider": "members", "id": f"{team['id']}/{member['id']}", "label": "ignored"}]})
    runtime = SimpleNamespace(context={"thread_id": "source", "user_id": "alice", AGENT_RUNS_CONTEXT_KEY: runs})
    await service.mentions([message], runtime)
    await service.mentions([message], runtime)
    await service.tick()
    assert len(runs.starts) == 1
    runs.denied = True
    with pytest.raises(AgentRunError):
        await service.mentions([message.model_copy(update={"id": "stolen"})], runtime)


@pytest.mark.asyncio
async def test_restart_requires_reconnect_and_preserves_existing_run(plugin):
    from deerflow_extension_agent_teams.service import Teams

    _, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    job = await actions["send"]({"team_id": team["id"], "member_id": team["members"][0]["id"], "text": "Check", "request_id": "job"}, context(runs))
    await service.tick()
    replacement = Teams(service.store.path)
    replacement.available = True
    await replacement.tick()
    assert len(runs.starts) == 1
    runs.finish(job["id"])
    await replacement.connect({"team_id": team["id"]}, context(runs))
    await replacement.tick()
    view = await replacement.get({"team_id": team["id"]}, context(runs))
    assert view["jobs"][0]["status"] == "completed"
    assert len(runs.starts) == 1


@pytest.mark.asyncio
async def test_revocation_disconnects_without_replacing_an_active_run(plugin):
    _, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    await actions["send"]({"team_id": team["id"], "member_id": team["members"][0]["id"], "text": "Check", "request_id": "one"}, context(runs))
    await service.tick()
    runs.denied = True
    await service.tick()
    view = await actions["get"]({"team_id": team["id"]}, context(runs))
    assert view["connected"] is False
    assert view["jobs"][0]["status"] == "running"
    assert len(runs.starts) == 1


@pytest.mark.asyncio
async def test_ambiguous_admission_retries_same_key_and_frozen_input(plugin, monkeypatch):
    _, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    original = runs.start
    calls = []

    async def uncertain(**kwargs):
        calls.append(kwargs)
        result = await original(**kwargs)
        if len(calls) == 1:
            raise TimeoutError
        return result

    monkeypatch.setattr(runs, "start", uncertain)
    await actions["send"]({"team_id": team["id"], "member_id": team["members"][0]["id"], "text": "Check", "request_id": "one"}, context(runs))
    await service.tick()
    await service.tick()
    assert calls[0] == calls[1]
    assert len(runs.starts) == 1


@pytest.mark.asyncio
async def test_cancel_stops_a_running_request_and_pending_delete_is_rejected(plugin):
    _, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    job = await actions["send"]({"team_id": team["id"], "member_id": team["members"][0]["id"], "text": "Check", "request_id": "one"}, context(runs))
    with pytest.raises(ValueError):
        await actions["delete"]({"team_id": team["id"]}, context(runs))
    await service.tick()
    await actions["cancel"]({"team_id": team["id"], "job_id": job["id"]}, context(runs))
    await service.tick()
    await service.tick()
    view = await actions["get"]({"team_id": team["id"]}, context(runs))
    assert view["jobs"][0]["status"] == "cancelled"
    await actions["delete"]({"team_id": team["id"]}, context(runs))
    assert (await actions["list"]({}, context(runs)))["teams"] == []
    assert len(runs.threads) == 2  # No destructive thread API is called.


@pytest.mark.asyncio
async def test_externally_advanced_state_is_never_misattributed(plugin):
    _, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    job = await actions["send"]({"team_id": team["id"], "member_id": team["members"][0]["id"], "text": "Check", "request_id": "one"}, context(runs))
    await service.tick()
    runs.finish(job["id"])
    runs.threads[team["members"][0]["thread_id"]]["values"]["messages"].extend([{"role": "user", "content": "Another task"}, {"role": "assistant", "content": "Unrelated result"}])
    await service.tick()
    view = await actions["get"]({"team_id": team["id"]}, context(runs))
    assert view["jobs"][0]["status"] == "failed"
    assert "Unrelated result" not in str(view["messages"])


@pytest.mark.asyncio
async def test_service_lock_prevents_two_workers_and_releases_on_shutdown(plugin):
    import sqlite3

    from deerflow_extension_agent_teams.service import Teams

    _, _, first = plugin
    second = Teams(first.store.path)
    await first.start(None)
    try:
        with pytest.raises(sqlite3.OperationalError):
            await second.start(None)
        assert not second.available
    finally:
        await first.stop()
    await second.start(None)
    await second.stop()


@pytest.mark.asyncio
async def test_real_tool_node_enforces_team_owner_and_current_thread(plugin):
    from deerflow_extension_api.agent_runs import AGENT_RUNS_CONTEXT_KEY
    from langchain_core.messages import AIMessage
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langgraph.prebuilt import ToolNode

    from deerflow.extensions.plugin_tools import build_plugin_tools

    loaded, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    tool = next(t for t in build_plugin_tools(loaded) if "send_member" in t.name)
    graph = StateGraph(MessagesState)
    graph.add_node("tools", ToolNode([tool]))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    args = {"team_id": team["id"], "member_id": team["members"][1]["id"], "text": "Review", "request_id": "from-model"}
    for owner, expected in [("bob", False), ("alice", True)]:
        result = await graph.compile().ainvoke(
            {"messages": [AIMessage(content="", tool_calls=[{"name": tool.name, "args": args, "id": "dispatch"}])]}, context={"thread_id": team["members"][0]["thread_id"], "user_id": owner, AGENT_RUNS_CONTEXT_KEY: runs}
        )
        assert ("queued" in result["messages"][-1].content) is expected
    await service.tick()
    assert len(runs.starts) == 1


@pytest.mark.asyncio
async def test_mention_middleware_runs_in_real_lead_pipeline(plugin, monkeypatch, tmp_path):
    from deerflow_extension_api import EXTENSION_TASK_STORE_KEY, ExtensionData
    from deerflow_extension_api.agent_runs import AGENT_RUNS_CONTEXT_KEY
    from langchain.agents import create_agent
    from langchain_core.language_models.fake_chat_models import FakeListChatModel
    from langchain_core.messages import HumanMessage

    from deerflow.agents.lead_agent.agent import build_middlewares
    from deerflow.agents.thread_state import ThreadState
    from deerflow.config.app_config import AppConfig
    from deerflow.config.paths import Paths
    from deerflow.config.sandbox_config import SandboxConfig

    loaded, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    await runs.create_thread(assistant_id="lead_agent", thread_id="source", metadata={})
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", Paths(str(tmp_path)))
    config = AppConfig(sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"))
    config.title.enabled = config.memory.enabled = config.summarization.enabled = False
    stack = build_middlewares(config={"configurable": {}}, model_name="offline", app_config=config, extensions=loaded, memory_enabled=False, owns_agent_skill_projection=False)
    graph = create_agent(FakeListChatModel(responses=["Request sent."]), middleware=stack, state_schema=ThreadState)
    member = team["members"][0]
    message = HumanMessage(id="native", content="@Research check release", additional_kwargs={"extension_mentions": [{"namespace": "community.agent-teams", "provider": "members", "id": f"{team['id']}/{member['id']}", "label": "Research"}]})
    result = await graph.ainvoke(
        {"messages": [message]}, config={"configurable": {"thread_id": "source"}}, context={"thread_id": "source", "user_id": "alice", AGENT_RUNS_CONTEXT_KEY: runs, EXTENSION_TASK_STORE_KEY: ExtensionData("native-run")}
    )
    assert any("requests queued" in str(m.content) for m in result["messages"])
    await service.tick()
    assert len(runs.starts) == 1


@pytest.mark.asyncio
async def test_fresh_thread_404_is_not_a_failed_first_request(plugin, monkeypatch):
    _, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    original = runs.get_state

    async def state(**kwargs):
        result = await original(**kwargs)
        if not result["values"]["messages"]:
            raise AgentRunError(404, "No checkpoint")
        return result

    monkeypatch.setattr(runs, "get_state", state)
    await actions["connect"]({"team_id": team["id"]}, context(runs))
    job = await actions["send"]({"team_id": team["id"], "member_id": team["members"][0]["id"], "text": "First task", "request_id": "one"}, context(runs))
    await service.tick()
    runs.finish(job["id"])
    await service.tick()
    view = await actions["get"]({"team_id": team["id"]}, context(runs))
    assert view["jobs"][0]["status"] == "completed"


@pytest.mark.asyncio
async def test_host_dynamic_context_id_rewrite_preserves_result_attribution(plugin):
    _, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    job = await actions["send"]({"team_id": team["id"], "member_id": team["members"][0]["id"], "text": "First task", "request_id": "one"}, context(runs))
    await service.tick()
    messages = runs.threads[team["members"][0]["thread_id"]]["values"]["messages"]
    original = messages[0]
    # Reproduce the real Gateway's admission metadata + dynamic reminder split.
    messages[:] = [{"type": "system", "id": original["id"], "content": "Current date"}, {**original, "id": original["id"] + "__user", "additional_kwargs": {"run_id": job["id"]}}]
    runs.finish(job["id"], "Correctly attributed")
    await service.tick()
    view = await actions["get"]({"team_id": team["id"]}, context(runs))
    assert view["jobs"][0]["status"] == "completed"
    assert view["messages"][-1]["text"] == "Correctly attributed"


@pytest.mark.asyncio
async def test_shared_thread_access_does_not_grant_foreign_team_access(plugin):
    from deerflow_extension_api.agent_runs import AGENT_RUNS_CONTEXT_KEY
    from langchain_core.messages import HumanMessage

    _, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    member = team["members"][0]
    await runs.create_thread(assistant_id="lead_agent", thread_id="source", metadata={})
    # This host double permits thread reads to both callers, like a shared
    # conversation. Plugin team data must still use the authenticated owner.
    runtime = SimpleNamespace(context={"thread_id": "source", "user_id": "bob", AGENT_RUNS_CONTEXT_KEY: runs})
    message = HumanMessage(id="foreign", content="Send", additional_kwargs={"extension_mentions": [{"namespace": "community.agent-teams", "provider": "members", "id": f"{team['id']}/{member['id']}", "label": "Spoof"}]})
    with pytest.raises(ValueError):
        await service.mentions([message], runtime)
    assert not runs.starts


@pytest.mark.asyncio
async def test_result_context_is_bounded_and_old_pending_jobs_are_paged(plugin):
    import json

    _, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    for i in range(25):
        await actions["send"]({"team_id": team["id"], "member_id": team["members"][0]["id"], "text": "资料" * 1000, "request_id": str(i)}, context(runs))
    view = await actions["get"]({"team_id": team["id"]}, context(runs))
    assert view["total_jobs"] == 25
    assert len(view["jobs"]) == 20
    assert len(json.dumps(view, ensure_ascii=False).encode()) < 64 * 1024
    second = await actions["get"]({"team_id": team["id"], "offset": 20}, context(runs))
    assert len(second["jobs"]) == 5
    assert {j["id"] for j in view["jobs"]}.isdisjoint(j["id"] for j in second["jobs"])


@pytest.mark.asyncio
async def test_handoff_chain_cannot_grow_without_bound(plugin):
    _, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    first, second = team["members"]
    root = await actions["send"]({"team_id": team["id"], "member_id": first["id"], "text": "Begin", "request_id": "root"}, context(runs))
    await service.tick()
    for i in range(11):
        await actions["send"]({"team_id": team["id"], "member_id": second["id"], "text": "Review", "request_id": str(i)}, context(runs, thread=first["thread_id"]))
    with pytest.raises(ValueError, match="limit"):
        await actions["send"]({"team_id": team["id"], "member_id": second["id"], "text": "Review", "request_id": "overflow"}, context(runs, thread=first["thread_id"]))
    stored = await service.db("get", "alice", team["id"])
    assert {j["root"] for j in stored["jobs"]} == {root["id"]}


@pytest.mark.asyncio
async def test_activity_keeps_task_result_and_handoff_provenance_after_context_rotation(plugin):
    _, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    sender, recipient = team["members"]
    first = await actions["send"]({"team_id": team["id"], "member_id": sender["id"], "text": "Research the release", "request_id": "initial"}, context(runs))
    await service.tick()
    peer = await actions["send"]({"team_id": team["id"], "member_id": recipient["id"], "text": "Review the evidence", "request_id": "peer"}, context(runs, thread=sender["thread_id"]))
    await service.tick()
    runs.finish(peer["id"], "Review passed")
    await service.tick()
    await service.db("change", "alice", team["id"], lambda t: t.update(messages=[]))
    view = await actions["get"]({"team_id": team["id"], "limit": 200, "details": True}, context(runs))
    job = next(j for j in view["jobs"] if j["id"] == peer["id"])
    assert job["text"] == "Review the evidence"
    assert job["result"] == "Review passed"
    assert job["source_member_id"] == sender["id"]
    assert job["parent_id"] == first["id"]
    assert job["root"] == first["id"]
    unchanged = await actions["get"]({"team_id": team["id"], "limit": 200, "details": True, "revision": view["revision"]}, context(runs))
    assert unchanged == {"unchanged": True, "revision": view["revision"]}
    assert job["created_at"]
    assert job["completed_at"]
    assert job["delivery"]["thread_id"] == sender["thread_id"]
    assert job["delivery"]["status"] == "queued"
    assert not {"input", "resume", "initial_run_id"} & job.keys()
    with pytest.raises(ValueError):
        await actions["get"]({"team_id": team["id"], "limit": 200, "details": True}, context(runs, "bob"))


@pytest.mark.asyncio
async def test_activity_reads_legacy_jobs_and_bounds_projection(plugin):
    _, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    sent = await actions["send"]({"team_id": team["id"], "member_id": team["members"][0]["id"], "text": "Legacy request", "request_id": "legacy"}, context(runs))
    await service.tick()
    runs.finish(sent["id"], "Legacy result")
    await service.tick()

    def old_version(t):
        for job in t["jobs"]:
            for key in ("result", "parent_id", "created_at", "completed_at"):
                job.pop(key, None)

    await service.db("change", "alice", team["id"], old_version)
    view = await actions["get"]({"team_id": team["id"], "limit": 1, "details": True}, context(runs))
    assert view["jobs"][0]["result"] == "Legacy result"
    assert view["jobs"][0]["created_at"] is None
    for limit in (0, 201, True, "20"):
        with pytest.raises(ValueError):
            await actions["get"]({"team_id": team["id"], "limit": limit}, context(runs))


@pytest.mark.asyncio
@pytest.mark.parametrize("created_threads", [1, 2])
async def test_reconnect_recovers_incomplete_creation_only_after_all_threads_exist(plugin, monkeypatch, created_threads):
    from deerflow_extension_agent_teams.service import Teams

    _, actions, service = plugin
    runs = Runs()
    ensure = runs.create_thread
    calls = []

    async def interrupted(**kwargs):
        result = await ensure(**kwargs)
        calls.append(result)
        if len(calls) == created_threads:
            raise TimeoutError("creation interrupted")
        return result

    monkeypatch.setattr(runs, "create_thread", interrupted)
    with pytest.raises(TimeoutError):
        await create(actions, runs)
    team = (await service.db("list", "alice"))[0]
    assert not team["ready"]
    original_ids = [m["thread_id"] for m in team["members"]]
    replacement = Teams(service.store.path)
    replacement.available = True
    calls.clear()
    with pytest.raises(TimeoutError):
        await replacement.connect({"team_id": team["id"]}, context(runs))
    assert not (await replacement.db("get", "alice", team["id"]))["ready"]
    assert not replacement.handles
    monkeypatch.setattr(runs, "create_thread", ensure)
    await replacement.connect({"team_id": team["id"]}, context(runs))
    await replacement.connect({"team_id": team["id"]}, context(runs))
    recovered = await replacement.get({"team_id": team["id"]}, context(runs))
    assert recovered["ready"] and recovered["connected"]
    assert [m["thread_id"] for m in recovered["members"]] == original_ids
    assert set(runs.threads) == set(original_ids)
    sent = await replacement.send({"team_id": team["id"], "member_id": team["members"][0]["id"], "text": "Recovered task", "request_id": "recovered"}, context(runs))
    await replacement.tick()
    runs.finish(sent["id"])
    await replacement.tick()
    assert (await replacement.get({"team_id": team["id"]}, context(runs)))["jobs"][0]["status"] == "completed"


@pytest.mark.asyncio
async def test_reconnect_and_delete_leave_no_orphaned_handle(plugin, monkeypatch):
    _, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    service.handles.clear()
    ensure = runs.create_thread
    deletion = None
    attempted = asyncio.Event()
    db = service.db

    async def delete():
        attempted.set()
        return await actions["delete"]({"team_id": team["id"]}, context(runs))

    async def immediate_delete_db(method, *args):
        # Once admitted, finish the competing deletion in one event-loop turn;
        # executor timing must not let an unlocked reconnect escape this test.
        if asyncio.current_task() is deletion:
            return getattr(service.store, method)(*args)
        return await db(method, *args)

    async def delete_during_reconnect(**kwargs):
        nonlocal deletion
        if deletion is None:
            deletion = asyncio.create_task(delete())
            await attempted.wait()
        return await ensure(**kwargs)

    monkeypatch.setattr(service, "db", immediate_delete_db)
    monkeypatch.setattr(runs, "create_thread", delete_during_reconnect)
    await actions["connect"]({"team_id": team["id"]}, context(runs))
    await deletion
    assert not service.handles
    assert (await actions["list"]({}, context(runs)))["teams"] == []
    await service.tick()


@pytest.mark.asyncio
@pytest.mark.parametrize("finish_as_admitted", [True, False])
async def test_request_capacity_reserves_all_receipts_and_keeps_retries_idempotent(plugin, finish_as_admitted):
    _, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    sender, recipient = team["members"]
    caller = context(runs, thread=sender["thread_id"])
    payload = {"team_id": team["id"], "member_id": recipient["id"], "text": "Check", "request_id": "0"}

    async def complete(job_id):
        stored = await service.db("get", "alice", team["id"])
        job = next(j for j in stored["jobs"] if j["id"] == job_id)
        await service.finish("alice", stored, job, "completed", "Result")
        # Duplicate terminal observations cannot allocate a second receipt.
        await service.finish("alice", stored, job, "completed", "Result")
        stored = await service.db("get", "alice", team["id"])
        receipt = next(j for j in stored["jobs"] if j.get("parent_id") == job_id)
        await service.finish("alice", stored, receipt, "completed", "Delivered")

    ids = []
    for index in range(100):
        sent = await actions["send"]({**payload, "request_id": str(index)}, caller)
        ids.append(sent["id"])
        if finish_as_admitted:
            await complete(sent["id"])
    if not finish_as_admitted:
        for job_id in ids:
            await complete(job_id)
    view = await actions["get"]({"team_id": team["id"], "limit": 200}, context(runs))
    assert view["total_jobs"] == len(view["jobs"]) == 200
    assert sum(j["kind"] == "request" for j in view["jobs"]) == 100
    assert sum(j["kind"] == "receipt" for j in view["jobs"]) == 100
    assert (await actions["send"](payload, caller))["id"] == ids[0]
    with pytest.raises(ValueError, match="limit"):
        await actions["send"]({**payload, "request_id": "101"}, caller)
    assert (await actions["get"]({"team_id": team["id"]}, context(runs)))["total_jobs"] == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("source_kind", ["peer", "mention", "receipt"])
@pytest.mark.parametrize("rounds", [1, 2])
async def test_real_clarification_waits_and_continues_with_human_messages(plugin, monkeypatch, source_kind, rounds):
    from deerflow_extension_api.agent_runs import AGENT_RUNS_CONTEXT_KEY
    from langchain.agents import create_agent
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage, HumanMessage
    from langgraph.checkpoint.memory import InMemorySaver

    from deerflow.agents.middlewares.clarification_middleware import ClarificationMiddleware
    from deerflow.tools.builtins.clarification_tool import ask_clarification_tool

    class Model(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    question = AIMessage(content="", tool_calls=[{"name": "ask_clarification", "id": "clarify-environment", "args": {"question": "Which environment?", "clarification_type": "missing_info"}, "type": "tool_call"}])
    questions = [question.model_copy(update={"tool_calls": [{**question.tool_calls[0], "id": f"clarify-{index}"}]}) for index in range(rounds)]
    graph = create_agent(Model(responses=[*questions, AIMessage(content="Confirmed staging.")]), tools=[ask_clarification_tool], middleware=[ClarificationMiddleware()], checkpointer=InMemorySaver())

    class ClarifyingRuns(Runs):
        async def start(self, *, thread_id, input, idempotency_key):
            if idempotency_key in self.runs:
                return self.runs[idempotency_key]
            run = await super().start(thread_id=thread_id, input=input, idempotency_key=idempotency_key)
            await graph.ainvoke(input, config={"configurable": {"thread_id": thread_id}})
            state = await graph.aget_state({"configurable": {"thread_id": thread_id}})
            self.threads[thread_id].update(values={"messages": [m.model_dump() for m in state.values["messages"]]}, next=list(state.next), interrupts=list(state.interrupts))
            self.runs[run.run_id] = AgentRun(thread_id, run.run_id, "success")
            return self.runs[run.run_id]

        async def resume(self, **kwargs):
            pytest.fail("Ordinary clarification must not use LangGraph resume")

    _, actions, service = plugin
    runs = ClarifyingRuns()
    team = await create(actions, runs)
    sender, recipient = team["members"]
    if source_kind == "mention":
        await runs.create_thread(assistant_id="lead_agent", thread_id="external", metadata={})
        message = HumanMessage(id="mention", content="Review", additional_kwargs={"extension_mentions": [{"namespace": "community.agent-teams", "provider": "members", "id": f"{team['id']}/{recipient['id']}"}]})
        await service.mentions([message], SimpleNamespace(context={"thread_id": "external", "user_id": "alice", AGENT_RUNS_CONTEXT_KEY: runs}))
    else:
        await actions["send"]({"team_id": team["id"], "member_id": recipient["id"], "text": "Review", "request_id": "peer"}, context(runs, thread=sender["thread_id"]))
        if source_kind == "receipt":
            stored = await service.db("get", "alice", team["id"])
            await service.finish("alice", stored, stored["jobs"][0], "completed", "Peer result")
    await service.tick()
    view = await actions["get"]({"team_id": team["id"], "details": True}, context(runs))
    waiting = view["jobs"][-1]
    assert waiting["status"] == "waiting_input"
    assert waiting["clarification"]["question"] == "Which environment?"
    assert len(view["jobs"]) == (2 if source_kind == "receipt" else 1)
    state = runs.threads[waiting["thread_id"]]
    assert not state["next"] and not state["interrupts"]
    request = state["values"]["messages"][-1]["artifact"]["human_input"]
    assert request["kind"] == "human_input_request"
    assert runs.runs[waiting["run_id"]].status == "success"
    await service.tick()
    assert len(runs.starts) == 1
    for index in range(rounds):
        await actions["resume"]({"team_id": team["id"], "job_id": waiting["id"], "response": "staging", "request_id": "answer"}, context(runs))
        if source_kind == "mention" and index == 0:
            from deerflow_extension_agent_teams.service import Teams

            start = runs.start
            attempts = []

            async def lost_response(**kwargs):
                attempts.append(kwargs)
                result = await start(**kwargs)
                if len(attempts) == 1:
                    raise TimeoutError("response admitted but acknowledgement lost")
                return result

            monkeypatch.setattr(runs, "start", lost_response)
            await service.tick()
            # Admission metadata survives the host's dynamic-context ID rewrite.
            messages = runs.threads[waiting["thread_id"]]["values"]["messages"]
            response_id = attempts[0]["input"]["messages"][0]["id"]
            position = next(i for i, message in enumerate(messages) if message.get("id") == response_id)
            original = messages[position]
            messages[position : position + 1] = [
                {"type": "system", "id": response_id, "content": "Current date"},
                {**original, "id": response_id + "__user", "additional_kwargs": {**original["additional_kwargs"], "run_id": attempts[0]["idempotency_key"]}},
            ]
            service = Teams(service.store.path)
            service.available = True
            await service.connect({"team_id": team["id"]}, context(runs))
            actions = {name: getattr(service, name) for name in actions}
            await service.tick()
            assert attempts[0] == attempts[1]
            monkeypatch.setattr(runs, "start", start)
        else:
            await service.tick()
        view = await actions["get"]({"team_id": team["id"], "details": True}, context(runs))
        current = next(j for j in view["jobs"] if j["id"] == waiting["id"])
        assert current["status"] == ("waiting_input" if index + 1 < rounds else "completed")
        assert len(runs.starts) == index + 2
    view = await actions["get"]({"team_id": team["id"], "details": True}, context(runs))
    completed = next(j for j in view["jobs"] if j["id"] == waiting["id"])
    assert completed["status"] == "completed"
    assert completed["result"] == "Confirmed staging."
    response = runs.starts[1][1]["messages"][0]
    assert response["role"] == "user" and response["content"] == "staging"
    assert response["additional_kwargs"]["human_input_response"]["request_id"] == request["request_id"]
    assert sum(j["kind"] == "receipt" for j in view["jobs"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("ambiguous_admission", [False, True])
async def test_peer_handoff_keeps_running_parent_and_budget_with_later_queued_requests(plugin, monkeypatch, ambiguous_admission):
    _, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    first, second = team["members"]
    payload = {"team_id": team["id"], "member_id": first["id"], "text": "Begin", "request_id": "A1"}
    running = await actions["send"](payload, context(runs))
    if ambiguous_admission:
        start = runs.start

        async def lost_admission(**kwargs):
            await start(**kwargs)
            raise TimeoutError("admission accepted")

        monkeypatch.setattr(runs, "start", lost_admission)
    await service.tick()
    await actions["send"]({**payload, "request_id": "A2"}, context(runs))
    peer_payload = {**payload, "member_id": second["id"], "text": "Review"}
    for index in range(11):
        sent = await actions["send"]({**peer_payload, "request_id": f"peer-{index}"}, context(runs, thread=first["thread_id"]))
        view = await actions["get"]({"team_id": team["id"]}, context(runs))
        peer = next(j for j in view["jobs"] if j["id"] == sent["id"])
        assert peer["parent_id"] == peer["root"] == running["id"]
    await actions["send"]({**payload, "request_id": "A3"}, context(runs))
    with pytest.raises(ValueError, match="limit"):
        await actions["send"]({**peer_payload, "request_id": "overflow"}, context(runs, thread=first["thread_id"]))
    assert len(runs.starts) == 1


@pytest.mark.asyncio
async def test_external_member_tool_call_does_not_inherit_an_unstarted_team_request(plugin):
    _, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    first, second = team["members"]
    await actions["send"]({"team_id": team["id"], "member_id": first["id"], "text": "Queued", "request_id": "queued"}, context(runs))
    sent = await actions["send"]({"team_id": team["id"], "member_id": second["id"], "text": "From ordinary member chat", "request_id": "peer"}, context(runs, thread=first["thread_id"]))
    view = await actions["get"]({"team_id": team["id"]}, context(runs))
    peer = next(j for j in view["jobs"] if j["id"] == sent["id"])
    assert peer["parent_id"] is None and peer["root"] == peer["id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["queued", "waiting", "resuming"])
async def test_clarification_never_overwrites_an_external_conversation_turn(plugin, stage):
    from langchain_core.messages import AIMessage

    from deerflow.agents.middlewares.clarification_middleware import ClarificationMiddleware

    _, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    member = team["members"][0]
    request = SimpleNamespace(tool_call={"name": "ask_clarification", "id": "outside", "args": {"question": "Which environment?", "clarification_type": "missing_info"}}, runtime=None)
    command = ClarificationMiddleware().wrap_tool_call(request, lambda _: pytest.fail("tool handler should be intercepted"))
    sent = await actions["send"]({"team_id": team["id"], "member_id": member["id"], "text": "Work", "request_id": "job"}, context(runs))
    if stage != "queued":
        await service.tick()
        runs.runs[sent["id"]] = AgentRun(member["thread_id"], sent["id"], "success")
    messages = runs.threads[member["thread_id"]]["values"]["messages"]
    messages.extend([AIMessage(content="", tool_calls=[{**request.tool_call, "type": "tool_call"}]).model_dump(), *[m.model_dump() for m in command.update["messages"]]])
    await service.tick()
    response = {"team_id": team["id"], "job_id": sent["id"], "response": "staging", "request_id": "response"}
    if stage == "queued":
        assert not runs.starts
    else:
        with pytest.raises(ValueError, match="Invalid response"):
            await actions["resume"]({**response, "response": {"approved": True}}, context(runs))
        if stage == "resuming":
            await actions["resume"](response, context(runs))
    messages.append({"type": "human", "content": "I answered directly in the member chat"})
    if stage == "waiting":
        with pytest.raises(ValueError, match="Clarification changed"):
            await actions["resume"](response, context(runs))
    await service.tick()
    assert len(runs.starts) == 1
    job = (await actions["get"]({"team_id": team["id"]}, context(runs)))["jobs"][0]
    assert job["status"] == {"queued": "running", "waiting": "waiting_input", "resuming": "failed"}[stage]


@pytest.mark.asyncio
async def test_cancel_reconciles_a_clarification_response_with_lost_admission_ack(plugin, monkeypatch):
    from deerflow.agents.middlewares.clarification_middleware import ClarificationMiddleware

    _, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    sender, member = team["members"]
    sent = await actions["send"]({"team_id": team["id"], "member_id": member["id"], "text": "Work", "request_id": "job"}, context(runs, thread=sender["thread_id"]))
    await service.tick()
    runs.runs[sent["id"]] = AgentRun(member["thread_id"], sent["id"], "success")
    request = SimpleNamespace(tool_call={"name": "ask_clarification", "id": "question", "args": {"question": "Which environment?", "clarification_type": "missing_info"}}, runtime=None)
    command = ClarificationMiddleware().wrap_tool_call(request, lambda _: pytest.fail("intercept clarification"))
    runs.threads[member["thread_id"]]["values"]["messages"].extend(m.model_dump() for m in command.update["messages"])
    await service.tick()
    await actions["resume"]({"team_id": team["id"], "job_id": sent["id"], "response": "staging", "request_id": "answer"}, context(runs))
    start = runs.start
    attempts = []

    async def lost_ack(**kwargs):
        attempts.append(kwargs)
        result = await start(**kwargs)
        if len(attempts) == 1:
            raise TimeoutError("ack lost")
        return result

    monkeypatch.setattr(runs, "start", lost_ack)
    await service.tick()
    response_run = next(r for r in runs.runs.values() if r.run_id != sent["id"])
    assert response_run.status == "running"
    await actions["cancel"]({"team_id": team["id"], "job_id": sent["id"]}, context(runs))
    await service.tick()
    assert runs.runs[response_run.run_id].status == "interrupted"
    assert attempts[0] == attempts[1]
    await service.tick()
    view = await actions["get"]({"team_id": team["id"]}, context(runs))
    assert view["jobs"][0]["status"] == "cancelled"
    assert len(view["jobs"]) == 1 and len(runs.starts) == 2


async def waiting_job(actions, service, runs, *, clarification=False):
    """Park a job for either an explicit interrupt or an ordinary clarification."""
    team = await create(actions, runs)
    sent = await actions["send"]({"team_id": team["id"], "member_id": team["members"][0]["id"], "text": "Check release", "request_id": "one"}, context(runs))
    await service.tick()
    runs.finish(sent["id"], interrupted=not clarification)
    if clarification:
        from deerflow.agents.middlewares.clarification_middleware import ClarificationMiddleware

        request = SimpleNamespace(tool_call={"name": "ask_clarification", "id": "question", "args": {"question": "Which environment?", "clarification_type": "missing_info"}}, runtime=None)
        command = ClarificationMiddleware().wrap_tool_call(request, lambda _: pytest.fail("intercept clarification"))
        runs.threads[team["members"][0]["thread_id"]]["values"]["messages"].extend(m.model_dump() for m in command.update["messages"])
    await service.tick()
    assert (await actions["get"]({"team_id": team["id"]}, context(runs)))["jobs"][0]["status"] == "waiting_input"
    return team, sent


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "answer",
    [
        pytest.param("漢" * 2000, id="cjk-2000-chars"),
        pytest.param("🙂" * 1000, id="emoji-1000-chars"),
        pytest.param("a" * 4000, id="ascii-4000-chars"),
        pytest.param('"' * 4000, id="json-quotes"),
        pytest.param("\n" * 3999 + "a", id="json-newlines"),
    ],
)
async def test_a_clarification_answer_within_the_documented_bounds_is_accepted(plugin, answer):
    # README: tasks and clarification answers accept up to 4,000 characters / 8,000 UTF-8 bytes,
    # and the UI validates exactly those two bounds before submitting.
    _, actions, service = plugin
    runs = Runs()
    team, sent = await waiting_job(actions, service, runs)
    await actions["resume"]({"team_id": team["id"], "job_id": sent["id"], "response": answer, "request_id": "answer"}, context(runs))
    assert (await actions["get"]({"team_id": team["id"]}, context(runs)))["jobs"][0]["status"] == "resuming"


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", ["漢" * 3000, {"text": "x" * 9000}])
async def test_an_oversized_clarification_answer_is_still_refused(plugin, answer):
    _, actions, service = plugin
    runs = Runs()
    team, sent = await waiting_job(actions, service, runs)
    with pytest.raises(ValueError, match="8 KiB"):
        await actions["resume"]({"team_id": team["id"], "job_id": sent["id"], "response": answer, "request_id": "answer"}, context(runs))
    assert (await actions["get"]({"team_id": team["id"]}, context(runs)))["jobs"][0]["status"] == "waiting_input"


@pytest.mark.asyncio
@pytest.mark.parametrize("clarification", [False, True], ids=["interrupt", "clarification"])
@pytest.mark.parametrize("size", [7999, 8000, 8001])
async def test_string_response_uses_the_raw_utf8_byte_boundary(plugin, clarification, size):
    _, actions, service = plugin
    runs = Runs()
    team, sent = await waiting_job(actions, service, runs, clarification=clarification)
    answer = "漢" * 2666 + "a" * (size - 7998)
    payload = {"team_id": team["id"], "job_id": sent["id"], "response": answer, "request_id": "answer"}
    if size > 8000:
        with pytest.raises(ValueError, match="8 KiB"):
            await actions["resume"](payload, context(runs))
    else:
        await actions["resume"](payload, context(runs))
    job = (await service.db("get", "alice", team["id"]))["jobs"][0]
    assert job["status"] == ("waiting_input" if size > 8000 else "resuming")
    if size <= 8000:
        assert job["resume"]["response"] == answer
        if clarification:
            assert job["resume"]["input"]["messages"][0]["content"] == answer


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [7999, 8000, 8001])
async def test_structured_response_keeps_the_utf8_json_byte_boundary(plugin, size):
    _, actions, service = plugin
    runs = Runs()
    team, sent = await waiting_job(actions, service, runs)
    # The JSON object adds 12 bytes around its string value.
    answer = {"text": "漢" * 2660 + "a" * (size - 7980 - 12)}
    payload = {"team_id": team["id"], "job_id": sent["id"], "response": answer, "request_id": "answer"}
    if size > 8000:
        with pytest.raises(ValueError, match="8 KiB"):
            await actions["resume"](payload, context(runs))
    else:
        await actions["resume"](payload, context(runs))
    job = (await service.db("get", "alice", team["id"]))["jobs"][0]
    assert job["status"] == ("waiting_input" if size > 8000 else "resuming")
    if size <= 8000:
        assert job["resume"]["response"] == answer


@pytest.mark.asyncio
@pytest.mark.parametrize("response_json", ['"\\ud800"', '"\\udc00"', '{"text": "\\ud800"}', '{"\\udc00": true}'])
async def test_malformed_unicode_response_uses_the_friendly_validation_error(plugin, response_json):
    _, actions, service = plugin
    runs = Runs()
    team, sent = await waiting_job(actions, service, runs)
    with pytest.raises(ValueError, match="^An explicit response of at most 8 KiB is required$"):
        await actions["resume"]({"team_id": team["id"], "job_id": sent["id"], "response": json.loads(response_json), "request_id": "answer"}, context(runs))
    job = (await service.db("get", "alice", team["id"]))["jobs"][0]
    assert job["status"] == "waiting_input"
    assert job["resume"] is None
