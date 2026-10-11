"""Regressions for MCP cache handling in ``get_available_tools()``."""

import json
import logging
from types import SimpleNamespace

from deerflow.tools.tools import get_available_tools


def _make_config():
    return SimpleNamespace(
        tools=[
            SimpleNamespace(name="bash", group="bash", use="deerflow.sandbox.tools:bash_tool"),
            SimpleNamespace(name="ls", group="file:read", use="tests:ls_tool"),
        ],
        models=[],
        sandbox=SimpleNamespace(use="deerflow.sandbox.local:LocalSandboxProvider", allow_host_bash=False),
        tool_search=SimpleNamespace(enabled=False),
        get_model_config=lambda name: None,
    )


def test_tool_assembly_refreshes_cache_when_no_server_is_enabled(monkeypatch):
    from deerflow.config.extensions_config import ExtensionsConfig

    monkeypatch.setattr("deerflow.tools.tools.get_app_config", lambda: _make_config())
    monkeypatch.setattr(
        "deerflow.tools.tools.resolve_variable",
        lambda use, _: SimpleNamespace(name="bash" if "bash" in use else "ls"),
    )
    monkeypatch.setattr(
        ExtensionsConfig,
        "from_file",
        classmethod(lambda cls, config_path=None: ExtensionsConfig(mcp_servers={}, skills={})),
    )

    calls: list[str] = []
    monkeypatch.setattr(
        "deerflow.mcp.cache.refresh_mcp_cache_if_active",
        lambda: calls.append("refresh") or False,
    )

    get_available_tools(include_mcp=True, subagent_enabled=False)

    assert calls == ["refresh"]


def test_tool_assembly_does_not_leak_credentials_on_malformed_config(monkeypatch, tmp_path, caplog):
    """A malformed config must not echo resolved $VAR secrets into the log."""
    cfg = tmp_path / "extensions_config.json"
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(cfg))
    monkeypatch.setenv("MCP_SECRET", "TOPSECRET123")
    cfg.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "srv1": {"enabled": True, "type": "stdio", "command": "npx", "headers": "$MCP_SECRET"},
                },
                "skills": {},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("deerflow.tools.tools.get_app_config", lambda: _make_config())
    monkeypatch.setattr(
        "deerflow.tools.tools.resolve_variable",
        lambda use, _: SimpleNamespace(name="bash" if "bash" in use else "ls"),
    )

    with caplog.at_level(logging.WARNING):
        get_available_tools(include_mcp=True, subagent_enabled=False)

    assert "TOPSECRET123" not in caplog.text
    mcp_records = [record for record in caplog.records if "MCP" in record.getMessage()]
    assert any("Failed to load MCP extensions config" in record.getMessage() for record in mcp_records)
    assert all(record.exc_info is None for record in mcp_records)


def test_tool_assembly_logs_diagnostics_for_non_config_failures(monkeypatch, caplog):
    """Only config-load failures are sanitized; other MCP errors keep diagnostics."""
    from deerflow.config.extensions_config import ExtensionsConfig

    monkeypatch.setattr("deerflow.tools.tools.get_app_config", lambda: _make_config())
    monkeypatch.setattr(
        "deerflow.tools.tools.resolve_variable",
        lambda use, _: SimpleNamespace(name="bash" if "bash" in use else "ls"),
    )
    monkeypatch.setattr(
        ExtensionsConfig,
        "from_file",
        classmethod(
            lambda cls, config_path=None: ExtensionsConfig.model_validate(
                {
                    "mcpServers": {"srv1": {"enabled": True, "type": "stdio", "command": "npx"}},
                    "skills": {},
                }
            )
        ),
    )

    def _boom():
        raise RuntimeError("retired pool close failed: pipe still open")

    monkeypatch.setattr("deerflow.mcp.cache.get_cached_mcp_tools", _boom)

    with caplog.at_level(logging.ERROR):
        get_available_tools(include_mcp=True, subagent_enabled=False)

    assert "retired pool close failed: pipe still open" in caplog.text
    assert any(record.exc_info is not None for record in caplog.records)
