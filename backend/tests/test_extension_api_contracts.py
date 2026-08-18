"""Tests for the extension contract surface.

The contracts carry two compatibility promises that are easy to break by
accident and impossible to catch at runtime later: every Protocol method has a
default implementation, and every optional dataclass field has a default. Both
are asserted here.
"""

from __future__ import annotations

import asyncio
import dataclasses
import importlib.resources
import inspect

import pytest
from deerflow_extension_api import (
    API_VERSION,
    AgentBuildContext,
    AgentScope,
    ExtensionData,
    ExtensionInstall,
    ExtensionRegistry,
    ExtensionRuntimeDeps,
    ExtensionService,
    HostPolicySnapshot,
    MiddlewareContributor,
    MiddlewarePlacement,
    Placement,
    SystemModelCallObserver,
    SystemModelRequest,
    SystemModelResult,
    SystemOperationKind,
    TaskInfo,
    TaskLifecycleContributor,
    TaskOutcome,
    extension,
)
from deerflow_extension_api.runtime_bridge import (
    EXTENSION_TASK_STORE_KEY,
    task_store_from_runtime,
)


def test_placement_members_cover_both_axes():
    assert Placement.MODEL_LOGICAL.value == "model_logical"
    assert Placement.MODEL_PHYSICAL.value == "model_physical"
    assert Placement.TOOL_VISIBLE.value == "tool_visible"
    assert Placement.TOOL_RAW.value == "tool_raw"
    assert Placement.STANDARD.value == "standard"


def test_agent_scope_both_is_union():
    assert AgentScope.BOTH == AgentScope.LEAD | AgentScope.SUBAGENT
    assert AgentScope.LEAD in AgentScope.BOTH


def test_middleware_placement_defaults():
    p = MiddlewarePlacement(middleware=object(), placement=Placement.STANDARD)
    assert p.scope is AgentScope.BOTH
    assert p.order == 0


@pytest.mark.parametrize(
    "cls",
    [
        HostPolicySnapshot,
        ExtensionRuntimeDeps,
        AgentBuildContext,
        TaskInfo,
        SystemModelRequest,
        SystemModelResult,
        MiddlewarePlacement,
    ],
)
def test_every_dataclass_is_frozen(cls):
    assert dataclasses.is_dataclass(cls)
    assert cls.__dataclass_params__.frozen, f"{cls.__name__} must be frozen"


@pytest.mark.parametrize(
    "cls",
    [HostPolicySnapshot, ExtensionRuntimeDeps, TaskInfo, SystemModelRequest, SystemModelResult],
)
def test_additive_dataclasses_are_constructible_with_required_fields_only(cls):
    """Fields added later must carry defaults, or old extensions break on upgrade.

    HostPolicySnapshot and the two system-call snapshots are host-constructed
    and fully optional. TaskInfo has a required identity core and optional
    remainder. AgentBuildContext gets its own dedicated test below because its
    scope is legitimately required.
    """
    if cls is TaskInfo:
        info = cls(task_id="t", run_id="r", thread_id="th", kind="lead")
        assert info.parent_task_id is None
        assert info.agent_name is None
        assert info.resumed is False
    else:
        assert cls() is not None


def test_agent_build_context_optional_fields_keep_their_defaults():
    """AgentBuildContext has one required field (scope); the rest must default.

    Unlike the fully-optional dataclasses above, scope is legitimately
    required, so this is not folded into the parametrized test above — it
    would misrepresent the required/optional split this suite is meant to
    document.
    """
    ctx = AgentBuildContext(scope=AgentScope.LEAD)
    assert ctx.agent_name is None
    assert ctx.model_name is None
    assert isinstance(ctx.policy, HostPolicySnapshot)


@pytest.mark.parametrize(
    "protocol",
    [
        ExtensionRegistry,
        ExtensionService,
        MiddlewareContributor,
        TaskLifecycleContributor,
        SystemModelCallObserver,
    ],
)
def test_every_protocol_method_has_a_default_implementation(protocol):
    """Adding a method to a Protocol is only additive when it has a default.

    Without this, shipping a new contract method breaks every already-released
    extension that does not implement it.
    """
    checked = 0
    for name, member in vars(protocol).items():
        if name.startswith("_") or not inspect.isfunction(member):
            continue
        checked += 1
        body = inspect.getsource(member).split("\n", 1)[1]
        assert "return" in body, f"{protocol.__name__}.{name} has no default implementation. Adding a contract method is only additive when it returns a default; otherwise every already-released extension breaks on upgrade."
    assert checked > 0, f"{protocol.__name__} declared no methods to check"


def test_contributor_defaults_return_empty():
    class _Bare:
        pass

    bare = _Bare()
    assert MiddlewareContributor.contribute_middlewares(bare, ExtensionData("app"), AgentBuildContext(scope=AgentScope.LEAD)) == ()


def test_task_lifecycle_contract_is_public_and_defaults_to_noop():
    class _Bare:
        pass

    app_store = ExtensionData("app")
    task_store = ExtensionData("task-1")
    info = TaskInfo(
        task_id="task-1",
        run_id="run-1",
        thread_id="thread-1",
        kind="lead",
    )

    assert TaskOutcome.COMPLETED.value == "completed"
    assert asyncio.run(TaskLifecycleContributor.on_task_start(_Bare(), app_store, task_store, info)) is None
    assert asyncio.run(TaskLifecycleContributor.on_task_stop(_Bare(), app_store, task_store, info, TaskOutcome.COMPLETED)) is None


def test_system_model_observer_contract_reports_success_and_failure_shapes():
    class _Bare:
        pass

    app_store = ExtensionData("app")
    task_store = ExtensionData("task-1")
    request = SystemModelRequest(messages=("prompt",), model_name="system-model")
    success = SystemModelResult(response="answer", duration_ms=1.5)
    failure = SystemModelResult(error=RuntimeError("provider failed"), duration_ms=2.0)

    assert SystemOperationKind.GOAL.value == "goal"
    assert asyncio.run(SystemModelCallObserver.on_system_model_call(_Bare(), app_store, task_store, SystemOperationKind.GOAL, request, success)) is None
    assert asyncio.run(SystemModelCallObserver.on_system_model_call(_Bare(), app_store, task_store, SystemOperationKind.GOAL, request, failure)) is None


def test_system_model_request_normalizes_messages_into_an_immutable_sequence():
    """``messages`` is a snapshot of a message sequence, never a per-character view.

    Title and summarization pass a single prompt string, so a bare ``str`` must not
    reach observers as a ``Sequence`` whose items are characters. A live ``list`` from
    a call site must also be copied: the snapshot is documented as read-only, and the
    caller keeps mutating its own list after the observation is dispatched.
    """
    assert SystemModelRequest(messages="one prompt").messages == ("one prompt",)

    live: list[str] = ["first"]
    request = SystemModelRequest(messages=live)
    live.append("second")
    assert request.messages == ("first",)

    assert SystemModelRequest().messages == ()
    assert SystemModelRequest(messages=("already", "a", "tuple")).messages == ("already", "a", "tuple")


def test_gateway_contribution_points_are_part_of_the_public_surface():
    import deerflow_extension_api

    for name in (
        "ExtensionRuntimeDeps",
        "ExtensionService",
    ):
        assert name in deerflow_extension_api.__all__
        assert hasattr(deerflow_extension_api, name)
    assert callable(ExtensionRegistry.service)
    assert callable(ExtensionRegistry.routers)
    assert not hasattr(deerflow_extension_api, "RouterContributor")


def test_task_store_from_runtime_reads_the_host_key():
    class _Runtime:
        def __init__(self, context):
            self.context = context

    store = ExtensionData("task-1")
    assert task_store_from_runtime(_Runtime({EXTENSION_TASK_STORE_KEY: store})) is store


def test_task_store_from_runtime_returns_none_on_missing_or_wrong_shape():
    class _Runtime:
        def __init__(self, context):
            self.context = context

    assert task_store_from_runtime(None) is None
    assert task_store_from_runtime(_Runtime({})) is None
    assert task_store_from_runtime(_Runtime("not-a-mapping")) is None
    assert task_store_from_runtime(_Runtime({EXTENSION_TASK_STORE_KEY: "wrong type"})) is None


def test_extension_decorator_stamps_api_requirement():
    @extension(api="0.1", name="demo")
    def install(registry, config):
        return None

    assert install.__deerflow_api__ == "0.1"
    assert install.__deerflow_name__ == "demo"


def test_task_outcome_members():
    assert {outcome.value for outcome in TaskOutcome} == {"completed", "aborted", "failed"}


def test_system_operation_kind_members():
    assert {kind.value for kind in SystemOperationKind} == {"goal", "memory", "title", "summarization"}


def test_registry_and_install_alias_are_part_of_the_public_surface():
    """Independent extensions annotate install(registry, config) against the
    contract package alone — importing the host's concrete registry would pin
    them to the harness release cadence and advertise host-only machinery."""
    import typing

    import deerflow_extension_api

    assert "ExtensionRegistry" in deerflow_extension_api.__all__
    assert "ExtensionInstall" in deerflow_extension_api.__all__
    parameters, return_type = typing.get_args(ExtensionInstall)
    assert parameters[0] is ExtensionRegistry, "install()'s first argument must be the public registry contract"


def test_distribution_marks_the_contract_package_as_typed():
    marker = importlib.resources.files("deerflow_extension_api").joinpath("py.typed")
    assert marker.is_file()


def test_contract_package_keeps_runtime_dependencies_empty():
    import tomllib
    from pathlib import Path

    pyproject = Path(__file__).parent.parent / "packages" / "extension-api" / "pyproject.toml"

    assert tomllib.loads(pyproject.read_text())["project"]["dependencies"] == []


def test_harness_pins_the_contract_package_exactly():
    """The version contract (extension-system design): the host pins the
    contract package exactly, extensions use ranges. A range here would let an
    older harness resolve a newer 1.x contract package — API_VERSION would
    then come from the upgraded package and newer extensions would look
    supported against a host whose registry/placements/hook pipeline still
    implements the older contract. The pin makes pip reject that skew at
    install time."""
    import tomllib
    from importlib.metadata import version
    from pathlib import Path

    from packaging.requirements import Requirement

    pyproject = Path(__file__).parent.parent / "packages" / "harness" / "pyproject.toml"
    dependencies = tomllib.loads(pyproject.read_text())["project"]["dependencies"]
    requirement = next(Requirement(dep) for dep in dependencies if Requirement(dep).name == "deerflow-extension-api")

    expected = f"=={version('deerflow-extension-api')}"
    assert str(requirement.specifier) == expected, f"the host must pin deerflow-extension-api exactly ({expected}); a range lets pip resolve a contract newer than the host implements"


def test_runtime_api_version_matches_the_installed_contract_package():
    """Every additive contract slice bumps both gates together."""
    from importlib.metadata import version

    assert API_VERSION == "0.1.2"
    assert API_VERSION == version("deerflow-extension-api")


def test_extension_service_contract_is_public_and_defaults_to_noop():
    class _Bare:
        pass

    deps = ExtensionRuntimeDeps()

    assert deps.app_store is None
    assert deps.session_factory is None
    assert asyncio.run(ExtensionService.start(_Bare(), deps)) is None
    assert asyncio.run(ExtensionService.stop(_Bare())) is None
