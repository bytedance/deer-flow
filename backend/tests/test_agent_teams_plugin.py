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


async def queue_active_budget_jobs(actions, runs):
    jobs = []
    for index in range(5):
        owner = "bob" if index == 4 else "alice"
        team = await actions["create"](
            {"request_id": f"team-{index}", "name": "Release", "goal": "Check readiness", "members": [{"name": "Research", "agent": "researcher"}, {"name": "Review", "agent": "reviewer"}]},
            context(runs, owner),
        )
        for member in team["members"]:
            if len(jobs) == 9:
                break
            payload = {"team_id": team["id"], "member_id": member["id"], "text": "Check", "request_id": f"job-{len(jobs)}"}
            sent = await actions["send"](payload, context(runs, owner))
            jobs.append({**sent, "owner": owner, "team_id": team["id"], "member_id": member["id"], "thread_id": member["thread_id"]})
    return jobs


@pytest.mark.asyncio
@pytest.mark.parametrize("wait_kind", ["interrupt", "clarification"])
async def test_unadmitted_conversation_waits_do_not_consume_other_teams_active_budget(plugin, wait_kind):
    from deerflow.agents.middlewares.clarification_middleware import ClarificationMiddleware

    _, actions, service = plugin
    runs = Runs()
    jobs = await queue_active_budget_jobs(actions, runs)
    for job in jobs[:8]:
        state = runs.threads[job["thread_id"]]
        if wait_kind == "interrupt":
            state.update(next=["tools"], interrupts=[{"value": "Approve?"}])
        else:
            request = SimpleNamespace(tool_call={"name": "ask_clarification", "id": "outside", "args": {"question": "Which environment?", "clarification_type": "missing_info"}}, runtime=None)
            command = ClarificationMiddleware().wrap_tool_call(request, lambda _: pytest.fail("tool handler should be intercepted"))
            state["values"]["messages"].extend(m.model_dump() for m in command.update["messages"])
    # A later request on the same waiting conversation must still remain queued.
    blocked = jobs[0]
    await actions["send"]({"team_id": blocked["team_id"], "member_id": blocked["member_id"], "text": "Later", "request_id": "later"}, context(runs))
    for _ in range(2):
        await service.tick()
        assert [thread for thread, _ in runs.starts] == [jobs[-1]["thread_id"]]
        for job in jobs[:8]:
            stored = await service.db("get", job["owner"], job["team_id"])
            assert all(item["status"] == "queued" and item["input"] is None for item in stored["jobs"])
    healthy = await actions["get"]({"team_id": jobs[-1]["team_id"]}, context(runs, "bob"))
    assert healthy["jobs"][0]["status"] == "running"


@pytest.mark.asyncio
@pytest.mark.parametrize("lost_ack", [False, True])
async def test_active_budget_retains_real_and_ambiguous_admissions(plugin, monkeypatch, lost_ack):
    _, actions, service = plugin
    runs = Runs()
    jobs = await queue_active_budget_jobs(actions, runs)
    if lost_ack:
        start = runs.start

        async def uncertain(**kwargs):
            await start(**kwargs)
            raise TimeoutError("admitted but acknowledgement lost")

        monkeypatch.setattr(runs, "start", uncertain)
    first_admissions = None
    for _ in range(2):
        await service.tick()
        assert len(runs.starts) == 8
        if first_admissions is None:
            first_admissions = set(runs.runs)
        assert set(runs.runs) == first_admissions
        for job in jobs:
            stored = await service.db("get", job["owner"], job["team_id"])
            saved = next(item for item in stored["jobs"] if item["id"] == job["id"])
            assert (saved["input"] is not None) == (job["id"] in first_admissions)
    assert jobs[-1]["id"] in first_admissions  # Bob receives a fair admission.


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


async def scheduling_team(actions, runs, owner, key, members=2):
    return await actions["create"]({"request_id": key, "name": key, "goal": "Check scheduling", "members": [{"name": f"Member {i}", "agent": "researcher"} for i in range(members)]}, context(runs, owner))


async def scheduling_send(actions, runs, owner, team, member, key):
    return await actions["send"]({"team_id": team["id"], "member_id": member["id"], "text": "Check", "request_id": key + member["id"]}, context(runs, owner))


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "send", "connect", "cancel", "resume", "delete"])
async def test_slow_team_does_not_block_another_teams_control(plugin, monkeypatch, operation):
    _, actions, service = plugin
    runs = Runs()
    slow = await scheduling_team(actions, runs, "alice", "Slow")
    healthy = await scheduling_team(actions, runs, "bob", "Healthy")
    slow_job = await scheduling_send(actions, runs, "alice", slow, slow["members"][0], "slow")
    healthy_job = None
    if operation in ("cancel", "resume"):
        healthy_job = await scheduling_send(actions, runs, "bob", healthy, healthy["members"][0], "healthy")
    await service.tick()
    if operation == "resume":
        runs.finish(healthy_job["id"], interrupted=True)
        await service.tick()
    entered, release = asyncio.Event(), asyncio.Event()
    get = runs.get

    async def stalled(**kwargs):
        if kwargs["thread_id"] == slow["members"][0]["thread_id"]:
            entered.set()
            await release.wait()
        return await get(**kwargs)

    monkeypatch.setattr(runs, "get", stalled)
    tick = asyncio.create_task(service.tick())
    control = None
    try:
        await asyncio.wait_for(entered.wait(), 2)
        if operation == "create":
            control = asyncio.create_task(scheduling_team(actions, runs, "bob", "New"))
        elif operation == "send":
            control = asyncio.create_task(scheduling_send(actions, runs, "bob", healthy, healthy["members"][1], "second"))
        else:
            payload = {"team_id": healthy["id"]}
            if healthy_job:
                payload["job_id"] = healthy_job["id"]
            if operation == "resume":
                payload.update(response={"approved": True}, request_id="answer")
            control = asyncio.create_task(actions[operation](payload, context(runs, "bob")))
        await asyncio.wait_for(asyncio.shield(control), 2)
        assert not release.is_set()
        assert runs.runs[slow_job["id"]].status == "running"
    finally:
        release.set()
        await tick
        if control:
            await control


@pytest.mark.asyncio
async def test_new_admissions_are_round_robin_by_owner_not_team_count(plugin):
    _, actions, service = plugin
    runs = Runs()
    owners = {}
    for owner, count, members in (("alice", 4, 2), ("bob", 1, 8)):
        for index in range(count):
            team = await scheduling_team(actions, runs, owner, f"{owner}-{index}", members)
            for member in team["members"]:
                owners[member["thread_id"]] = owner
                await scheduling_send(actions, runs, owner, team, member, "first")
    await service.tick()
    started = [owners[thread] for thread, _ in runs.starts]
    assert len(started) == 8
    assert started.count("alice") == started.count("bob") == 4


@pytest.mark.asyncio
async def test_owner_rotation_survives_one_slot_at_a_time(plugin):
    _, actions, service = plugin
    runs = Runs()
    owners = {}
    for owner in ("alice", "bob"):
        team = await scheduling_team(actions, runs, owner, owner, 8)
        for member in team["members"]:
            owners[member["thread_id"]] = owner
            await scheduling_send(actions, runs, owner, team, member, "first")
    await service.tick()
    admitted = []
    for _ in range(4):
        first = next(run for run in runs.runs.values() if run.status == "running")
        runs.finish(first.run_id)
        before = len(runs.starts)
        await service.tick()
        assert len(runs.starts) == before + 1
        admitted.append(owners[runs.starts[-1][0]])
        assert sum(run.status == "running" for run in runs.runs.values()) == 8
    assert admitted == ["alice", "bob", "alice", "bob"]


@pytest.mark.asyncio
async def test_owner_rotation_finishes_the_round_after_single_job_owners_leave_pending(plugin):
    _, actions, service = plugin
    runs = Runs()
    owners = {}
    for owner, members in [("alice", 8), *((f"owner-{i}", 2) for i in range(1, 17))]:
        team = await scheduling_team(actions, runs, owner, owner, members)
        for member in team["members"][: 8 if owner == "alice" else 1]:
            owners[member["thread_id"]] = owner
            await scheduling_send(actions, runs, owner, team, member, "first")
    await service.tick()
    assert {owners[thread] for thread, _ in runs.starts} == {"alice", *(f"owner-{i}" for i in range(1, 8))}
    admitted = []
    for _ in range(10):
        first = next(run for run in runs.runs.values() if run.status == "running")
        runs.finish(first.run_id)
        before = len(runs.starts)
        await service.tick()
        assert len(runs.starts) == before + 1
        admitted.append(owners[runs.starts[-1][0]])
        assert sum(run.status == "running" for run in runs.runs.values()) == 8
    assert admitted == [*(f"owner-{i}" for i in range(8, 17)), "alice"]


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_waiting_owner", [False, True])
async def test_owner_rotation_appends_new_owners_and_drops_cancelled_queues(plugin, cancel_waiting_owner):
    _, actions, service = plugin
    runs = Runs()
    owners, waiting = {}, None
    for owner, members in [("alice", 8), *((f"owner-{i}", 2) for i in range(1, 9))]:
        team = await scheduling_team(actions, runs, owner, owner, members)
        for member in team["members"][: 8 if owner == "alice" else 1]:
            owners[member["thread_id"]] = owner
            sent = await scheduling_send(actions, runs, owner, team, member, "first")
            if owner == "owner-8":
                waiting = (team, sent)
    await service.tick()
    late = await scheduling_team(actions, runs, "late", "late")
    owners[late["members"][0]["thread_id"]] = "late"
    await scheduling_send(actions, runs, "late", late, late["members"][0], "first")
    if cancel_waiting_owner:
        team, sent = waiting
        await actions["cancel"]({"team_id": team["id"], "job_id": sent["id"]}, context(runs, "owner-8"))
        await actions["delete"]({"team_id": team["id"]}, context(runs, "owner-8"))
    admitted = []
    for _ in range(4):
        first = next(run for run in runs.runs.values() if run.status == "running")
        runs.finish(first.run_id)
        before = len(runs.starts)
        await service.tick()
        assert len(runs.starts) == before + 1
        admitted.append(owners[runs.starts[-1][0]])
        assert sum(run.status == "running" for run in runs.runs.values()) == 8
    assert admitted == (["alice", "late", "alice", "alice"] if cancel_waiting_owner else ["owner-8", "alice", "late", "alice"])
    # With only Alice's backlog left, spare slots must remain usable.
    for run in list(runs.runs.values()):
        if run.status == "running":
            runs.finish(run.run_id)
    await service.tick()
    assert len(runs.starts) == (16 if cancel_waiting_owner else 17)
    for run in list(runs.runs.values()):
        if run.status == "running":
            runs.finish(run.run_id)
    await service.tick()
    assert not any(run.status == "running" for run in runs.runs.values())


@pytest.mark.asyncio
async def test_background_loop_keeps_cancelling_other_teams_while_one_call_stalls(plugin, monkeypatch):
    _, actions, service = plugin
    runs = Runs()
    slow = await scheduling_team(actions, runs, "alice", "Slow")
    healthy = await scheduling_team(actions, runs, "bob", "Healthy")
    await scheduling_send(actions, runs, "alice", slow, slow["members"][0], "slow")
    sent = await scheduling_send(actions, runs, "bob", healthy, healthy["members"][0], "healthy")
    entered, healthy_running, cancelled, release = (asyncio.Event() for _ in range(4))
    get, cancel = runs.get, runs.cancel

    async def stalled(**kwargs):
        if kwargs["thread_id"] == slow["members"][0]["thread_id"]:
            entered.set()
            await release.wait()
        else:
            healthy_running.set()
        return await get(**kwargs)

    async def record_cancel(**kwargs):
        await cancel(**kwargs)
        cancelled.set()

    monkeypatch.setattr(runs, "get", stalled)
    monkeypatch.setattr(runs, "cancel", record_cancel)
    await service.start(None)
    try:
        await asyncio.wait_for(entered.wait(), 3)
        await asyncio.wait_for(healthy_running.wait(), 3)
        await asyncio.wait_for(actions["cancel"]({"team_id": healthy["id"], "job_id": sent["id"]}, context(runs, "bob")), 2)
        await asyncio.wait_for(cancelled.wait(), 3)
        assert not release.is_set()
        # Shutdown cancels and drains gated workers; it never needs the host gate.
        await asyncio.wait_for(service.stop(), 3)
        assert not service.workers and not service.in_flight
        assert not service.available and service.process_lock is None
    finally:
        release.set()
        await service.stop()


@pytest.mark.asyncio
async def test_overlapping_ticks_keep_pre_freeze_reservations_within_eight(plugin, monkeypatch):
    _, actions, service = plugin
    runs = Runs()
    for index in range(9):
        owner = f"owner-{index}"
        team = await scheduling_team(actions, runs, owner, owner)
        await scheduling_send(actions, runs, owner, team, team["members"][0], "first")
    entered, release = asyncio.Event(), asyncio.Event()
    get_state = runs.get_state

    async def gated(**kwargs):
        entered.set()
        await release.wait()
        return await get_state(**kwargs)

    monkeypatch.setattr(runs, "get_state", gated)
    first = asyncio.create_task(service.tick())
    try:
        await asyncio.wait_for(entered.wait(), 3)
        await asyncio.wait_for(asyncio.gather(*(service.tick() for _ in range(3))), 2)
        assert not runs.starts  # No input has frozen; reservations still own slots.
    finally:
        release.set()
        await first
    assert len(runs.starts) == 8
    assert not service.in_flight and not service.workers


@pytest.mark.asyncio
async def test_more_than_eight_owners_rotate_into_the_next_free_slot(plugin):
    _, actions, service = plugin
    runs = Runs()
    jobs = []
    for index in range(9):
        owner = f"owner-{index}"
        team = await scheduling_team(actions, runs, owner, owner)
        jobs.append(await scheduling_send(actions, runs, owner, team, team["members"][0], "first"))
    await service.tick()
    assert set(runs.runs) == {job["id"] for job in jobs[:8]}
    runs.finish(jobs[0]["id"])
    await service.tick()
    assert jobs[-1]["id"] in runs.runs
    assert sum(run.status == "running" for run in runs.runs.values()) == 8


@pytest.mark.asyncio
async def test_pending_resumes_wait_for_slots_and_cancel_without_admitting_an_answer(plugin):
    _, actions, service = plugin
    runs = Runs()
    parked = await scheduling_team(actions, runs, "alice", "Parked")
    sent = await scheduling_send(actions, runs, "alice", parked, parked["members"][0], "park")
    await service.tick()
    runs.finish(sent["id"], interrupted=True)
    await service.tick()
    busy = await scheduling_team(actions, runs, "bob", "Busy", 8)
    for member in busy["members"]:
        await scheduling_send(actions, runs, "bob", busy, member, "busy")
    await service.tick()
    assert sum(run.status == "running" for run in runs.runs.values()) == 8
    payload = {"team_id": parked["id"], "job_id": sent["id"], "response": {"approved": True}, "request_id": "answer"}
    await actions["resume"](payload, context(runs, "alice"))
    await service.tick()
    assert len(runs.runs) == 9  # The finished interrupted run plus eight busy runs.
    assert (await service.db("get", "alice", parked["id"]))["jobs"][0]["status"] == "resuming"
    await actions["cancel"]({"team_id": parked["id"], "job_id": sent["id"]}, context(runs, "alice"))
    await service.tick()
    assert len(runs.runs) == 9
    assert (await service.db("get", "alice", parked["id"]))["jobs"][0]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_frozen_slots_survive_disconnection_and_service_restart(plugin, monkeypatch):
    from deerflow_extension_agent_teams.service import Teams

    _, actions, service = plugin
    runs = Runs()
    team = await scheduling_team(actions, runs, "alice", "Busy", 8)
    for member in team["members"]:
        await scheduling_send(actions, runs, "alice", team, member, "busy")
    await service.tick()
    runs.denied = True
    await service.tick()
    assert not service.handles and len(runs.starts) == 8
    replacement = Teams(service.store.path)
    healthy_runs = Runs()
    # The real start loads the durable slot owners even before they reconnect.
    await replacement.start(None)
    try:
        healthy = await scheduling_team({"create": replacement.create}, healthy_runs, "bob", "Healthy")
        await scheduling_send({"send": replacement.send}, healthy_runs, "bob", healthy, healthy["members"][0], "new")
        await replacement.tick()
        assert not healthy_runs.starts
        runs.denied = False
        await replacement.connect({"team_id": team["id"]}, context(runs))
        for run in list(runs.runs.values()):
            runs.finish(run.run_id)
        await replacement.tick()
        await replacement.tick()
        assert len(healthy_runs.starts) == 1
    finally:
        await replacement.stop()


@pytest.mark.asyncio
async def test_receipts_for_a_shared_source_are_serialized_across_teams(plugin):
    from deerflow_extension_agent_teams.service import identity

    _, actions, service = plugin
    runs = Runs()
    await runs.create_thread(assistant_id="lead_agent", thread_id="shared", metadata={})
    requests = []
    for owner in ("alice", "bob"):
        team = await scheduling_team(actions, runs, owner, owner)
        sent = await service.db("change", owner, team["id"], lambda t: service.enqueue(t, member_id=t["members"][0]["id"], content="Check", request_id="shared-request", source="shared"))
        requests.append((owner, team, sent))
    await service.tick()
    for _, _, job in requests:
        runs.finish(job["id"])
    await service.tick()
    await service.tick()
    receipts = []
    for owner, team, request in requests:
        stored = await service.db("get", owner, team["id"])
        receipt = next(j for j in stored["jobs"] if j["id"] == identity(request["id"], "receipt"))
        receipts.append((receipt["created_at"], owner, team, receipt))
    receipts.sort(key=lambda entry: entry[0])
    first, later = receipts
    assert first[3]["id"] in runs.runs and later[3]["id"] not in runs.runs
    assert later[3]["input"] is None  # No competing admission/checkpoint on the source.
    runs.finish(first[3]["id"])
    await service.tick()
    await service.tick()
    assert later[3]["id"] in runs.runs
    assert sum(thread == "shared" for thread, _ in runs.starts) == 2


@pytest.mark.asyncio
async def test_startup_snapshot_failure_releases_the_process_lock(plugin, monkeypatch):
    from deerflow_extension_agent_teams.service import Teams

    _, _, service = plugin
    db = service.db

    async def fail_snapshot(method, *args):
        if method == "scheduling_snapshots":
            raise OSError("snapshot failed")
        return await db(method, *args)

    monkeypatch.setattr(service, "db", fail_snapshot)
    with pytest.raises(OSError, match="snapshot failed"):
        await service.start(None)
    assert service.process_lock is None and not service.task
    second = Teams(service.store.path)
    await second.start(None)
    await second.stop()


@pytest.mark.asyncio
async def test_first_unfinished_thread_occupant_does_not_depend_on_timestamps(plugin):
    _, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    member = team["members"][0]
    first = await scheduling_send(actions, runs, "alice", team, member, "first")
    later = await scheduling_send(actions, runs, "alice", team, member, "later")
    await service.db("change", "alice", team["id"], lambda t: t["jobs"][1].pop("created_at"))
    await service.tick()
    assert first["id"] in runs.runs and later["id"] not in runs.runs


@pytest.mark.asyncio
async def test_cancel_and_delete_before_worker_admission_release_only_that_reservation(plugin, monkeypatch):
    _, actions, service = plugin
    runs = Runs()
    jobs = []
    for index in range(9):
        owner = f"owner-{index}"
        team = await scheduling_team(actions, runs, owner, owner)
        sent = await scheduling_send(actions, runs, owner, team, team["members"][0], "first")
        jobs.append((owner, team, sent))
    entered, release = asyncio.Event(), asyncio.Event()
    work_team = service.work_team
    ready = 0

    async def gated(*args):
        nonlocal ready
        ready += 1
        if ready == 8:
            entered.set()
        await release.wait()
        await work_team(*args)

    monkeypatch.setattr(service, "work_team", gated)
    tick = asyncio.create_task(service.tick())
    try:
        await asyncio.wait_for(entered.wait(), 3)
        owner, team, sent = jobs[0]
        await actions["cancel"]({"team_id": team["id"], "job_id": sent["id"]}, context(runs, owner))
        await actions["delete"]({"team_id": team["id"]}, context(runs, owner))
        assert not runs.starts
    finally:
        release.set()
        await tick
    assert sent["id"] not in runs.runs
    assert len(runs.starts) == 8 and jobs[-1][2]["id"] in runs.runs
    assert not service.workers and not service.in_flight


@pytest.mark.asyncio
async def test_resume_with_lost_ack_keeps_its_slot_before_any_new_owner_admission(plugin, monkeypatch):
    _, actions, service = plugin
    runs = Runs()
    parked = await scheduling_team(actions, runs, "alice", "Parked")
    sent = await scheduling_send(actions, runs, "alice", parked, parked["members"][0], "park")
    await service.tick()
    runs.finish(sent["id"], interrupted=True)
    await service.tick()
    busy = await scheduling_team(actions, runs, "bob", "Busy", 8)
    for member in busy["members"][:7]:
        await scheduling_send(actions, runs, "bob", busy, member, "busy")
    await service.tick()
    start = runs.resume

    async def lost_ack(**kwargs):
        await start(**kwargs)
        raise TimeoutError("resume admitted; acknowledgement lost")

    monkeypatch.setattr(runs, "resume", lost_ack)
    await actions["resume"]({"team_id": parked["id"], "job_id": sent["id"], "response": {"approved": True}, "request_id": "answer"}, context(runs, "alice"))
    await service.tick()
    stored = (await service.db("get", "alice", parked["id"]))["jobs"][0]
    assert stored["resume"]["started"]
    later = await scheduling_team(actions, runs, "carol", "Later")
    queued = await scheduling_send(actions, runs, "carol", later, later["members"][0], "new")
    await service.tick()
    assert queued["id"] not in runs.runs
    assert sum(run.status == "running" for run in runs.runs.values()) == 8


@pytest.mark.asyncio
async def test_scheduler_does_not_read_or_decode_completed_history_per_team(plugin, monkeypatch):
    _, actions, service = plugin
    runs = Runs()
    for index in range(100):
        owner = f"archive-{index // 20}"
        team = await scheduling_team(actions, runs, owner, f"History {index}")
        await scheduling_send(actions, runs, owner, team, team["members"][0], "completed")
        await service.db("change", owner, team["id"], lambda t: t["jobs"][0].update(status="completed", input={"messages": []}))
    connections, decoded = [], []
    connect, decode = service.store.connection, json.loads

    def record_connection():
        db = connect()
        connections.append(db)
        return db

    def record_decode(*args, **kwargs):
        decoded.append(1)
        return decode(*args, **kwargs)

    monkeypatch.setattr(service.store, "connection", record_connection)
    monkeypatch.setattr(json, "loads", record_decode)
    await service.tick(wait=False)
    assert len(connections) == 1
    assert not decoded and not runs.starts


@pytest.mark.asyncio
async def test_deleted_team_does_not_leave_a_repeated_missing_key_lookup(plugin, monkeypatch):
    _, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    await service.db("delete", "alice", team["id"])
    methods = []
    db = service.db

    async def record(method, *args):
        methods.append(method)
        return await db(method, *args)

    monkeypatch.setattr(service, "db", record)
    await service.tick(wait=False)
    await service.tick(wait=False)
    assert "get" not in methods
    assert not service.workers


@pytest.mark.asyncio
async def test_pending_projection_tracks_queue_wait_finish_and_requeue(plugin):
    _, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    key = ("alice", team["id"])
    assert key not in await service.db("scheduling_snapshots")
    sent = await scheduling_send(actions, runs, "alice", team, team["members"][0], "first")
    assert key in await service.db("scheduling_snapshots")
    await service.tick()
    runs.finish(sent["id"], interrupted=True)
    await service.tick()
    waiting = (await service.db("scheduling_snapshots"))[key]["jobs"][0]
    assert waiting["status"] == "waiting_input" and waiting["input"] is not None
    assert not service.charged(waiting)  # Keep the thread head, release the slot.
    await actions["cancel"]({"team_id": team["id"], "job_id": sent["id"]}, context(runs))
    await service.tick()
    assert key not in await service.db("scheduling_snapshots")
    assert (await actions["get"]({"team_id": team["id"]}, context(runs)))["connected"]
    runs.threads[team["members"][0]["thread_id"]].update(next=[], interrupts=[])
    await scheduling_send(actions, runs, "alice", team, team["members"][0], "second")
    assert key in await service.db("scheduling_snapshots")


@pytest.mark.asyncio
async def test_pending_projection_keeps_a_receipt_created_by_terminal_result(plugin):
    _, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    sender, recipient = team["members"]
    sent = await actions["send"]({"team_id": team["id"], "member_id": recipient["id"], "text": "Check", "request_id": "peer"}, context(runs, thread=sender["thread_id"]))
    await service.tick()
    runs.finish(sent["id"])
    await service.tick()
    jobs = (await service.db("scheduling_snapshots"))[("alice", team["id"])]["jobs"]
    assert jobs[0]["status"] == "completed" and jobs[-1]["kind"] == "receipt"
    assert jobs[-1]["status"] == "queued"


def test_pending_projection_backfills_legacy_rows_and_uses_an_index(plugin, tmp_path):
    import sqlite3
    from contextlib import closing

    from deerflow_extension_agent_teams.store import Store

    path = tmp_path / "legacy.sqlite"
    states = ["completed", "queued", "waiting_input", "resuming", "unknown-legacy-state"]
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE teams (id TEXT PRIMARY KEY, owner TEXT NOT NULL, data TEXT NOT NULL)")
        for index, status in enumerate(states):
            job = {"status": status, "input": {"messages": []}, "resume": {"started": False}}
            db.execute("INSERT INTO teams VALUES (?,?,?)", (str(index), f"owner-{index}", json.dumps({"jobs": [job]})))
    store = Store(path)
    snapshots = store.scheduling_snapshots()
    assert set(snapshots) == {(f"owner-{i}", str(i)) for i in range(1, len(states))}
    with closing(store.connection()) as db:
        plan = db.execute("EXPLAIN QUERY PLAN SELECT owner, id, data FROM teams WHERE has_pending_jobs=1 ORDER BY rowid").fetchall()
        assert any("teams_pending_jobs" in row[3] for row in plan)
    # Reopening must use the projection instead of re-decoding legacy history.
    again = Store(path)
    assert again.scheduling_snapshots() == snapshots


def test_legacy_backfill_finishes_reading_before_updating_the_scanned_table(plugin, tmp_path, monkeypatch):
    import sqlite3
    from contextlib import closing

    from deerflow_extension_agent_teams.store import Store

    class BackfillCursor(sqlite3.Cursor):
        def fetchall(self):
            rows = super().fetchall()
            self.connection.scanning = False
            return rows

        def __next__(self):
            try:
                return super().__next__()
            except StopIteration:
                self.connection.scanning = False
                raise

    class BackfillConnection(sqlite3.Connection):
        scanning = False

        def execute(self, sql, parameters=()):
            if sql.startswith("UPDATE teams"):
                assert not self.scanning, "Updating teams before its SELECT has finished"
            cursor = self.cursor(BackfillCursor).execute(sql, parameters)
            if sql == "SELECT id, data FROM teams":
                self.scanning = True
            return cursor

    path = tmp_path / "legacy-scan.sqlite"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE teams (id TEXT PRIMARY KEY, owner TEXT NOT NULL, data TEXT NOT NULL)")
        for index in range(100):
            db.execute("INSERT INTO teams VALUES (?,?,?)", (str(index), "alice", json.dumps({"jobs": [{"status": "completed" if index % 2 else "queued"}], "padding": "x" * 4000})))
    monkeypatch.setattr(Store, "connection", lambda store: sqlite3.connect(store.path, factory=BackfillConnection))
    assert set(Store(path).scheduling_snapshots()) == {("alice", str(i)) for i in range(0, 100, 2)}


def test_failed_projection_backfill_rolls_back_schema_and_rows(plugin, tmp_path):
    import sqlite3
    from contextlib import closing

    from deerflow_extension_agent_teams.store import Store

    path = tmp_path / "invalid-legacy.sqlite"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE teams (id TEXT PRIMARY KEY, owner TEXT NOT NULL, data TEXT NOT NULL)")
        db.execute("INSERT INTO teams VALUES ('first','alice',?)", (json.dumps({"jobs": [{"status": "queued"}]}),))
        db.execute("INSERT INTO teams VALUES ('invalid','bob','invalid json')")
    with pytest.raises(json.JSONDecodeError):
        Store(path)
    with closing(sqlite3.connect(path)) as db, db:
        assert "has_pending_jobs" not in {row[1] for row in db.execute("PRAGMA table_info(teams)")}
        db.execute("UPDATE teams SET data=? WHERE id='invalid'", (json.dumps({"jobs": [{"status": "completed"}]}),))
    assert set(Store(path).scheduling_snapshots()) == {("alice", "first")}


@pytest.mark.asyncio
async def test_history_results_remain_retrievable_after_shared_messages_rotate_and_restart(plugin):
    from deerflow_extension_agent_teams.service import Teams

    _, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    researcher, reviewer = team["members"]
    sent = await scheduling_send(actions, runs, "alice", team, researcher, "research")
    await service.tick()
    runs.finish(sent["id"], "Original research evidence")
    await service.tick()
    for index in range(51):
        later = await scheduling_send(actions, runs, "alice", team, researcher, f"later-{index}")
        stored = await service.db("get", "alice", team["id"])
        await service.finish("alice", stored, next(job for job in stored["jobs"] if job["id"] == later["id"]), "completed", "Later evidence")
    caller = context(runs, thread=reviewer["thread_id"])
    stored = await service.db("get", "alice", team["id"])
    assert len(stored["messages"]) == 100
    assert not any(message["job_id"] == sent["id"] for message in stored["messages"])
    found = await service.search_results({"team_id": team["id"], "member_id": researcher["id"], "query": "ORIGINAL research"}, caller)
    assert [item["job_id"] for item in found["items"]] == [sent["id"]]
    result = await service.read_result({"team_id": team["id"], "job_id": sent["id"]}, caller)
    assert result["result"] == {"available": True, "text": "Original research evidence", "truncated": False, "reason": None}
    assert result["member_id"] == researcher["id"] and result["conversation"]["thread_id"] == researcher["thread_id"]
    assert result["conversation"]["run_id"] == sent["id"]
    replacement = Teams(service.store.path)
    assert await replacement.search_results({"team_id": team["id"], "member_id": researcher["id"], "query": "ORIGINAL research"}, caller) == found
    assert await replacement.read_result({"team_id": team["id"], "job_id": sent["id"]}, caller) == result
    assert not replacement.handles and not replacement.available
    assert await service.db("get", "alice", team["id"]) == stored


@pytest.mark.asyncio
async def test_history_pages_keep_their_anchor_when_messages_arrive_and_report_expiry(plugin):
    _, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    member = team["members"][0]
    caller = context(runs, thread=member["thread_id"])
    jobs = [await scheduling_send(actions, runs, "alice", team, member, str(i)) for i in range(5)]
    page = await service.read_history({"team_id": team["id"], "member_id": member["id"], "limit": 2}, caller)
    assert [item["job_id"] for item in page["items"]] == [jobs[4]["id"], jobs[3]["id"]]
    await scheduling_send(actions, runs, "alice", team, member, "new")
    payload = {"team_id": team["id"], "member_id": member["id"], "cursor": page["next_cursor"], "limit": 2}
    later = await service.read_history(payload, caller)
    assert [item["job_id"] for item in later["items"]] == [jobs[2]["id"], jobs[1]["id"]]
    final = await service.read_history({**payload, "cursor": later["next_cursor"]}, caller)
    assert [item["job_id"] for item in final["items"]] == [jobs[0]["id"]] and final["next_cursor"] is None
    with pytest.raises(ValueError, match="cursor|Cursor"):
        await service.read_history({**payload, "member_id": team["members"][1]["id"]}, caller)
    await service.db("change", "alice", team["id"], lambda t: t.update(messages=t["messages"][-1:]))
    expired = await service.read_history(payload, caller)
    assert expired["cursor_expired"] and expired["items"] == [] and expired["next_cursor"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["read_history", "search_results", "read_result"])
@pytest.mark.parametrize("owner,thread", [("bob", "member"), ("alice", "outside"), ("alice", None)])
async def test_history_tools_require_the_owner_and_a_current_member_thread(plugin, method, owner, thread):
    _, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    job = await scheduling_send(actions, runs, "alice", team, team["members"][0], "one")
    payload = {"team_id": team["id"], **({"job_id": job["id"]} if method == "read_result" else {})}
    actual_thread = team["members"][0]["thread_id"] if thread == "member" else thread
    caller = ToolContext(ExtensionPrincipal(owner), {"enabled": True}, actual_thread, agent_runs=runs)
    with pytest.raises(ValueError):
        await getattr(service, method)(payload, caller)


@pytest.mark.asyncio
@pytest.mark.parametrize("extra", [{"limit": 0}, {"limit": 21}, {"limit": True}, {"cursor": "bad"}, {"query": []}, {"query": " "}, {"member_id": "missing"}, {"owner": "bob"}])
async def test_history_page_options_are_validated(plugin, extra):
    _, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    caller = context(runs, thread=team["members"][0]["thread_id"])
    with pytest.raises(ValueError):
        await service.read_history({"team_id": team["id"], **extra}, caller)


@pytest.mark.asyncio
async def test_history_pages_bound_escaped_unicode_and_keep_forward_progress(plugin):
    _, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    member = team["members"][0]
    caller = context(runs, thread=member["thread_id"])
    jobs = [await actions["send"]({"team_id": team["id"], "member_id": member["id"], "text": '\\"' * 2000, "request_id": str(i)}, context(runs)) for i in range(20)]
    cursor, seen = None, []
    while True:
        page = await service.read_history({"team_id": team["id"], "limit": 20, **({"cursor": cursor} if cursor else {})}, caller)
        assert len(json.dumps(page, ensure_ascii=False).encode()) <= 24000
        assert page["items"]
        seen.extend(item["job_id"] for item in page["items"])
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert seen == [job["id"] for job in reversed(jobs)]
    await service.db("change", "alice", team["id"], lambda t: t["messages"][-1].update(text="中😀" * 4000))
    page = await service.read_history({"team_id": team["id"], "limit": 1}, caller)
    assert page["items"][0]["truncated"] and len(page["items"][0]["text"].encode()) <= 6000


@pytest.mark.asyncio
async def test_history_result_reports_legacy_unavailability_and_never_projects_execution_inputs(plugin):
    _, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    member = team["members"][0]
    caller = context(runs, thread=member["thread_id"])
    sent = await scheduling_send(actions, runs, "alice", team, member, "old")
    stored = await service.db("get", "alice", team["id"])
    await service.finish("alice", stored, stored["jobs"][0], "completed", "Legacy evidence")

    def legacy(t):
        t["jobs"][0].pop("result")
        t["jobs"][0].pop("result_truncated", None)
        t["jobs"][0].update(input={"private": "frozen-secret"}, resume={"response": "approval-secret"})

    await service.db("change", "alice", team["id"], legacy)
    result = await service.read_result({"team_id": team["id"], "job_id": sent["id"]}, caller)
    assert result["result"]["text"] == "Legacy evidence" and result["result"]["truncated"] is None
    page = await service.read_history({"team_id": team["id"], "job_id": sent["id"]}, caller)
    assert page["items"][0]["truncated"] is None
    assert "frozen-secret" not in json.dumps(result) and "approval-secret" not in json.dumps(result)
    await service.db("change", "alice", team["id"], lambda t: t.update(messages=[]))
    result = await service.read_result({"team_id": team["id"], "job_id": sent["id"]}, caller)
    assert result["result"] == {"available": False, "text": None, "truncated": None, "reason": "not_retained"}
    assert result["conversation"]["thread_id"] == member["thread_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", ["Evidence", "中😀" * 1000], ids=["short", "truncated"])
async def test_history_result_preserves_admission_and_output_truncation_provenance(plugin, answer):
    _, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    member = team["members"][0]
    job = await scheduling_send(actions, runs, "alice", team, member, "one")
    caller = context(runs, thread=member["thread_id"])
    pending = await service.read_result({"team_id": team["id"], "job_id": job["id"]}, caller)
    assert pending["result"]["reason"] == "not_completed"
    await service.tick()
    runs.finish(job["id"], answer)
    await service.tick()
    result = await service.read_result({"team_id": team["id"], "job_id": job["id"]}, caller)
    assert result["result"]["truncated"] is (len(answer.encode()) > 6000)
    assert len(result["result"]["text"].encode()) <= 6000
    assert result["status"] == "completed" and result["conversation"]["run_id"] == job["id"]


@pytest.mark.asyncio
async def test_history_result_search_pages_filter_jobs_and_exclude_delivery_receipts(plugin):
    _, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    sender, recipient = team["members"]
    caller = context(runs, thread=sender["thread_id"])
    jobs = []
    for index in range(4):
        sent = await actions["send"]({"team_id": team["id"], "member_id": recipient["id"], "text": "Review original evidence", "request_id": str(index)}, caller)
        stored = await service.db("get", "alice", team["id"])
        job = next(j for j in stored["jobs"] if j["id"] == sent["id"])
        await service.finish("alice", stored, job, "failed" if index == 3 else "completed", "Final evidence")
        jobs.append(sent)
    cancelled = await scheduling_send(actions, runs, "alice", team, sender, "cancel")
    await actions["cancel"]({"team_id": team["id"], "job_id": cancelled["id"]}, context(runs))
    cancelled_result = await service.read_result({"team_id": team["id"], "job_id": cancelled["id"]}, caller)
    assert cancelled_result["result"]["reason"] == "cancelled"
    payload = {"team_id": team["id"], "member_id": recipient["id"], "query": "ORIGINAL", "limit": 2}
    first = await service.search_results(payload, caller)
    assert [item["job_id"] for item in first["items"]] == [job["id"] for job in reversed(jobs[2:])]
    assert first["items"][0]["status"] == "failed"
    assert all(item["kind"] == "request" and item["requester_member_id"] == sender["id"] for item in first["items"])
    second = await service.search_results({**payload, "cursor": first["next_cursor"]}, caller)
    assert [item["job_id"] for item in second["items"]] == [job["id"] for job in reversed(jobs[:2])]
    assert second["next_cursor"] is None
    one = await service.search_results({"team_id": team["id"], "job_id": jobs[0]["id"]}, caller)
    assert one["total_matches"] == 1
    assert len(json.dumps(first, ensure_ascii=False).encode()) <= 24000


@pytest.mark.asyncio
async def test_history_tools_dispatch_through_real_tool_node_and_continue_a_peer_handoff(plugin):
    from deerflow_extension_api.agent_runs import AGENT_RUNS_CONTEXT_KEY
    from langchain_core.messages import AIMessage
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langgraph.prebuilt import ToolNode

    from deerflow.extensions.plugin_tools import build_plugin_tools

    loaded, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    researcher, reviewer = team["members"]
    job = await scheduling_send(actions, runs, "alice", team, researcher, "research")
    await service.tick()
    runs.finish(job["id"], "Original evidence for peer review")
    await service.tick()
    tools = [tool for tool in build_plugin_tools(loaded) if any(name in tool.name for name in ("read_team_history", "search_team_results", "read_team_result"))]
    assert len(tools) == 3
    graph = StateGraph(MessagesState)
    graph.add_node("tools", ToolNode(tools))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    calls = [{"name": tool.name, "args": {"team_id": team["id"], "job_id": job["id"]}, "id": tool.name} for tool in tools]
    compiled = graph.compile()
    result = await compiled.ainvoke({"messages": [AIMessage(content="", tool_calls=calls)]}, context={"thread_id": reviewer["thread_id"], "user_id": "alice", AGENT_RUNS_CONTEXT_KEY: runs})
    outputs = {message.tool_call_id: json.loads(message.content) for message in result["messages"] if message.type == "tool"}
    saved = next(value for name, value in outputs.items() if "read_team_result" in name)
    assert saved["result"]["text"] == "Original evidence for peer review"
    sent = await actions["send"]({"team_id": team["id"], "member_id": researcher["id"], "text": "Review retrieved evidence: " + saved["result"]["text"], "request_id": "retrieved-handoff"}, context(runs, thread=reviewer["thread_id"]))
    await service.tick()
    assert sent["id"] in runs.runs
    assert "Original evidence for peer review" in runs.starts[-1][1]["messages"][0]["content"]
    denied = await compiled.ainvoke({"messages": [AIMessage(content="", tool_calls=calls)]}, context={"thread_id": "outside", "user_id": "alice", AGENT_RUNS_CONTEXT_KEY: runs})
    assert all("Original evidence" not in message.content for message in denied["messages"] if message.type == "tool")


@pytest.mark.asyncio
async def test_history_result_pages_and_reads_bound_the_complete_escaped_json(plugin):
    _, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    member = team["members"][0]
    caller = context(runs, thread=member["thread_id"])
    jobs = []
    for index in range(20):
        sent = await actions["send"]({"team_id": team["id"], "member_id": member["id"], "text": '\\"' * 2000, "request_id": str(index)}, context(runs))
        stored = await service.db("get", "alice", team["id"])
        await service.finish("alice", stored, stored["jobs"][-1], "completed", '\\"' * 3000)
        jobs.append(sent)
    cursor, first_cursor, seen = None, None, []
    while True:
        payload = {"team_id": team["id"], "limit": 20, **({"cursor": cursor} if cursor else {})}
        page = await service.search_results(payload, caller)
        assert page["items"] and len(json.dumps(page, ensure_ascii=False).encode()) <= 24000
        if not seen:
            first_cursor = page["next_cursor"]
        seen.extend(item["job_id"] for item in page["items"])
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert seen == [job["id"] for job in reversed(jobs)]
    result = await service.read_result({"team_id": team["id"], "job_id": jobs[0]["id"]}, caller)
    assert len(json.dumps(result, ensure_ascii=False).encode()) <= 24000
    assert len(result["result"]["text"].encode()) == 6000
    assert "input" not in result and "resume" not in result
    assert first_cursor
    with pytest.raises(ValueError, match="cursor|Cursor"):
        await service.read_history({"team_id": team["id"], "cursor": first_cursor}, caller)


@pytest.mark.asyncio
async def test_history_result_cursors_support_non_hex_job_ids_and_expiry(plugin, monkeypatch):
    from deerflow_extension_agent_teams import service as module

    _, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    member = team["members"][0]
    caller = context(runs, thread=member["thread_id"])
    identity = module.identity
    monkeypatch.setattr(module, "identity", lambda *parts: "request-" + identity(*parts))
    jobs = []
    for index in range(2):
        sent = await scheduling_send(actions, runs, "alice", team, member, str(index))
        stored = await service.db("get", "alice", team["id"])
        await service.finish("alice", stored, stored["jobs"][-1], "completed", "Retained evidence")
        jobs.append(sent)
    payload = {"team_id": team["id"], "limit": 1}
    first = await service.search_results(payload, caller)
    assert first["items"][0]["job_id"] == jobs[1]["id"]
    await scheduling_send(actions, runs, "alice", team, member, "later")
    stored = await service.db("get", "alice", team["id"])
    await service.finish("alice", stored, stored["jobs"][-1], "completed", "New evidence")
    continuation = {**payload, "cursor": first["next_cursor"]}
    second = await service.search_results(continuation, caller)
    assert [item["job_id"] for item in second["items"]] == [jobs[0]["id"]]
    assert second["next_cursor"] is None and not second["cursor_expired"]
    await service.db("change", "alice", team["id"], lambda t: t.update(jobs=[job for job in t["jobs"] if job["id"] != jobs[1]["id"]]))
    expired = await service.search_results(continuation, caller)
    assert expired["cursor_expired"] and expired["items"] == [] and expired["next_cursor"] is None


@pytest.mark.asyncio
async def test_history_result_cursors_issued_before_anchor_hashing_expire(plugin):
    _, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    member = team["members"][0]
    caller = context(runs, thread=member["thread_id"])
    for index in range(2):
        await scheduling_send(actions, runs, "alice", team, member, str(index))
        stored = await service.db("get", "alice", team["id"])
        await service.finish("alice", stored, stored["jobs"][-1], "completed", "Retained evidence")
    payload = {"team_id": team["id"], "limit": 1}
    first = await service.search_results(payload, caller)
    fingerprint = first["next_cursor"].split(":")[0]
    legacy_cursor = f"{fingerprint}:{first['items'][0]['job_id']}"
    expired = await service.search_results({**payload, "cursor": legacy_cursor}, caller)
    assert expired["cursor_expired"] and expired["items"] == [] and expired["next_cursor"] is None


@pytest.mark.asyncio
async def test_history_cancelled_results_are_unavailable_before_and_after_admission(plugin):
    _, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    member = team["members"][0]
    caller = context(runs, thread=member["thread_id"])
    unavailable = {"available": False, "text": None, "truncated": None, "reason": "cancelled"}
    for admitted in (False, True):
        sent = await scheduling_send(actions, runs, "alice", team, member, str(admitted))
        if admitted:
            await service.tick()
            assert sent["id"] in runs.runs
        await actions["cancel"]({"team_id": team["id"], "job_id": sent["id"]}, context(runs))
        if admitted:
            await service.tick()
            await service.tick()
        result = await service.read_result({"team_id": team["id"], "job_id": sent["id"]}, caller)
        assert result["status"] == "cancelled" and result["result"] == unavailable
    found = await service.search_results({"team_id": team["id"]}, caller)
    assert len(found["items"]) == 2 and all(item["result"] == unavailable for item in found["items"])
    notice = "Request cancelled; checkpoint retained"
    history = await service.read_history({"team_id": team["id"], "job_id": sent["id"]}, caller)
    assert any(item["kind"] == "cancelled" and item["text"] == notice for item in history["items"])
    stored = await service.db("get", "alice", team["id"])
    assert stored["jobs"][-1]["result"] == notice
    await service.db("change", "alice", team["id"], lambda t: t["jobs"][-1].pop("result"))
    legacy = await service.read_result({"team_id": team["id"], "job_id": sent["id"]}, caller)
    assert legacy["result"] == unavailable
    filtered = await service.search_results({"team_id": team["id"], "query": notice}, caller)
    assert filtered["items"] == []
