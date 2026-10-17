"""Immutable file versions and run-bound configuration evidence."""

import os

import pytest


def test_evidence_projects_actual_assembly_without_credentials():
    from deerflow_extension_api import AgentAssemblyDescriptor

    from deerflow.runtime.assembly_evidence import project_assembly_evidence

    descriptor = AgentAssemblyDescriptor(
        namespace="deerflow",
        agent_name="reviewer",
        requested_model="old",
        effective_model="actual",
        model_parameters={"temperature": 0.2, "api_key": "secret", "extra": {"Authorization": "Bearer nested-secret"}},
        thinking_enabled=False,
        reasoning_effort=None,
        base_prompt_hash="prompt-sha",
        tools=(),
        middlewares=(),
        deferred_tool_names=(),
        enabled_skills=("review",),
        effective_policies={"skill_catalog_hash": "skill-sha"},
    )
    proof = project_assembly_evidence(descriptor, thread_id="thread", run_id="run")
    assert proof["run_id"] == "run" and proof["model"] == "actual"
    assert proof["parameters"]["temperature"] == 0.2
    assert "secret" not in str(proof)
    assert proof == project_assembly_evidence(descriptor, thread_id="thread", run_id="run")
    from dataclasses import replace

    changed = project_assembly_evidence(replace(descriptor, base_prompt_hash="new-prompt"), thread_id="thread", run_id="run")
    assert proof["version"] != changed["version"]


def test_artifact_versions_are_append_only_and_owner_scoped(tmp_path, monkeypatch):
    from pathlib import Path

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "examples/deerflow-extension-workflows"))
    from deerflow_extension_workflows.store import Store

    store = Store(tmp_path / "workflows.sqlite")
    one = store.capture_artifact("alice", "workflow", "step", "report.pdf", b"original")
    two = store.capture_artifact("alice", "workflow", "step2", "report.pdf", b"edited")
    assert one["version"] != two["version"]
    assert store.artifact("alice", "workflow", one["version"])[1] == b"original"
    with pytest.raises(ValueError):
        store.artifact("bob", "workflow", one["version"])
    with pytest.raises(ValueError):
        store.capture_artifact("alice", "workflow", "step", "report.pdf", b"overwrite")


@pytest.mark.skipif(os.name == "nt", reason="output capture is POSIX-only (dir_fd and O_NOFOLLOW)")
def test_host_output_capture_rejects_unsafe_files(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from deerflow_extension_api import AgentRunError
    from fastapi import HTTPException

    from app.gateway.extension_artifacts import MAX_BYTES, read_output_snapshot

    output = tmp_path / "outputs"
    output.mkdir()
    monkeypatch.setattr("app.gateway.extension_artifacts.get_paths", lambda: SimpleNamespace(base_dir=tmp_path, sandbox_outputs_dir=lambda *a, **k: output))
    report = output / "report.txt"
    report.write_bytes(b"original")
    captured = read_output_snapshot("alice", "thread", "/mnt/user-data/outputs/report.txt")
    report.write_bytes(b"edited")
    assert captured == b"original"
    (output / "link").symlink_to(report)
    for path in ("link", "../report.txt"):
        with pytest.raises((AgentRunError, HTTPException)):
            read_output_snapshot("alice", "thread", "/mnt/user-data/outputs/" + path)
    report.write_bytes(b"x" * (MAX_BYTES + 1))
    with pytest.raises(AgentRunError):
        read_output_snapshot("alice", "thread", "/mnt/user-data/outputs/report.txt")


@pytest.mark.asyncio
@pytest.mark.parametrize("admit", ["create", "create_or_reject"])
@pytest.mark.parametrize("evidence_key", [None, "renamed_host_evidence"])
async def test_client_cannot_supply_host_evidence(admit, evidence_key, monkeypatch):
    from deerflow.runtime import RunManager, assembly_evidence

    if evidence_key is not None:
        monkeypatch.setattr(assembly_evidence, "EVIDENCE_KEY", evidence_key)
    key = assembly_evidence.EVIDENCE_KEY
    manager = RunManager()
    try:
        record = await getattr(manager, admit)("thread", metadata={key: {"source": "forged"}, "safe": "value"})
        assert key not in record.metadata
        assert record.metadata["safe"] == "value"
    finally:
        await manager.shutdown()
