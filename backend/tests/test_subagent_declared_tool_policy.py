"""Subagent tool restrictions cover extension declarations in the real graph."""

import importlib.util
import sys
from collections import UserList
from pathlib import Path
from types import ModuleType

import pytest
from deerflow_extension_api import AgentScope, MiddlewarePlacement, Placement, extension
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool

from deerflow.config.app_config import AppConfig
from deerflow.extensions.loader import ExtensionSpec, load_extensions
from deerflow.subagents.config import SubagentConfig


def _callable_without_description() -> str:
    # Missing documentation is intentional: LangChain must reject this callable.
    return "report"


@pytest.mark.parametrize(
    "declaration",
    [
        pytest.param("read_report", id="string"),
        pytest.param(None, id="none"),
        pytest.param(object(), id="non-callable"),
        pytest.param(_callable_without_description, id="invalid-callable"),
    ],
)
def test_invalid_declaration_reports_middleware_context(declaration):
    from deerflow.agents.middlewares.tool_declarations import DeclaredToolViewError, apply_declared_tool_policy

    middleware = _middleware([declaration])
    declarations = middleware.tools

    with pytest.raises(DeclaredToolViewError) as raised:
        apply_declared_tool_policy([middleware], allowed=None, disallowed=["task"])

    assert middleware.name in str(raised.value)
    assert "BaseTool" in str(raised.value)
    assert "callable" in str(raised.value)
    assert raised.value.__cause__ is not None
    assert middleware.tools is declarations
    assert middleware.tools[0] is declaration


@pytest.fixture
def executor_module(monkeypatch, tmp_path):
    # Use the real module despite conftest's circular-import stub.
    path = Path(__file__).parents[1] / "packages/harness/deerflow/subagents/executor.py"
    spec = importlib.util.spec_from_file_location("_declared_policy_executor", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    yield module
    module._shutdown_isolated_subagent_loop()


class RecordingModel(GenericFakeChatModel):
    bound_tool_names: list[list[str]] = []

    def bind_tools(self, tools, **kwargs):
        self.bound_tool_names.append([tool.name for tool in tools])
        return self


def _load_extension(monkeypatch, middleware):
    class Contributor:
        def contribute_middlewares(self, app_store, context):
            return [MiddlewarePlacement(middleware, Placement.TOOL_VISIBLE, AgentScope.SUBAGENT)]

    @extension(api="0.2.0", name="declared-policy-test")
    def install(registry, config):
        registry.middlewares(Contributor())

    module = ModuleType("_declared_policy_extension")
    module.install = install
    monkeypatch.setitem(sys.modules, module.__name__, module)
    loaded, diagnostics = load_extensions([ExtensionSpec(use=f"{module.__name__}:install", required=True)])
    assert not [item for item in diagnostics if item.level == "error"]
    return loaded


def _middleware(tools):
    class ReportMiddleware(AgentMiddleware):
        pass

    middleware = ReportMiddleware()
    middleware.tools = tools
    return middleware


def _report_tool(name, executed):
    def report() -> str:
        """Return a synthetic report without external side effects."""
        executed.append(name)
        return name

    return StructuredTool.from_function(report, name=name, return_direct=True)


def _app_config():
    return AppConfig.model_validate(
        {
            "models": [{"name": "offline", "use": "langchain_openai:ChatOpenAI", "model": "offline"}],
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "summarization": {"enabled": False},
        }
    )


async def _run(executor_module, monkeypatch, extensions, config, responses, *, tools=(), app_config=None):
    model = RecordingModel(messages=iter(responses))
    monkeypatch.setattr(executor_module, "create_chat_model", lambda **kwargs: model)
    executor = executor_module.SubagentExecutor(
        config=config,
        tools=list(tools),
        extensions=extensions,
        app_config=app_config or _app_config(),
        parent_model="offline",
        thread_id="policy-thread",
        user_id="policy-user",
    )
    result = await executor._aexecute("Review the synthetic report")
    assert result.status == executor_module.SubagentStatus.COMPLETED, result.error
    return result, model


def _call(name, identifier):
    return AIMessage(content="", tool_calls=[{"name": name, "args": {}, "id": identifier}])


@pytest.mark.asyncio
@pytest.mark.parametrize("container", [list, tuple, UserList], ids=["list", "tuple", "sequence"])
@pytest.mark.parametrize(
    "allowed, disallowed, denied_name",
    [
        (["read_report"], ["task"], "publish_report"),
        (None, ["task", "publish_report"], "publish_report"),
        (["read_report", "publish_report"], ["publish_report"], "publish_report"),
        (None, ["task"], "task"),
    ],
    ids=["allowlist", "denylist", "deny-wins", "default-task-denial"],
)
async def test_restricted_extension_tool_cannot_execute(executor_module, monkeypatch, allowed, disallowed, denied_name, container):
    executed = []
    declarations = container([_report_tool(denied_name, executed), _report_tool("read_report", executed)])
    middleware = _middleware(declarations)
    extensions = _load_extension(monkeypatch, middleware)
    config = SubagentConfig(name="reviewer", description="Read reports", skills=[], tools=allowed, disallowed_tools=disallowed)

    result, model = await _run(executor_module, monkeypatch, extensions, config, [_call(denied_name, "denied-call"), _call("read_report", "allowed-call")])

    assert executed == ["read_report"]
    assert result.result == "read_report"
    assert model.bound_tool_names
    assert all(denied_name not in names and "read_report" in names for names in model.bound_tool_names)
    # The extension may reuse this same middleware for another subagent.
    assert middleware.tools is declarations
    assert [tool.name for tool in declarations] == [denied_name, "read_report"]


@pytest.mark.asyncio
async def test_empty_allowlist_excludes_all_extension_declarations(executor_module, monkeypatch):
    executed = []
    extensions = _load_extension(monkeypatch, _middleware([_report_tool("publish_report", executed)]))
    config = SubagentConfig(name="reviewer", description="No tools", skills=[], tools=[])

    result, model = await _run(executor_module, monkeypatch, extensions, config, [AIMessage(content="Reviewed without tools")])

    assert result.result == "Reviewed without tools"
    assert not any(model.bound_tool_names)
    assert executed == []


@pytest.mark.asyncio
@pytest.mark.parametrize("container", [list, tuple, UserList], ids=["list", "tuple", "sequence"])
async def test_shared_extension_can_publish_for_an_unrestricted_subagent(executor_module, monkeypatch, container):
    executed = []
    declarations = container([_report_tool("publish_report", executed), _report_tool("read_report", executed)])
    middleware = _middleware(declarations)
    extensions = _load_extension(monkeypatch, middleware)
    restricted = SubagentConfig(name="reviewer", description="Read reports", skills=[], tools=["read_report"])
    await _run(executor_module, monkeypatch, extensions, restricted, [_call("read_report", "read-call")])
    unrestricted = SubagentConfig(name="publisher", description="Publish reports", skills=[], tools=None, disallowed_tools=[])

    result, model = await _run(executor_module, monkeypatch, extensions, unrestricted, [_call("publish_report", "publish-call")])

    assert result.result == "publish_report"
    assert executed == ["read_report", "publish_report"]
    assert "publish_report" in model.bound_tool_names[0]
    assert middleware.tools is declarations


@pytest.mark.asyncio
@pytest.mark.parametrize("allowed", [["read_report"], ["read_report", "publish_report"]], ids=["callable-denied", "callable-allowed"])
async def test_callable_declarations_keep_their_names_and_shared_identity(executor_module, monkeypatch, allowed):
    executed = []

    def publish_report() -> str:
        """Publish a synthetic report."""
        executed.append("publish_report")
        return "published"

    declarations = [publish_report, _report_tool("read_report", executed)]
    middleware = _middleware(declarations)
    extensions = _load_extension(monkeypatch, middleware)
    config = SubagentConfig(name="reviewer", description="Read reports", skills=[], tools=allowed)
    permitted = "publish_report" in allowed
    responses = [_call("publish_report", "publish-call"), _call("read_report", "read-call")]

    result, model = await _run(executor_module, monkeypatch, extensions, config, responses)

    assert result.result == "read_report"
    assert executed == (["publish_report", "read_report"] if permitted else ["read_report"])
    assert all(("publish_report" in names) is permitted for names in model.bound_tool_names)
    assert middleware.tools is declarations
    assert declarations[0] is publish_report


@pytest.mark.asyncio
async def test_subagent_policy_intersects_global_authorization(executor_module, monkeypatch):
    executed = []
    declarations = [_report_tool(name, executed) for name in ("publish_report", "archive_report", "read_report")]
    extensions = _load_extension(monkeypatch, _middleware(declarations))
    config = SubagentConfig(name="reviewer", description="Read reports", skills=[], disallowed_tools=["publish_report"])
    app_config = _app_config()
    app_config.authorization = type(app_config.authorization).model_validate(
        {
            "enabled": True,
            "default_role": "user",
            "provider": {
                "use": "deerflow.authz.rbac:RbacAuthorizationProvider",
                "config": {"roles": {"user": {"tools": {"allow": ["publish_report", "read_report"]}}}},
            },
        }
    )

    result, model = await _run(
        executor_module,
        monkeypatch,
        extensions,
        config,
        [_call("publish_report", "config-denied"), _call("archive_report", "provider-denied"), _call("read_report", "both-allow")],
        app_config=app_config,
    )

    assert result.result == "read_report"
    assert executed == ["read_report"]
    assert all(names == ["read_report"] for names in model.bound_tool_names)


@pytest.mark.asyncio
async def test_generated_discovery_helper_retains_its_filtered_catalog(executor_module, monkeypatch):
    from deerflow.tools.mcp_metadata import tag_mcp_tool

    executed = []
    mcp_tool = tag_mcp_tool(_report_tool("mcp_report", executed))
    extensions = _load_extension(monkeypatch, _middleware([_report_tool("publish_report", executed)]))
    config = SubagentConfig(name="reviewer", description="Read MCP reports", skills=[], tools=["mcp_report"], disallowed_tools=["task", "tool_search"])
    app_config = _app_config()
    app_config.tool_search.enabled = True
    discover = AIMessage(content="", tool_calls=[{"name": "tool_search", "args": {"query": "select:mcp_report"}, "id": "discover"}])

    result, model = await _run(
        executor_module,
        monkeypatch,
        extensions,
        config,
        [discover, _call("mcp_report", "read-call")],
        tools=[mcp_tool],
        app_config=app_config,
    )

    assert result.result == "mcp_report"
    assert executed == ["mcp_report"]
    assert "tool_search" in model.bound_tool_names[0]
    assert "mcp_report" not in model.bound_tool_names[0]
    assert "mcp_report" in model.bound_tool_names[-1]
    assert all("publish_report" not in names for names in model.bound_tool_names)


def test_unrestricted_policy_does_not_inspect_middleware_declarations():
    from deerflow.agents.middlewares.tool_declarations import apply_declared_tool_policy

    class UninspectedMiddleware(AgentMiddleware):
        @property
        def tools(self):
            raise AssertionError("An unrestricted build must not read this property")

    stack = [UninspectedMiddleware()]

    assert apply_declared_tool_policy(stack, allowed=None, disallowed=[]) is stack


@pytest.mark.parametrize("container", [list, UserList], ids=["list", "sequence"])
def test_allowed_callable_property_keeps_the_original_middleware(container):
    from deerflow.agents.middlewares.tool_declarations import apply_declared_tool_policy

    def read_report() -> str:
        """Return a synthetic report."""
        return "report"

    declarations = container([read_report])

    class PropertyMiddleware(AgentMiddleware):
        @property
        def tools(self):
            return declarations

    original = PropertyMiddleware()

    stack = [original]
    view = apply_declared_tool_policy(stack, allowed=["read_report"], disallowed=["task"])

    assert view is stack
    assert view[0] is original
    assert original.tools is declarations
    assert original.tools[0] is read_report


def test_restricted_policy_rejects_iterator_without_consuming_shared_declarations():
    from deerflow.agents.middlewares.tool_declarations import DeclaredToolViewError, apply_declared_tool_policy

    tool = _report_tool("read_report", [])
    declarations = iter([tool])
    original = _middleware(declarations)

    with pytest.raises(DeclaredToolViewError, match="Sequence"):
        apply_declared_tool_policy([original], allowed=None, disallowed=["task"])

    assert original.tools is declarations
    assert next(declarations) is tool


def _audit_executor(executor_module, monkeypatch, config, *, tools=(), extensions=None, app_config=None):
    model = RecordingModel(messages=iter([AIMessage(content="Reviewed")]))
    monkeypatch.setattr(executor_module, "create_chat_model", lambda **kwargs: model)
    executor = executor_module.SubagentExecutor(config=config, tools=list(tools), extensions=extensions, app_config=app_config or _app_config(), parent_model="offline", thread_id="audit-thread", user_id="audit-user")
    builds = []
    real_create_agent = executor_module.create_agent

    def record_build(**kwargs):
        builds.append(kwargs)
        return real_create_agent(**kwargs)

    monkeypatch.setattr(executor_module, "create_agent", record_build)
    return executor, builds


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "allowed, disallowed, denied_name",
    [(["read_report"], ["task"], "publish_report"), (None, ["publish_report"], "publish_report"), (None, ["task"], "task")],
    ids=["allowlist", "denylist", "default-task-denial"],
)
async def test_final_audit_rejects_explicit_tool_injection(executor_module, monkeypatch, allowed, disallowed, denied_name):
    from deerflow.agents.middlewares.tool_declarations import DeclaredToolViewError

    config = SubagentConfig(name="reviewer", description="Audit tools", skills=[], tools=allowed, disallowed_tools=disallowed)
    read = _report_tool("read_report", [])
    executor, builds = _audit_executor(executor_module, monkeypatch, config, tools=[read])

    # An assembly caller supplies a new explicit list after constructor filtering.
    with pytest.raises(DeclaredToolViewError, match=denied_name):
        await executor._create_agent(tools=[read, _report_tool(denied_name, [])])

    assert builds == []


@pytest.mark.asyncio
@pytest.mark.parametrize("denied_name", ["publish_report", "tool_search"])
async def test_final_audit_rejects_late_middleware_declarations(executor_module, monkeypatch, denied_name):
    from deerflow.agents.middlewares.tool_declarations import DeclaredToolViewError

    config = SubagentConfig(name="reviewer", description="Audit tools", skills=[], tools=["read_report"], disallowed_tools=["task", "tool_search"])
    executor, builds = _audit_executor(executor_module, monkeypatch, config)
    real_resolve = executor._resolve_recursion_limit
    injections = []

    def introduce_late_declaration(middlewares):
        # Fault injection: simulate a later assembly pass adding a new tool
        # channel after the existing declaration filter has already run.
        middleware = _middleware([_report_tool(denied_name, [])])
        middlewares.append(middleware)
        injections.append(middleware)
        return real_resolve(middlewares)

    monkeypatch.setattr(executor, "_resolve_recursion_limit", introduce_late_declaration)

    with pytest.raises(DeclaredToolViewError, match=denied_name):
        await executor._create_agent()

    assert len(injections) == 1
    assert builds == []


@pytest.mark.asyncio
async def test_final_audit_does_not_exempt_a_tool_search_lookalike(executor_module, monkeypatch):
    from deerflow.agents.middlewares.tool_declarations import DeclaredToolViewError
    from deerflow.tools.mcp_metadata import tag_mcp_tool

    config = SubagentConfig(name="reviewer", description="Audit discovery", skills=[], tools=["mcp_report"], disallowed_tools=["task", "tool_search"])
    app_config = _app_config()
    app_config.tool_search.enabled = True
    executor, builds = _audit_executor(executor_module, monkeypatch, config, tools=[tag_mcp_tool(_report_tool("mcp_report", []))], app_config=app_config)
    _, _, setup = await executor._build_initial_state("Review reports")
    lookalike = _report_tool("tool_search", [])
    assert setup.tool_search_tool is not None and setup.tool_search_tool is not lookalike

    with pytest.raises(DeclaredToolViewError, match="tool_search"):
        await executor._create_agent(tools=[lookalike], deferred_setup=setup)

    assert builds == []


@pytest.mark.asyncio
async def test_generated_skill_discovery_survives_final_audit(executor_module, monkeypatch, tmp_path):
    from deerflow.skills.types import Skill, SkillCategory

    skill = Skill(name="demo", description="Demo skill", license=None, skill_dir=tmp_path, skill_file=tmp_path / "SKILL.md", relative_path=Path("demo"), category=SkillCategory.PUBLIC, enabled=True)

    class StaticSkillStorage:
        def load_skills(self, **kwargs):
            return [skill]

    monkeypatch.setattr("deerflow.skills.storage.get_or_new_user_skill_storage", lambda *args, **kwargs: StaticSkillStorage())
    config = SubagentConfig(name="reviewer", description="Audit discovery", skills=["demo"], tools=[], disallowed_tools=["task", "describe_skill"])
    app_config = _app_config()
    app_config.skills.deferred_discovery = True
    executor, builds = _audit_executor(executor_module, monkeypatch, config, app_config=app_config)
    _, tools, setup = await executor._build_initial_state("Review skills")
    assert [tool.name for tool in tools] == ["describe_skill"]

    await executor._create_agent(tools=tools, deferred_setup=setup)

    assert len(builds) == 1
    assert builds[0]["tools"][0] is tools[0]


def test_final_audit_is_a_noop_for_an_unrestricted_policy():
    from deerflow.agents.middlewares.tool_declarations import verify_subagent_tool_policy

    class UninspectedMiddleware:
        @property
        def tools(self):
            raise AssertionError("Unrestricted builds must not inspect declarations")

    verify_subagent_tool_policy([None], [UninspectedMiddleware()], allowed=None, disallowed=[])


@pytest.mark.asyncio
@pytest.mark.parametrize("container", [list, tuple, UserList], ids=["list", "tuple", "sequence"])
async def test_callable_names_are_resolved_once_per_build(executor_module, monkeypatch, container):
    from deerflow.agents.middlewares import tool_declarations

    executed = []

    def read_report() -> str:
        """Read a synthetic report."""
        executed.append("callable")
        return "report"

    def publish_report() -> str:
        """Publish a synthetic report."""
        executed.append("denied")
        return "published"

    declarations = container([read_report, publish_report])
    middleware = _middleware(declarations)
    extensions = _load_extension(monkeypatch, middleware)
    config = SubagentConfig(name="reviewer", description="Read reports", skills=[], tools=["read_report", "finish_report"])
    converted = []
    real_create_tool = tool_declarations.create_tool

    def record_conversion(declaration):
        converted.append(declaration)
        return real_create_tool(declaration)

    monkeypatch.setattr(tool_declarations, "create_tool", record_conversion)
    for build in range(2):
        converted.clear()
        await _run(
            executor_module,
            monkeypatch,
            extensions,
            config,
            [_call("read_report", f"read-{build}"), _call("finish_report", f"finish-{build}")],
            tools=[_report_tool("finish_report", executed)],
        )
        assert converted.count(read_report) == 1
        assert converted.count(publish_report) == 1
        assert middleware.tools is declarations
        assert declarations[0] is read_report
    assert executed == ["callable", "finish_report", "callable", "finish_report"]


@pytest.mark.asyncio
async def test_final_audit_resolves_a_new_callable_after_narrowing(executor_module, monkeypatch):
    from deerflow.agents.middlewares.tool_declarations import DeclaredToolViewError

    def publish_report() -> str:
        """Publish a synthetic report."""
        return "published"

    config = SubagentConfig(name="reviewer", description="Read reports", skills=[], tools=["read_report"])
    executor, builds = _audit_executor(executor_module, monkeypatch, config)
    real_resolve = executor._resolve_recursion_limit
    injections = []

    def inject_callable(middlewares):
        injections.append(publish_report)
        middlewares.append(_middleware([publish_report]))
        return real_resolve(middlewares)

    monkeypatch.setattr(executor, "_resolve_recursion_limit", inject_callable)
    with pytest.raises(DeclaredToolViewError, match="publish_report"):
        await executor._create_agent()
    assert injections == [publish_report]
    assert builds == []


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["callable", "base-tool"])
async def test_final_audit_rechecks_a_renamed_declaration(executor_module, monkeypatch, kind):
    from deerflow.agents.middlewares.tool_declarations import DeclaredToolViewError

    def read_report() -> str:
        """Read a synthetic report."""
        return "report"

    declaration = read_report if kind == "callable" else _report_tool("read_report", [])
    extensions = _load_extension(monkeypatch, _middleware([declaration]))
    config = SubagentConfig(name="reviewer", description="Read reports", skills=[], tools=["read_report"])
    executor, builds = _audit_executor(executor_module, monkeypatch, config, extensions=extensions)
    real_resolve = executor._resolve_recursion_limit
    mutations = []

    def rename_declaration(middlewares):
        # Extension/schema normalization may copy declarations. Mutate the
        # actual final stack rather than the contributor's original object.
        name_attribute = "__name__" if kind == "callable" else "name"
        live_declaration = next(tool for middleware in middlewares for tool in getattr(middleware, "tools", ()) if getattr(tool, name_attribute, None) == "read_report")
        mutations.append(live_declaration)
        setattr(live_declaration, name_attribute, "publish_report")
        return real_resolve(middlewares)

    monkeypatch.setattr(executor, "_resolve_recursion_limit", rename_declaration)
    with pytest.raises(DeclaredToolViewError, match="publish_report"):
        await executor._create_agent(extensions=extensions)
    assert len(mutations) == 1
    assert builds == []


@pytest.mark.parametrize("source", ["explicit", "middleware"])
@pytest.mark.parametrize(
    "allowed, disallowed, reason",
    [
        (["read_report"], [], "missing from the tools allowlist"),
        (None, ["publish_report"], "listed in disallowed_tools"),
        (["read_report"], ["publish_report"], "listed in disallowed_tools"),
    ],
    ids=["allowlist-miss", "denylist-hit", "deny-precedence"],
)
def test_final_audit_reports_the_policy_check_that_failed(source, allowed, disallowed, reason):
    from deerflow.agents.middlewares.tool_declarations import DeclaredToolViewError, verify_subagent_tool_policy

    declaration = _report_tool("publish_report", [])
    middleware = _middleware([declaration])
    tools, middlewares = ([declaration], []) if source == "explicit" else ([], [middleware])
    with pytest.raises(DeclaredToolViewError) as raised:
        verify_subagent_tool_policy(tools, middlewares, allowed=allowed, disallowed=disallowed)
    message = str(raised.value)
    assert "publish_report" in message
    assert reason in message
    assert ("Subagent explicit tool list" if source == "explicit" else middleware.name) in message
    assert "before graph creation" in message
