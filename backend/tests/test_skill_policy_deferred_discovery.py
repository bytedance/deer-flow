"""Deferred tool/skill discovery stays catalog/hash scoped.

With the Skill tool policy removed, `allowed-tools` never filters
model-visible schemas, execution, or tool_search promotions. These tests pin
the still-supported deferred behaviors: the deferred filter scopes promotion by
catalog hash and the genuine user turn, promoted names come only from the
build-time catalog, the
promotion audit records the final Command, and skill discovery metadata
(describe_skill) stays catalog scoped. Genuine authorization denials are
covered by the authorization suites.
"""

import asyncio
import json
from pathlib import Path

from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from pydantic import Field

from deerflow.agents.middlewares.deferred_tool_filter_middleware import DeferredToolFilterMiddleware
from deerflow.agents.middlewares.skill_activation_middleware import SkillActivationMiddleware
from deerflow.agents.middlewares.tool_promotion_audit_middleware import DeferredToolPromotionAuditMiddleware
from deerflow.agents.thread_state import ThreadState
from deerflow.runtime.serialization import serialize
from deerflow.skills.describe import build_skill_search_setup
from deerflow.skills.types import Skill, SkillCategory
from deerflow.tools.builtins.tool_search import build_deferred_tool_setup
from deerflow.tools.mcp_metadata import tag_mcp_tool

_SLASH_SOURCE_OWNER_TOKEN = "test-slash-source-owner"
_CALC_CALLS: list[str] = []


class _Recorder:
    def __init__(self):
        self.calls: list[dict] = []
        self.skill_usages: list[dict] = []

    def record_middleware(self, **kwargs):
        self.calls.append(kwargs)

    def record_skill_usage(self, *args, **kwargs):
        self.skill_usages.append(args[0] if args else kwargs)


@tool
def calc(expression: str) -> str:
    """Evaluate an arithmetic expression."""
    _CALC_CALLS.append(expression)
    return "4"


@tool
def other_lookup(query: str) -> str:
    """Another catalog tool."""
    return "other data"


class _StorageStub:
    def __init__(self, skills: list[Skill]):
        self._skills = skills
        self.load_calls = 0

    def load_skills(self, *, enabled_only: bool = False) -> list[Skill]:
        self.load_calls += 1
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


def _skill(name: str, allowed_tools: list[str] | None) -> Skill:
    skill_dir = Path(f"/tmp/skills/public/{name}")
    return Skill(
        name=name,
        description=f"Description for {name}",
        license="MIT",
        skill_dir=skill_dir,
        skill_file=skill_dir / "SKILL.md",
        relative_path=Path(name),
        category=SkillCategory.PUBLIC,
        allowed_tools=None if allowed_tools is None else tuple(allowed_tools),
        enabled=True,
    )


def _deferred_setup():
    return build_deferred_tool_setup(
        [tag_mcp_tool(calc), tag_mcp_tool(other_lookup)],
        enabled=True,
    )


class _ActivationStorageStub:
    """Temp-backed storage stub: load_skills plus the path guards the real
    SkillActivationMiddleware needs to read SKILL.md from disk."""

    def __init__(self, root: Path, skills: list[Skill]):
        self._root = root
        self._skills = skills

    def load_skills(self, *, enabled_only: bool = False) -> list[Skill]:
        return [skill for skill in self._skills if skill.enabled or not enabled_only]

    def get_container_root(self) -> str:
        return "/mnt/skills"

    def get_skills_root_path(self) -> Path:
        return self._root

    def validate_skill_file_path(self, skill_file: Path) -> Path:
        resolved = skill_file.resolve()
        root = self._root.resolve()
        resolved.relative_to(root)  # raises ValueError outside the root
        return resolved


def _write_activated_skill(tmp_path: Path) -> Skill:
    """Real SKILL.md with a declared-but-empty allowed-tools sequence."""
    skill_dir = tmp_path / "example-safe-skill"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        "\n".join(
            [
                "---",
                "name: example-safe-skill",
                "description: Uses the configured MCP calculator",
                "license: MIT",
                "allowed-tools: []",
                "---",
                "",
                "# Calculator",
                "",
                "Use the deferred MCP calculator.",
            ]
        ),
        encoding="utf-8",
    )
    return Skill(
        name="example-safe-skill",
        description="Uses the configured MCP calculator",
        license="MIT",
        skill_dir=skill_dir,
        skill_file=skill_file,
        relative_path=Path("example-safe-skill"),
        category=SkillCategory.CUSTOM,
        allowed_tools=(),
        enabled=True,
    )


def test_enabled_skills_preserve_deferred_mcp_discovery_and_calling(tmp_path):
    """A real slash activation of a skill whose SKILL.md declares an empty
    allowed-tools list still leaves deferred discovery and promotion intact:
    tool_search stays bound, `calc` is promoted and executes, and only the
    promoted tool becomes visible (allowed-tools is compatibility metadata,
    never a filter)."""
    skill = _write_activated_skill(tmp_path)
    storage = _ActivationStorageStub(tmp_path, [skill])
    activation = SkillActivationMiddleware(slash_source_owner_token=_SLASH_SOURCE_OWNER_TOKEN)
    activation._storage = lambda: storage
    setup = _deferred_setup()
    model = _RecordingModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "tool_search",
                        "args": {"query": "select:calc"},
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
        tools=[calc, other_lookup, setup.tool_search_tool],
        middleware=[
            activation,
            DeferredToolFilterMiddleware(setup.deferred_names, setup.catalog_hash),
        ],
        state_schema=ThreadState,
    )

    recorder = _Recorder()
    result = graph.invoke(
        {"messages": [HumanMessage(content="/example-safe-skill use the configured MCP calculator", id="msg-1")], "promoted": {"catalog_hash": setup.catalog_hash, "names": []}},
        context={"__run_journal": recorder},
        config={"recursion_limit": 20},
    )

    # The slash activation really ran: usage was recorded for the skill.
    assert [usage.get("name") for usage in recorder.skill_usages if isinstance(usage, dict)] == ["example-safe-skill"]
    assert model.bound_tool_names[0] == ["tool_search"]
    assert "calc" in model.bound_tool_names[1]
    # Still hidden because it was not promoted — not by any skill declaration.
    assert "other_lookup" not in model.bound_tool_names[1]
    assert _CALC_CALLS == ["2 + 2"]
    assert result["promoted"] == {
        "catalog_hash": setup.catalog_hash,
        "names": ["calc"],
        "turn_id": "msg-1",
    }


def test_promotion_is_scoped_to_the_build_time_catalog():
    """tool_search can only promote names present in the deferred catalog; a
    query naming a non-deferred tool promotes nothing."""
    setup = _deferred_setup()
    model = _RecordingModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "tool_search",
                        "args": {"query": "select:read_file"},
                        "id": "search-miss",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="done"),
        ]
    )
    graph = create_agent(
        model=model,
        tools=[calc, other_lookup, setup.tool_search_tool],
        middleware=[
            DeferredToolFilterMiddleware(setup.deferred_names, setup.catalog_hash),
        ],
        state_schema=ThreadState,
    )

    result = graph.invoke(
        {"messages": [HumanMessage(content="search for a non-deferred tool", id="user-catalog-miss")]},
        context={},
    )

    assert result["promoted"] == {
        "catalog_hash": setup.catalog_hash,
        "names": [],
        "turn_id": "user-catalog-miss",
    }
    assert all("calc" not in names for names in model.bound_tool_names[1:])


def test_promotion_audit_records_final_command_names():
    """The audit middleware observes the final tool_search Command and records
    the promoted names exactly once per search."""
    setup = _deferred_setup()
    recorder = _Recorder()
    model = _RecordingModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "tool_search",
                        "args": {"query": "select:calc,other_lookup"},
                        "id": "search-call",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="done"),
        ]
    )
    graph = create_agent(
        model=model,
        tools=[calc, other_lookup, setup.tool_search_tool],
        middleware=[
            DeferredToolPromotionAuditMiddleware(setup.deferred_names, setup.catalog_hash),
            DeferredToolFilterMiddleware(setup.deferred_names, setup.catalog_hash),
        ],
        state_schema=ThreadState,
    )

    asyncio.run(
        graph.ainvoke(
            {"messages": [HumanMessage(content="promote both tools")]},
            context={"__run_journal": recorder},
        )
    )

    assert recorder.calls[0]["changes"]["tool_names"] == ["calc", "other_lookup"]


def test_skill_discovery_metadata_stays_catalog_scoped():
    """describe_skill answers only from its build-time catalog, independent of
    any skill's allowed-tools declaration."""
    listed = _skill("listed", [])
    skill_setup = build_skill_search_setup(
        [listed],
        enabled=True,
    )
    model = _RecordingModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "describe_skill",
                        "args": {"name": f"select:{listed.name},unknown"},
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
        middleware=[],
        state_schema=ThreadState,
    )

    result = graph.invoke(
        {"messages": [HumanMessage(content="describe available skills")]},
        context={},
    )

    assert model.bound_tool_names[0] == ["describe_skill"]
    described = [message for message in result["messages"] if isinstance(message, ToolMessage) and message.tool_call_id == "describe-call"]
    assert len(described) == 1
    assert "Skill: listed" in described[0].content
    assert "Skill: unknown" not in described[0].content


def test_activation_tokens_do_not_appear_in_debug_or_checkpoint_streams(tmp_path):
    """The slash-source owner token stays out of observable streams even though
    the (historical) policy decision key is no longer published."""
    skill = _skill("restricted", [])
    activation = SkillActivationMiddleware(slash_source_owner_token=_SLASH_SOURCE_OWNER_TOKEN)
    activation._storage = lambda: _StorageStub([skill])
    model = _RecordingModel([AIMessage(content="done")])
    graph = create_agent(
        model=model,
        tools=[],
        middleware=[activation],
        state_schema=ThreadState,
    )

    events = list(
        graph.stream(
            {"messages": [HumanMessage(content="finish")]},
            context={},
            stream_mode=["debug", "checkpoints"],
        )
    )
    serialized = [serialize(chunk, mode=mode) for mode, chunk in events]
    payload = json.dumps(serialized, ensure_ascii=False, default=str)

    assert events
    assert _SLASH_SOURCE_OWNER_TOKEN not in payload
    assert "__slash_skill_secret_source" not in payload
    assert "__skill_tool_policy_decision" not in payload
