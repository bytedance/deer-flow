"""Tests for the built-in ACP invocation tool."""

import asyncio
import contextlib
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from deerflow.config.acp_config import ACPAgentConfig
from deerflow.config.extensions_config import ExtensionsConfig, McpServerConfig, reset_extensions_config, set_extensions_config
from deerflow.tools.builtins.invoke_acp_agent_tool import (
    _build_acp_mcp_servers,
    _build_mcp_servers,
    _build_permission_response,
    _format_invocation_error,
    _get_work_dir,
    _resolve_agent_command,
    build_invoke_acp_agent_tool,
)
from deerflow.tools.tools import get_available_tools


def test_build_mcp_servers_filters_disabled_and_maps_transports():
    set_extensions_config(ExtensionsConfig(mcp_servers={"stale": McpServerConfig(enabled=True, type="stdio", command="echo")}, skills={}))
    fresh_config = ExtensionsConfig(
        mcp_servers={
            "stdio": McpServerConfig(enabled=True, type="stdio", command="npx", args=["srv"]),
            "http": McpServerConfig(enabled=True, type="http", url="https://example.com/mcp"),
            "disabled": McpServerConfig(enabled=False, type="stdio", command="echo"),
        },
        skills={},
    )
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        "deerflow.config.extensions_config.ExtensionsConfig.from_file",
        classmethod(lambda cls: fresh_config),
    )

    try:
        assert _build_mcp_servers() == {
            "stdio": {"transport": "stdio", "command": "npx", "args": ["srv"]},
            "http": {"transport": "http", "url": "https://example.com/mcp"},
        }
    finally:
        monkeypatch.undo()
        reset_extensions_config()


def test_build_acp_mcp_servers_formats_list_payload():
    set_extensions_config(ExtensionsConfig(mcp_servers={"stale": McpServerConfig(enabled=True, type="stdio", command="echo")}, skills={}))
    fresh_config = ExtensionsConfig(
        mcp_servers={
            "stdio": McpServerConfig(enabled=True, type="stdio", command="npx", args=["srv"], env={"FOO": "bar"}),
            "http": McpServerConfig(enabled=True, type="http", url="https://example.com/mcp", headers={"Authorization": "Bearer token"}),
            "disabled": McpServerConfig(enabled=False, type="stdio", command="echo"),
        },
        skills={},
    )
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        "deerflow.config.extensions_config.ExtensionsConfig.from_file",
        classmethod(lambda cls: fresh_config),
    )

    try:
        assert _build_acp_mcp_servers() == [
            {
                "name": "stdio",
                "type": "stdio",
                "command": "npx",
                "args": ["srv"],
                "env": [{"name": "FOO", "value": "bar"}],
            },
            {
                "name": "http",
                "type": "http",
                "url": "https://example.com/mcp",
                "headers": [{"name": "Authorization", "value": "Bearer token"}],
            },
        ]
    finally:
        monkeypatch.undo()
        reset_extensions_config()


def test_build_permission_response_prefers_allow_once():
    response = _build_permission_response(
        [
            SimpleNamespace(kind="reject_once", optionId="deny"),
            SimpleNamespace(kind="allow_always", optionId="always"),
            SimpleNamespace(kind="allow_once", optionId="once"),
        ],
        auto_approve=True,
    )

    assert response.outcome.outcome == "selected"
    assert response.outcome.option_id == "once"


def test_build_permission_response_denies_when_no_allow_option():
    response = _build_permission_response(
        [
            SimpleNamespace(kind="reject_once", optionId="deny"),
            SimpleNamespace(kind="reject_always", optionId="deny-forever"),
        ],
        auto_approve=True,
    )

    assert response.outcome.outcome == "cancelled"


def test_build_permission_response_denies_when_auto_approve_false():
    """P1.2: When auto_approve=False, permission is always denied regardless of options."""
    response = _build_permission_response(
        [
            SimpleNamespace(kind="allow_once", optionId="once"),
            SimpleNamespace(kind="allow_always", optionId="always"),
        ],
        auto_approve=False,
    )

    assert response.outcome.outcome == "cancelled"


def test_missing_mcode_command_returns_install_and_login_guidance():
    result = _format_invocation_error("mcode", "mcode", FileNotFoundError())

    assert "npm install --global @minimax-ai/code" in result
    assert "mcode login" in result
    assert "restart DeerFlow" in result


@pytest.mark.anyio
async def test_build_invoke_tool_description_and_unknown_agent_error():
    tool = build_invoke_acp_agent_tool(
        {
            "codex": ACPAgentConfig(command="codex-acp", description="Codex CLI"),
            "claude_code": ACPAgentConfig(command="claude-code-acp", description="Claude Code"),
        }
    )

    assert "Available agents:" in tool.description
    assert "- codex: Codex CLI" in tool.description
    assert "- claude_code: Claude Code" in tool.description
    assert "Do NOT include /mnt/user-data paths" in tool.description
    assert "/mnt/acp-workspace/" in tool.description

    result = await tool.coroutine(agent="missing", prompt="do work")
    assert result == "Error: Unknown agent 'missing'. Available: codex, claude_code"


def test_get_work_dir_uses_base_dir_when_no_thread_id(monkeypatch, tmp_path):
    """_get_work_dir(None) uses {base_dir}/acp-workspace/ (global fallback)."""
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    result = _get_work_dir(None)
    expected = tmp_path / "acp-workspace"
    assert result == str(expected)
    assert expected.exists()


def test_get_work_dir_uses_per_thread_path_when_thread_id_given(monkeypatch, tmp_path):
    """P1.1: _get_work_dir(thread_id) uses {base_dir}/threads/{thread_id}/acp-workspace/."""
    from deerflow.config import paths as paths_module
    from deerflow.runtime import user_context as uc_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    monkeypatch.setattr(uc_module, "get_effective_user_id", lambda: None)
    result = _get_work_dir("thread-abc-123")
    expected = tmp_path / "threads" / "thread-abc-123" / "acp-workspace"
    assert result == str(expected)
    assert expected.exists()


def test_get_work_dir_falls_back_to_global_for_invalid_thread_id(monkeypatch, tmp_path):
    """P1.1: Invalid thread_id (e.g. path traversal chars) falls back to global workspace."""
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    result = _get_work_dir("../../evil")
    expected = tmp_path / "acp-workspace"
    assert result == str(expected)
    assert expected.exists()


@pytest.mark.anyio
async def test_invoke_acp_agent_uses_fixed_acp_workspace(monkeypatch, tmp_path):
    """ACP agent uses {base_dir}/acp-workspace/ when no thread_id is available (no config)."""
    from deerflow.config import paths as paths_module

    # An empty PATH directory keeps the configured command unresolvable, so the
    # spawn assertion below checks the configuration rather than the host PATH.
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))

    monkeypatch.setattr(
        "deerflow.config.extensions_config.ExtensionsConfig.from_file",
        classmethod(
            lambda cls: ExtensionsConfig(
                mcp_servers={"github": McpServerConfig(enabled=True, type="stdio", command="npx", args=["github-mcp"])},
                skills={},
            )
        ),
    )

    captured: dict[str, object] = {}

    class DummyClient:
        def __init__(self) -> None:
            self._chunks: list[str] = []

        @property
        def collected_text(self) -> str:
            return "".join(self._chunks)

        async def session_update(self, session_id: str, update, **kwargs) -> None:
            if hasattr(update, "content") and hasattr(update.content, "text"):
                self._chunks.append(update.content.text)

        async def request_permission(self, options, session_id: str, tool_call, **kwargs):
            raise AssertionError("request_permission should not be called in this test")

    class DummyConn:
        async def initialize(self, **kwargs):
            captured["initialize"] = kwargs

        async def new_session(self, **kwargs):
            captured["new_session"] = kwargs
            return SimpleNamespace(session_id="session-1")

        async def prompt(self, **kwargs):
            captured["prompt"] = kwargs
            client = captured["client"]
            await client.session_update(
                "session-1",
                SimpleNamespace(
                    session_update="agent_thought_chunk",
                    content=text_content_block("internal reasoning"),
                ),
            )
            await client.session_update(
                "session-1",
                SimpleNamespace(
                    session_update="agent_message_chunk",
                    content=text_content_block("ACP result"),
                ),
            )

    class DummyProcessContext:
        def __init__(self, client, cmd, *args, cwd):
            captured["client"] = client
            captured["spawn"] = {"cmd": cmd, "args": list(args), "cwd": cwd}

        async def __aenter__(self):
            return DummyConn(), object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class DummyRequestError(Exception):
        @staticmethod
        def method_not_found(method: str):
            return DummyRequestError(method)

    monkeypatch.setitem(
        sys.modules,
        "acp",
        SimpleNamespace(
            PROTOCOL_VERSION="2026-03-24",
            Client=DummyClient,
            RequestError=DummyRequestError,
            spawn_agent_process=lambda client, cmd, *args, env=None, cwd: DummyProcessContext(client, cmd, *args, cwd=cwd),
            text_block=lambda text: {"type": "text", "text": text},
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "acp.schema",
        SimpleNamespace(
            ClientCapabilities=lambda: {"supports": []},
            Implementation=lambda **kwargs: kwargs,
            TextContentBlock=type(
                "TextContentBlock",
                (),
                {"__init__": lambda self, text: setattr(self, "text", text)},
            ),
        ),
    )
    text_content_block = sys.modules["acp.schema"].TextContentBlock

    expected_cwd = str(tmp_path / "acp-workspace")

    tool = build_invoke_acp_agent_tool(
        {
            "codex": ACPAgentConfig(
                command="codex-acp",
                args=["--json"],
                description="Codex CLI",
                model="gpt-5-codex",
            )
        }
    )

    try:
        result = await tool.coroutine(
            agent="codex",
            prompt="Implement the fix",
        )
    finally:
        sys.modules.pop("acp", None)
        sys.modules.pop("acp.schema", None)

    assert result == "ACP result"
    assert captured["spawn"] == {"cmd": "codex-acp", "args": ["--json"], "cwd": expected_cwd}
    assert captured["new_session"] == {
        "cwd": expected_cwd,
        "mcp_servers": [
            {
                "name": "github",
                "type": "stdio",
                "command": "npx",
                "args": ["github-mcp"],
                "env": [],
            }
        ],
        "model": "gpt-5-codex",
    }
    assert captured["prompt"] == {
        "session_id": "session-1",
        "prompt": [{"type": "text", "text": "Implement the fix"}],
    }


@pytest.mark.anyio
async def test_invoke_acp_agent_uses_per_thread_workspace_when_thread_id_in_config(monkeypatch, tmp_path):
    """P1.1: When thread_id is in the RunnableConfig, ACP agent uses per-thread workspace."""
    from deerflow.config import paths as paths_module
    from deerflow.runtime import user_context as uc_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    monkeypatch.setattr(uc_module, "get_effective_user_id", lambda: None)

    monkeypatch.setattr(
        "deerflow.config.extensions_config.ExtensionsConfig.from_file",
        classmethod(lambda cls: ExtensionsConfig(mcp_servers={}, skills={})),
    )

    captured: dict[str, object] = {}

    class DummyClient:
        def __init__(self) -> None:
            self._chunks: list[str] = []

        @property
        def collected_text(self) -> str:
            return "".join(self._chunks)

        async def session_update(self, session_id, update, **kwargs):
            pass

        async def request_permission(self, options, session_id, tool_call, **kwargs):
            raise AssertionError("should not be called")

    class DummyConn:
        async def initialize(self, **kwargs):
            pass

        async def new_session(self, **kwargs):
            captured["new_session"] = kwargs
            return SimpleNamespace(session_id="s1")

        async def prompt(self, **kwargs):
            pass

    class DummyProcessContext:
        def __init__(self, client, cmd, *args, cwd):
            captured["cwd"] = cwd

        async def __aenter__(self):
            return DummyConn(), object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class DummyRequestError(Exception):
        @staticmethod
        def method_not_found(method):
            return DummyRequestError(method)

    monkeypatch.setitem(
        sys.modules,
        "acp",
        SimpleNamespace(
            PROTOCOL_VERSION="2026-03-24",
            Client=DummyClient,
            RequestError=DummyRequestError,
            spawn_agent_process=lambda client, cmd, *args, env=None, cwd: DummyProcessContext(client, cmd, *args, cwd=cwd),
            text_block=lambda text: {"type": "text", "text": text},
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "acp.schema",
        SimpleNamespace(
            ClientCapabilities=lambda: {},
            Implementation=lambda **kwargs: kwargs,
            TextContentBlock=type("TextContentBlock", (), {"__init__": lambda self, text: setattr(self, "text", text)}),
        ),
    )

    thread_id = "thread-xyz-789"
    expected_cwd = str(tmp_path / "threads" / thread_id / "acp-workspace")

    tool = build_invoke_acp_agent_tool({"codex": ACPAgentConfig(command="codex-acp", description="Codex CLI")})

    try:
        await tool.coroutine(
            agent="codex",
            prompt="Do something",
            config={"configurable": {"thread_id": thread_id}},
        )
    finally:
        sys.modules.pop("acp", None)
        sys.modules.pop("acp.schema", None)

    assert captured["cwd"] == expected_cwd


@pytest.mark.anyio
async def test_invoke_acp_agent_passes_env_to_spawn(monkeypatch, tmp_path):
    """env map in ACPAgentConfig is passed to spawn_agent_process; $VAR values are resolved."""
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    monkeypatch.setattr(
        "deerflow.config.extensions_config.ExtensionsConfig.from_file",
        classmethod(lambda cls: ExtensionsConfig(mcp_servers={}, skills={})),
    )
    monkeypatch.setenv("TEST_OPENAI_KEY", "sk-from-env")

    captured: dict[str, object] = {}

    class DummyClient:
        def __init__(self) -> None:
            self._chunks: list[str] = []

        @property
        def collected_text(self) -> str:
            return ""

        async def session_update(self, session_id, update, **kwargs):
            pass

        async def request_permission(self, options, session_id, tool_call, **kwargs):
            raise AssertionError("should not be called")

    class DummyConn:
        async def initialize(self, **kwargs):
            pass

        async def new_session(self, **kwargs):
            return SimpleNamespace(session_id="s1")

        async def prompt(self, **kwargs):
            pass

    class DummyProcessContext:
        def __init__(self, client, cmd, *args, env=None, cwd):
            captured["env"] = env

        async def __aenter__(self):
            return DummyConn(), object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class DummyRequestError(Exception):
        @staticmethod
        def method_not_found(method):
            return DummyRequestError(method)

    monkeypatch.setitem(
        sys.modules,
        "acp",
        SimpleNamespace(
            PROTOCOL_VERSION="2026-03-24",
            Client=DummyClient,
            RequestError=DummyRequestError,
            spawn_agent_process=lambda client, cmd, *args, env=None, cwd: DummyProcessContext(client, cmd, *args, env=env, cwd=cwd),
            text_block=lambda text: {"type": "text", "text": text},
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "acp.schema",
        SimpleNamespace(
            ClientCapabilities=lambda: {},
            Implementation=lambda **kwargs: kwargs,
            TextContentBlock=type("TextContentBlock", (), {"__init__": lambda self, text: setattr(self, "text", text)}),
        ),
    )

    tool = build_invoke_acp_agent_tool(
        {
            "codex": ACPAgentConfig(
                command="codex-acp",
                description="Codex CLI",
                env={"OPENAI_API_KEY": "$TEST_OPENAI_KEY", "FOO": "bar"},
            )
        }
    )

    try:
        await tool.coroutine(agent="codex", prompt="Do something")
    finally:
        sys.modules.pop("acp", None)
        sys.modules.pop("acp.schema", None)

    assert captured["env"] == {"OPENAI_API_KEY": "sk-from-env", "FOO": "bar"}


@pytest.mark.anyio
async def test_invoke_acp_agent_skips_invalid_mcp_servers(monkeypatch, tmp_path, caplog):
    """Invalid MCP config should be logged and skipped instead of failing ACP invocation."""
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    monkeypatch.setattr(
        "deerflow.tools.builtins.invoke_acp_agent_tool._build_acp_mcp_servers",
        lambda: (_ for _ in ()).throw(ValueError("missing command")),
    )

    captured: dict[str, object] = {}

    class DummyClient:
        def __init__(self) -> None:
            self._chunks: list[str] = []

        @property
        def collected_text(self) -> str:
            return ""

        async def session_update(self, session_id, update, **kwargs):
            pass

        async def request_permission(self, options, session_id, tool_call, **kwargs):
            raise AssertionError("should not be called")

    class DummyConn:
        async def initialize(self, **kwargs):
            pass

        async def new_session(self, **kwargs):
            captured["new_session"] = kwargs
            return SimpleNamespace(session_id="s1")

        async def prompt(self, **kwargs):
            pass

    class DummyProcessContext:
        def __init__(self, client, cmd, *args, env=None, cwd=None):
            captured["spawn"] = {"cmd": cmd, "args": list(args), "env": env, "cwd": cwd}

        async def __aenter__(self):
            return DummyConn(), object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class DummyRequestError(Exception):
        @staticmethod
        def method_not_found(method):
            return DummyRequestError(method)

    monkeypatch.setitem(
        sys.modules,
        "acp",
        SimpleNamespace(
            PROTOCOL_VERSION="2026-03-24",
            Client=DummyClient,
            RequestError=DummyRequestError,
            spawn_agent_process=lambda client, cmd, *args, env=None, cwd: DummyProcessContext(client, cmd, *args, env=env, cwd=cwd),
            text_block=lambda text: {"type": "text", "text": text},
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "acp.schema",
        SimpleNamespace(
            ClientCapabilities=lambda: {},
            Implementation=lambda **kwargs: kwargs,
            TextContentBlock=type("TextContentBlock", (), {"__init__": lambda self, text: setattr(self, "text", text)}),
        ),
    )

    tool = build_invoke_acp_agent_tool({"codex": ACPAgentConfig(command="codex-acp", description="Codex CLI")})
    caplog.set_level("WARNING")

    try:
        await tool.coroutine(agent="codex", prompt="Do something")
    finally:
        sys.modules.pop("acp", None)
        sys.modules.pop("acp.schema", None)

    assert captured["new_session"]["mcp_servers"] == []
    assert "continuing without MCP servers" in caplog.text
    assert "missing command" in caplog.text


@pytest.mark.anyio
async def test_invoke_acp_agent_passes_none_env_when_not_configured(monkeypatch, tmp_path):
    """When env is empty, None is passed to spawn_agent_process (subprocess inherits parent env)."""
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    monkeypatch.setattr(
        "deerflow.config.extensions_config.ExtensionsConfig.from_file",
        classmethod(lambda cls: ExtensionsConfig(mcp_servers={}, skills={})),
    )

    captured: dict[str, object] = {}

    class DummyClient:
        def __init__(self) -> None:
            self._chunks: list[str] = []

        @property
        def collected_text(self) -> str:
            return ""

        async def session_update(self, session_id, update, **kwargs):
            pass

        async def request_permission(self, options, session_id, tool_call, **kwargs):
            raise AssertionError("should not be called")

    class DummyConn:
        async def initialize(self, **kwargs):
            pass

        async def new_session(self, **kwargs):
            return SimpleNamespace(session_id="s1")

        async def prompt(self, **kwargs):
            pass

    class DummyProcessContext:
        def __init__(self, client, cmd, *args, env=None, cwd):
            captured["env"] = env

        async def __aenter__(self):
            return DummyConn(), object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class DummyRequestError(Exception):
        @staticmethod
        def method_not_found(method):
            return DummyRequestError(method)

    monkeypatch.setitem(
        sys.modules,
        "acp",
        SimpleNamespace(
            PROTOCOL_VERSION="2026-03-24",
            Client=DummyClient,
            RequestError=DummyRequestError,
            spawn_agent_process=lambda client, cmd, *args, env=None, cwd: DummyProcessContext(client, cmd, *args, env=env, cwd=cwd),
            text_block=lambda text: {"type": "text", "text": text},
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "acp.schema",
        SimpleNamespace(
            ClientCapabilities=lambda: {},
            Implementation=lambda **kwargs: kwargs,
            TextContentBlock=type("TextContentBlock", (), {"__init__": lambda self, text: setattr(self, "text", text)}),
        ),
    )

    tool = build_invoke_acp_agent_tool({"codex": ACPAgentConfig(command="codex-acp", description="Codex CLI")})

    try:
        await tool.coroutine(agent="codex", prompt="Do something")
    finally:
        sys.modules.pop("acp", None)
        sys.modules.pop("acp.schema", None)

    assert captured["env"] is None


def test_get_available_tools_includes_invoke_acp_agent_when_agents_configured(monkeypatch):
    from deerflow.config.acp_config import load_acp_config_from_dict

    load_acp_config_from_dict(
        {
            "codex": {
                "command": "codex-acp",
                "args": [],
                "description": "Codex CLI",
            }
        }
    )

    fake_config = SimpleNamespace(
        tools=[],
        models=[],
        tool_search=SimpleNamespace(enabled=False),
        get_model_config=lambda name: None,
    )
    monkeypatch.setattr("deerflow.tools.tools.get_app_config", lambda: fake_config)
    monkeypatch.setattr(
        "deerflow.config.extensions_config.ExtensionsConfig.from_file",
        classmethod(lambda cls: ExtensionsConfig(mcp_servers={}, skills={})),
    )

    tools = get_available_tools(include_mcp=True, subagent_enabled=False)
    assert "invoke_acp_agent" in [tool.name for tool in tools]

    load_acp_config_from_dict({})


def test_get_available_tools_sync_invoke_acp_agent_preserves_thread_workspace(monkeypatch, tmp_path):
    from deerflow.config import paths as paths_module
    from deerflow.runtime import user_context as uc_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    monkeypatch.setattr(uc_module, "get_effective_user_id", lambda: None)
    monkeypatch.setattr(
        "deerflow.config.extensions_config.ExtensionsConfig.from_file",
        classmethod(lambda cls: ExtensionsConfig(mcp_servers={}, skills={})),
    )
    monkeypatch.setattr("deerflow.tools.tools.is_host_bash_allowed", lambda config=None: True)

    captured: dict[str, object] = {}

    class DummyClient:
        @property
        def collected_text(self) -> str:
            return "ok"

        async def session_update(self, session_id, update, **kwargs):
            pass

        async def request_permission(self, options, session_id, tool_call, **kwargs):
            raise AssertionError("should not be called")

    class DummyConn:
        async def initialize(self, **kwargs):
            pass

        async def new_session(self, **kwargs):
            return SimpleNamespace(session_id="s1")

        async def prompt(self, **kwargs):
            pass

    class DummyProcessContext:
        def __init__(self, client, cmd, *args, env=None, cwd):
            captured["cwd"] = cwd

        async def __aenter__(self):
            return DummyConn(), object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setitem(
        sys.modules,
        "acp",
        SimpleNamespace(
            PROTOCOL_VERSION="2026-03-24",
            Client=DummyClient,
            spawn_agent_process=lambda client, cmd, *args, env=None, cwd: DummyProcessContext(client, cmd, *args, env=env, cwd=cwd),
            text_block=lambda text: {"type": "text", "text": text},
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "acp.schema",
        SimpleNamespace(
            ClientCapabilities=lambda: {},
            Implementation=lambda **kwargs: kwargs,
            TextContentBlock=type("TextContentBlock", (), {"__init__": lambda self, text: setattr(self, "text", text)}),
        ),
    )

    explicit_config = SimpleNamespace(
        tools=[],
        models=[],
        tool_search=SimpleNamespace(enabled=False),
        skill_evolution=SimpleNamespace(enabled=False),
        sandbox=SimpleNamespace(),
        get_model_config=lambda name: None,
        acp_agents={"codex": ACPAgentConfig(command="codex-acp", description="Codex CLI")},
    )
    tools = get_available_tools(include_mcp=False, subagent_enabled=False, app_config=explicit_config)
    tool = next(tool for tool in tools if tool.name == "invoke_acp_agent")

    thread_id = "thread-sync-123"
    tool.invoke(
        {"agent": "codex", "prompt": "Do something"},
        config={"configurable": {"thread_id": thread_id}},
    )

    assert captured["cwd"] == str(tmp_path / "threads" / thread_id / "acp-workspace")


def test_get_available_tools_uses_explicit_app_config_for_acp_agents(monkeypatch):
    explicit_agents = {"codex": ACPAgentConfig(command="codex-acp", description="Codex CLI")}
    explicit_config = SimpleNamespace(
        tools=[],
        models=[],
        tool_search=SimpleNamespace(enabled=False),
        skill_evolution=SimpleNamespace(enabled=False),
        get_model_config=lambda name: None,
        acp_agents=explicit_agents,
    )
    sentinel_tool = SimpleNamespace(name="invoke_acp_agent")
    captured: dict[str, object] = {}

    def fail_get_acp_agents():
        raise AssertionError("ambient get_acp_agents() must not be used when app_config is explicit")

    def fake_build_invoke_acp_agent_tool(agents):
        captured["agents"] = agents
        return sentinel_tool

    monkeypatch.setattr("deerflow.tools.tools.is_host_bash_allowed", lambda config=None: True)
    monkeypatch.setattr("deerflow.config.acp_config.get_acp_agents", fail_get_acp_agents)
    monkeypatch.setattr("deerflow.tools.builtins.invoke_acp_agent_tool.build_invoke_acp_agent_tool", fake_build_invoke_acp_agent_tool)

    tools = get_available_tools(include_mcp=False, subagent_enabled=False, app_config=explicit_config)

    assert captured["agents"] is explicit_agents
    assert "invoke_acp_agent" in [tool.name for tool in tools]


# A real ACP subprocess can stop responding at any protocol phase. Keep the
# SDK's transport and cleanup intact so these tests detect leaked child processes.
_ACP_AGENT_SCRIPT = """\
import asyncio
import sys
from pathlib import Path

import acp
from acp.schema import InitializeResponse, NewSessionResponse, PromptResponse


class _TestAgent:
    def on_connect(self, conn):
        self._conn = conn

    async def _enter_phase(self, phase):
        Path(sys.argv[3]).write_text(phase, encoding="utf-8")
        if phase == "prompt":
            await self._conn.session_update(session_id="test-session", update=acp.update_agent_thought_text(phase))
        if phase == sys.argv[1]:
            await asyncio.Event().wait()
        delay = float(sys.argv[2])
        if delay:
            await asyncio.sleep(delay)

    async def initialize(self, protocol_version, client_capabilities=None, client_info=None, **kwargs):
        await self._enter_phase("initialize")
        return InitializeResponse(protocol_version=protocol_version)

    async def new_session(self, cwd, additional_directories=None, mcp_servers=None, **kwargs):
        await self._enter_phase("new_session")
        return NewSessionResponse(session_id="test-session")

    async def prompt(self, session_id, prompt, **kwargs):
        await self._enter_phase("prompt")
        return PromptResponse(stop_reason="end_turn")


asyncio.run(acp.run_agent(_TestAgent()))
"""


@pytest.fixture
def acp_subprocess_tool(monkeypatch, tmp_path):
    import acp as acp_module

    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    monkeypatch.setattr(
        "deerflow.config.extensions_config.ExtensionsConfig.from_file",
        classmethod(lambda cls: ExtensionsConfig(mcp_servers={}, skills={})),
    )
    script_path = tmp_path / "test_acp_agent.py"
    script_path.write_text(_ACP_AGENT_SCRIPT, encoding="utf-8")
    phase_path = tmp_path / "phase.txt"
    captured = {}
    phase_entered = asyncio.Event()
    real_spawn_agent_process = acp_module.spawn_agent_process

    @contextlib.asynccontextmanager
    async def _spying_spawn_agent_process(client, cmd, *args, env=None, cwd=None):
        original_session_update = client.session_update

        async def _session_update(session_id, update, **kwargs):
            if getattr(update, "session_update", None) == "agent_thought_chunk":
                phase_entered.set()
            await original_session_update(session_id, update, **kwargs)

        client.session_update = _session_update
        async with real_spawn_agent_process(client, cmd, *args, env=env, cwd=cwd) as (conn, proc):
            captured["proc"] = proc
            yield conn, proc

    monkeypatch.setattr(acp_module, "spawn_agent_process", _spying_spawn_agent_process)

    def build_tool(hang_phase="", phase_delay=0, timeout_seconds=2):
        tool = build_invoke_acp_agent_tool(
            {
                "test": ACPAgentConfig(
                    command=sys.executable,
                    args=[str(script_path), hang_phase, str(phase_delay), str(phase_path)],
                    description="Test ACP agent",
                    timeout_seconds=timeout_seconds,
                )
            }
        )
        return tool

    return SimpleNamespace(build_tool=build_tool, captured=captured, phase_entered=phase_entered, phase_path=phase_path)


@pytest.mark.anyio
@pytest.mark.parametrize("phase", ["initialize", "new_session", "prompt"])
async def test_invoke_acp_agent_times_out_and_kills_hung_subprocess(acp_subprocess_tool, phase):
    tool = acp_subprocess_tool.build_tool(hang_phase=phase)
    start = time.monotonic()
    # The outer timeout only bounds a regression; it must not supply the tool's deadline.
    result = await asyncio.wait_for(tool.coroutine(agent="test", prompt="do work"), timeout=15)
    assert time.monotonic() - start < 10
    assert "timed out" in result.lower()
    assert "test" in result
    assert acp_subprocess_tool.phase_path.read_text(encoding="utf-8") == phase
    assert acp_subprocess_tool.captured["proc"].returncode is not None


@pytest.mark.anyio
async def test_invoke_acp_agent_shares_one_timeout_budget(acp_subprocess_tool):
    # Each phase completes within 3s, but their combined 3.6s exceeds one invocation budget.
    tool = acp_subprocess_tool.build_tool(phase_delay=1.2, timeout_seconds=3)
    result = await asyncio.wait_for(tool.coroutine(agent="test", prompt="do work"), timeout=15)
    assert "timed out" in result.lower()
    assert acp_subprocess_tool.captured["proc"].returncode is not None


@pytest.mark.anyio
async def test_invoke_acp_agent_completes_within_timeout(acp_subprocess_tool):
    tool = acp_subprocess_tool.build_tool()
    result = await asyncio.wait_for(tool.coroutine(agent="test", prompt="do work"), timeout=15)
    assert result == "(no response)"
    assert acp_subprocess_tool.phase_path.read_text(encoding="utf-8") == "prompt"
    assert acp_subprocess_tool.captured["proc"].returncode is not None


@pytest.mark.anyio
async def test_invoke_acp_agent_cancellation_closes_subprocess(acp_subprocess_tool):
    tool = acp_subprocess_tool.build_tool(hang_phase="prompt", timeout_seconds=60)
    invocation = asyncio.create_task(tool.coroutine(agent="test", prompt="do work"))
    try:
        await asyncio.wait_for(acp_subprocess_tool.phase_entered.wait(), timeout=15)
        invocation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(invocation, timeout=15)
        assert acp_subprocess_tool.captured["proc"].returncode is not None
    finally:
        if not invocation.done():
            invocation.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await invocation


@pytest.mark.anyio
@pytest.mark.parametrize("phase", ["initialize", "new_session", "prompt"])
async def test_invoke_acp_agent_preserves_sdk_timeout_errors(acp_subprocess_tool, monkeypatch, phase):
    from acp.client.connection import ClientSideConnection

    async def raise_sdk_timeout(self, *args, **kwargs):
        raise TimeoutError("SDK transport timed out")

    monkeypatch.setattr(ClientSideConnection, phase, raise_sdk_timeout)
    tool = acp_subprocess_tool.build_tool(timeout_seconds=60)
    result = await asyncio.wait_for(tool.coroutine(agent="test", prompt="do work"), timeout=15)
    assert result == "Error invoking ACP agent 'test': SDK transport timed out"
    assert "timeout_seconds" not in result
    assert acp_subprocess_tool.captured["proc"].returncode is not None


def _write_launcher_shim(directory: Path, name: str, command: str) -> Path:
    """Write an executable launcher shim for ``name`` under ``directory``."""
    directory.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        shim = directory / f"{name}.cmd"
        shim.write_text(f"@echo off\n{command}\n", encoding="utf-8")
    else:
        shim = directory / name
        shim.write_text(f"#!/bin/sh\nexec {command}\n", encoding="utf-8")
        shim.chmod(0o755)
    return shim


@pytest.mark.anyio
async def test_invoke_acp_agent_spawns_the_path_resolved_command(monkeypatch, tmp_path):
    """A bare configured command reaches the ACP SDK as its PATH-resolved path.

    Windows resolves npm-installed launchers through ``PATHEXT`` (``npx`` ->
    ``npx.cmd``) and ``asyncio.create_subprocess_exec`` does not, so the
    resolved path must be handed to the SDK instead of the bare name.
    """
    import acp as acp_module

    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    monkeypatch.setattr(
        "deerflow.config.extensions_config.ExtensionsConfig.from_file",
        classmethod(lambda cls: ExtensionsConfig(mcp_servers={}, skills={})),
    )
    script_path = tmp_path / "test_acp_agent.py"
    script_path.write_text(_ACP_AGENT_SCRIPT, encoding="utf-8")
    phase_path = tmp_path / "phase.txt"

    shim_name = "deerflow-acp-probe"
    shim = _write_launcher_shim(tmp_path / "bin", shim_name, f'"{sys.executable}" "{script_path}" "" 0 "{phase_path}"')
    monkeypatch.setenv("PATH", str(shim.parent))

    captured: dict[str, object] = {}
    real_spawn_agent_process = acp_module.spawn_agent_process

    @contextlib.asynccontextmanager
    async def _spying_spawn_agent_process(client, cmd, *args, env=None, cwd=None):
        captured["cmd"] = cmd
        async with real_spawn_agent_process(client, cmd, *args, env=env, cwd=cwd) as (conn, proc):
            yield conn, proc

    monkeypatch.setattr(acp_module, "spawn_agent_process", _spying_spawn_agent_process)

    tool = build_invoke_acp_agent_tool({"probe": ACPAgentConfig(command=shim_name, description="Probe", timeout_seconds=30)})
    result = await asyncio.wait_for(tool.coroutine(agent="probe", prompt="do work"), timeout=20)

    # Windows PATHEXT matching reports the shim with its extension case
    # normalized, so compare paths rather than raw strings.
    assert Path(captured["cmd"]) == shim
    assert result == "(no response)"


@pytest.mark.anyio
async def test_invoke_acp_agent_reports_guidance_for_an_unresolvable_command(monkeypatch, tmp_path):
    """A command PATH cannot resolve still reports the configured name.

    ``_resolve_agent_command`` falls back to the configured value when nothing
    matches, so the not-found guidance must name what the user configured.
    """
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    monkeypatch.setattr(
        "deerflow.config.extensions_config.ExtensionsConfig.from_file",
        classmethod(lambda cls: ExtensionsConfig(mcp_servers={}, skills={})),
    )

    tool = build_invoke_acp_agent_tool({"probe": ACPAgentConfig(command="deerflow-missing-acp-agent", description="Probe", timeout_seconds=30)})
    result = await asyncio.wait_for(tool.coroutine(agent="probe", prompt="do work"), timeout=20)

    assert "Command 'deerflow-missing-acp-agent' was not found on PATH" in result
    assert "acp_agents.probe.command" in result


def test_resolve_agent_command_only_resolves_bare_names(monkeypatch):
    """A configured path is left to the spawn, which runs in the ACP workspace."""
    monkeypatch.setattr(
        "deerflow.tools.builtins.invoke_acp_agent_tool.shutil.which",
        lambda command: f"/resolved/{command}",
    )

    assert _resolve_agent_command("npx") == "/resolved/npx"
    assert _resolve_agent_command("bin/agent") == "bin/agent"
    assert _resolve_agent_command("./bin/agent") == "./bin/agent"


@pytest.mark.anyio
async def test_invoke_acp_agent_reports_the_configured_command_when_spawn_fails(monkeypatch, tmp_path):
    """A command PATH resolves can still fail to launch.

    The remediation text has to stay anchored to the configured command, so the
    ``codex-acp`` hint below survives the resolution.
    """
    import acp as acp_module

    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    monkeypatch.setattr(
        "deerflow.config.extensions_config.ExtensionsConfig.from_file",
        classmethod(lambda cls: ExtensionsConfig(mcp_servers={}, skills={})),
    )
    shim_dir = tmp_path / "bin"
    _write_launcher_shim(shim_dir, "codex-acp", "echo")
    _write_launcher_shim(shim_dir, "codex", "echo")
    monkeypatch.setenv("PATH", str(shim_dir))

    def _raise_missing(*args, **kwargs):
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr(acp_module, "spawn_agent_process", _raise_missing)

    tool = build_invoke_acp_agent_tool({"codex": ACPAgentConfig(command="codex-acp", description="Codex CLI", timeout_seconds=30)})
    result = await asyncio.wait_for(tool.coroutine(agent="codex", prompt="do work"), timeout=20)

    assert "Command 'codex-acp' was not found on PATH" in result
    assert "does not speak ACP directly" in result
