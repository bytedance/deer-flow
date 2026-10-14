"""Skill allowed-tools is compatibility metadata, not a tool authority.

`allowed-tools` stays parsed, exported, and described, but it must never filter
model-visible schemas, refuse calls, or rewrite tool_search promotions. Agent
assembly/execution authorization (provider filtering + Guardrails) owns the
permission ceiling.

These regressions drive the real `build_middlewares` (lead) and
`build_subagent_runtime_middlewares` chains through `create_agent`, activate a
synthetic skill via a real slash command, and assert both model binding and
actual ToolNode execution on sync and async paths.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from pydantic import Field

from deerflow.agents.lead_agent import agent as lead_agent_module
from deerflow.agents.middlewares.skill_activation_middleware import SkillActivationMiddleware
from deerflow.agents.middlewares.tool_error_handling_middleware import build_subagent_runtime_middlewares
from deerflow.agents.thread_state import ThreadState
from deerflow.authz.rbac import RbacAuthorizationProvider
from deerflow.config.app_config import AppConfig
from deerflow.config.authorization_config import AuthorizationConfig, AuthorizationProviderConfig
from deerflow.config.loop_detection_config import LoopDetectionConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.skills.types import Skill, SkillCategory

_PARSE_CALLS: list[str] = []
_WRITE_CALLS: list[str] = []


@tool
def parse_document(path: str) -> str:
    """Parse a document and return its text."""
    _PARSE_CALLS.append(path)
    return "parsed"


@tool
def write_file(path: str, content: str) -> str:
    """Write content to a file."""
    _WRITE_CALLS.append(path)
    return "written"


@tool
def read_file(path: str) -> str:
    """Read a file from the skills container."""
    return "file body"


class _RecordingModel(GenericFakeChatModel):
    bound_tool_names: list[list[str]] = Field(default_factory=list)

    def __init__(self, responses: list[AIMessage]):
        super().__init__(messages=iter(responses))

    def bind_tools(self, tools: Any, **kwargs: Any):
        self.bound_tool_names.append([getattr(candidate, "name", "") for candidate in tools])
        return self


class _NoopMiddleware:
    def __repr__(self) -> str:  # pragma: no cover - debug aid only
        return "<noop-test-middleware>"


def _make_app_config() -> AppConfig:
    return AppConfig(
        models=[
            ModelConfig(
                name="safe-model",
                display_name="safe-model",
                description=None,
                use="langchain_openai:ChatOpenAI",
                model="safe-model",
                supports_thinking=False,
                supports_vision=False,
            )
        ],
        sandbox=SandboxConfig(use="test"),
        loop_detection=LoopDetectionConfig(enabled=False),
    )


def _make_skill(tmp_path: Path, name: str, allowed_tools: list[str] | None) -> Skill:
    skill_dir = tmp_path / name
    skill_dir.mkdir(exist_ok=True)
    lines = [
        "---",
        f"name: {name}",
        "description: Demo skill for tool authority regressions",
        "license: MIT",
    ]
    if allowed_tools is None:
        pass
    elif not allowed_tools:
        # An actual empty YAML sequence, not a null `allowed-tools:` key.
        lines.append("allowed-tools: []")
    else:
        lines.append("allowed-tools:")
        lines.extend(f"  - {entry}" for entry in allowed_tools)
    lines.extend(["---", "", "# Demo", "", "Use the parser."])
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("\n".join(lines), encoding="utf-8")
    return Skill(
        name=name,
        description="Demo skill for tool authority regressions",
        license="MIT",
        skill_dir=skill_dir,
        skill_file=skill_file,
        relative_path=Path(name),
        category=SkillCategory.CUSTOM,
        allowed_tools=None if allowed_tools is None else tuple(allowed_tools),
        enabled=True,
    )


def _make_storage(tmp_path: Path, skills: list[Skill]):
    def _validate_skill_file_path(skill_file: Path) -> Path:
        resolved = skill_file.resolve()
        root = tmp_path.resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            raise ValueError("Resolved skill file must stay within the configured skills root.")
        return resolved

    return SimpleNamespace(
        load_skills=lambda *, enabled_only: [skill for skill in skills if skill.enabled] if enabled_only else skills,
        get_container_root=lambda: "/mnt/skills",
        get_skills_root_path=lambda: tmp_path,
        validate_skill_file_path=_validate_skill_file_path,
    )


def _lead_middlewares(monkeypatch, app_config: AppConfig) -> list:
    monkeypatch.setattr(lead_agent_module, "build_lead_runtime_middlewares", lambda *, app_config, lazy_init=True: [])
    monkeypatch.setattr(lead_agent_module, "_create_summarization_middleware", lambda **_kwargs: None)
    monkeypatch.setattr(lead_agent_module, "_create_todo_list_middleware", lambda is_plan_mode: None)
    monkeypatch.setattr(lead_agent_module, "TitleMiddleware", lambda *, app_config, extensions: _NoopMiddleware())
    monkeypatch.setattr(lead_agent_module, "MemoryMiddleware", lambda *args, **kwargs: _NoopMiddleware())
    return lead_agent_module.build_middlewares(
        {"configurable": {"is_plan_mode": False, "subagent_enabled": False}},
        model_name="safe-model",
        app_config=app_config,
    )


def _subagent_middlewares(app_config: AppConfig) -> list:
    return build_subagent_runtime_middlewares(app_config=app_config, model_name="safe-model")


def _skill_authority_slice(middlewares: list) -> list:
    """The contiguous skill-activation block the builder installs.

    Before the obsolete Skill tool policy was removed this was
    [SkillActivationMiddleware, SkillToolPolicyMiddleware]; after removal it is
    just [SkillActivationMiddleware]. Slicing by the builder's own output keeps
    the regression meaningful against either assembly.
    """
    start = next(i for i, middleware in enumerate(middlewares) if isinstance(middleware, SkillActivationMiddleware))
    end = start + 1
    while end < len(middlewares) and type(middlewares[end]).__name__ == "SkillToolPolicyMiddleware":
        end += 1
    return middlewares[start:end]


def _patch_skill_storages(middlewares: list, storage) -> None:
    for middleware in middlewares:
        module_name = type(middleware).__module__
        if module_name.endswith("skill_activation_middleware") or module_name.endswith("skill_tool_policy_middleware"):
            middleware._storage = lambda: storage


def _scripted_model() -> _RecordingModel:
    return _RecordingModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "parse_document",
                        "args": {"path": "report.pdf"},
                        "id": "parse-call",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="done"),
        ]
    )


class _Journal:
    def __init__(self) -> None:
        self.middleware_calls: list[dict] = []
        self.skill_usages: list[Any] = []

    def record_middleware(self, *args, **kwargs):
        self.middleware_calls.append(kwargs)

    def record_skill_usage(self, *args, **kwargs):
        self.skill_usages.append(args[0] if args else kwargs)


def _invoke(graph, *, asynchronous: bool) -> tuple[dict, _Journal]:
    journal = _Journal()
    graph_input = {"messages": [HumanMessage(content="/demo-skill parse the report", id="msg-1")]}
    context = {"__run_journal": journal}
    config = {"recursion_limit": 20}
    if asynchronous:
        result = asyncio.run(graph.ainvoke(graph_input, context=context, config=config))
    else:
        result = graph.invoke(graph_input, context=context, config=config)
    return result, journal


@pytest.mark.parametrize("builder", ["lead", "subagent"])
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize(
    "allowed_tools",
    [["write_file"], [], None],
    ids=["restrictive", "empty", "omitted"],
)
def test_active_skill_allowed_tools_does_not_remove_authorized_tools(monkeypatch, tmp_path, builder, asynchronous, allowed_tools):
    """A slash-activated skill keeps every already-authorized tool bound and executable.

    allowed-tools is compatibility metadata: restrictive, empty, or omitted
    declarations must not narrow the Agent's tool set on the lead or Subagent
    assembly, sync or async. The restrictive case lists only `write_file` while
    the scripted model executes `parse_document`: an Agent-authorized tool
    OMITTED by the restrictive metadata must still run.
    """
    skill = _make_skill(tmp_path, "demo-skill", allowed_tools)
    storage = _make_storage(tmp_path, [skill])
    app_config = _make_app_config()
    if builder == "lead":
        middlewares = _lead_middlewares(monkeypatch, app_config)
    else:
        middlewares = _subagent_middlewares(app_config)
    slice_ = _skill_authority_slice(middlewares)
    _patch_skill_storages(slice_, storage)
    assert slice_, "builder must install SkillActivationMiddleware"

    model = _scripted_model()
    graph = create_agent(
        model=model,
        tools=[read_file, parse_document, write_file],
        middleware=slice_,
        state_schema=ThreadState,
    )

    _PARSE_CALLS.clear()
    result, journal = _invoke(graph, asynchronous=asynchronous)

    assert {"read_file", "parse_document", "write_file"} <= set(model.bound_tool_names[0])
    assert _PARSE_CALLS == ["report.pdf"]
    assert _WRITE_CALLS == []
    assert result["messages"][-1].content == "done"
    # The real slash activation still ran: usage was recorded for the skill.
    assert [usage.get("name") for usage in journal.skill_usages if isinstance(usage, dict)] == ["demo-skill"]


def test_allowed_tools_metadata_cannot_grant_rbac_denied_tool(monkeypatch, tmp_path):
    """Declaring a tool in allowed-tools never bypasses genuine Agent authorization.

    Control test: RBAC denies `write_file` for the guest role. A skill whose
    allowed-tools lists `write_file` must not make it executable; the
    Guardrail-backed authorization middleware still refuses the call.
    """
    from deerflow.agents.middlewares.tool_error_handling_middleware import build_lead_runtime_middlewares

    provider = RbacAuthorizationProvider(roles={"guest": {"tools": {"allow": ["read_file", "parse_document"]}}})
    skill = _make_skill(tmp_path, "demo-skill", ["write_file"])
    storage = _make_storage(tmp_path, [skill])
    app_config = _make_app_config()
    app_config.authorization = AuthorizationConfig(
        enabled=True,
        provider=AuthorizationProviderConfig(use="unused:Provider"),
    )

    monkeypatch.setattr(lead_agent_module, "_create_summarization_middleware", lambda **_kwargs: None)
    monkeypatch.setattr(lead_agent_module, "_create_todo_list_middleware", lambda is_plan_mode: None)
    monkeypatch.setattr(lead_agent_module, "TitleMiddleware", lambda *, app_config, extensions: _NoopMiddleware())
    monkeypatch.setattr(lead_agent_module, "MemoryMiddleware", lambda *args, **kwargs: _NoopMiddleware())

    runtime_middlewares = build_lead_runtime_middlewares(
        app_config=app_config,
        authorization_provider=provider,
    )
    full_chain = _lead_middlewares(monkeypatch, app_config)
    slice_ = _skill_authority_slice(full_chain)
    _patch_skill_storages(slice_, storage)

    model = _RecordingModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "write_file",
                        "args": {"path": "out.txt", "content": "x"},
                        "id": "denied-call",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="done"),
        ]
    )
    graph = create_agent(
        model=model,
        tools=[read_file, parse_document, write_file],
        middleware=[*runtime_middlewares, *slice_],
        state_schema=ThreadState,
    )

    _WRITE_CALLS.clear()
    journal = SimpleNamespace(
        record_middleware=lambda *args, **kwargs: None,
        record_skill_usage=lambda *args, **kwargs: None,
    )
    result = graph.invoke(
        {"messages": [HumanMessage(content="/demo-skill write the report", id="msg-1")]},
        context={"__run_journal": journal, "user_role": "guest", "thread_id": "t-authority-test"},
        config={"recursion_limit": 20, "configurable": {"thread_id": "t-authority-test"}},
    )

    assert _WRITE_CALLS == []
    blocked = [message for message in result["messages"] if isinstance(message, ToolMessage) and message.tool_call_id == "denied-call"]
    assert len(blocked) == 1
    assert blocked[0].status == "error"
    # The denial must be visible in the ToolMessage content itself, not only
    # via the status error flag.
    assert "authz.denied" in blocked[0].content


def test_skill_authority_slice_covers_real_builders(monkeypatch):
    """Both builders keep producing real middleware chains for the regressions."""
    app_config = _make_app_config()
    lead = _skill_authority_slice(_lead_middlewares(monkeypatch, app_config))
    subagent = _skill_authority_slice(_subagent_middlewares(app_config))
    assert all(isinstance(middleware, SkillActivationMiddleware) or "SkillToolPolicyMiddleware" in type(middleware).__name__ for middleware in lead)
    assert all(isinstance(middleware, SkillActivationMiddleware) or "SkillToolPolicyMiddleware" in type(middleware).__name__ for middleware in subagent)
