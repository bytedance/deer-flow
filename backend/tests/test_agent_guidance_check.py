from __future__ import annotations

import importlib.util
from pathlib import Path, PurePosixPath

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER_PATH = REPO_ROOT / "scripts" / "check_agent_guidance.py"
EXPECTED_GUIDANCE_PATHS = {
    "AGENTS.md",
    "backend/AGENTS.md",
    "frontend/AGENTS.md",
    "backend/app/gateway/AGENTS.md",
    "backend/app/channels/AGENTS.md",
    "backend/packages/harness/deerflow/AGENTS.md",
    "backend/packages/harness/deerflow/agents/AGENTS.md",
    "backend/packages/harness/deerflow/agents/middlewares/AGENTS.md",
    "backend/packages/harness/deerflow/agents/memory/AGENTS.md",
    "backend/packages/harness/deerflow/config/AGENTS.md",
    "backend/packages/harness/deerflow/extensions/AGENTS.md",
    "backend/packages/harness/deerflow/runtime/AGENTS.md",
    "backend/packages/harness/deerflow/sandbox/AGENTS.md",
    "backend/packages/harness/deerflow/mcp/AGENTS.md",
    "backend/packages/harness/deerflow/models/AGENTS.md",
    "backend/packages/harness/deerflow/persistence/migrations/AGENTS.md",
    "backend/packages/harness/deerflow/reflection/AGENTS.md",
    "backend/packages/harness/deerflow/skills/AGENTS.md",
    "backend/packages/harness/deerflow/subagents/AGENTS.md",
    "backend/packages/harness/deerflow/tools/AGENTS.md",
    "backend/packages/harness/deerflow/tracing/AGENTS.md",
    "backend/packages/harness/deerflow/tui/AGENTS.md",
    "frontend/src/AGENTS.md",
    "scripts/AGENTS.md",
}


def _load_checker():
    assert CHECKER_PATH.exists(), f"{CHECKER_PATH} must exist"
    spec = importlib.util.spec_from_file_location("deerflow_agent_guidance_check", CHECKER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()


def _files(**overrides: str) -> dict[PurePosixPath, str]:
    files = {PurePosixPath("AGENTS.md"): "# Repository instructions\n"}
    files.update({PurePosixPath(path): text for path, text in overrides.items()})
    return files


def _codes(findings, severity: str | None = None) -> list[str]:
    return [finding.code for finding in findings if severity is None or finding.severity == severity]


def test_normalized_utf8_size_uses_lf_and_counts_non_ascii_bytes() -> None:
    assert checker.normalized_utf8_size("a\r\n中\r") == len("a\n中\n".encode())


@pytest.mark.parametrize(
    ("path", "soft", "hard"),
    [
        ("AGENTS.md", 12 * 1024, 16 * 1024),
        ("backend/AGENTS.md", 24 * 1024, 32 * 1024),
        ("backend/app/gateway/AGENTS.md", 40 * 1024, 48 * 1024),
    ],
)
def test_budget_depends_on_directory_level(path: str, soft: int, hard: int) -> None:
    assert checker.agent_budget(PurePosixPath(path)) == (soft, hard)


def test_single_file_over_hard_limit_is_an_error(tmp_path: Path) -> None:
    findings = checker.analyze(tmp_path, _files(**{"AGENTS.md": "x" * (16 * 1024 + 1)}))

    assert "AG001" in _codes(findings, "error")


def test_effective_ancestor_chain_can_fail_when_each_file_is_valid(tmp_path: Path) -> None:
    files = _files(
        **{
            "AGENTS.md": "r" * (15 * 1024),
            "backend/AGENTS.md": "m" * (31 * 1024),
            "backend/app/AGENTS.md": "l" * (47 * 1024),
            "backend/app/gateway/AGENTS.md": "g" * (47 * 1024),
        }
    )

    findings = checker.analyze(tmp_path, files)

    assert "AG001" not in _codes(findings, "error")
    assert "AG002" in _codes(findings, "error")


def test_legacy_hard_violation_may_shrink_but_may_not_grow(tmp_path: Path) -> None:
    base = _files(**{"AGENTS.md": "x" * (17 * 1024)})
    smaller = _files(**{"AGENTS.md": "x" * (17 * 1024 - 1)})
    grown = _files(**{"AGENTS.md": "x" * (17 * 1024 + 1)})

    smaller_findings = checker.analyze(tmp_path, smaller, base_files=base)
    grown_findings = checker.analyze(tmp_path, grown, base_files=base)

    assert "AG001" not in _codes(smaller_findings, "error")
    assert "AG001" in _codes(grown_findings, "error")


def test_discovery_uses_exact_agents_basename() -> None:
    paths = [
        PurePosixPath("AGENTS.md"),
        PurePosixPath("backend/AGENTS.md"),
        PurePosixPath("backend/CLAUDE.md"),
        PurePosixPath("backend/docs/GITHUB_AGENTS.md"),
    ]

    assert checker.guidance_paths(paths) == {
        PurePosixPath("AGENTS.md"),
        PurePosixPath("backend/AGENTS.md"),
    }


def test_repository_has_the_approved_scoped_guidance_shape() -> None:
    actual = {path.as_posix() for path in checker.guidance_paths(checker._worktree_paths(REPO_ROOT))}

    assert actual == EXPECTED_GUIDANCE_PATHS


def test_repository_guidance_stays_below_soft_budgets_and_avoids_doc_indexes() -> None:
    for relative_text in EXPECTED_GUIDANCE_PATHS:
        relative = PurePosixPath(relative_text)
        path = REPO_ROOT / relative_text
        assert path.is_file(), relative
        soft, _ = checker.agent_budget(relative)
        text = path.read_text(encoding="utf-8")
        assert checker.normalized_utf8_size(text) <= soft, relative
        assert "Subsystem Index" not in text


def test_local_guidance_files_contain_the_split_original_sections() -> None:
    expected_headings = {
        "backend/app/gateway/AGENTS.md": "### Gateway API (`app/gateway/`)",
        "backend/app/channels/AGENTS.md": "### IM Channels System (`app/channels/`)",
        "backend/packages/harness/deerflow/agents/AGENTS.md": "### Agent System",
        "backend/packages/harness/deerflow/agents/middlewares/AGENTS.md": "### Middleware Chain",
        "backend/packages/harness/deerflow/agents/memory/AGENTS.md": "### Memory System",
        "backend/packages/harness/deerflow/config/AGENTS.md": "### Configuration System",
        "backend/packages/harness/deerflow/extensions/AGENTS.md": "### Python Extension System",
        "backend/packages/harness/deerflow/runtime/AGENTS.md": "### Checkpoint Channel Modes",
        "backend/packages/harness/deerflow/sandbox/AGENTS.md": "### Sandbox System",
        "backend/packages/harness/deerflow/mcp/AGENTS.md": "### MCP System",
        "backend/packages/harness/deerflow/models/AGENTS.md": "### Model Factory",
        "backend/packages/harness/deerflow/persistence/migrations/AGENTS.md": "### Schema Migrations",
        "backend/packages/harness/deerflow/reflection/AGENTS.md": "### Reflection System",
        "backend/packages/harness/deerflow/skills/AGENTS.md": "### Skills System",
        "backend/packages/harness/deerflow/subagents/AGENTS.md": "### Subagent System",
        "backend/packages/harness/deerflow/tools/AGENTS.md": "### Tool System",
        "backend/packages/harness/deerflow/tracing/AGENTS.md": "### Tracing System",
        "backend/packages/harness/deerflow/tui/AGENTS.md": "### Terminal Workbench / TUI",
        "frontend/src/AGENTS.md": "### Data Flow",
    }

    for relative_text, heading in expected_headings.items():
        text = (REPO_ROOT / relative_text).read_text(encoding="utf-8")
        assert heading in text, relative_text
        assert "Before changing files in this directory" not in text, relative_text


def test_repository_exposes_one_local_and_one_ci_entrypoint() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    workflow = (REPO_ROOT / ".github" / "workflows" / "lint-check.yml").read_text(encoding="utf-8")

    assert "check-agent-guidance:" in makefile
    assert "scripts/check_agent_guidance.py" in makefile
    assert workflow.count("agent-guidance:") == 1
    assert "fetch-depth: 0" in workflow
    assert "--base-ref" in workflow
    assert "--before" in workflow
