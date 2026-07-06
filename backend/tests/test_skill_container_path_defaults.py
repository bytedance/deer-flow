"""Regression tests for the skills sandbox container root default."""

from __future__ import annotations

import ast
from pathlib import Path


def test_mnt_skills_literal_is_owned_by_skill_constants_module():
    package_root = Path(__file__).parents[1] / "packages" / "harness" / "deerflow"
    allowed = {package_root / "constants.py"}
    offenders: list[str] = []

    for path in package_root.rglob("*.py"):
        if path in allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value == "/mnt/skills":
                offenders.append(str(path.relative_to(package_root)))

    assert offenders == []


def test_runtime_middlewares_use_top_level_skills_container_constant():
    package_root = Path(__file__).parents[1] / "packages" / "harness" / "deerflow"
    offenders: list[str] = []

    for relative_path in (
        Path("agents/middlewares/durable_context_middleware.py"),
        Path("agents/middlewares/tool_error_handling_middleware.py"),
    ):
        path = package_root / relative_path
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "deerflow.config.skills_config":
                imported_names = {alias.name for alias in node.names}
                if "DEFAULT_SKILLS_CONTAINER_PATH" in imported_names:
                    offenders.append(str(relative_path))

    assert offenders == []
