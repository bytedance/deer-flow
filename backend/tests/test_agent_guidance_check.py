from __future__ import annotations

import importlib.util
from pathlib import Path, PurePosixPath

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER_PATH = REPO_ROOT / "scripts" / "check_agent_guidance.py"


def _load_checker():
    assert CHECKER_PATH.exists(), f"{CHECKER_PATH} must exist"
    spec = importlib.util.spec_from_file_location("deerflow_agent_guidance_check", CHECKER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()


def _guidance(*, agent_text: str = "# Guidance\n", claude_text: str = "@AGENTS.md\n") -> dict[PurePosixPath, str]:
    return {
        PurePosixPath("AGENTS.md"): agent_text,
        PurePosixPath("CLAUDE.md"): claude_text,
    }


def _codes(findings, severity: str | None = None) -> list[str]:
    return [finding.code for finding in findings if severity is None or finding.severity == severity]


def test_normalized_utf8_size_uses_lf_and_counts_non_ascii_bytes() -> None:
    assert checker.normalized_utf8_size("a\r\n中\r") == len("a\n中\n".encode())


@pytest.mark.parametrize(
    ("path", "soft", "hard"),
    [
        ("AGENTS.md", 12 * 1024, 16 * 1024),
        ("backend/AGENTS.md", 24 * 1024, 32 * 1024),
        ("backend/runtime/AGENTS.md", 12 * 1024, 16 * 1024),
    ],
)
def test_budget_depends_on_guidance_level(path: str, soft: int, hard: int) -> None:
    assert checker.agent_budget(PurePosixPath(path)) == (soft, hard)


def test_single_file_over_hard_limit_is_an_error(tmp_path: Path) -> None:
    files = _guidance(agent_text="x" * (16 * 1024 + 1))

    findings = checker.analyze(tmp_path, files)

    assert "AG001" in _codes(findings, "error")


def test_ancestor_chain_over_limit_fails_even_when_each_file_is_below_its_limit(tmp_path: Path) -> None:
    files = _guidance(agent_text="r" * (14 * 1024))
    files.update(
        {
            PurePosixPath("backend/AGENTS.md"): "m" * (30 * 1024),
            PurePosixPath("backend/CLAUDE.md"): "@AGENTS.md\n",
            PurePosixPath("backend/runtime/AGENTS.md"): "n" * (5 * 1024),
            PurePosixPath("backend/runtime/CLAUDE.md"): "@AGENTS.md\n",
        }
    )

    findings = checker.analyze(tmp_path, files)

    assert "AG001" not in _codes(findings, "error")
    assert "AG002" in _codes(findings, "error")


def test_legacy_hard_violation_may_stay_equal_but_may_not_grow(tmp_path: Path) -> None:
    base = _guidance(agent_text="x" * (17 * 1024))
    unchanged = _guidance(agent_text="x" * (17 * 1024))
    grown = _guidance(agent_text="x" * (17 * 1024 + 1))

    unchanged_findings = checker.analyze(tmp_path, unchanged, base_files=base)
    grown_findings = checker.analyze(tmp_path, grown, base_files=base)

    assert "AG001" not in _codes(unchanged_findings, "error")
    assert "AG001" in _codes(grown_findings, "error")


def test_missing_sibling_wrapper_is_an_error(tmp_path: Path) -> None:
    findings = checker.analyze(tmp_path, {PurePosixPath("AGENTS.md"): "# Guide\n"})

    assert "AG004" in _codes(findings, "error")


def test_root_guidance_pair_cannot_be_deleted_together(tmp_path: Path) -> None:
    findings = checker.analyze(tmp_path, {})

    assert "AG004" in _codes(findings, "error")


@pytest.mark.parametrize(
    "wrapper",
    [
        "See AGENTS.md\n",
        "@../AGENTS.md\n",
        "@AGENTS.md\n@AGENTS.md\n",
        "@AGENTS.md\n@OTHER.md\n",
    ],
)
def test_wrapper_requires_one_standalone_local_import(tmp_path: Path, wrapper: str) -> None:
    findings = checker.analyze(tmp_path, _guidance(claude_text=wrapper))

    assert "AG005" in _codes(findings, "error")


def test_valid_local_links_pass_and_missing_or_escaping_links_fail(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("# Guide\n", encoding="utf-8")
    agent_text = "\n".join(
        [
            "[valid](docs/guide.md#section)",
            "[missing](docs/missing.md)",
            "[escape](../outside.md)",
            "[external](https://example.com)",
            "[anchor](#local)",
            "```markdown",
            "[fenced](docs/not-real.md)",
            "```",
        ]
    )

    findings = checker.analyze(tmp_path, _guidance(agent_text=agent_text))

    link_errors = [finding for finding in findings if finding.code == "AG003"]
    assert len(link_errors) == 2
    assert {finding.line for finding in link_errors} == {2, 3}


def test_changed_markdown_checks_heading_without_long_line_noise(tmp_path: Path) -> None:
    doc_path = PurePosixPath("docs/changed.md")
    files = _guidance()
    files[doc_path] = "## ### Broken\n" + "x" * 501 + "\n"

    findings = checker.analyze(tmp_path, files, changed_paths={doc_path})

    assert "AG007" not in _codes(findings, "warning")
    assert "AG008" in _codes(findings, "error")


def test_agent_guidance_warns_on_long_non_code_line(tmp_path: Path) -> None:
    files = _guidance(agent_text="x" * 501 + "\n")

    findings = checker.analyze(tmp_path, files)

    assert "AG007" in _codes(findings, "warning")


def test_unchanged_regular_markdown_is_not_checked(tmp_path: Path) -> None:
    doc_path = PurePosixPath("docs/legacy.md")
    files = _guidance()
    files[doc_path] = "[legacy missing](missing.md)\n"

    findings = checker.analyze(tmp_path, files, changed_paths=set())

    assert "AG003" not in _codes(findings)


def test_guidance_discovery_uses_exact_basename() -> None:
    paths = [
        PurePosixPath("AGENTS.md"),
        PurePosixPath("backend/CLAUDE.md"),
        PurePosixPath("backend/docs/GITHUB_AGENTS.md"),
    ]

    assert checker.guidance_paths(paths) == {
        PurePosixPath("AGENTS.md"),
        PurePosixPath("backend/CLAUDE.md"),
    }


def test_repository_exposes_local_and_ci_guidance_checks() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    workflow = (REPO_ROOT / ".github" / "workflows" / "lint-check.yml").read_text(encoding="utf-8")
    pr_template = (REPO_ROOT / ".github" / "pull_request_template.md").read_text(encoding="utf-8")

    assert "check-agent-guidance:" in makefile
    assert "scripts/check_agent_guidance.py" in makefile
    assert "agent-guidance:" in workflow
    assert "fetch-depth: 0" in workflow
    assert "scripts/check_agent_guidance.py" in workflow
    assert "--base-ref" in workflow
    assert "--before" in workflow
    assert "## Documentation impact" in pr_template
    assert "canonical document path or `n/a` with a reason" in pr_template.lower()
