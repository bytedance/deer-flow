from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "sandbox-network-proxy-image.yaml"


def test_pull_request_proxy_build_has_read_only_permissions():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    validate = workflow["jobs"]["validate"]
    build = next(step for step in validate["steps"] if step["name"] == "Build image")

    assert validate["if"] == "github.event_name == 'pull_request'"
    assert validate["permissions"] == {"contents": "read"}
    assert build["with"]["push"] is False


def test_proxy_publish_credentials_are_gated_to_upstream_main_pushes():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    publish = workflow["jobs"]["publish"]
    build = next(step for step in publish["steps"] if step["name"] == "Build and publish image")

    assert publish["if"] == "github.event_name == 'push' && github.ref == 'refs/heads/main' && github.repository == 'bytedance/deer-flow'"
    assert publish["permissions"] == {
        "contents": "read",
        "packages": "write",
        "attestations": "write",
        "id-token": "write",
    }
    assert build["with"]["push"] is True
    assert "workflow_dispatch" not in WORKFLOW.read_text(encoding="utf-8")
