"""Prompt-contract tests for benefit-based subagent routing."""

from deerflow.agents.lead_agent import prompt as prompt_module
from deerflow.subagents.builtins.bash_agent import BASH_AGENT_CONFIG
from deerflow.subagents.builtins.general_purpose import GENERAL_PURPOSE_CONFIG
from deerflow.tools.builtins.task_tool import task_tool


def _build_section(monkeypatch, names: list[str] | None = None, max_concurrent: int = 3) -> str:
    monkeypatch.setattr(prompt_module, "get_available_subagent_names", lambda: names or ["general-purpose"])
    return prompt_module._build_subagent_section(max_concurrent)


def test_routing_requires_clear_net_benefit(monkeypatch) -> None:
    section = _build_section(monkeypatch)

    assert "Default to direct execution" in section
    assert "Do not delegate merely because a task is complex" in section
    assert "Delegate only when the expected benefit is clearly greater than the expected cost" in section
    assert "parallel wall-clock savings" in section
    assert "specialist capability" in section
    assert "context isolation" in section
    assert "duplicate context and repository discovery" in section
    assert "coordination and synthesis" in section
    assert "state-conflict risk" in section
    assert "side-effect risk" in section


def test_hard_vetoes_apply_to_parallel_dispatch_not_single_agent_chains(monkeypatch) -> None:
    section = _build_section(monkeypatch)

    assert "Hard vetoes for parallel dispatch" in section
    assert "Inter-agent dependencies" in section
    assert "overlapping files, shared mutable state, or external side effects" in section
    assert "A bounded sequential chain may still be delegated to one subagent" in section
    assert "Delegation costs and negative signals" in section
    assert "Duplicate discovery" in section
    assert "Cheap direct path" in section


def test_later_batches_retain_within_batch_parallel_benefit(monkeypatch) -> None:
    section = _build_section(monkeypatch)

    assert "Re-evaluate the remaining work after every batch" in section
    assert "Later batches cannot overlap earlier batches" in section
    assert "material within-batch parallel savings" in section
    assert "Use the fewest subagents needed" in section


def test_hard_limit_warning_is_emphatic_and_explains_lost_work(monkeypatch) -> None:
    section = _build_section(monkeypatch)

    assert "HARD LIMITS - NON-NEGOTIABLE" in section
    assert "MAXIMUM 3 `task` CALLS PER RESPONSE - NEVER emit more" in section
    assert "VIOLATION IS A HARD ERROR" in section
    assert "Excess calls are discarded and their work is lost" in section


def test_multi_batch_example_preserves_reassessment_and_synthesis(monkeypatch) -> None:
    section = _build_section(monkeypatch)

    assert "Multi-batch example (limit 3)" in section
    assert "Batch 1: launch up to 3 independent scopes" in section
    assert "Wait for the batch, then re-evaluate" in section
    assert "Batch 2" in section
    assert "Synthesize all retained results" in section


def test_single_subagent_limit_omits_parallel_batch_guidance(monkeypatch) -> None:
    section = _build_section(monkeypatch, max_concurrent=1)

    assert "Expected benefit = specialist capability + context isolation" in section
    assert "delegate only for material specialist or context-isolation benefit" in section
    assert "Parallel dispatch cannot reduce wall-clock latency" in section
    assert "parallel wall-clock savings" not in section
    assert "material within-batch parallel savings" not in section
    assert "Multi-batch example" not in section
    assert "Compare independent providers" not in section


def test_general_purpose_and_task_descriptions_match_routing_policy() -> None:
    tool_description = task_tool.description
    role_description = GENERAL_PURPOSE_CONFIG.description

    assert "expected benefit" in tool_description
    assert "independent" in tool_description
    assert "Splitting dependent steps across parallel subagents" in tool_description
    assert "clear delegation benefit" in role_description
    assert "merely because it is sequential" in role_description
    assert "bounded dependent chain may still be delegated" in role_description


def test_bash_descriptions_require_benefit_beyond_routine_commands(monkeypatch) -> None:
    section = _build_section(monkeypatch, ["general-purpose", "bash"])
    policy = "Routine git, build, test, or deploy operations are not sufficient reason to delegate"

    assert policy in section
    assert policy in task_tool.description
    assert policy in BASH_AGENT_CONFIG.description
    assert "Execute commands one at a time when they depend on each other" in BASH_AGENT_CONFIG.system_prompt
