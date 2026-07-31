"""Purity check: the hexagonal inner ring must stay infrastructure-free.

``packages/harness/deerflow/domain/`` holds domain models, ports, and
application services. Per the hexagonal layering rules it may depend on the
standard library (and other domain modules) only — no ORM/HTTP/validation
frameworks, no app layer, and no harness infrastructure modules. This is the
machine-checkable form of "the domain doesn't depend on any other module".

Same AST-scan strength (and same accepted blind spots, e.g. dynamic imports)
as test_harness_boundary.py.
"""

import ast
from pathlib import Path

DOMAIN_ROOT = Path(__file__).parent.parent / "packages" / "harness" / "deerflow" / "domain"

BANNED_PREFIXES = (
    # third-party infrastructure
    "sqlalchemy",
    "alembic",
    "aiosqlite",
    "fastapi",
    "starlette",
    "pydantic",
    "langchain",
    "langgraph",
    # app layer (also covered by test_harness_boundary, restated for clarity)
    "app",
    # harness infrastructure modules
    "deerflow.persistence",
    "deerflow.runtime",
    "deerflow.mcp",
    "deerflow.sandbox",
    "deerflow.agents",
    "deerflow.tools",
    "deerflow.skills",
    "deerflow.community",
    "deerflow.tui",
)


def _collect_imports(filepath: Path) -> list[tuple[int, str]]:
    """Return (line_number, module_path) for every import in *filepath*."""
    source = filepath.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return []

    results: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                results.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                results.append((node.lineno, node.module))
    return results


def test_domain_has_no_infrastructure_imports():
    assert DOMAIN_ROOT.is_dir(), f"domain package missing: {DOMAIN_ROOT}"
    violations: list[str] = []

    for py_file in sorted(DOMAIN_ROOT.rglob("*.py")):
        for lineno, module in _collect_imports(py_file):
            if any(module == prefix or module.startswith(prefix + ".") for prefix in BANNED_PREFIXES):
                rel = py_file.relative_to(DOMAIN_ROOT.parent.parent.parent)
                violations.append(f"  {rel}:{lineno}  imports {module}")

    assert not violations, "Hexagonal inner ring (domain/) must stay infrastructure-free:\n" + "\n".join(violations)
