"""Keep repository-root declarations valid when test files move between folders."""

import ast
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = TESTS_ROOT.parent.parent


def _root_declarations():
    for path in sorted(TESTS_ROOT.rglob("test_*.py")):
        source_text = path.read_text(encoding="utf-8-sig")
        if "Path(__file__)" not in source_text:
            continue
        tree = ast.parse(source_text)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign) or not any(isinstance(target, ast.Name) and target.id.lower().strip("_") in {"repo_root", "repository_root"} for target in node.targets):
                continue
            value = node.value
            if not isinstance(value, ast.Subscript) or not isinstance(value.value, ast.Attribute) or value.value.attr != "parents":
                continue
            source = ast.unparse(value.value.value)
            if source not in {"Path(__file__)", "Path(__file__).resolve()"} or not isinstance(value.slice, ast.Constant):
                continue
            yield path, value.slice.value, node.lineno


def test_repository_root_declarations_resolve_to_checkout():
    declarations = list(_root_declarations())
    assert declarations, "No repository-root declarations were checked"
    incorrect = [f"{path.relative_to(TESTS_ROOT).as_posix()}:{line}: parents[{index}] resolves to {path.resolve().parents[index]}" for path, index, line in declarations if path.resolve().parents[index] != REPO_ROOT]
    assert not incorrect, "Incorrect repository roots:\n" + "\n".join(incorrect)
