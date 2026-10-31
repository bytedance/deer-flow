import asyncio
import sys
import types
from types import SimpleNamespace

import pytest
from langchain_core.tools import StructuredTool

import deerflow_extension_skill_evolution.status as status_module
from deerflow_extension_skill_evolution.config import SkillEvolutionSettings
from deerflow_extension_skill_evolution.service import CapabilityHandle
from deerflow_extension_skill_evolution.status import NAMESPACE, StatusReporter


def _fake_tool() -> StructuredTool:
    def _run(action: str, name: str = "", content: str = "") -> str:
        return "ok"

    return StructuredTool.from_function(func=_run, name="skill_manage", description="fake host tool")


def _stub_host_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    leaf = types.ModuleType("deerflow.tools.skill_manage_tool")
    leaf.skill_manage_tool = _fake_tool()
    monkeypatch.setitem(sys.modules, "deerflow.tools.skill_manage_tool", leaf)


def _reporter(mutation_handle: CapabilityHandle | None = None, evidence_handle: CapabilityHandle | None = None, model_handle: CapabilityHandle | None = None, **settings_kwargs) -> StatusReporter:
    return StatusReporter(
        settings=SkillEvolutionSettings(**settings_kwargs),
        extension_version="0.3.0",
        mutations_handle=mutation_handle or CapabilityHandle(),
        evidence_handle=evidence_handle or CapabilityHandle(),
        model_handle=model_handle,
    )


def test_snapshot_reports_config_version_and_host(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_host_tool(monkeypatch)
    monkeypatch.setattr(status_module, "_legacy_core_switch_enabled", lambda: False)
    snapshot = _reporter(min_tool_calls_hint=7).snapshot()
    assert snapshot["namespace"] == NAMESPACE
    assert snapshot["distribution"] == "deerflow-extension-skill-evolution"
    assert snapshot["version"] == "0.3.0"
    assert snapshot["config"] == {
        "min_tool_calls_hint": 7,
        "prefer_patch": True,
        "confirm_before_create": True,
        "scope": "lead",
        "feedback_mode": "draft",
        "evolution_mode": "model",
        "feedback_storage": "not_configured",
    }
    assert snapshot["host"]["skill_manage_tool"] == "available"
    assert snapshot["host"]["legacy_skill_evolution_enabled"] is False
    assert snapshot["host"]["skill_mutations"] == {"state": "not_granted"}
    assert snapshot["host"]["completed_run_evidence"] == {"state": "not_granted"}
    assert snapshot["host"]["managed_pipeline"] == "unavailable"
    assert snapshot["restart_required"] is False


def test_snapshot_flags_legacy_core_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_host_tool(monkeypatch)
    monkeypatch.setattr(status_module, "_legacy_core_switch_enabled", lambda: True)
    snapshot = _reporter().snapshot()
    assert snapshot["host"]["legacy_skill_evolution_enabled"] is True


def test_snapshot_marks_missing_host_tool_without_leaking_exception_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "deerflow.tools.skill_manage_tool", None)
    monkeypatch.setattr(status_module, "_legacy_core_switch_enabled", lambda: False)
    snapshot = _reporter().snapshot()
    assert snapshot["host"]["skill_manage_tool"] == "unavailable"
    # No exception details, paths, or module internals anywhere in the payload.
    assert "Traceback" not in repr(snapshot)
    assert "ImportError" not in repr(snapshot)


def test_snapshot_reports_granted_mutation_service(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_host_tool(monkeypatch)
    monkeypatch.setattr(status_module, "_legacy_core_switch_enabled", lambda: False)
    mutations = CapabilityHandle()
    capabilities = SimpleNamespace(operations=("stage", "check", "commit"), protocol_version="skill-mutations-v1", topology="posix-single-host-local-filesystem")
    mutations.bind(SimpleNamespace(capabilities=capabilities))
    snapshot = _reporter(mutation_handle=mutations).snapshot()
    assert snapshot["host"]["skill_mutations"] == {
        "state": "granted",
        "operations": ["stage", "check", "commit"],
        "protocol_version": "skill-mutations-v1",
        "topology": "posix-single-host-local-filesystem",
    }


def test_snapshot_marks_pipeline_available_only_with_both_handles(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_host_tool(monkeypatch)
    monkeypatch.setattr(status_module, "_legacy_core_switch_enabled", lambda: False)
    mutations, evidence = CapabilityHandle(), CapabilityHandle()
    capabilities = SimpleNamespace(operations=("stage",), protocol_version="skill-mutations-v1", topology="posix-single-host-local-filesystem")
    mutations.bind(SimpleNamespace(capabilities=capabilities))
    # The real evidence reader exposes no capabilities summary at all.
    evidence.bind(object())
    only_mutations = _reporter(mutation_handle=mutations).snapshot()
    assert only_mutations["host"]["managed_pipeline"] == "unavailable"
    both = _reporter(mutation_handle=mutations, evidence_handle=evidence).snapshot()
    assert both["host"]["managed_pipeline"] == "available"
    assert both["host"]["completed_run_evidence"] == {"state": "granted"}


def test_snapshot_survives_an_unreadable_capabilities_property(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_host_tool(monkeypatch)
    monkeypatch.setattr(status_module, "_legacy_core_switch_enabled", lambda: False)

    class _Broken:
        @property
        def capabilities(self):
            raise RuntimeError("/secret/host/path involved")

    handle = CapabilityHandle()
    handle.bind(_Broken())
    snapshot = _reporter(mutation_handle=handle).snapshot()
    assert snapshot["host"]["skill_mutations"] == {"state": "granted", "capabilities": "unreadable"}
    assert "/secret/host/path" not in repr(snapshot)


def test_status_action_is_async_and_payload_free(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_host_tool(monkeypatch)
    monkeypatch.setattr(status_module, "_legacy_core_switch_enabled", lambda: False)
    reporter = _reporter()
    result = asyncio.run(reporter.status({"anything": "ignored"}, None))
    assert result == reporter.snapshot()
    assert result["namespace"] == NAMESPACE
    assert result["host"]["skill_manage_tool"] == "available"


def test_snapshot_reports_agent_feedback_mode_and_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_host_tool(monkeypatch)
    monkeypatch.setattr(status_module, "_legacy_core_switch_enabled", lambda: False)
    snapshot = _reporter(feedback_mode="agent", storage_path="/tmp/skill-evolution.sqlite").snapshot()
    assert snapshot["config"]["feedback_mode"] == "agent"
    assert snapshot["config"]["feedback_storage"] == "configured"


def test_snapshot_reports_model_invocation_and_evolution_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_host_tool(monkeypatch)
    monkeypatch.setattr(status_module, "_legacy_core_switch_enabled", lambda: False)
    # Without the model grant the jobs stay unavailable even when the
    # managed pipeline itself is granted.
    mutations, evidence = CapabilityHandle(), CapabilityHandle()
    capabilities = SimpleNamespace(operations=("stage",), protocol_version="skill-mutations-v1", topology="posix-single-host-local-filesystem")
    mutations.bind(SimpleNamespace(capabilities=capabilities))
    evidence.bind(object())
    without_model = _reporter(mutation_handle=mutations, evidence_handle=evidence).snapshot()
    assert without_model["host"]["model_invocation"] == {"state": "not_granted"}
    assert without_model["host"]["evolution_jobs"] == "unavailable"
    model = CapabilityHandle()
    model.bind(object())
    with_model = _reporter(mutation_handle=mutations, evidence_handle=evidence, model_handle=model).snapshot()
    assert with_model["host"]["model_invocation"] == {"state": "granted"}
    assert with_model["host"]["evolution_jobs"] == "available"


def test_agent_evolution_catalog_keeps_memory_reserved(monkeypatch):
    _stub_host_tool(monkeypatch)
    snapshot = _reporter().snapshot()
    assert snapshot["product"] == "agent-evolution"
    assert [(item["id"], item["state"]) for item in snapshot["modules"]] == [("skill", "available"), ("memory", "planned")]
    # Stable identity keeps installed grants, stored settings and page URLs intact.
    assert snapshot["namespace"] == "community.skill-evolution"


def test_browser_chat_models_enable_jobs_without_plugin_model_grant(monkeypatch):
    _stub_host_tool(monkeypatch)
    monkeypatch.setattr(status_module, "_legacy_core_switch_enabled", lambda: False)
    mutations, evidence = CapabilityHandle(), CapabilityHandle()
    mutations.bind(SimpleNamespace(capabilities=SimpleNamespace(operations=("stage", "check", "commit"), protocol_version="v1", topology="local")))
    evidence.bind(object())
    reporter = _reporter(mutation_handle=mutations, evidence_handle=evidence)
    result = asyncio.run(reporter.status({}, SimpleNamespace(chat_models=object())))
    assert result["host"]["model_invocation"] == {"state": "not_granted"}
    assert result["host"]["chat_models"] == "available"
    assert result["host"]["evolution_jobs"] == "available"
