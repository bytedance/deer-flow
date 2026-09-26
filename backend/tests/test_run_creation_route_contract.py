"""Static authorization contract for HTTP routes that can create Agent runs."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROUTERS_DIR = Path(__file__).resolve().parent.parent / "app" / "gateway" / "routers"

# These scheduled-task mutations create or re-enable work that the background
# scheduler later launches through the normal Gateway run lifecycle.
SCHEDULED_RUN_ENABLING_HANDLERS = {
    "create_scheduled_task",
    "update_scheduled_task",
    "resume_scheduled_task",
}

_ROUTE_DECORATOR_RE = re.compile(r"router\.(get|post|delete|put|patch)")


def _is_route_handler(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute) and isinstance(decorator.func.value, ast.Name) and _ROUTE_DECORATOR_RE.fullmatch(f"{decorator.func.value.id}.{decorator.func.attr}")
        for decorator in node.decorator_list
    )


def _calls_run_launcher(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        if isinstance(child.func, ast.Name) and child.func.id == "start_run":
            return True
        if isinstance(child.func, ast.Attribute) and child.func.attr == "dispatch_task":
            return True
    return False


def _requires_runs_create(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        if not isinstance(decorator.func, ast.Name) or decorator.func.id != "require_permission":
            continue
        if len(decorator.args) < 2:
            continue
        resource, action = decorator.args[:2]
        if isinstance(resource, ast.Constant) and resource.value == "runs" and isinstance(action, ast.Constant) and action.value == "create":
            return True
    return False


def test_every_run_creation_route_requires_runs_create():
    violations = []
    for path in sorted(ROUTERS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not _is_route_handler(node):
                continue
            if node.name not in SCHEDULED_RUN_ENABLING_HANDLERS and not _calls_run_launcher(node):
                continue
            if not _requires_runs_create(node):
                violations.append(f"{path.name}:{node.name}")

    assert not violations, "run-creating routes without runs:create:\n" + "\n".join(violations)
