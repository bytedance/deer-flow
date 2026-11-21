"""Bundled run-postmortem example: host loading, route mounting and evidence reads."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from deerflow_extension_api import CompletedRunEvent, CompletedRunEventPage, CompletedRunSnapshot, EvidenceLimits, ExtensionRuntimeDeps
from deerflow_extension_api.run_evidence import RunPage

from deerflow.extensions.browser_assets import load_browser_assets
from deerflow.extensions.loader import ExtensionSpec, load_extensions

pytestmark = pytest.mark.bundled_extension

EXAMPLE = Path(__file__).resolve().parents[2] / "examples/deerflow-extension-run-postmortem"
USE = "deerflow_extension_run_postmortem:install"
PREFIX = "/api/extension-run-postmortem"


class FakeEvidence:
    """Contract-shaped evidence for one sealed error run."""

    async def list_changed_runs(self, *, cursor: str | None = None, limit: int = 200) -> RunPage:
        return RunPage(items=())

    async def get_snapshot(self, *, thread_id: str, run_id: str, limits: EvidenceLimits = EvidenceLimits()) -> CompletedRunSnapshot:
        return CompletedRunSnapshot(snapshot_ref="snap", evidence_revision="rev", thread_id=thread_id, run_id=run_id, owner_id="alice", agent_id="lead_agent", origin="scheduled", status="error", seal_state="sealed", event_count=2)

    async def read_events(self, *, snapshot_ref: str, cursor: str | None = None, limits: EvidenceLimits = EvidenceLimits()) -> CompletedRunEventPage:
        if cursor is not None:
            return CompletedRunEventPage()
        return CompletedRunEventPage(
            items=(
                CompletedRunEvent(event_id="e1", seq=1, event_type="run.start", category="trace", content_json=json.dumps({"status": "running"}), content_bytes=0, content_sha256=""),
                CompletedRunEvent(event_id="e2", seq=2, event_type="run.error", category="error", content_json=json.dumps({"message": "boom"}), content_bytes=0, content_sha256=""),
            )
        )


def _load(monkeypatch, config: dict):
    monkeypatch.syspath_prepend(str(EXAMPLE))
    return load_extensions([ExtensionSpec(use=USE, config=config)])


def test_install_registers_one_service_and_its_router(monkeypatch):
    loaded, diagnostics = _load(monkeypatch, {"enabled": True})

    assert not diagnostics
    ((_, service),) = loaded.services
    assert service.ready is False  # the host starts services; install only registers
    assert [getattr(router, "prefix", "") for _, router in loaded.routers] == [PREFIX]
    ((_, plugin),) = loaded.plugins
    assert plugin.namespace == "community.run-postmortem"
    assert [action.name for action in plugin.backend] == ["latest", "report", "markdown"]
    assets = load_browser_assets(plugin.frontend)
    assert assets.entry == "static/postmortem.mjs"
    assert assets.module == "run-postmortem.v1"
    assert "static/postmortem.mjs" in assets.files


@pytest.mark.asyncio
async def test_report_is_derived_from_host_evidence(monkeypatch):
    loaded, _ = _load(monkeypatch, {"enabled": True})
    ((_, service),) = loaded.services
    await service.start(ExtensionRuntimeDeps(completed_run_evidence=FakeEvidence()))

    postmortem = await service.postmortem(thread_id="thread-1", run_id="run-1")

    assert postmortem.owner_id == "alice"
    assert [entry.event_type for entry in postmortem.timeline] == ["run.start", "run.error"]
    assert {anomaly.code for anomaly in postmortem.anomalies} == {"run_failed", "run_or_model_errors"}
    await service.stop()
    assert service.ready is False


def test_disabled_configuration_registers_nothing(monkeypatch):
    loaded, diagnostics = _load(monkeypatch, {"enabled": False})

    assert not diagnostics
    assert loaded.services == ()
    assert loaded.routers == ()
    assert loaded.plugins == ()


def test_a_mistyped_off_switch_fails_the_load(monkeypatch):
    loaded, diagnostics = _load(monkeypatch, {"enabled": "false"})

    assert diagnostics
    assert loaded.services == ()
    assert loaded.routers == ()
    assert loaded.plugins == ()
