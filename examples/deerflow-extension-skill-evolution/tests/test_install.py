import asyncio
import sys
import types
from types import SimpleNamespace

import pytest
from langchain_core.tools import StructuredTool

from deerflow_extension_skill_evolution import __version__, install
from deerflow_extension_skill_evolution import modes as modes_module


class _RecordingRegistry:
    """Registry double that only records; mirrors the ExtensionRegistry protocol surface."""

    def __init__(self, *, accepts_plugins: bool = True) -> None:
        self.middleware_contributors: list = []
        self.plugin_contributions: list = []
        self.services: list = []
        self._accepts_plugins = accepts_plugins

    def middlewares(self, contributor) -> None:
        self.middleware_contributors.append(contributor)

    def service(self, service) -> None:
        self.services.append(service)

    def plugin(self, contribution) -> bool:
        if not self._accepts_plugins:
            return False
        self.plugin_contributions.append(contribution)
        return True


def _stub_host_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    leaf = types.ModuleType("deerflow.tools.skill_manage_tool")

    def _run(action: str, name: str = "", content: str = "") -> str:
        return "ok"

    leaf.skill_manage_tool = StructuredTool.from_function(func=_run, name="skill_manage", description="fake host tool")
    monkeypatch.setitem(sys.modules, "deerflow.tools.skill_manage_tool", leaf)


def test_install_registers_middlewares_service_and_plugin(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_host_tool(monkeypatch)
    registry = _RecordingRegistry()
    install(registry, {"min_tool_calls_hint": 3})

    assert len(registry.middleware_contributors) == 1
    assert len(registry.services) == 1
    assert len(registry.plugin_contributions) == 1
    contribution = registry.plugin_contributions[0]
    assert contribution.namespace == "community.skill-evolution"
    assert contribution.enabled is True
    assert [action.name for action in contribution.backend] == [
        "status",
        "skill_config",
        "skill_config_write",
        "evolved_skills",
        "evolved_version",
        "managed_read",
        "managed_stage",
        "managed_check",
        "managed_propose",
        "managed_publish",
        "managed_discard",
        "managed_rollback",
        "annotation_draft",
        "annotation_evolve",
        "evolution_status",
        "evolution_discard",
        "skill_trajectories",
        "trajectory_annotate",
        "trajectory_unannotate",
    ]
    # The status page ships as packaged browser assets under the package root.
    from deerflow_extension_api import BrowserAssets

    assert isinstance(contribution.frontend, BrowserAssets)
    assert contribution.frontend.module == "skill-evolution.v1"
    # The registered backend action is wired and callable.
    snapshot = asyncio.run(contribution.backend[0].handler({}, None))
    assert snapshot["config"]["min_tool_calls_hint"] == 3
    # Before Gateway service start, no mutation handle is bound.
    assert snapshot["host"]["skill_mutations"] == {"state": "not_granted"}


def test_installed_service_reports_a_granted_handle_through_status(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_host_tool(monkeypatch)
    registry = _RecordingRegistry()
    install(registry, {})
    service = registry.services[0]
    asyncio.run(service.start(SimpleNamespace(skill_mutations=SimpleNamespace(capabilities=SimpleNamespace(operations=("stage",), protocol_version="skill-mutations-v1", topology="posix-single-host-local-filesystem")))))
    snapshot = asyncio.run(registry.plugin_contributions[0].backend[0].handler({}, None))
    assert snapshot["host"]["skill_mutations"]["state"] == "granted"
    asyncio.run(service.stop())
    snapshot = asyncio.run(registry.plugin_contributions[0].backend[0].handler({}, None))
    assert snapshot["host"]["skill_mutations"] == {"state": "not_granted"}


def test_install_is_fail_closed_on_invalid_config(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_host_tool(monkeypatch)
    registry = _RecordingRegistry()
    with pytest.raises(ValueError, match="Unknown skill-evolution config key"):
        install(registry, {"enabled": True})
    assert registry.middleware_contributors == []
    assert registry.services == []
    assert registry.plugin_contributions == []


def test_install_wires_the_evolved_skills_record_store(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _stub_host_tool(monkeypatch)
    registry = _RecordingRegistry()
    install(registry, {"storage_path": str(tmp_path / "evolved.sqlite")})
    evolved = next(action for action in registry.plugin_contributions[0].backend if action.name == "evolved_skills")
    ctx = SimpleNamespace(principal=SimpleNamespace(user_id="user-1"))
    # No pipeline commit has happened yet: the listing is empty but enabled.
    assert asyncio.run(evolved.handler({}, ctx)) == {"ok": True, "skills": []}


def test_install_degrades_the_evolved_skills_listing_without_storage_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_host_tool(monkeypatch)
    registry = _RecordingRegistry()
    install(registry, {})
    evolved = next(action for action in registry.plugin_contributions[0].backend if action.name == "evolved_skills")
    ctx = SimpleNamespace(principal=SimpleNamespace(user_id="user-1"))
    assert asyncio.run(evolved.handler({}, ctx)) == {"ok": False, "error": {"code": "UNAVAILABLE"}}


def test_install_rejects_a_malformed_storage_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_host_tool(monkeypatch)
    registry = _RecordingRegistry()
    with pytest.raises(ValueError, match="storage_path"):
        install(registry, {"storage_path": "   "})
    assert registry.plugin_contributions == []


def test_install_is_fail_closed_without_host_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "deerflow.tools.skill_manage_tool", None)
    registry = _RecordingRegistry()
    with pytest.raises(RuntimeError, match="skill_manage"):
        install(registry, {})
    assert registry.middleware_contributors == []


def test_install_degrades_to_log_only_when_host_rejects_plugins(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    _stub_host_tool(monkeypatch)
    registry = _RecordingRegistry(accepts_plugins=False)
    with caplog.at_level("INFO", logger="deerflow_extension_skill_evolution"):
        install(registry, {})
    assert len(registry.middleware_contributors) == 1  # core capability unaffected
    assert registry.plugin_contributions == []
    assert any("managed-mutation surfaces are disabled" in record.message for record in caplog.records)


def test_install_exposes_the_declared_version() -> None:
    assert isinstance(__version__, str)
    assert __version__


def _declared_tool_names(registry: _RecordingRegistry) -> list[str]:
    (contributor,) = registry.middleware_contributors
    (placement,) = contributor.contribute_middlewares(None, SimpleNamespace(scope=None))
    return [tool.name for tool in placement.middleware.tools]


def _stub_feedback_seams(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the host seams build_skill_feedback_tool imports lazily."""
    user_context = types.ModuleType("deerflow.runtime.user_context")
    user_context.resolve_runtime_user_id = lambda runtime: "stub-user"
    monkeypatch.setitem(sys.modules, "deerflow.runtime.user_context", user_context)
    tools_types = types.ModuleType("deerflow.tools.types")
    from langchain.tools import ToolRuntime

    tools_types.Runtime = ToolRuntime[dict, object]
    monkeypatch.setitem(sys.modules, "deerflow.tools.types", tools_types)


def test_install_declares_the_feedback_tool_whenever_annotations_have_storage(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _stub_host_tool(monkeypatch)
    _stub_feedback_seams(monkeypatch)

    # The skill_feedback tool records annotations — the raw material for
    # BOTH evolution shapes — so it is declared whenever a store exists,
    # regardless of the evolution mode.
    with_store = _RecordingRegistry()
    install(with_store, {"storage_path": str(tmp_path / "a.sqlite")})
    assert _declared_tool_names(with_store) == ["skill_manage", "skill_feedback"]

    without_storage = _RecordingRegistry()
    install(without_storage, {"feedback_mode": "agent"})
    assert _declared_tool_names(without_storage) == ["skill_manage"]

    # A host without the tool seams degrades to page-side annotation only:
    # a None entry in sys.modules makes the lazy import fail.
    _stub_host_tool(monkeypatch)
    _stub_feedback_seams(monkeypatch)
    monkeypatch.setitem(sys.modules, "deerflow.runtime.user_context", None)
    degraded = _RecordingRegistry()
    install(degraded, {"storage_path": str(tmp_path / "c.sqlite")})
    assert _declared_tool_names(degraded) == ["skill_manage"]


def test_install_binds_the_model_invoker_handle_into_the_status_snapshot(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _stub_host_tool(monkeypatch)
    _stub_feedback_seams(monkeypatch)
    registry = _RecordingRegistry()
    install(registry, {"storage_path": str(tmp_path / "evolved.sqlite"), "feedback_mode": "agent"})
    service = registry.services[0]
    capabilities = SimpleNamespace(operations=("stage",), protocol_version="skill-mutations-v1", topology="posix-single-host-local-filesystem")
    asyncio.run(service.start(SimpleNamespace(skill_mutations=SimpleNamespace(capabilities=capabilities), completed_run_evidence=object(), model_invoker=object())))
    snapshot = asyncio.run(registry.plugin_contributions[0].backend[0].handler({}, None))
    assert snapshot["host"]["model_invocation"] == {"state": "granted"}
    assert snapshot["host"]["evolution_jobs"] == "available"
    asyncio.run(service.stop())
    snapshot = asyncio.run(registry.plugin_contributions[0].backend[0].handler({}, None))
    assert snapshot["host"]["model_invocation"] == {"state": "not_granted"}
    assert snapshot["host"]["evolution_jobs"] == "unavailable"


def test_install_gates_the_evolution_actions_on_the_live_mode(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """The evolution_mode switch is read per call, not bound at install.

    Both action shapes are always wired; each answers UNAVAILABLE when the
    persisted mode (settings.json beside the install) selects the other
    shape. Flipping the file flips the behavior without a restart.
    """
    _stub_host_tool(monkeypatch)
    settings = tmp_path / "settings.json"
    monkeypatch.setattr(modes_module, "settings_path", lambda: settings)
    registry = _RecordingRegistry()
    install(registry, {"storage_path": str(tmp_path / "store.sqlite")})
    # Bind the (fake) granted capabilities so the only remaining gate is
    # the mode itself.
    asyncio.run(registry.services[0].start(SimpleNamespace(skill_mutations=object(), completed_run_evidence=object(), model_invoker=object())))
    actions = {action.name: action for action in registry.plugin_contributions[0].backend}
    ctx = SimpleNamespace(principal=SimpleNamespace(user_id="user-1"))

    # Default (no settings.json): the model-evolution shape owns feedback.
    # The launch proceeds past the mode gate and fails later on the fake
    # mutation backbone (INTERNAL), while the draft action is refused.
    assert asyncio.run(actions["annotation_draft"].handler({"skill_name": "demo-evolution"}, ctx)) == {"ok": False, "error": {"code": "UNAVAILABLE"}}
    launched = asyncio.run(actions["annotation_evolve"].handler({"skill_name": "demo-evolution"}, ctx))
    assert launched != {"ok": False, "error": {"code": "UNAVAILABLE"}}

    # Flip the switch to append: the draft action answers, the model launch
    # is refused — read live from the persisted file.
    modes_module.write_evolution_mode("append", path=tmp_path / "store.sqlite.settings.json")
    assert asyncio.run(actions["annotation_draft"].handler({"skill_name": "demo-evolution"}, ctx)) != {"ok": False, "error": {"code": "UNAVAILABLE"}}
    assert asyncio.run(actions["annotation_evolve"].handler({"skill_name": "demo-evolution"}, ctx)) == {"ok": False, "error": {"code": "UNAVAILABLE"}}

    # Status reports the live mode for the page.
    snapshot = asyncio.run(actions["status"].handler({}, ctx))
    assert snapshot["config"]["evolution_mode"] == "append"


def test_install_migrates_legacy_mode_and_shares_it_across_actions(monkeypatch, tmp_path):
    _stub_host_tool(monkeypatch)
    legacy = tmp_path / "legacy-settings.json"
    modes_module.write_evolution_mode("append", path=legacy)
    monkeypatch.setattr(modes_module, "settings_path", lambda: legacy)
    registry = _RecordingRegistry()
    install(registry, {"storage_path": str(tmp_path / "store.sqlite")})
    legacy.unlink()
    actions = {action.name: action for action in registry.plugin_contributions[0].backend}
    ctx = SimpleNamespace(principal=SimpleNamespace(user_id="user-1"))
    assert asyncio.run(actions["status"].handler({}, ctx))["config"]["evolution_mode"] == "append"
    assert asyncio.run(actions["annotation_evolve"].handler({"skill_name": "demo-evolution"}, ctx))["error"]["code"] == "UNAVAILABLE"
    configurator = actions["skill_config_write"].handler.__self__
    configurator._mode_writer("model")
    assert asyncio.run(actions["status"].handler({}, ctx))["config"]["evolution_mode"] == "model"
    assert asyncio.run(actions["annotation_draft"].handler({"skill_name": "demo-evolution"}, ctx))["error"]["code"] == "UNAVAILABLE"
