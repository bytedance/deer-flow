from __future__ import annotations

import json
import re
from pathlib import Path

from app.gateway.routers.mcp import (
    McpConfigUpdateRequest,
    McpServerConfigResponse,
    _validate_mcp_update_request,
)
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.skills.parser import parse_skill_file
from deerflow.skills.types import SkillCategory

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_CONFIG = REPO_ROOT / "extensions_config.example.json"
SKILL_DIR = REPO_ROOT / "skills" / "public" / "research-report-audit"


def _example_server() -> dict:
    payload = json.loads(EXAMPLE_CONFIG.read_text(encoding="utf-8"))
    return payload["mcpServers"]["research_audit"]


def test_research_audit_example_is_disabled_and_pinned() -> None:
    server = _example_server()

    assert server["enabled"] is False
    assert server["type"] == "stdio"
    assert server["command"] == "uvx"
    assert server["tool_name_prefix"] is True
    assert len(server["args"]) == 3
    assert server["args"][0] == "--from"
    assert server["args"][-1] == "adversarial-research-audit-mcp"
    assert re.fullmatch(
        r"git\+https://github\.com/chenhz01/adversarial-research-audit\.git@[0-9a-f]{40}",
        server["args"][1],
    )
    assert server["routing"]["mode"] == "prefer"
    assert {"audit", "report", "coverage", "citation"} <= set(server["routing"]["keywords"])

    ExtensionsConfig.model_validate(json.loads(EXAMPLE_CONFIG.read_text(encoding="utf-8")))


def test_research_audit_example_passes_gateway_stdio_policy(monkeypatch) -> None:
    monkeypatch.delenv("DEER_FLOW_MCP_STDIO_COMMAND_ALLOWLIST", raising=False)
    request = McpConfigUpdateRequest(mcp_servers={"research_audit": McpServerConfigResponse.model_validate(_example_server())})

    _validate_mcp_update_request(request)


def test_research_report_audit_skill_parses_without_restricting_report_tools() -> None:
    skill = parse_skill_file(
        SKILL_DIR / "SKILL.md",
        SkillCategory.PUBLIC,
        Path("research-report-audit"),
    )

    assert skill is not None
    assert skill.name == "research-report-audit"
    assert skill.allowed_tools is None
    assert "explicitly" in skill.description.lower()
    assert "audit" in skill.description.lower()


def test_research_report_audit_skill_pins_workflow_contract() -> None:
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")

    assert "research_audit_audit_report" in text
    assert "verify_sources" in text
    assert "at most twice" in text
    assert "Never invent" in text
    assert "<report-stem>.audit.json" in text
    assert "UNAUDITED" in text
    assert "DEGRADED" in text
