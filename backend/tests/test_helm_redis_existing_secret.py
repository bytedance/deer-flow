"""Bundled Redis and the Gateway must use the same Secret credentials."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
import yaml
from support.shell import require_posix_sh

REPO_ROOT = Path(__file__).resolve().parents[2]
CHART = REPO_ROOT / "deploy" / "helm" / "deer-flow"
PASSWORD = "p a$$'\"@:/?#%[]*"


def _render_chart(*settings: str) -> list[dict]:
    helm = shutil.which("helm")
    if helm is None:
        pytest.skip("helm is unavailable")
    command = [helm, "template", "deer-flow", str(CHART)]
    for setting in settings:
        command.extend(["--set", setting])
    rendered = subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8").stdout
    return [document for document in yaml.safe_load_all(rendered) if isinstance(document, dict)]


def _container(documents: list[dict], name: str) -> dict:
    workload = next(document for document in documents if document.get("kind") in {"Deployment", "StatefulSet"} and document["metadata"]["name"].endswith(f"-{name}"))
    return next(container for container in workload["spec"]["template"]["spec"]["containers"] if container["name"] == name)


def _secret_ref(container: dict, env_name: str) -> dict:
    return next(item for item in container["env"] if item["name"] == env_name)["valueFrom"]["secretKeyRef"]


def _run_command(command: list[str], tmp_path: Path, password: str | None) -> list[str]:
    """Execute the rendered shell with argv-recording Redis executables."""
    assert command[:2] == ["sh", "-c"]
    for name in ("redis-server", "redis-cli"):
        executable = tmp_path / name
        executable.write_text(f"#!/bin/sh\nprintf '%s\\0' {name} \"$@\"\n", encoding="utf-8", newline="\n")
        executable.chmod(0o755)
    env = {key: value for key, value in os.environ.items() if key != "REDIS_PASSWORD"}
    if password is not None:
        env["REDIS_PASSWORD"] = password
    # cd accepts native checkout paths in Git Bash, and pwd supplies its PATH form.
    script = 'PATH="$(cd "$1" && pwd):$PATH"; export PATH; ' + command[2]
    result = subprocess.run([require_posix_sh(), "-c", script, "_", tmp_path.as_posix()], env=env, check=True, capture_output=True, text=True, encoding="utf-8")
    return result.stdout.rstrip("\0").split("\0")


@pytest.mark.parametrize("password", ["", PASSWORD])
def test_chart_managed_redis_credentials_match_the_gateway(password: str, tmp_path: Path) -> None:
    documents = _render_chart(f"redis.auth.password={password}")
    redis = _container(documents, "redis")
    gateway_ref = _secret_ref(_container(documents, "gateway"), "DEER_FLOW_STREAM_BRIDGE_REDIS_URL")
    secret = next(document for document in documents if document.get("kind") == "Secret" and document["metadata"]["name"] == gateway_ref["name"])
    url = urlsplit(secret["stringData"][gateway_ref["key"]])
    assert unquote(url.password or "") == password
    assert url.hostname == gateway_ref["name"]
    if password:
        assert secret["stringData"]["redis-password"] == password
        assert _secret_ref(redis, "REDIS_PASSWORD") == {"name": gateway_ref["name"], "key": "redis-password"}
    else:
        assert "redis-password" not in secret["stringData"]
        assert "env" not in redis
    expected_auth = ["--requirepass", password] if password else []
    assert _run_command(redis["command"] + redis["args"], tmp_path, password or None) == ["redis-server", "--appendonly", "yes", *expected_auth]
    for probe in ("readinessProbe", "livenessProbe"):
        expected_auth = ["--no-auth-warning", "-a", password] if password else []
        assert _run_command(redis[probe]["exec"]["command"], tmp_path, password or None) == ["redis-cli", *expected_auth, "ping"]


@pytest.mark.parametrize("password", [None, "", PASSWORD])
@pytest.mark.parametrize("ignored_password", ["", "ignored-values-password"])
def test_bundled_redis_uses_optional_existing_secret_password(password: str | None, ignored_password: str, tmp_path: Path) -> None:
    documents = _render_chart("redis.existingSecret=managed-redis", f"redis.auth.password={ignored_password}")
    redis = _container(documents, "redis")
    assert _secret_ref(redis, "REDIS_PASSWORD") == {"name": "managed-redis", "key": "redis-password", "optional": True}
    assert _secret_ref(_container(documents, "gateway"), "DEER_FLOW_STREAM_BRIDGE_REDIS_URL") == {"name": "managed-redis", "key": "redis-url"}
    assert not any(document.get("kind") == "Secret" and document["metadata"]["name"].endswith("-redis") for document in documents)
    if ignored_password:
        # The stale value must not leak into the manifest: it is the only input
        # here that a template edit could accidentally start rendering.
        assert ignored_password not in yaml.safe_dump(documents)
    expected_auth = ["--requirepass", password] if password else []
    assert _run_command(redis["command"] + redis["args"], tmp_path, password) == ["redis-server", "--appendonly", "yes", *expected_auth]
    for probe in ("readinessProbe", "livenessProbe"):
        argv = _run_command(redis[probe]["exec"]["command"], tmp_path, password)
        assert argv == ["redis-cli", *(["--no-auth-warning", "-a", password] if password else []), "ping"]


@pytest.mark.parametrize(
    "settings",
    [
        ("redis.existingSecret=false",),
        ("redis.external.existingSecret=false", "redis.existingSecret=false"),
    ],
    ids=["existing-secret-false", "both-secrets-false"],
)
def test_falsy_existing_secret_still_uses_the_chart_managed_secret(settings: tuple[str, ...]) -> None:
    # `false` is how people spell "not set" in values.yaml. `or` returns its
    # last operand even when falsy, so it would name the Secret `false` — and
    # nothing creates a Secret by that name, leaving both refs dangling.
    documents = _render_chart(*settings, f"redis.auth.password={PASSWORD}")
    gateway_ref = _secret_ref(_container(documents, "gateway"), "DEER_FLOW_STREAM_BRIDGE_REDIS_URL")
    redis_ref = _secret_ref(_container(documents, "redis"), "REDIS_PASSWORD")
    assert isinstance(gateway_ref["name"], str)
    assert gateway_ref == {"name": redis_ref["name"], "key": "redis-url"}
    assert redis_ref["key"] == "redis-password"
    assert any(document.get("kind") == "Secret" and document["metadata"]["name"] == gateway_ref["name"] for document in documents)


@pytest.mark.parametrize("enabled", ["true", "false"])
def test_external_secret_precedence_is_unchanged(enabled: str) -> None:
    # The existing helper gives external.existingSecret precedence in both modes.
    documents = _render_chart(f"redis.enabled={enabled}", "redis.existingSecret=bundled-secret", "redis.external.existingSecret=external-secret")
    assert _secret_ref(_container(documents, "gateway"), "DEER_FLOW_STREAM_BRIDGE_REDIS_URL") == {"name": "external-secret", "key": "redis-url"}
    if enabled == "true":
        assert _secret_ref(_container(documents, "redis"), "REDIS_PASSWORD") == {"name": "external-secret", "key": "redis-password", "optional": True}
    else:
        assert not any(document.get("kind") == "StatefulSet" and document["metadata"]["name"].endswith("-redis") for document in documents)
    assert not any(document.get("kind") == "Secret" and document["metadata"]["name"].endswith("-redis") for document in documents)


@pytest.mark.parametrize("setting", ["redis.existingSecret=managed-external", "redis.external.redisUrl=redis://:password@managed.example:6380/1"])
def test_external_redis_does_not_deploy_a_bundled_instance(setting: str) -> None:
    documents = _render_chart("redis.enabled=false", setting)
    assert not any(document.get("kind") == "StatefulSet" and document["metadata"]["name"].endswith("-redis") for document in documents)
    ref = _secret_ref(_container(documents, "gateway"), "DEER_FLOW_STREAM_BRIDGE_REDIS_URL")
    if setting.startswith("redis.existingSecret="):
        assert ref == {"name": "managed-external", "key": "redis-url"}
    else:
        secret = next(document for document in documents if document.get("kind") == "Secret" and document["metadata"]["name"] == ref["name"])
        assert secret["stringData"] == {"redis-url": setting.split("=", 1)[1]}
