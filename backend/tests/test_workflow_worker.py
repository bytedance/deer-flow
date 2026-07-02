"""Tests for durable workflow worker helpers."""

from deerflow.runtime.workflows import WorkflowLeaseConfig, default_workflow_worker_identity


def test_default_workflow_worker_identity_uses_configured_id(monkeypatch):
    monkeypatch.setenv("DEER_FLOW_WORKFLOW_WORKER_ID", "worker-a")

    identity = default_workflow_worker_identity()

    assert identity.worker_id == "worker-a"
    assert identity.hostname
    assert identity.process_id > 0


def test_default_workflow_worker_identity_derives_stable_shape(monkeypatch):
    monkeypatch.delenv("DEER_FLOW_WORKFLOW_WORKER_ID", raising=False)

    identity = default_workflow_worker_identity(prefix="deerflow-test")

    assert identity.worker_id.startswith("deerflow-test:")
    assert identity.hostname in identity.worker_id
    assert str(identity.process_id) in identity.worker_id


def test_workflow_lease_config_from_env(monkeypatch):
    monkeypatch.setenv("DEER_FLOW_WORKFLOW_LEASE_SECONDS", "120")
    monkeypatch.setenv("DEER_FLOW_WORKFLOW_RENEW_INTERVAL_SECONDS", "30")

    config = WorkflowLeaseConfig.from_env()

    assert config.lease_seconds == 120
    assert config.renewal_interval_seconds == 30


def test_workflow_lease_config_ignores_invalid_env(monkeypatch):
    monkeypatch.setenv("DEER_FLOW_WORKFLOW_LEASE_SECONDS", "-1")
    monkeypatch.setenv("DEER_FLOW_WORKFLOW_RENEW_INTERVAL_SECONDS", "not-int")

    config = WorkflowLeaseConfig.from_env()

    assert config == WorkflowLeaseConfig()
