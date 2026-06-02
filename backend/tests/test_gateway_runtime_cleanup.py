"""Regression coverage for the Gateway-owned LangGraph API runtime."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_root_makefile_no_longer_exposes_transition_gateway_targets():
    makefile = _read("Makefile")

    assert "dev-pro" not in makefile
    assert "start-pro" not in makefile
    assert "dev-daemon-pro" not in makefile
    assert "start-daemon-pro" not in makefile
    assert "docker-start-pro" not in makefile
    assert "up-pro" not in makefile
    assert not re.search(r"serve\.sh .*--gateway", makefile)
    assert "docker.sh start --gateway" not in makefile
    assert "deploy.sh --gateway" not in makefile


def test_service_launchers_always_use_gateway_runtime():
    operational_files = {
        "scripts/serve.sh": _read("scripts/serve.sh"),
        "scripts/docker.sh": _read("scripts/docker.sh"),
        "scripts/deploy.sh": _read("scripts/deploy.sh"),
        "docker/docker-compose-dev.yaml": _read("docker/docker-compose-dev.yaml"),
        "docker/docker-compose.yaml": _read("docker/docker-compose.yaml"),
    }

    for path, content in operational_files.items():
        assert "start --gateway" not in content, path
        assert "deploy.sh --gateway" not in content, path
        assert "langgraph dev" not in content, path
        assert "LANGGRAPH_UPSTREAM" not in content, path
        assert "LANGGRAPH_REWRITE" not in content, path


def test_nginx_routes_official_langgraph_prefix_to_gateway_api():
    for path in ("docker/nginx/nginx.local.conf", "docker/nginx/nginx.conf"):
        content = _read(path)

        assert "/api/langgraph-compat" not in content
        assert "proxy_pass http://langgraph" not in content
        assert "rewrite ^/api/langgraph/(.*) /api/$1 break;" in content
        assert "proxy_pass http://gateway" in content or "proxy_pass http://$gateway_upstream" in content


def test_nginx_defers_cors_to_gateway_allowlist():
    for path in ("docker/nginx/nginx.local.conf", "docker/nginx/nginx.conf"):
        content = _read(path)

        assert "Access-Control-Allow-Origin" not in content
        assert "Access-Control-Allow-Methods" not in content
        assert "Access-Control-Allow-Headers" not in content
        assert "Access-Control-Allow-Credentials" not in content
        assert "proxy_hide_header 'Access-Control-Allow-" not in content
        assert "if ($request_method = 'OPTIONS')" not in content


def test_gateway_cors_configuration_uses_gateway_allowlist():
    gateway_config = _read("backend/app/gateway/config.py")
    gateway_app = _read("backend/app/gateway/app.py")
    csrf_middleware = _read("backend/app/gateway/csrf_middleware.py")

    assert not re.search(r"(?<!GATEWAY_)[\"']CORS_ORIGINS[\"']", gateway_config)
    assert "cors_origins" not in gateway_config
    assert "get_configured_cors_origins" in gateway_app
    assert "GATEWAY_CORS_ORIGINS" in csrf_middleware


def test_frontend_rewrites_langgraph_prefix_to_gateway():
    next_config = _read("frontend/next.config.js")
    api_client = _read("frontend/src/core/api/api-client.ts")

    assert "DEER_FLOW_INTERNAL_LANGGRAPH_BASE_URL" not in next_config
    assert "http://127.0.0.1:2024" not in next_config
    assert "langgraph-compat" not in api_client


def test_smoke_test_docs_do_not_expect_standalone_langgraph_server():
    smoke_files = {
        ".agent/skills/smoke-test/SKILL.md": _read(".agent/skills/smoke-test/SKILL.md"),
        ".agent/skills/smoke-test/references/SOP.md": _read(".agent/skills/smoke-test/references/SOP.md"),
        ".agent/skills/smoke-test/references/troubleshooting.md": _read(".agent/skills/smoke-test/references/troubleshooting.md"),
        ".agent/skills/smoke-test/scripts/check_local_env.sh": _read(".agent/skills/smoke-test/scripts/check_local_env.sh"),
        ".agent/skills/smoke-test/scripts/deploy_local.sh": _read(".agent/skills/smoke-test/scripts/deploy_local.sh"),
        ".agent/skills/smoke-test/scripts/health_check.sh": _read(".agent/skills/smoke-test/scripts/health_check.sh"),
        ".agent/skills/smoke-test/templates/report.local.template.md": _read(".agent/skills/smoke-test/templates/report.local.template.md"),
        ".agent/skills/smoke-test/templates/report.docker.template.md": _read(".agent/skills/smoke-test/templates/report.docker.template.md"),
    }

    for path, content in smoke_files.items():
        assert "localhost:2024" not in content, path
        assert "127.0.0.1:2024" not in content, path
        assert "deer-flow-langgraph" not in content, path
        assert "langgraph.log" not in content, path
        assert "LangGraph service" not in content, path
        assert "langgraph dev" not in content, path


def test_gateway_runtime_docs_do_not_reference_transition_modes():
    docs = {
        "backend/docs/AUTH_UPGRADE.md": _read("backend/docs/AUTH_UPGRADE.md"),
        "backend/docs/AUTH_TEST_DOCKER_GAP.md": _read("backend/docs/AUTH_TEST_DOCKER_GAP.md"),
        "docs/CODE_CHANGE_SUMMARY_BY_FILE.md": _read("docs/CODE_CHANGE_SUMMARY_BY_FILE.md"),
    }

    for path, content in docs.items():
        assert "make dev-pro" not in content, path
        assert "./scripts/deploy.sh --gateway" not in content, path
        assert "docker compose --profile gateway" not in content, path
        assert "`/api/langgraph/*` → LangGraph" not in content, path
