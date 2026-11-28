"""The Ingress backend and operator notes must follow ``nginx.service.port``.

A chart render with a non-default nginx port previously left the Ingress
backend on the hard-coded 2026, so the controller could not resolve a Service
port, and the post-install port-forward example targeted the old port.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CHART = REPO_ROOT / "deploy" / "helm" / "deer-flow"
NOTES = CHART / "templates" / "NOTES.txt"


def _render(port: int) -> tuple[list[dict], str]:
    helm = shutil.which("helm")
    if helm is None:
        pytest.skip("helm is unavailable")
    result = subprocess.run(
        [helm, "template", "deer-flow", str(CHART), "--set", "ingress.enabled=true", "--set", f"nginx.service.port={port}"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    documents = [document for document in yaml.safe_load_all(result.stdout) if isinstance(document, dict)]
    return documents, result.stdout


def _document(documents: list[dict], kind: str, name: str | None = None) -> dict:
    return next(document for document in documents if document.get("kind") == kind and (name is None or document.get("metadata", {}).get("name") == name))


@pytest.mark.parametrize("port", [2026, 8080], ids=["default-port", "custom-port"])
def test_ingress_and_notes_follow_the_configured_nginx_port(port: int) -> None:
    documents, rendered = _render(port)
    service = _document(documents, "Service", "nginx")
    ingress = _document(documents, "Ingress")

    assert service["spec"]["ports"][0]["name"] == "http"
    assert service["spec"]["ports"][0]["port"] == port

    backend = ingress["spec"]["rules"][0]["http"]["paths"][0]["backend"]["service"]
    assert backend["name"] == "nginx"
    assert backend["port"] == {"name": "http"}, "the Ingress must target the Service's named port, not a hard-coded number"

    notes = NOTES.read_text(encoding="utf-8")
    assert "{{ $nginxPort }}:{{ $nginxPort }}" in notes
    assert "http://localhost:{{ $nginxPort }}" in notes
    assert "2026:2026" not in notes
