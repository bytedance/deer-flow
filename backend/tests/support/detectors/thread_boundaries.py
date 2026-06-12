"""Inventory async/thread boundary points for developer review.

This detector is intentionally non-invasive: it parses Python source with AST
and reports places where code crosses sync/async/thread boundaries. Findings
are review evidence, not automatic bug decisions.

Not directly executable: import as `support.detectors.thread_boundaries` or
run via the CLI shim `scripts/detect_thread_boundaries.py`.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from support.detectors.repo_root import resolve_repo_root

REPO_ROOT = resolve_repo_root(Path(__file__))
DEFAULT_SCAN_PATHS = (
    REPO_ROOT / "backend" / "app",
    REPO_ROOT / "backend" / "packages" / "harness" / "deerflow",
)
IGNORED_DIR_NAMES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
}
SEVERITY_ORDER = {"INFO": 0, "WARN": 1, "FAIL": 2}


@dataclass(frozen=True)
class BoundaryFinding:
    severity: str
    category: str
    path: str
    line: int
    column: int
    function: str
    async_context: bool
    symbol: str
    message: str
    code: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class _FunctionContext:
    name: str
    is_async: bool


@dataclass(frozen=True)
class _CallRule:
    severity: str
    category: str
    message: str


EXACT_CALL_RULES: dict[str, _CallRule] = {
    "asyncio.run": _CallRule(
        "WARN",
        "SYNC_ASYNC_BRIDGE",
        "Runs a coroutine from synchronous code by creating an event loop boundary.",
    ),
    "asyncio.to_thread": _CallRule(
        "INFO",
        "ASYNC_THREAD_OFFLOAD",
        "Offloads synchronous work from an async context into a worker thread.",
    ),
    "asyncio.new_event_loop": _CallRule(
        "WARN",
        "NEW_EVENT_LOOP",
        "Creates a separate event loop; review resource ownership across loops.",
    ),
    "asyncio.run_coroutine_threadsafe": _CallRule(
        "WARN",
        "CROSS_THREAD_COROUTINE",
        "Submits a coroutine to an event loop from another thread.",
    ),
    "concurrent.futures.ThreadPoolExecutor": _CallRule(
        "INFO",
        "THREAD_POOL",
        "Creates a thread pool boundary.",
    ),
    "threading.Thread": _CallRule(
        "INFO",
        "RAW_THREAD",
        "Creates a raw thread; ContextVar values do not propagate automatically.",
    ),
    "threading.Timer": _CallRule(
        "INFO",
        "RAW_TIMER_THREAD",
        "Creates a timer-backed raw thread; ContextVar values do not propagate automatically.",
    ),
    "make_sync_tool_wrapper": _CallRule(
        "INFO",
        "SYNC_TOOL_WRAPPER",
        "Adapts an async tool coroutine for synchronous tool invocation.",
    ),
}
THREAD_POOL_CONSTRUCTORS = {"concurrent.futures.ThreadPoolExecutor"}
ASYNC_TOOL_FACTORY_CALLS = {
    "StructuredTool.from_function",
    "langchain.tools.StructuredTool.from_function",
    "langchain_core.tools.StructuredTool.from_function",
}
LANGCHAIN_INVOKE_RECEIVER_NAMES = {
    "agent",
    "chain",
    "chat_model",
    "graph",
    "llm",
    "model",
    "runnable",
}
LANGCHAIN_INVOKE_RECEIVER_SUFFIXES = (
    "_agent",
    "_chain",
    "_graph",
    "_llm",
    "_model",
    "_runnable",
)

ASYNC_BLOCKING_CALL_RULES: dict[str, _CallRule] = {
    "time.sleep": _CallRule(
        "WARN",
        "BLOCKING_CALL_IN_ASYNC",
        "Blocks the event loop when called directly inside async code.",
    ),
    "subprocess.run": _CallRule(
        "WARN",
        "BLOCKING_SUBPROCESS_IN_ASYNC",
        "Runs a blocking subprocess from async code.",
    ),
    "subprocess.check_call": _CallRule(
        "WARN",
        "BLOCKING_SUBPROCESS_IN_ASYNC",
        "Runs a blocking subprocess from async code.",
    ),
    "subprocess.check_output": _CallRule(
        "WARN",
        "BLOCKING_SUBPROCESS_IN_ASYNC",
        "Runs a blocking subprocess from async code.",
    ),
    "subprocess.Popen": _CallRule(
        "WARN",
        "BLOCKING_SUBPROCESS_IN_ASYNC",
        "Starts a subprocess from async code; review whether it blocks later.",
    ),
}


def dotted_name(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = dotted_name(node.value)
        if parent:
            return f"{parent}.{node.attr}"
        return node.attr
    return None


def call_receiver_name(node: ast.Call) -> str | None:
    if not isinstance(node.func, ast.Attribute):
        return None
    return dotted_name(node.func.value)


def is_none_node(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


class BoundaryVisitor(ast.NodeVisitor):
    def __init__(self, path: Path, relative_path: str, source_lines: Sequence[str]) -> None:
        self.path = path
        self.relative_path = relative_path
        self.source_lines = source_lines
        self.findings: list[BoundaryFinding] = []
        self.function_stack: list[_FunctionContext] = []
        self.import_aliases: dict[str, str] = {}
        self.executor_names: set[str] = set()

    @property
    def current_function(self) -> str:
        if not self.function_stack:
            return "<module>"
        return ".".join(context.name for context in self.function_stack)

    @property
    def in_async_context(self) -> bool:
        return bool(self.function_stack and self.function_stack[-1].is_async)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            local_name = alias.asname or alias.name.split(".", 1)[0]
            canonical_name = alias.name if alias.asname else local_name
            self.import_aliases[local_name] = canonical_name

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module is None:
            return
        for alias in node.names:
            local_name = alias.asname or alias.name
            self.import_aliases[local_name] = f"{node.module}.{alias.name}"

    def visit_Assign(self, node: ast.Assign) -> None:
        self._record_executor_targets(node.value, node.targets)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self._record_executor_targets(node.value, [node.target])
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            if item.optional_vars is not None:
                self._record_executor_targets(item.context_expr, [item.optional_vars])
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.function_stack.append(_FunctionContext(node.name, is_async=False))
        self.generic_visit(node)
        self.function_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.function_stack.append(_FunctionContext(node.name, is_async=True))
        try:
            self._check_async_tool_definition(node)
            self.generic_visit(node)
        finally:
            self.function_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        call_name = self._canonical_name(dotted_name(node.func))
        if call_name:
            self._check_call(node, call_name)
        self.generic_visit(node)

    def _check_async_tool_definition(self, node: ast.AsyncFunctionDef) -> None:
        for decorator in node.decorator_list:
            decorator_call = decorator.func if isinstance(decorator, ast.Call) else decorator
            decorator_name = self._canonical_name(dotted_name(decorator_call))
            if decorator_name in {"langchain.tools.tool", "langchain_core.tools.tool"}:
                self._emit(
                    node,
                    severity="INFO",
                    category="ASYNC_TOOL_DEFINITION",
                    symbol=decorator_name,
                    message="Defines an async LangChain tool; sync clients need a wrapper before invoke().",
                )
                return

    def _check_call(self, node: ast.Call, call_name: str) -> None:
        rule = EXACT_CALL_RULES.get(call_name)
        if rule:
            self._emit_rule(node, call_name, rule)

        if call_name.endswith(".run_until_complete"):
            self._emit(
                node,
                severity="WARN",
                category="RUN_UNTIL_COMPLETE",
                symbol=call_name,
                message="Drives an event loop from synchronous code; review nested-loop behavior.",
            )

        if self._is_executor_submit(node, call_name):
            self._emit(
                node,
                severity="INFO",
                category="EXECUTOR_SUBMIT",
                symbol=call_name,
                message="Submits work to an executor; review context propagation and cancellation.",
            )

        if call_name in ASYNC_TOOL_FACTORY_CALLS:
            if any(keyword.arg == "coroutine" and not is_none_node(keyword.value) for keyword in node.keywords):
                self._emit(
                    node,
                    severity="INFO",
                    category="ASYNC_ONLY_TOOL_FACTORY",
                    symbol=call_name,
                    message="Creates a StructuredTool from a coroutine; sync clients need a wrapper.",
                )

        if self.in_async_context and call_name in ASYNC_BLOCKING_CALL_RULES:
            self._emit_rule(node, call_name, ASYNC_BLOCKING_CALL_RULES[call_name])

        if self.in_async_context and self._is_langchain_invoke(node, call_name, method_name="invoke"):
            self._emit(
                node,
                severity="WARN",
                category="SYNC_INVOKE_IN_ASYNC",
                symbol=call_name,
                message="Calls a synchronous invoke() from async code; review event-loop blocking.",
            )

        if not self.in_async_context and self._is_langchain_invoke(node, call_name, method_name="ainvoke"):
            self._emit(
                node,
                severity="WARN",
                category="ASYNC_INVOKE_IN_SYNC",
                symbol=call_name,
                message="Calls async ainvoke() from sync code; review how the coroutine is awaited.",
            )

    def _canonical_name(self, name: str | None) -> str | None:
        if name is None:
            return None
        parts = name.split(".")
        if parts and parts[0] in self.import_aliases:
            return ".".join((self.import_aliases[parts[0]], *parts[1:]))
        return name

    def _record_executor_targets(self, value: ast.AST, targets: Sequence[ast.AST]) -> None:
        if not isinstance(value, ast.Call):
            return
        call_name = self._canonical_name(dotted_name(value.func))
        if call_name not in THREAD_POOL_CONSTRUCTORS:
            return
        for target in targets:
            for name in self._target_names(target):
                self.executor_names.add(name)

    def _target_names(self, target: ast.AST) -> Iterable[str]:
        if isinstance(target, ast.Name):
            yield target.id
        elif isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                yield from self._target_names(element)

    def _is_executor_submit(self, node: ast.Call, call_name: str) -> bool:
        if not call_name.endswith(".submit"):
            return False
        receiver_name = call_receiver_name(node)
        return receiver_name in self.executor_names

    def _is_langchain_invoke(self, node: ast.Call, call_name: str, *, method_name: str) -> bool:
        if not call_name.endswith(f".{method_name}"):
            return False
        receiver_name = call_receiver_name(node)
        if receiver_name is None:
            return False
        receiver_leaf = receiver_name.rsplit(".", 1)[-1]
        return receiver_leaf in LANGCHAIN_INVOKE_RECEIVER_NAMES or receiver_leaf.endswith(LANGCHAIN_INVOKE_RECEIVER_SUFFIXES)

    def _emit_rule(self, node: ast.AST, symbol: str, rule: _CallRule) -> None:
        self._emit(
            node,
            severity=rule.severity,
            category=rule.category,
            symbol=symbol,
            message=rule.message,
        )

    def _emit(self, node: ast.AST, *, severity: str, category: str, symbol: str, message: str) -> None:
        line = getattr(node, "lineno", 0)
        column = getattr(node, "col_offset", 0)
        code = ""
        if line > 0 and line <= len(self.source_lines):
            code = self.source_lines[line - 1].strip()
        self.findings.append(
            BoundaryFinding(
                severity=severity,
                category=category,
                path=self.relative_path,
                line=line,
                column=column,
                function=self.current_function,
                async_context=self.in_async_context,
                symbol=symbol,
                message=message,
                code=code,
            )
        )


def relative_to_repo(path: Path, repo_root: Path = REPO_ROOT) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def scan_file(path: Path, *, repo_root: Path = REPO_ROOT) -> list[BoundaryFinding]:
    source = path.read_text(encoding="utf-8")
    source_lines = source.splitlines()
    relative_path = relative_to_repo(path, repo_root)
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        line = exc.lineno or 0
        code = source_lines[line - 1].strip() if line > 0 and line <= len(source_lines) else ""
        return [
            BoundaryFinding(
                severity="WARN",
                category="PARSE_ERROR",
                path=relative_path,
                line=line,
                column=max((exc.offset or 1) - 1, 0),
                function="<module>",
                async_context=False,
                symbol="SyntaxError",
                message=str(exc),
                code=code,
            )
        ]

    visitor = BoundaryVisitor(path, relative_path, source_lines)
    visitor.visit(tree)
    return visitor.findings


def is_ignored_path(path: Path) -> bool:
    return any(part in IGNORED_DIR_NAMES for part in path.parts)


def iter_python_files(paths: Iterable[Path]) -> Iterable[Path]:
    for path in paths:
        if not path.exists() or is_ignored_path(path):
            continue
        if path.is_file():
            if path.suffix == ".py" and not is_ignored_path(path):
                yield path
            continue
        for dirpath, dirnames, filenames in os.walk(path):
            dirnames[:] = [dirname for dirname in dirnames if dirname not in IGNORED_DIR_NAMES]
            for filename in filenames:
                if filename.endswith(".py"):
                    yield Path(dirpath) / filename


def scan_paths(paths: Iterable[Path], *, repo_root: Path = REPO_ROOT) -> list[BoundaryFinding]:
    findings: list[BoundaryFinding] = []
    for path in sorted(iter_python_files(paths)):
        findings.extend(scan_file(path, repo_root=repo_root))
    return sorted(findings, key=lambda finding: (finding.path, finding.line, finding.column, finding.category))


def filter_findings(findings: Iterable[BoundaryFinding], min_severity: str) -> list[BoundaryFinding]:
    threshold = SEVERITY_ORDER[min_severity]
    return [finding for finding in findings if SEVERITY_ORDER[finding.severity] >= threshold]


def format_text(findings: Sequence[BoundaryFinding]) -> str:
    if not findings:
        return "No async/thread boundary findings."

    lines: list[str] = []
    for finding in findings:
        lines.append(f"{finding.severity} {finding.category} {finding.path}:{finding.line}:{finding.column + 1} in {finding.function} async={str(finding.async_context).lower()}")
        lines.append(f"  symbol: {finding.symbol}")
        lines.append(f"  note: {finding.message}")
        if finding.code:
            lines.append(f"  code: {finding.code}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=("Detect async/thread boundary points for developer review. Findings are an inventory, not automatic bug decisions."))
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Files or directories to scan. Defaults to backend app and harness sources.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    parser.add_argument(
        "--min-severity",
        choices=tuple(SEVERITY_ORDER),
        default="INFO",
        help="Only show findings at or above this severity.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    paths = args.paths or list(DEFAULT_SCAN_PATHS)
    findings = filter_findings(scan_paths(paths), args.min_severity)

    if args.format == "json":
        print(json.dumps([finding.to_dict() for finding in findings], indent=2, sort_keys=True))
    else:
        print(format_text(findings))
    return 0
