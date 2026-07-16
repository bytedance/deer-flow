import asyncio
import json
from pathlib import Path

from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from pydantic import Field

from deerflow.agents.middlewares.deferred_tool_filter_middleware import DeferredToolFilterMiddleware
from deerflow.agents.middlewares.mcp_routing_middleware import McpRoutingMiddleware
from deerflow.agents.middlewares.skill_tool_policy_middleware import SkillToolPolicyMiddleware
from deerflow.agents.thread_state import ThreadState
from deerflow.runtime.secret_context import SKILL_TOOL_POLICY_DECISION_CONTEXT_KEY, write_slash_skill_source_path
from deerflow.runtime.serialization import serialize
from deerflow.skills.describe import build_skill_search_setup
from deerflow.skills.types import Skill, SkillCategory
from deerflow.tools.builtins.tool_search import build_deferred_tool_setup
from deerflow.tools.mcp_metadata import tag_mcp_tool

_SLASH_SOURCE_OWNER_TOKEN = "test-slash-source-owner"
_CALC_CALLS: list[str] = []
_DENIED_CALLS: list[str] = []


@tool
def calc(expression: str) -> str:
    """Evaluate an arithmetic expression."""
    _CALC_CALLS.append(expression)
    return "4"


@tool
def denied_lookup(query: str) -> str:
    """Run a lookup the active skill does not authorize."""
    _DENIED_CALLS.append(query)
    return "denied data"


class _StorageStub:
    def __init__(self, skills: list[Skill]):
        self._skills = skills

    def load_skills(self, *, enabled_only: bool = False) -> list[Skill]:
        return [skill for skill in self._skills if skill.enabled or not enabled_only]

    def get_container_root(self) -> str:
        return "/mnt/skills"


class _RecordingModel(GenericFakeChatModel):
    bound_tool_names: list[list[str]] = Field(default_factory=list)

    def __init__(self, responses: list[AIMessage]):
        super().__init__(messages=iter(responses))

    def bind_tools(self, tools, **kwargs):
        self.bound_tool_names.append([getattr(candidate, "name", "") for candidate in tools])
        return self


def _skill(name: str, allowed_tools: list[str]) -> Skill:
    skill_dir = Path(f"/tmp/skills/public/{name}")
    return Skill(
        name=name,
        description=f"Description for {name}",
        license="MIT",
        skill_dir=skill_dir,
        skill_file=skill_dir / "SKILL.md",
        relative_path=Path(name),
        category=SkillCategory.PUBLIC,
        allowed_tools=tuple(allowed_tools),
        enabled=True,
    )


def _active_policy(skill: Skill) -> tuple[SkillToolPolicyMiddleware, dict[str, object]]:
    middleware = SkillToolPolicyMiddleware(slash_source_owner_token=_SLASH_SOURCE_OWNER_TOKEN)
    middleware._storage = lambda: _StorageStub([skill])
    context: dict[str, object] = {}
    write_slash_skill_source_path(
        context,
        skill.get_container_file_path(),
        owner_token=_SLASH_SOURCE_OWNER_TOKEN,
    )
    return middleware, context


def _deferred_setup():
    return build_deferred_tool_setup(
        [tag_mcp_tool(calc), tag_mcp_tool(denied_lookup)],
        enabled=True,
    )


def test_active_skill_can_search_promote_and_call_allowed_deferred_tool():
    restricted = _skill("restricted", ["calc"])
    policy, context = _active_policy(restricted)
    setup = _deferred_setup()
    model = _RecordingModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "tool_search",
                        "args": {"query": "select:calc,denied_lookup"},
                        "id": "search-call",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "calc",
                        "args": {"expression": "2 + 2"},
                        "id": "calc-call",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="done"),
        ]
    )
    _CALC_CALLS.clear()
    graph = create_agent(
        model=model,
        tools=[calc, denied_lookup, setup.tool_search_tool],
        middleware=[
            policy,
            DeferredToolFilterMiddleware(setup.deferred_names, setup.catalog_hash),
        ],
        state_schema=ThreadState,
    )

    result = asyncio.run(
        graph.ainvoke(
            {"messages": [HumanMessage(content="use the allowed calculator")]},
            context=context,
        )
    )

    assert model.bound_tool_names[0] == ["tool_search"]
    assert "calc" in model.bound_tool_names[1]
    assert "denied_lookup" not in model.bound_tool_names[1]
    assert _CALC_CALLS == ["2 + 2"]
    assert result["promoted"] == {"catalog_hash": setup.catalog_hash, "names": ["calc"]}
    search_result = [message for message in result["messages"] if isinstance(message, ToolMessage) and message.tool_call_id == "search-call"]
    assert len(search_result) == 1
    assert '"name": "calc"' in search_result[0].content
    assert "denied_lookup" not in search_result[0].content


def test_tool_search_promotion_cannot_expose_or_execute_denied_deferred_tool():
    restricted = _skill("restricted", ["calc"])
    policy, context = _active_policy(restricted)
    setup = _deferred_setup()
    model = _RecordingModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "tool_search",
                        "args": {"query": "select:denied_lookup"},
                        "id": "search-denied",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "denied_lookup",
                        "args": {"query": "secret"},
                        "id": "denied-call",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="done"),
        ]
    )
    _DENIED_CALLS.clear()
    graph = create_agent(
        model=model,
        tools=[calc, denied_lookup, setup.tool_search_tool],
        middleware=[
            policy,
            DeferredToolFilterMiddleware(setup.deferred_names, setup.catalog_hash),
        ],
        state_schema=ThreadState,
    )

    result = graph.invoke(
        {"messages": [HumanMessage(content="try the denied lookup")]},
        context=context,
    )

    assert all("denied_lookup" not in names for names in model.bound_tool_names)
    assert _DENIED_CALLS == []
    assert result["promoted"] == {
        "catalog_hash": setup.catalog_hash,
        "names": [],
    }
    search_result = [message for message in result["messages"] if isinstance(message, ToolMessage) and message.tool_call_id == "search-denied"]
    assert len(search_result) == 1
    assert "denied_lookup" not in search_result[0].content
    blocked = [message for message in result["messages"] if isinstance(message, ToolMessage) and message.tool_call_id == "denied-call"]
    assert len(blocked) == 1
    assert blocked[0].status == "error"
    assert "not allowed by the active skill policy" in blocked[0].content


def test_auto_promotion_cannot_expose_or_execute_denied_deferred_tool():
    restricted = _skill("restricted", ["calc"])
    policy, context = _active_policy(restricted)
    setup = _deferred_setup()
    routing = McpRoutingMiddleware(
        {"denied_lookup": {"priority": 100, "keywords": ["denied lookup"]}},
        setup.catalog_hash,
        3,
    )
    model = _RecordingModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "denied_lookup",
                        "args": {"query": "secret"},
                        "id": "auto-denied-call",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="done"),
        ]
    )
    _DENIED_CALLS.clear()
    graph = create_agent(
        model=model,
        tools=[calc, denied_lookup, setup.tool_search_tool],
        middleware=[
            policy,
            routing,
            DeferredToolFilterMiddleware(setup.deferred_names, setup.catalog_hash),
        ],
        state_schema=ThreadState,
    )

    result = graph.invoke(
        {"messages": [HumanMessage(content="run the denied lookup")]},
        context=context,
    )

    assert all("denied_lookup" not in names for names in model.bound_tool_names)
    assert _DENIED_CALLS == []
    assert result["promoted"] == {
        "catalog_hash": setup.catalog_hash,
        "names": ["denied_lookup"],
    }
    blocked = [message for message in result["messages"] if isinstance(message, ToolMessage) and message.tool_call_id == "auto-denied-call"]
    assert len(blocked) == 1
    assert blocked[0].status == "error"
    assert "not allowed by the active skill policy" in blocked[0].content


def test_restrictive_skill_keeps_deferred_skill_discovery_available():
    restricted = _skill("restricted", [])
    hidden = _skill("hidden", ["write_file"])
    skill_setup = build_skill_search_setup(
        [restricted],
        enabled=True,
    )
    policy, context = _active_policy(restricted)
    model = _RecordingModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "describe_skill",
                        "args": {"name": f"select:{restricted.name},{hidden.name}"},
                        "id": "describe-call",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="done"),
        ]
    )
    graph = create_agent(
        model=model,
        tools=[skill_setup.describe_skill_tool],
        middleware=[policy],
        state_schema=ThreadState,
    )

    result = graph.invoke(
        {"messages": [HumanMessage(content="describe available skills")]},
        context=context,
    )

    assert model.bound_tool_names[0] == ["describe_skill"]
    described = [message for message in result["messages"] if isinstance(message, ToolMessage) and message.tool_call_id == "describe-call"]
    assert len(described) == 1
    assert "Skill: restricted" in described[0].content
    assert "Skill: hidden" not in described[0].content


def test_policy_tokens_do_not_appear_in_debug_or_checkpoint_streams():
    restricted = _skill("restricted", [])
    policy, context = _active_policy(restricted)
    model = _RecordingModel([AIMessage(content="done")])
    graph = create_agent(
        model=model,
        tools=[],
        middleware=[policy],
        state_schema=ThreadState,
    )

    events = list(
        graph.stream(
            {"messages": [HumanMessage(content="finish")]},
            context=context,
            stream_mode=["debug", "checkpoints"],
        )
    )
    serialized = [serialize(chunk, mode=mode) for mode, chunk in events]
    payload = json.dumps(serialized, ensure_ascii=False, default=str)

    assert events
    assert _SLASH_SOURCE_OWNER_TOKEN not in payload
    assert policy._decision_owner_token not in payload
    assert "__slash_skill_secret_source" not in payload
    assert SKILL_TOOL_POLICY_DECISION_CONTEXT_KEY not in payload
