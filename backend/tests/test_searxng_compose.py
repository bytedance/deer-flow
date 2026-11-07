"""Offline deployment contracts for the optional private SearXNG service."""

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml
from support.compose import DOCKER, requires_docker_compose

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = REPO_ROOT / "docker" / "docker-compose.searxng.yaml"
SETTINGS_PATH = REPO_ROOT / "docker" / "searxng" / "settings.yml"


def test_searxng_publishes_only_the_loopback_default():
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    assert set(compose["services"]) == {"searxng"}
    service = compose["services"]["searxng"]
    assert service["image"] == "searxng/searxng:latest"
    assert service["ports"] == ["${BIND_HOST:-127.0.0.1}:${SEARXNG_PORT:-8088}:8080"]
    assert service["volumes"] == ["./searxng/settings.yml:/etc/searxng/settings.yml:ro"]


def test_searxng_secret_is_required_from_environment():
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    settings = yaml.safe_load(SETTINGS_PATH.read_text(encoding="utf-8"))
    secret = compose["services"]["searxng"]["environment"]["SEARXNG_SECRET"]
    assert secret.startswith("${SEARXNG_SECRET:?") and secret.endswith("}")
    assert "secret_key" not in settings.get("server", {})


def test_searxng_json_and_multiple_general_engines():
    settings = yaml.safe_load(SETTINGS_PATH.read_text(encoding="utf-8"))
    assert "json" in settings["search"]["formats"]
    assert settings["server"]["limiter"] is False
    assert settings["server"]["public_instance"] is False
    enabled = {engine["name"] for engine in settings["engines"] if engine.get("disabled") is False}
    assert len(enabled - {"duckduckgo"}) >= 4
    assert enabled == set(settings["use_default_settings"]["engines"]["keep_only"])


def test_searxng_joins_both_stack_networks():
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    networks = compose["services"]["searxng"]["networks"]
    for filename in ("docker-compose.yaml", "docker-compose-dev.yaml"):
        base = yaml.safe_load((REPO_ROOT / "docker" / filename).read_text(encoding="utf-8"))
        assert set(networks) & set(base["services"]["gateway"]["networks"])
    assert set(networks) <= set(compose["networks"])


@requires_docker_compose
@pytest.mark.parametrize("base", [None, "docker-compose.yaml", "docker-compose-dev.yaml"])
def test_real_compose_renders_searxng(base, tmp_path):
    env = {key: value for key, value in os.environ.items() if not key.startswith(("COMPOSE_", "DEER_FLOW_", "BIND_HOST", "SEARXNG_"))}
    env.update(
        SEARXNG_SECRET="test-only-secret",
        DEER_FLOW_ROOT=str(REPO_ROOT),
        DEER_FLOW_HOME=str(tmp_path),
        DEER_FLOW_CONFIG_PATH=str(REPO_ROOT / "config.example.yaml"),
        DEER_FLOW_EXTENSIONS_CONFIG_PATH=str(REPO_ROOT / "extensions_config.example.json"),
        BETTER_AUTH_SECRET="test-only-secret",
        DEER_FLOW_INTERNAL_AUTH_TOKEN="test-only-token",
    )
    command = [DOCKER, "compose", "-p", "searxng-test"]
    if base:
        command.extend(["-f", str(REPO_ROOT / "docker" / base)])
    command.extend(["-f", str(COMPOSE_PATH), "config", "--format", "json"])
    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr
    service = json.loads(result.stdout)["services"]["searxng"]
    assert service["ports"][0]["host_ip"] == "127.0.0.1"
    assert service["ports"][0]["published"] == "8088"
    assert service["environment"]["SEARXNG_SECRET"] == "test-only-secret"
    assert service["volumes"][0]["source"] == str(SETTINGS_PATH)


@requires_docker_compose
@pytest.mark.parametrize("secret", [None, ""])
def test_real_compose_rejects_missing_or_empty_secret(secret, tmp_path):
    env = dict(os.environ)
    env.pop("SEARXNG_SECRET", None)
    if secret is not None:
        env["SEARXNG_SECRET"] = secret
    # Explicit empty env file prevents a developer's .env supplying the secret.
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    result = subprocess.run(
        [DOCKER, "compose", "--env-file", str(env_file), "-f", str(COMPOSE_PATH), "config"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode != 0
    assert "SEARXNG_SECRET" in result.stderr


# searxng/searxng 2026.11.1 marks these `inactive: true` upstream (proof-of-work
# CAPTCHAs), so listing them in keep_only/engines silently loads nothing.
UPSTREAM_INACTIVE_GENERAL_ENGINES = {"mojeek", "startpage", "dogpile", "marginalia"}


def test_searxng_enables_no_upstream_inactive_engines():
    settings = yaml.safe_load(SETTINGS_PATH.read_text(encoding="utf-8"))
    listed = set(settings["use_default_settings"]["engines"]["keep_only"])
    assert not listed & UPSTREAM_INACTIVE_GENERAL_ENGINES


def _searxng_down_recipe() -> str:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    return makefile.split("\nsearxng-down:\n", 1)[1].split("\n\n", 1)[0]


def test_searxng_down_recipe_is_shell_neutral():
    # Windows runs recipes under cmd.exe, which has no `VAR=value cmd` prefix
    # assignment or `${VAR:-default}` expansion; make supplies the placeholder instead.
    recipe = _searxng_down_recipe()
    assert "SEARXNG_SECRET=" not in recipe
    assert "${" not in recipe
    assert "$${" not in recipe


@pytest.mark.skipif(os.name == "nt", reason="stub docker executable is a POSIX script")
@pytest.mark.parametrize(("secret", "expected"), [(None, "unused-for-down"), ("", "unused-for-down"), ("real-secret", "real-secret")])
def test_searxng_down_does_not_require_the_secret(tmp_path, secret, expected):
    stub = tmp_path / "docker"
    stub.write_text('#!/bin/sh\nprintf "%s|%s\\n" "$SEARXNG_SECRET" "$*"\n', encoding="utf-8")
    stub.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k != "SEARXNG_SECRET"}
    env["PATH"] = f"{tmp_path}{os.pathsep}{env['PATH']}"
    if secret is not None:
        env["SEARXNG_SECRET"] = secret
    out = subprocess.run(["make", "-s", "searxng-down"], cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=True).stdout
    assert out.strip() == f"{expected}|compose -p deer-flow-searxng -f docker/docker-compose.searxng.yaml down"
