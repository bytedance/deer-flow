from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "backend-windows-live-policy.yml"

_REQUIRED_PATHS = {
    "backend/app/gateway/routers/agents.py",
    "backend/app/gateway/routers/skills.py",
    "backend/packages/harness/deerflow/persistence/agents/file.py",
    "backend/packages/harness/deerflow/persistence/managed_subagents/file.py",
    "backend/packages/harness/deerflow/skills/storage/**",
    "backend/packages/harness/deerflow/tools/builtins/setup_agent_tool.py",
    "backend/packages/harness/deerflow/tools/skill_manage_tool.py",
    "backend/packages/harness/deerflow/utils/file_lock.py",
    "backend/tests/test_file_lock_retry.py",
    "backend/tests/test_local_skill_storage_write.py",
}

_REQUIRED_NODES = {
    "tests/test_local_skill_storage_write.py",
    "tests/test_file_lock_retry.py",
    "tests/test_agent_storage_backend.py",
    "tests/test_agent_display_name.py",
    "tests/test_skill_history_jsonl.py",
    "tests/test_managed_subagent_store.py",
    "tests/test_skill_manage_tool.py",
    "tests/blocking_io/test_skill_manage_tool.py",
    "tests/blocking_io/test_agents_router.py",
    "tests/test_skills_custom_multiprocess.py",
}


def test_windows_workflow_runs_skill_and_agent_byte_guards_on_relevant_prs():
    raw = WORKFLOW.read_text(encoding="utf-8")
    # PyYAML resolves the unquoted ``on`` key as True under YAML 1.1.
    workflow = yaml.safe_load(raw)
    pull_request = workflow.get("on", workflow.get(True))["pull_request"]

    assert _REQUIRED_PATHS <= set(pull_request["paths"])
    assert _REQUIRED_NODES <= {line.strip() for line in raw.splitlines()}
