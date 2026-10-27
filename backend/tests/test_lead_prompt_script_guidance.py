"""The lead prompt coaches script writing only when a ``bash`` tool is bound.

With the default LocalSandboxProvider, host bash is off and no ``bash`` tool is bound, yet the
workspace section still told the agent how to write scripts. In real Gateway runs in flash mode
(thinking off), about a third of file tasks then wrote a helper script that no tool could run.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.tools import StructuredTool

from deerflow.agents.lead_agent import prompt as prompt_module
from deerflow.config.subagents_config import SubagentsAppConfig

SCRIPT_GUIDANCE = "When writing scripts or commands that create/read files from the workspace"
NO_BASH_GUIDANCE = "No `bash` tool is bound: work out results directly and write them with `write_file` instead of saving helper scripts"
ROUTINE_SHELL_EXAMPLE = "- Run a routine test, build, or git command directly. Use one Bash subagent only when a bounded shell workflow has material context-isolation benefit."
NO_BASH_ROUTINE_EXAMPLE = "- Do a routine file read, search, or edit directly. No `bash` tool is bound, and a subagent has none either."


def _app_config(*, allow_host_bash=False, acp_agents=None):
    return SimpleNamespace(
        sandbox=SimpleNamespace(use="deerflow.sandbox.local:LocalSandboxProvider", allow_host_bash=allow_host_bash, mounts=[]),
        skills=SimpleNamespace(container_path="/mnt/skills", use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage", get_skills_path=lambda: Path("/tmp/skills")),
        skill_evolution=SimpleNamespace(enabled=False),
        tool_search=SimpleNamespace(enabled=False),
        memory=SimpleNamespace(enabled=False, injection_enabled=True, max_injection_tokens=2000),
        acp_agents=acp_agents or {},
        subagents=SubagentsAppConfig(),
    )


@pytest.fixture
def render(monkeypatch):
    monkeypatch.setattr(prompt_module, "get_or_new_skill_storage", lambda app_config=None: SimpleNamespace(load_skills=lambda enabled_only=True: []))
    monkeypatch.setattr(prompt_module, "get_agent_soul", lambda agent_name=None, **kwargs: "")

    def _render(config=None, **kwargs):
        config = config or _app_config()
        monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)
        return prompt_module.apply_prompt_template(app_config=config, **kwargs)

    return _render


def test_prompt_keeps_script_guidance_when_bash_is_bound(render):
    prompt = render(bash_available=True)

    assert SCRIPT_GUIDANCE in prompt
    assert "Avoid hardcoding `/mnt/user-data/...` inside generated scripts" in prompt
    assert NO_BASH_GUIDANCE not in prompt


def test_prompt_drops_script_guidance_without_bash(render):
    prompt = render(bash_available=False)

    assert SCRIPT_GUIDANCE not in prompt
    assert "inside generated scripts" not in prompt
    assert NO_BASH_GUIDANCE in prompt
    # The rest of the workspace section is unchanged.
    assert "Treat `/mnt/user-data/workspace` as your default current working directory" in prompt
    assert "Final deliverables must be copied to `/mnt/user-data/outputs`" in prompt


def test_prompt_defaults_to_the_script_guidance(render):
    # Callers that do not pass bash_available keep today's prompt.
    assert render() == render(bash_available=True)


@pytest.mark.parametrize("max_concurrent", [1, 3])
def test_subagent_section_agrees_with_the_lead_about_bash(render, max_concurrent):
    # Host bash allowed, so the registry offers the bash subagent, but the lead's own tools lack bash
    # (for example a custom agent's tool_groups); the bash subagent inherits those groups.
    config = _app_config(allow_host_bash=True)

    with_bash = render(config, subagent_enabled=True, max_concurrent_subagents=max_concurrent, bash_available=True)
    without_bash = render(config, subagent_enabled=True, max_concurrent_subagents=max_concurrent, bash_available=False)

    assert 'bash("npm test")' in with_bash
    assert ROUTINE_SHELL_EXAMPLE in with_bash
    assert NO_BASH_ROUTINE_EXAMPLE not in with_bash
    assert "- **bash**: For bounded shell workflows" in with_bash

    assert 'bash("npm test")' not in without_bash
    assert "(bash, ls, read_file, web_search, etc.)" not in without_bash
    assert "Run a routine test, build, or git command" not in without_bash
    assert "Bash subagent" not in without_bash
    assert NO_BASH_ROUTINE_EXAMPLE in without_bash
    # The sandbox provider is not the cause here, so the hint must not send the operator to another one.
    assert "- **bash**: Not available in this run: no `bash` tool is bound for this agent, and a bash subagent is limited to the same tools. Use the direct file/web tools." in without_bash
    assert "AioSandboxProvider" not in without_bash


@pytest.mark.parametrize("max_concurrent", [1, 3])
def test_subagent_examples_drop_shell_work_when_host_bash_is_off(render, max_concurrent):
    # The default local sandbox: the registry drops the bash subagent and the lead binds no bash.
    prompt = render(_app_config(allow_host_bash=False), subagent_enabled=True, max_concurrent_subagents=max_concurrent, bash_available=False)

    assert "- **bash**:" not in prompt
    assert "Run a routine test, build, or git command" not in prompt
    assert "Bash subagent" not in prompt
    assert NO_BASH_ROUTINE_EXAMPLE in prompt


@pytest.mark.parametrize("max_concurrent", [1, 3])
def test_subagent_examples_do_not_name_a_bash_subagent_that_is_not_offered(render, max_concurrent):
    # A custom agent may bind bash itself while its allowed_subagents leave the bash subagent out.
    prompt = render(_app_config(allow_host_bash=True), subagent_enabled=True, max_concurrent_subagents=max_concurrent, allowed_subagents=["general-purpose"], bash_available=True)

    assert "- **bash**:" not in prompt
    assert "- Run a routine test, build, or git command directly.\n" in prompt
    assert "Bash subagent" not in prompt
    assert NO_BASH_ROUTINE_EXAMPLE not in prompt


def test_acp_section_only_suggests_bash_cp_with_bash(render):
    config = _app_config(acp_agents={"codex": SimpleNamespace()})

    assert "use `ls`, `read_file`, or `bash cp` to retrieve output files" in render(config, bash_available=True)
    without_bash = render(config, bash_available=False)
    assert "bash cp" not in without_bash
    assert "use `ls` and `read_file` to retrieve output files" in without_bash


def _tool(name: str) -> StructuredTool:
    return StructuredTool.from_function(func=lambda: "", name=name, description=name)


def test_has_bash_tool_matches_the_bash_tool_by_exact_name():
    assert prompt_module.has_bash_tool([_tool("read_file"), _tool("bash")]) is True
    assert prompt_module.has_bash_tool([_tool("read_file"), _tool("write_file")]) is False
    assert prompt_module.has_bash_tool([_tool("bash_output"), _tool("run_bash"), _tool("bashful")]) is False
    assert prompt_module.has_bash_tool([object()]) is False
    assert prompt_module.has_bash_tool([]) is False


@pytest.mark.parametrize("bootstrap", [False, True])
@pytest.mark.parametrize(
    ("tool_names", "authorization_denies_bash", "expected"),
    [
        (["read_file", "write_file", "bash"], False, True),
        (["read_file", "write_file"], False, False),
        # Authorization removes bash after the tools are loaded: the prompt follows the authorized set.
        (["read_file", "write_file", "bash"], True, False),
    ],
)
def test_lead_agent_tells_the_prompt_whether_it_binds_bash(monkeypatch, bootstrap, tool_names, authorization_denies_bash, expected):
    from deerflow.agents.lead_agent import agent as lead_agent_module
    from deerflow.agents.lead_agent.agent import assemble_lead_agent
    from deerflow.config.app_config import AppConfig
    from deerflow.config.model_config import ModelConfig
    from deerflow.config.sandbox_config import SandboxConfig

    app_config = AppConfig(
        models=[
            ModelConfig(
                name="prompt-test-model",
                display_name="prompt-test-model",
                description=None,
                use="langchain_openai:ChatOpenAI",
                model="prompt-test-model",
                supports_thinking=False,
                supports_vision=False,
            )
        ],
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
    )
    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: app_config)
    monkeypatch.setattr(lead_agent_module, "create_chat_model", lambda **kwargs: object())
    monkeypatch.setattr(lead_agent_module, "create_agent", lambda **kwargs: kwargs)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [_tool(name) for name in tool_names])
    if authorization_denies_bash:
        monkeypatch.setattr(lead_agent_module, "apply_tool_authorization", lambda tools, **kwargs: ([tool for tool in tools if tool.name != "bash"], None))
    prompt_calls = []

    def render_prompt(**kwargs):
        prompt_calls.append(kwargs)
        return "prompt"

    monkeypatch.setattr(lead_agent_module, "apply_prompt_template", render_prompt)

    assemble_lead_agent({"configurable": {"thread_id": "t-script-guidance", "is_bootstrap": bootstrap}})

    assert len(prompt_calls) == 1
    assert prompt_calls[0]["bash_available"] is expected
