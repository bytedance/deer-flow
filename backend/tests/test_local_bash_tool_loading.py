from types import SimpleNamespace

from deerflow.sandbox.security import is_host_bash_allowed
from deerflow.tools.tools import get_available_tools


def _make_config(*, allow_host_bash: bool, sandbox_use: str = "deerflow.sandbox.local:LocalSandboxProvider", extra_tools: list[SimpleNamespace] | None = None):
    return SimpleNamespace(
        tools=[
            SimpleNamespace(name="bash", group="bash", use="deerflow.sandbox.tools:bash_tool"),
            SimpleNamespace(name="ls", group="file:read", use="tests:ls_tool"),
            *(extra_tools or []),
        ],
        models=[],
        sandbox=SimpleNamespace(
            use=sandbox_use,
            allow_host_bash=allow_host_bash,
        ),
        tool_search=SimpleNamespace(enabled=False),
        get_model_config=lambda name: None,
    )


def test_chat_uses_resolved_text_retrieval_tools_in_authorized_groups(monkeypatch):
    config = _make_config(
        allow_host_bash=True,
        extra_tools=[
            SimpleNamespace(name="engine_search", group="web", use="tests:search"),
            SimpleNamespace(name="web_fetch", group="web", use="tests:capture"),
            SimpleNamespace(name="reader", group="web", use="tests:read_conversation"),
        ],
    )
    monkeypatch.setattr("deerflow.tools.tools.get_app_config", lambda: config)
    names = {"tests:search": "web_search", "tests:capture": "write_file", "tests:read_conversation": "read_conversation"}
    monkeypatch.setattr("deerflow.tools.tools.resolve_variable", lambda use, _: SimpleNamespace(name=names[use]))
    bound = get_available_tools(groups=["web"], include_mcp=False, chat_mode=True)
    assert {t.name for t in bound} == {"web_search", "ask_clarification"}


def test_get_available_tools_hides_bash_for_default_local_sandbox(monkeypatch):
    monkeypatch.setattr("deerflow.tools.tools.get_app_config", lambda: _make_config(allow_host_bash=False))
    monkeypatch.setattr(
        "deerflow.tools.tools.resolve_variable",
        lambda use, _: SimpleNamespace(name="bash" if "bash" in use else "ls"),
    )

    names = [tool.name for tool in get_available_tools(include_mcp=False, subagent_enabled=False)]

    assert "bash" not in names
    assert "ls" in names


def test_get_available_tools_keeps_bash_when_explicitly_enabled(monkeypatch):
    monkeypatch.setattr("deerflow.tools.tools.get_app_config", lambda: _make_config(allow_host_bash=True))
    monkeypatch.setattr(
        "deerflow.tools.tools.resolve_variable",
        lambda use, _: SimpleNamespace(name="bash" if "bash" in use else "ls"),
    )

    names = [tool.name for tool in get_available_tools(include_mcp=False, subagent_enabled=False)]

    assert "bash" in names
    assert "ls" in names


def test_get_available_tools_hides_renamed_host_bash_alias(monkeypatch):
    config = _make_config(
        allow_host_bash=False,
        extra_tools=[SimpleNamespace(name="shell", group="bash", use="deerflow.sandbox.tools:bash_tool")],
    )
    monkeypatch.setattr("deerflow.tools.tools.get_app_config", lambda: config)
    monkeypatch.setattr(
        "deerflow.tools.tools.resolve_variable",
        lambda use, _: SimpleNamespace(name="bash" if "bash_tool" in use else "ls"),
    )

    names = [tool.name for tool in get_available_tools(include_mcp=False, subagent_enabled=False)]

    assert "bash" not in names
    assert "shell" not in names
    assert "ls" in names


def test_get_available_tools_keeps_bash_for_aio_sandbox(monkeypatch):
    config = _make_config(
        allow_host_bash=False,
        sandbox_use="deerflow.community.aio_sandbox:AioSandboxProvider",
    )
    monkeypatch.setattr("deerflow.tools.tools.get_app_config", lambda: config)
    monkeypatch.setattr(
        "deerflow.tools.tools.resolve_variable",
        lambda use, _: SimpleNamespace(name="bash" if "bash_tool" in use else "ls"),
    )

    names = [tool.name for tool in get_available_tools(include_mcp=False, subagent_enabled=False)]

    assert "bash" in names
    assert "ls" in names


def test_is_host_bash_allowed_defaults_false_when_sandbox_missing():
    assert is_host_bash_allowed(SimpleNamespace()) is False
    assert is_host_bash_allowed(SimpleNamespace(sandbox=None)) is False
