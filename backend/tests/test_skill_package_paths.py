"""Tests for the shared skill-package path helpers.

`is_eval_fixture_path` decides whether a package file is an eval fixture. It is
shared by the review resource graph and by SkillScan's nested-`SKILL.md` rule, so
a path that is under *any* `evals/fixtures/` segment must be recognised — not only
a path whose first `evals` segment is followed by `fixtures`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deerflow.skills.package_paths import is_eval_fixture_path, is_eval_fixture_skill_md
from deerflow.skills.skillscan.orchestrator import scan_skill_dir

_MINIMAL_SKILL_MD = "---\nname: demo\ndescription: A demo skill\n---\n\nBody.\n"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        # A single `evals/fixtures/` segment: the behaviour that already worked.
        ("evals/fixtures/blocked/SKILL.md", True),
        ("evals/fixtures/blocked/scripts/run.py", True),
        # The fixtures directory itself is not *under* it.
        ("evals/fixtures", False),
        # An earlier plain `evals` segment must not mask a later `evals/fixtures`.
        ("evals/cases/inner/evals/fixtures/blocked/SKILL.md", True),
        ("evals/cases/inner/evals/fixtures", False),
        # Same depth as the row above, only the leading directory differs: this
        # isolates the short circuit from path depth.
        ("evals/fixtures/inner/evals/fixtures/blocked/SKILL.md", True),
        # More than two `evals` segments.
        ("evals/cases/a/evals/cases/b/evals/fixtures/blocked/SKILL.md", True),
        # No `evals` segment, or no `fixtures` directly after one.
        ("SKILL.md", False),
        ("scripts/run.py", False),
        ("evals/cases/inner/SKILL.md", False),
        ("evals", False),
        ("", False),
    ],
)
def test_is_eval_fixture_path(path: str, expected: bool) -> None:
    assert is_eval_fixture_path(path) is expected


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("evals/fixtures/blocked/SKILL.md", True),
        ("evals/cases/inner/evals/fixtures/blocked/SKILL.md", True),
        ("evals/cases/inner/SKILL.md", False),
        ("SKILL.md", False),
        ("evals/fixtures/blocked/README.md", False),
    ],
)
def test_is_eval_fixture_skill_md(path: str, expected: bool) -> None:
    assert is_eval_fixture_skill_md(path) is expected


def _write_package(root: Path, nested: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text(_MINIMAL_SKILL_MD, encoding="utf-8")
    nested_path = root / nested
    nested_path.parent.mkdir(parents=True, exist_ok=True)
    nested_path.write_text("---\nname: blocked\ndescription: A fixture sample\n---\n\nBody.\n", encoding="utf-8")


def test_nested_eval_fixture_skill_md_is_withheld_from_skillscan(tmp_path: Path) -> None:
    """A fixture sample under a later `evals/fixtures/` is withheld, so the package is not blocked."""
    root = tmp_path / "pkg"
    nested = "evals/cases/inner/evals/fixtures/blocked/SKILL.md"
    _write_package(root, nested)

    assert is_eval_fixture_skill_md(nested) is True

    result = scan_skill_dir(root)

    assert [finding["rule_id"] for finding in result["findings"]] == []
    assert result["blocked"] is False


def test_skill_md_outside_eval_fixtures_is_still_reported(tmp_path: Path) -> None:
    """Withholding stays scoped to fixtures: a nested non-fixture SKILL.md is still CRITICAL."""
    root = tmp_path / "pkg"
    _write_package(root, "evals/cases/inner/SKILL.md")

    result = scan_skill_dir(root)

    assert [(finding["rule_id"], finding["severity"]) for finding in result["findings"]] == [("package-nested-skill-md", "CRITICAL")]
    assert result["blocked"] is True
