"""Tests for the built-in ACP invocation tool."""

import sys
from types import SimpleNamespace

import pytest

from deerflow.config.acp_config import ACPAgentConfig
from deerflow.config.extensions_config import ExtensionsConfig, McpServerConfig, set_extensions_config
from deerflow.tools.builtins.invoke_acp_agent_tool import (
    _build_acp_mcp_servers,
    _build_mcp_servers,
    _build_permission_response,
    _format_tool_io,
    _get_work_dir,
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
        set_extensions_config(ExtensionsConfig(mcp_servers={}, skills={}))


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
        set_extensions_config(ExtensionsConfig(mcp_servers={}, skills={}))


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
    """ACP agent uses the global workspace and returns only AgentMessageChunk text."""
    from deerflow.config import paths as paths_module

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
            thought_chunk = sys.modules["acp.schema"].AgentThoughtChunk()
            thought_chunk.content = text_content_block("internal thought")
            await client.session_update("session-1", thought_chunk)

            await client.session_update("session-1", sys.modules["acp.schema"].ToolCallStart())

            user_chunk = sys.modules["acp.schema"].UserMessageChunk()
            user_chunk.content = text_content_block("user prompt echo")
            await client.session_update("session-1", user_chunk)

            agent_chunk = sys.modules["acp.schema"].AgentMessageChunk()
            agent_chunk.content = text_content_block("ACP result")
            await client.session_update("session-1", agent_chunk)

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
            AgentMessageChunk=type("AgentMessageChunk", (), {}),
            AgentThoughtChunk=type("AgentThoughtChunk", (), {}),
            ToolCallStart=type("ToolCallStart", (), {"tool_call_id": "tc-1", "title": "read file", "kind": "read"}),
            ToolCallUpdate=type("ToolCallUpdate", (), {}),
            UserMessageChunk=type("UserMessageChunk", (), {}),
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


# ---------------------------------------------------------------------------
# _format_tool_io unit tests
# ---------------------------------------------------------------------------


def test_format_tool_io_serializes_dict():
    result = _format_tool_io({"key": "val"})
    assert '"key"' in result
    assert '"val"' in result


def test_format_tool_io_truncates_long_output():
    long_obj = {"data": "x" * 3000}
    result = _format_tool_io(long_obj)
    assert result.endswith("...")
    assert len(result) <= 2003  # 2000 chars + "..."


def test_format_tool_io_falls_back_to_repr_on_json_error():
    class Unserializable:
        pass

    result = _format_tool_io(Unserializable())
    assert "Unserializable" in result


def test_format_tool_io_does_not_append_ellipsis_when_not_truncated():
    result = _format_tool_io({"key": "val"})
    assert not result.endswith("...")


# ---------------------------------------------------------------------------
# ToolCallUpdate integration test
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_session_update_logs_tool_call_update_raw_io(monkeypatch, tmp_path, caplog):
    """ToolCallUpdate with raw_input/raw_output is logged at DEBUG level."""
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    monkeypatch.setattr(
        "deerflow.config.extensions_config.ExtensionsConfig.from_file",
        classmethod(lambda cls: ExtensionsConfig(mcp_servers={}, skills={})),
    )

    TextContentBlock = type("TextContentBlock", (), {"__init__": lambda self, text: setattr(self, "text", text)})
    AgentMessageChunk = type("AgentMessageChunk", (), {})
    AgentThoughtChunk = type("AgentThoughtChunk", (), {})
    ToolCallStart = type("ToolCallStart", (), {"tool_call_id": "tc-1", "title": "search", "kind": "read"})
    ToolCallUpdate = type(
        "ToolCallUpdate",
        (),
        {"tool_call_id": "tc-1", "title": "search", "status": "completed", "raw_input": {"query": "foo"}, "raw_output": {"result": "bar"}},
    )

    captured: dict[str, object] = {}

    class DummyClient:
        def __init__(self) -> None:
            self._chunks: list[str] = []

        async def session_update(self, session_id, update, **kwargs):
            pass

        async def request_permission(self, options, session_id, tool_call, **kwargs):
            raise AssertionError("should not be called")

    class DummyConn:
        async def initialize(self, **kwargs):
            pass

        async def new_session(self, **kwargs):
            return SimpleNamespace(session_id="s2")

        async def prompt(self, **kwargs):
            client = captured["client"]
            await client.session_update("s2", ToolCallUpdate())
            agent_msg = AgentMessageChunk()
            agent_msg.content = TextContentBlock("done")
            await client.session_update("s2", agent_msg)

    class DummyProcessContext:
        def __init__(self, client, cmd, *args, env=None, cwd):
            captured["client"] = client

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
            AgentMessageChunk=AgentMessageChunk,
            AgentThoughtChunk=AgentThoughtChunk,
            ToolCallStart=ToolCallStart,
            ToolCallUpdate=ToolCallUpdate,
            TextContentBlock=TextContentBlock,
        ),
    )

    tool = build_invoke_acp_agent_tool({"codex": ACPAgentConfig(command="codex-acp", description="Codex CLI")})

    try:
        with caplog.at_level("DEBUG"):
            result = await tool.coroutine(agent="codex", prompt="Search for foo")
    finally:
        sys.modules.pop("acp", None)
        sys.modules.pop("acp.schema", None)

    assert result == "done"
    messages = [r.message for r in caplog.records]
    assert any("tool update" in m and "params" in m and "search" in m and "tc-1" in m for m in messages)
    assert any("tool update" in m and "result" in m and "search" in m and "tc-1" in m for m in messages)


# ---------------------------------------------------------------------------
# Thought logging integration tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_session_update_logs_thought_chunks_immediately(monkeypatch, tmp_path, caplog):
    """AgentThoughtChunk text is logged as soon as the chunk arrives."""
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    monkeypatch.setattr(
        "deerflow.config.extensions_config.ExtensionsConfig.from_file",
        classmethod(lambda cls: ExtensionsConfig(mcp_servers={}, skills={})),
    )

    TextContentBlock = type("TextContentBlock", (), {"__init__": lambda self, text: setattr(self, "text", text)})
    AgentMessageChunk = type("AgentMessageChunk", (), {})
    AgentThoughtChunk = type("AgentThoughtChunk", (), {})
    ToolCallStart = type("ToolCallStart", (), {"tool_call_id": "tc-2", "title": "bash", "kind": "exec"})
    ToolCallUpdate = type("ToolCallUpdate", (), {})

    captured: dict[str, object] = {}

    class DummyClient:
        def __init__(self) -> None:
            self._chunks: list[str] = []

        async def session_update(self, session_id, update, **kwargs):
            pass

        async def request_permission(self, options, session_id, tool_call, **kwargs):
            raise AssertionError("should not be called")

    class DummyConn:
        async def initialize(self, **kwargs):
            pass

        async def new_session(self, **kwargs):
            return SimpleNamespace(session_id="s3")

        async def prompt(self, **kwargs):
            client = captured["client"]
            thought = AgentThoughtChunk()
            thought.content = TextContentBlock("thinking hard")
            await client.session_update("s3", thought)
            captured["thought_logged_immediately"] = any("thinking hard" in record.message for record in caplog.records)
            await client.session_update("s3", ToolCallStart())
            msg = AgentMessageChunk()
            msg.content = TextContentBlock("result")
            await client.session_update("s3", msg)

    class DummyProcessContext:
        def __init__(self, client, cmd, *args, env=None, cwd):
            captured["client"] = client

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
            AgentMessageChunk=AgentMessageChunk,
            AgentThoughtChunk=AgentThoughtChunk,
            ToolCallStart=ToolCallStart,
            ToolCallUpdate=ToolCallUpdate,
            TextContentBlock=TextContentBlock,
        ),
    )

    tool = build_invoke_acp_agent_tool({"codex": ACPAgentConfig(command="codex-acp", description="Codex CLI")})

    try:
        with caplog.at_level("DEBUG"):
            result = await tool.coroutine(agent="codex", prompt="Do it")
    finally:
        sys.modules.pop("acp", None)
        sys.modules.pop("acp.schema", None)

    assert result == "result"
    assert captured["thought_logged_immediately"] is True
    assert any("thinking hard" in r.message for r in caplog.records)
    tool_call_messages = [r.message for r in caplog.records if "ACP agent tool start" in r.message]
    assert tool_call_messages
    assert tool_call_messages[0].index("bash") < tool_call_messages[0].index("tc-2")


@pytest.mark.anyio
async def test_session_update_logs_truncated_thought_with_ellipsis(monkeypatch, tmp_path, caplog):
    """Long thought chunks include an ellipsis when truncated for logging."""
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    monkeypatch.setattr(
        "deerflow.config.extensions_config.ExtensionsConfig.from_file",
        classmethod(lambda cls: ExtensionsConfig(mcp_servers={}, skills={})),
    )

    TextContentBlock = type("TextContentBlock", (), {"__init__": lambda self, text: setattr(self, "text", text)})
    AgentMessageChunk = type("AgentMessageChunk", (), {})
    AgentThoughtChunk = type("AgentThoughtChunk", (), {})
    ToolCallStart = type("ToolCallStart", (), {})
    ToolCallUpdate = type("ToolCallUpdate", (), {})

    captured: dict[str, object] = {}
    long_thought = "x" * 250

    class DummyClient:
        def __init__(self) -> None:
            self._chunks: list[str] = []

        async def session_update(self, session_id, update, **kwargs):
            pass

        async def request_permission(self, options, session_id, tool_call, **kwargs):
            raise AssertionError("should not be called")

    class DummyConn:
        async def initialize(self, **kwargs):
            pass

        async def new_session(self, **kwargs):
            return SimpleNamespace(session_id="s3b")

        async def prompt(self, **kwargs):
            client = captured["client"]
            thought = AgentThoughtChunk()
            thought.content = TextContentBlock(long_thought)
            await client.session_update("s3b", thought)
            msg = AgentMessageChunk()
            msg.content = TextContentBlock("result")
            await client.session_update("s3b", msg)

    class DummyProcessContext:
        def __init__(self, client, cmd, *args, env=None, cwd):
            captured["client"] = client

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
            AgentMessageChunk=AgentMessageChunk,
            AgentThoughtChunk=AgentThoughtChunk,
            ToolCallStart=ToolCallStart,
            ToolCallUpdate=ToolCallUpdate,
            TextContentBlock=TextContentBlock,
        ),
    )

    tool = build_invoke_acp_agent_tool({"codex": ACPAgentConfig(command="codex-acp", description="Codex CLI")})

    try:
        with caplog.at_level("DEBUG"):
            result = await tool.coroutine(agent="codex", prompt="Do it")
    finally:
        sys.modules.pop("acp", None)
        sys.modules.pop("acp.schema", None)

    assert result == "result"
    thought_messages = [r.message for r in caplog.records if "ACP agent thought" in r.message]
    assert thought_messages
    assert thought_messages[0].endswith("...")


@pytest.mark.anyio
async def test_session_update_logs_tool_call_update_status_only(monkeypatch, tmp_path, caplog):
    """ToolCallUpdate with neither raw_input nor raw_output logs the status line."""
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    monkeypatch.setattr(
        "deerflow.config.extensions_config.ExtensionsConfig.from_file",
        classmethod(lambda cls: ExtensionsConfig(mcp_servers={}, skills={})),
    )

    TextContentBlock = type("TextContentBlock", (), {"__init__": lambda self, text: setattr(self, "text", text)})
    AgentMessageChunk = type("AgentMessageChunk", (), {})
    AgentThoughtChunk = type("AgentThoughtChunk", (), {})
    ToolCallStart = type("ToolCallStart", (), {})
    ToolCallUpdate = type(
        "ToolCallUpdate",
        (),
        {"tool_call_id": "tc-3", "status": "in_progress", "title": "bash"},
    )

    captured: dict[str, object] = {}

    class DummyClient:
        def __init__(self) -> None:
            self._chunks: list[str] = []

        async def session_update(self, session_id, update, **kwargs):
            pass

        async def request_permission(self, options, session_id, tool_call, **kwargs):
            raise AssertionError("should not be called")

    class DummyConn:
        async def initialize(self, **kwargs):
            pass

        async def new_session(self, **kwargs):
            return SimpleNamespace(session_id="s4")

        async def prompt(self, **kwargs):
            client = captured["client"]
            await client.session_update("s4", ToolCallUpdate())
            msg = AgentMessageChunk()
            msg.content = TextContentBlock("done")
            await client.session_update("s4", msg)

    class DummyProcessContext:
        def __init__(self, client, cmd, *args, env=None, cwd):
            captured["client"] = client

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
            AgentMessageChunk=AgentMessageChunk,
            AgentThoughtChunk=AgentThoughtChunk,
            ToolCallStart=ToolCallStart,
            ToolCallUpdate=ToolCallUpdate,
            TextContentBlock=TextContentBlock,
        ),
    )

    tool = build_invoke_acp_agent_tool({"codex": ACPAgentConfig(command="codex-acp", description="Codex CLI")})

    try:
        with caplog.at_level("DEBUG"):
            result = await tool.coroutine(agent="codex", prompt="Run bash")
    finally:
        sys.modules.pop("acp", None)
        sys.modules.pop("acp.schema", None)

    assert result == "done"
    assert any("tool update" in r.message and "status" in r.message and "tc-3" in r.message and "in_progress" in r.message for r in caplog.records)
    tool_status_messages = [r.message for r in caplog.records if "ACP agent tool update" in r.message and "status" in r.message]
    assert tool_status_messages
    assert tool_status_messages[0].index("bash") < tool_status_messages[0].index("tc-3")


@pytest.mark.anyio
async def test_invoke_acp_agent_logs_thought_on_prompt_failure(monkeypatch, tmp_path, caplog):
    """Thought text is still logged when prompt execution later fails."""
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    monkeypatch.setattr(
        "deerflow.config.extensions_config.ExtensionsConfig.from_file",
        classmethod(lambda cls: ExtensionsConfig(mcp_servers={}, skills={})),
    )

    TextContentBlock = type("TextContentBlock", (), {"__init__": lambda self, text: setattr(self, "text", text)})
    AgentThoughtChunk = type("AgentThoughtChunk", (), {})

    captured: dict[str, object] = {}

    class DummyClient:
        def __init__(self) -> None:
            self._chunks: list[str] = []

        async def session_update(self, session_id, update, **kwargs):
            pass

        async def request_permission(self, options, session_id, tool_call, **kwargs):
            raise AssertionError("should not be called")

    class DummyConn:
        async def initialize(self, **kwargs):
            pass

        async def new_session(self, **kwargs):
            return SimpleNamespace(session_id="s5")

        async def prompt(self, **kwargs):
            client = captured["client"]
            thought = AgentThoughtChunk()
            thought.content = TextContentBlock("partial failure thought")
            await client.session_update("s5", thought)
            raise RuntimeError("prompt failed")

    class DummyProcessContext:
        def __init__(self, client, cmd, *args, env=None, cwd):
            captured["client"] = client

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
            AgentMessageChunk=type("AgentMessageChunk", (), {}),
            AgentThoughtChunk=AgentThoughtChunk,
            ToolCallStart=type("ToolCallStart", (), {}),
            ToolCallUpdate=type("ToolCallUpdate", (), {}),
            TextContentBlock=TextContentBlock,
        ),
    )

    tool = build_invoke_acp_agent_tool({"codex": ACPAgentConfig(command="codex-acp", description="Codex CLI")})

    try:
        with caplog.at_level("DEBUG"):
            result = await tool.coroutine(agent="codex", prompt="Fail")
    finally:
        sys.modules.pop("acp", None)
        sys.modules.pop("acp.schema", None)

    assert result == "Error invoking ACP agent 'codex': prompt failed"
    assert any("partial failure thought" in r.message for r in caplog.records)


@pytest.mark.anyio
async def test_invoke_acp_agent_logs_truncated_result_with_ellipsis(monkeypatch, tmp_path, caplog):
    """Long final responses include an ellipsis in the info preview log."""
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    monkeypatch.setattr(
        "deerflow.config.extensions_config.ExtensionsConfig.from_file",
        classmethod(lambda cls: ExtensionsConfig(mcp_servers={}, skills={})),
    )

    TextContentBlock = type("TextContentBlock", (), {"__init__": lambda self, text: setattr(self, "text", text)})
    AgentMessageChunk = type("AgentMessageChunk", (), {})
    long_result = "r" * 1200

    captured: dict[str, object] = {}

    class DummyClient:
        def __init__(self) -> None:
            self._chunks: list[str] = []

        async def session_update(self, session_id, update, **kwargs):
            pass

        async def request_permission(self, options, session_id, tool_call, **kwargs):
            raise AssertionError("should not be called")

    class DummyConn:
        async def initialize(self, **kwargs):
            pass

        async def new_session(self, **kwargs):
            return SimpleNamespace(session_id="s6")

        async def prompt(self, **kwargs):
            client = captured["client"]
            msg = AgentMessageChunk()
            msg.content = TextContentBlock(long_result)
            await client.session_update("s6", msg)

    class DummyProcessContext:
        def __init__(self, client, cmd, *args, env=None, cwd):
            captured["client"] = client

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
            AgentMessageChunk=AgentMessageChunk,
            AgentThoughtChunk=type("AgentThoughtChunk", (), {}),
            ToolCallStart=type("ToolCallStart", (), {}),
            ToolCallUpdate=type("ToolCallUpdate", (), {}),
            TextContentBlock=TextContentBlock,
        ),
    )

    tool = build_invoke_acp_agent_tool({"codex": ACPAgentConfig(command="codex-acp", description="Codex CLI")})

    try:
        with caplog.at_level("INFO"):
            result = await tool.coroutine(agent="codex", prompt="Do it")
    finally:
        sys.modules.pop("acp", None)
        sys.modules.pop("acp.schema", None)

    assert result == long_result
    return_messages = [r.message for r in caplog.records if "ACP agent 'codex' returned " in r.message]
    assert return_messages
    assert any(message.endswith("...") for message in return_messages if "characters" not in message)
