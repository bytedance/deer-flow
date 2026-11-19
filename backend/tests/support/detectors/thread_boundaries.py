"""Inventory backend async, executor, thread, and event-loop boundaries.

The static detector parses source without importing application modules.  The
optional runtime inspector resolves configured tool objects and model classes,
but never invokes a tool, instantiates a model, or calls an external service.

Not directly executable: import as ``support.detectors.thread_boundaries`` or
run via ``scripts/detect_thread_boundaries.py``.
"""

from __future__ import annotations

import argparse
import ast
import inspect
import json
import os
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

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
SCHEMA_VERSION = 1

# Stable machine-readable execution domains.  Keep these values independent of
# category names: categories explain what happened, while boundary_kind tells
# later starvation tests which worker domain a finding consumes.
ASYNCIO_DEFAULT_EXECUTOR = "asyncio_default_executor"
DEDICATED_EXECUTOR = "dedicated_executor"
ANYIO_WORKER_THREAD = "anyio_worker_thread"
DIRECT_EVENT_LOOP_BLOCKING = "direct_event_loop_blocking"
SEPARATE_EVENT_LOOP = "separate_event_loop"
UNRESOLVED_DYNAMIC_BOUNDARY = "unresolved_dynamic_boundary"
BOUNDARY_KINDS = (
    ASYNCIO_DEFAULT_EXECUTOR,
    DEDICATED_EXECUTOR,
    ANYIO_WORKER_THREAD,
    DIRECT_EVENT_LOOP_BLOCKING,
    SEPARATE_EVENT_LOOP,
    UNRESOLVED_DYNAMIC_BOUNDARY,
)


@dataclass(frozen=True)
class BoundaryFinding:
    severity: str
    category: str
    boundary_kind: str
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
class RuntimeToolFinding:
    configured_name: str | None
    name: str
    type: str
    source_module: str
    synchronous_function: str | None
    async_coroutine: str | None
    async_requires_default_executor: bool
    boundary_kind: str | None
    source: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class RuntimeModelFinding:
    name: str
    type: str
    source_module: str
    agenerate_overridden: bool
    astream_overridden: bool
    inherits_base_chat_model_executor_fallback: bool
    boundary_kind: str | None
    source: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class UnresolvedComponent:
    component_kind: str
    name: str
    source: str
    error: str
    boundary_kind: str = UNRESOLVED_DYNAMIC_BOUNDARY

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class RuntimeInventory:
    tools: list[RuntimeToolFinding]
    models: list[RuntimeModelFinding]
    unresolved: list[UnresolvedComponent]

    def to_dict(self) -> dict[str, object]:
        return {
            "tools": [tool.to_dict() for tool in self.tools],
            "models": [model.to_dict() for model in self.models],
            "unresolved": [component.to_dict() for component in self.unresolved],
        }


@dataclass(frozen=True)
class _FunctionContext:
    name: str
    is_async: bool


@dataclass(frozen=True)
class _CallRule:
    severity: str
    category: str
    boundary_kind: str
    message: str


EXACT_CALL_RULES: dict[str, _CallRule] = {
    "asyncio.run": _CallRule(
        "WARN",
        "SYNC_ASYNC_BRIDGE",
        SEPARATE_EVENT_LOOP,
        "Runs a coroutine from synchronous code by creating an event loop boundary.",
    ),
    "asyncio.to_thread": _CallRule(
        "INFO",
        "ASYNC_THREAD_OFFLOAD",
        ASYNCIO_DEFAULT_EXECUTOR,
        "Offloads synchronous work into the asyncio default executor.",
    ),
    "deerflow.utils.file_io.run_file_io": _CallRule(
        "INFO",
        "ASYNC_FILE_IO_OFFLOAD",
        DEDICATED_EXECUTOR,
        "Offloads filesystem work into DeerFlow's dedicated file-IO executor.",
    ),
    "anyio.to_thread.run_sync": _CallRule(
        "INFO",
        "ANYIO_WORKER_THREAD",
        ANYIO_WORKER_THREAD,
        "Offloads synchronous work into AnyIO's worker-thread limiter domain.",
    ),
    "starlette.concurrency.run_in_threadpool": _CallRule(
        "INFO",
        "ANYIO_WORKER_THREAD",
        ANYIO_WORKER_THREAD,
        "Offloads synchronous work through Starlette into AnyIO worker threads.",
    ),
    "asyncio.new_event_loop": _CallRule(
        "WARN",
        "NEW_EVENT_LOOP",
        SEPARATE_EVENT_LOOP,
        "Creates a separate event loop.",
    ),
    "asyncio.Runner": _CallRule(
        "WARN",
        "NEW_EVENT_LOOP",
        SEPARATE_EVENT_LOOP,
        "Creates an asyncio runner that owns a separate event loop.",
    ),
    "asyncio.run_coroutine_threadsafe": _CallRule(
        "WARN",
        "CROSS_THREAD_COROUTINE",
        SEPARATE_EVENT_LOOP,
        "Submits a coroutine to an event loop from another thread.",
    ),
    "concurrent.futures.ThreadPoolExecutor": _CallRule(
        "INFO",
        "THREAD_POOL",
        DEDICATED_EXECUTOR,
        "Creates a dedicated thread-pool executor.",
    ),
    "threading.Thread": _CallRule(
        "INFO",
        "RAW_THREAD",
        UNRESOLVED_DYNAMIC_BOUNDARY,
        "Creates a raw thread outside the classified executor domains.",
    ),
    "threading.Timer": _CallRule(
        "INFO",
        "RAW_TIMER_THREAD",
        UNRESOLVED_DYNAMIC_BOUNDARY,
        "Creates a timer-backed raw thread outside the classified executor domains.",
    ),
    "make_sync_tool_wrapper": _CallRule(
        "INFO",
        "SYNC_TOOL_WRAPPER",
        DEDICATED_EXECUTOR,
        "Adapts an async tool for sync invocation through DeerFlow's dedicated tool executor.",
    ),
    "deerflow.tools.sync.make_sync_tool_wrapper": _CallRule(
        "INFO",
        "SYNC_TOOL_WRAPPER",
        DEDICATED_EXECUTOR,
        "Adapts an async tool for sync invocation through DeerFlow's dedicated tool executor.",
    ),
}
THREAD_POOL_CONSTRUCTORS = {"concurrent.futures.ThreadPoolExecutor"}
RUN_IN_EXECUTOR_CALLS = {"langchain_core.runnables.run_in_executor"}
ASYNC_TOOL_FACTORY_CALLS = {
    "StructuredTool.from_function",
    "langchain.tools.StructuredTool.from_function",
    "langchain_core.tools.StructuredTool.from_function",
}
TOOL_DECORATORS = {
    "langchain.tools.tool",
    "langchain_core.tools.tool",
}
BASE_TOOL_CLASSES = {
    "langchain.tools.BaseTool",
    "langchain_core.tools.BaseTool",
    "langchain_core.tools.base.BaseTool",
}
STRUCTURED_TOOL_CLASSES = {
    "langchain.tools.StructuredTool",
    "langchain_core.tools.StructuredTool",
    "langchain_core.tools.structured.StructuredTool",
}
BASE_CHAT_MODEL_CLASSES = {
    "langchain.chat_models.BaseChatModel",
    "langchain_core.language_models.BaseChatModel",
    "langchain_core.language_models.chat_models.BaseChatModel",
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
        DIRECT_EVENT_LOOP_BLOCKING,
        "Blocks the event loop when called directly inside async code.",
    ),
    "subprocess.run": _CallRule(
        "WARN",
        "BLOCKING_SUBPROCESS_IN_ASYNC",
        DIRECT_EVENT_LOOP_BLOCKING,
        "Runs a blocking subprocess from async code.",
    ),
    "subprocess.check_call": _CallRule(
        "WARN",
        "BLOCKING_SUBPROCESS_IN_ASYNC",
        DIRECT_EVENT_LOOP_BLOCKING,
        "Runs a blocking subprocess from async code.",
    ),
    "subprocess.check_output": _CallRule(
        "WARN",
        "BLOCKING_SUBPROCESS_IN_ASYNC",
        DIRECT_EVENT_LOOP_BLOCKING,
        "Runs a blocking subprocess from async code.",
    ),
    "subprocess.Popen": _CallRule(
        "WARN",
        "BLOCKING_SUBPROCESS_IN_ASYNC",
        DIRECT_EVENT_LOOP_BLOCKING,
        "Starts a subprocess from async code; review whether later operations block.",
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
    def __init__(self, path: Path, relative_path: str, source_lines: Sequence[str], tree: ast.Module) -> None:
        self.path = path
        self.relative_path = relative_path
        self.source_lines = source_lines
        self.findings: list[BoundaryFinding] = []
        self.function_stack: list[_FunctionContext] = []
        self.import_aliases: dict[str, str] = {}
        self.executor_names: set[str] = set()
        self.thread_helpers: dict[str, str] = {}
        self._prepare(tree)

    @property
    def current_function(self) -> str:
        if not self.function_stack:
            return "<module>"
        return ".".join(context.name for context in self.function_stack)

    @property
    def in_async_context(self) -> bool:
        return bool(self.function_stack and self.function_stack[-1].is_async)

    def _prepare(self, tree: ast.Module) -> None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self._record_import(node)
            elif isinstance(node, ast.ImportFrom):
                self._record_import_from(node)
        self._discover_executor_names(tree)
        self._discover_thread_helpers(tree)

    def _discover_executor_names(self, tree: ast.Module) -> None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                self._record_executor_targets(node.value, node.targets)
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                self._record_executor_targets(node.value, [node.target])
            elif isinstance(node, ast.With):
                for item in node.items:
                    if item.optional_vars is not None:
                        self._record_executor_targets(item.context_expr, [item.optional_vars])

    def _record_import(self, node: ast.Import) -> None:
        for alias in node.names:
            local_name = alias.asname or alias.name.split(".", 1)[0]
            canonical_name = alias.name if alias.asname else local_name
            self.import_aliases[local_name] = canonical_name

    def _record_import_from(self, node: ast.ImportFrom) -> None:
        if node.module is None:
            return
        for alias in node.names:
            local_name = alias.asname or alias.name
            self.import_aliases[local_name] = f"{node.module}.{alias.name}"

    def visit_Import(self, node: ast.Import) -> None:
        self._record_import(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self._record_import_from(node)

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

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.function_stack.append(_FunctionContext(node.name, is_async=False))
        try:
            self._check_fallback_class(node)
            self.generic_visit(node)
        finally:
            self.function_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.function_stack.append(_FunctionContext(node.name, is_async=False))
        try:
            self._check_sync_tool_definition(node)
            self.generic_visit(node)
        finally:
            self.function_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.function_stack.append(_FunctionContext(node.name, is_async=True))
        try:
            self._check_async_tool_definition(node)
            self.generic_visit(node)
        finally:
            self.function_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        raw_name = dotted_name(node.func)
        call_name = self._canonical_name(raw_name)
        if call_name:
            self._check_call(node, raw_name or call_name, call_name)
        self.generic_visit(node)

    def _discover_thread_helpers(self, tree: ast.Module) -> None:
        """Discover simple same-module wrappers around a known offload call."""
        for definition in tree.body:
            if not isinstance(definition, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            kinds: set[str] = set()
            for node in ast.walk(definition):
                if not isinstance(node, ast.Call):
                    continue
                call_name = self._canonical_name(dotted_name(node.func))
                if call_name == "asyncio.to_thread":
                    kinds.add(ASYNCIO_DEFAULT_EXECUTOR)
                elif call_name in {
                    "anyio.to_thread.run_sync",
                    "starlette.concurrency.run_in_threadpool",
                }:
                    kinds.add(ANYIO_WORKER_THREAD)
                elif call_name == "deerflow.utils.file_io.run_file_io":
                    kinds.add(DEDICATED_EXECUTOR)
                elif self._is_run_in_executor(call_name):
                    kinds.add(self._executor_boundary_kind(node))
            if len(kinds) == 1:
                self.thread_helpers[definition.name] = kinds.pop()

    def _check_sync_tool_definition(self, node: ast.FunctionDef) -> None:
        if self._has_tool_decorator(node):
            self._emit(
                node,
                severity="INFO",
                category="SYNC_TOOL_DEFINITION",
                boundary_kind=ASYNCIO_DEFAULT_EXECUTOR,
                symbol=self._tool_decorator_name(node) or "tool",
                message="Defines a synchronous LangChain tool whose async fallback uses the default executor.",
            )

    def _check_async_tool_definition(self, node: ast.AsyncFunctionDef) -> None:
        decorator_name = self._tool_decorator_name(node)
        if decorator_name:
            self._emit(
                node,
                severity="INFO",
                category="ASYNC_TOOL_DEFINITION",
                boundary_kind=UNRESOLVED_DYNAMIC_BOUNDARY,
                symbol=decorator_name,
                message="Defines a native async LangChain tool; sync callers may still require a wrapper.",
            )

    def _has_tool_decorator(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        return self._tool_decorator_name(node) is not None

    def _tool_decorator_name(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
        for decorator in node.decorator_list:
            decorator_call = decorator.func if isinstance(decorator, ast.Call) else decorator
            decorator_name = self._canonical_name(dotted_name(decorator_call))
            if decorator_name in TOOL_DECORATORS:
                return decorator_name
        return None

    def _check_fallback_class(self, node: ast.ClassDef) -> None:
        base_names = {self._canonical_name(dotted_name(base)) for base in node.bases}
        method_names = {child.name for child in node.body if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))}
        if base_names & (BASE_TOOL_CLASSES | STRUCTURED_TOOL_CLASSES):
            if "_run" in method_names and "_arun" not in method_names:
                self._emit(
                    node,
                    severity="INFO",
                    category="SYNC_TOOL_CLASS_FALLBACK",
                    boundary_kind=ASYNCIO_DEFAULT_EXECUTOR,
                    symbol=node.name,
                    message="A sync-only BaseTool subclass inherits the default-executor async fallback.",
                )
        if base_names & BASE_CHAT_MODEL_CLASSES:
            if "_agenerate" not in method_names:
                self._emit(
                    node,
                    severity="INFO",
                    category="MODEL_AGENERATE_FALLBACK",
                    boundary_kind=ASYNCIO_DEFAULT_EXECUTOR,
                    symbol=node.name,
                    message="The model inherits BaseChatModel._agenerate's default-executor fallback.",
                )
            if "_astream" not in method_names:
                self._emit(
                    node,
                    severity="INFO",
                    category="MODEL_ASTREAM_FALLBACK",
                    boundary_kind=ASYNCIO_DEFAULT_EXECUTOR,
                    symbol=node.name,
                    message="The model inherits BaseChatModel._astream's default-executor fallback.",
                )

    def _check_call(self, node: ast.Call, raw_name: str, call_name: str) -> None:
        rule = EXACT_CALL_RULES.get(call_name)
        if rule:
            self._emit_rule(node, call_name, rule)

        if call_name.endswith(".new_event_loop") and call_name != "asyncio.new_event_loop":
            self._emit(
                node,
                severity="WARN",
                category="NEW_EVENT_LOOP",
                boundary_kind=SEPARATE_EVENT_LOOP,
                symbol=call_name,
                message="Creates a separate event loop through an event-loop policy or compatible API.",
            )

        if call_name.endswith(".run_until_complete"):
            self._emit(
                node,
                severity="WARN",
                category="RUN_UNTIL_COMPLETE",
                boundary_kind=SEPARATE_EVENT_LOOP,
                symbol=call_name,
                message="Drives an event loop synchronously.",
            )

        if self._is_run_in_executor(call_name):
            boundary_kind = self._executor_boundary_kind(node)
            category = {
                ASYNCIO_DEFAULT_EXECUTOR: "RUN_IN_DEFAULT_EXECUTOR",
                DEDICATED_EXECUTOR: "RUN_IN_DEDICATED_EXECUTOR",
                UNRESOLVED_DYNAMIC_BOUNDARY: "RUN_IN_DYNAMIC_EXECUTOR",
            }[boundary_kind]
            self._emit(
                node,
                severity="INFO",
                category=category,
                boundary_kind=boundary_kind,
                symbol=call_name,
                message="Submits work through run_in_executor; the executor argument determines ownership.",
            )

        if call_name.endswith(".set_default_executor"):
            self._emit(
                node,
                severity="INFO",
                category="SET_DEFAULT_EXECUTOR",
                boundary_kind=DEDICATED_EXECUTOR,
                symbol=call_name,
                message="Replaces an event loop's default executor with an explicitly owned executor.",
            )

        if self._is_executor_submit(node, raw_name):
            self._emit(
                node,
                severity="INFO",
                category="EXECUTOR_SUBMIT",
                boundary_kind=DEDICATED_EXECUTOR,
                symbol=call_name,
                message="Submits work directly to a dedicated ThreadPoolExecutor.",
            )

        if call_name in ASYNC_TOOL_FACTORY_CALLS:
            has_coroutine = any(keyword.arg == "coroutine" and not is_none_node(keyword.value) for keyword in node.keywords)
            if has_coroutine:
                self._emit(
                    node,
                    severity="INFO",
                    category="ASYNC_ONLY_TOOL_FACTORY",
                    boundary_kind=UNRESOLVED_DYNAMIC_BOUNDARY,
                    symbol=call_name,
                    message="Creates a StructuredTool with a native async coroutine.",
                )
            elif self._factory_has_sync_function(node):
                self._emit(
                    node,
                    severity="INFO",
                    category="SYNC_ONLY_TOOL_FACTORY",
                    boundary_kind=ASYNCIO_DEFAULT_EXECUTOR,
                    symbol=call_name,
                    message="Creates a sync-only StructuredTool whose async fallback uses the default executor.",
                )

        helper_kind = self.thread_helpers.get(raw_name)
        if helper_kind is not None and raw_name != self.current_function.rsplit(".", 1)[-1]:
            self._emit(
                node,
                severity="INFO",
                category="THREAD_HELPER_CALL",
                boundary_kind=helper_kind,
                symbol=raw_name,
                message="Calls a same-module helper that wraps a classified thread boundary.",
            )

        if self.in_async_context and call_name in ASYNC_BLOCKING_CALL_RULES:
            self._emit_rule(node, call_name, ASYNC_BLOCKING_CALL_RULES[call_name])

        if self.in_async_context and self._is_langchain_invoke(node, call_name, method_name="invoke"):
            self._emit(
                node,
                severity="WARN",
                category="SYNC_INVOKE_IN_ASYNC",
                boundary_kind=DIRECT_EVENT_LOOP_BLOCKING,
                symbol=call_name,
                message="Calls synchronous invoke() directly from async code.",
            )

        if not self.in_async_context and self._is_langchain_invoke(node, call_name, method_name="ainvoke"):
            self._emit(
                node,
                severity="WARN",
                category="ASYNC_INVOKE_IN_SYNC",
                boundary_kind=UNRESOLVED_DYNAMIC_BOUNDARY,
                symbol=call_name,
                message="Calls async ainvoke() from sync code; review how the coroutine is driven.",
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
            self.executor_names.update(self._target_names(target))

    def _target_names(self, target: ast.AST) -> Iterable[str]:
        name = dotted_name(target)
        if name:
            yield name
        elif isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                yield from self._target_names(element)

    def _is_executor_submit(self, node: ast.Call, raw_name: str) -> bool:
        if not raw_name.endswith(".submit"):
            return False
        receiver_name = call_receiver_name(node)
        return receiver_name in self.executor_names

    def _is_run_in_executor(self, call_name: str | None) -> bool:
        return bool(call_name and (call_name in RUN_IN_EXECUTOR_CALLS or call_name == "run_in_executor" or call_name.endswith(".run_in_executor")))

    def _executor_boundary_kind(self, node: ast.Call) -> str:
        executor_arg: ast.AST | None = node.args[0] if node.args else None
        for keyword in node.keywords:
            if keyword.arg == "executor":
                executor_arg = keyword.value
                break
        if is_none_node(executor_arg):
            return ASYNCIO_DEFAULT_EXECUTOR
        executor_name = dotted_name(executor_arg)
        if executor_name in self.executor_names:
            return DEDICATED_EXECUTOR
        return UNRESOLVED_DYNAMIC_BOUNDARY

    def _factory_has_sync_function(self, node: ast.Call) -> bool:
        if node.args and not is_none_node(node.args[0]):
            return True
        return any(keyword.arg == "func" and not is_none_node(keyword.value) for keyword in node.keywords)

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
            boundary_kind=rule.boundary_kind,
            symbol=symbol,
            message=rule.message,
        )

    def _emit(
        self,
        node: ast.AST,
        *,
        severity: str,
        category: str,
        boundary_kind: str,
        symbol: str,
        message: str,
    ) -> None:
        line = getattr(node, "lineno", 0)
        column = getattr(node, "col_offset", 0)
        code = ""
        if line > 0 and line <= len(self.source_lines):
            code = self.source_lines[line - 1].strip()
        self.findings.append(
            BoundaryFinding(
                severity=severity,
                category=category,
                boundary_kind=boundary_kind,
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
                boundary_kind=UNRESOLVED_DYNAMIC_BOUNDARY,
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

    visitor = BoundaryVisitor(path, relative_path, source_lines, tree)
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


def scan_paths(
    paths: Iterable[Path],
    *,
    repo_root: Path = REPO_ROOT,
) -> list[BoundaryFinding]:
    findings: list[BoundaryFinding] = []
    for path in sorted(iter_python_files(paths)):
        findings.extend(scan_file(path, repo_root=repo_root))
    return sorted(
        findings,
        key=lambda finding: (
            finding.path,
            finding.line,
            finding.column,
            finding.category,
        ),
    )


def filter_findings(
    findings: Iterable[BoundaryFinding],
    min_severity: str,
) -> list[BoundaryFinding]:
    threshold = SEVERITY_ORDER[min_severity]
    return [finding for finding in findings if SEVERITY_ORDER[finding.severity] >= threshold]


def _callable_reference(value: Any) -> str | None:
    if value is None or not callable(value):
        return None
    unwrapped = inspect.unwrap(value)
    module = getattr(unwrapped, "__module__", type(unwrapped).__module__)
    qualname = getattr(
        unwrapped,
        "__qualname__",
        getattr(unwrapped, "__name__", type(unwrapped).__qualname__),
    )
    return f"{module}.{qualname}"


def _type_reference(value: object | type) -> str:
    cls = value if isinstance(value, type) else type(value)
    return f"{cls.__module__}.{cls.__qualname__}"


def _inspect_tool(
    tool: object,
    *,
    configured_name: str | None = None,
    source: str | None = None,
) -> RuntimeToolFinding:
    from langchain_core.tools import BaseTool, StructuredTool

    tool_class = type(tool)
    coroutine = getattr(tool, "coroutine", None)
    sync_function = getattr(tool, "func", None)
    if not callable(sync_function):
        run_method = getattr(tool_class, "_run", None)
        sync_function = run_method if run_method is not None and run_method is not BaseTool._run else None

    arun_method = getattr(tool_class, "_arun", None)
    requires_default_executor = not callable(coroutine) and arun_method in {
        BaseTool._arun,
        StructuredTool._arun,
    }
    async_callable = coroutine
    if not callable(async_callable) and not requires_default_executor:
        async_callable = arun_method

    return RuntimeToolFinding(
        configured_name=configured_name,
        name=str(getattr(tool, "name", configured_name or tool_class.__name__)),
        type=_type_reference(tool),
        source_module=tool_class.__module__,
        synchronous_function=_callable_reference(sync_function),
        async_coroutine=_callable_reference(async_callable),
        async_requires_default_executor=requires_default_executor,
        boundary_kind=(ASYNCIO_DEFAULT_EXECUTOR if requires_default_executor else None),
        source=source,
    )


def _inspect_model(
    name: str,
    model: object | type,
    *,
    source: str | None = None,
) -> RuntimeModelFinding:
    from langchain_core.language_models.chat_models import BaseChatModel

    model_class = model if isinstance(model, type) else type(model)
    agenerate_overridden = getattr(model_class, "_agenerate", None) is not BaseChatModel._agenerate
    astream_overridden = getattr(model_class, "_astream", None) is not BaseChatModel._astream
    inherits_fallback = not agenerate_overridden or not astream_overridden
    return RuntimeModelFinding(
        name=name,
        type=_type_reference(model_class),
        source_module=model_class.__module__,
        agenerate_overridden=agenerate_overridden,
        astream_overridden=astream_overridden,
        inherits_base_chat_model_executor_fallback=inherits_fallback,
        boundary_kind=ASYNCIO_DEFAULT_EXECUTOR if inherits_fallback else None,
        source=source,
    )


def inspect_runtime_components(
    *,
    tools: Iterable[object] = (),
    models: Iterable[tuple[str, object | type]] = (),
) -> RuntimeInventory:
    """Inspect already-resolved components without invoking or constructing them."""
    return RuntimeInventory(
        tools=[_inspect_tool(tool) for tool in tools],
        models=[_inspect_model(name, model) for name, model in models],
        unresolved=[],
    )


def inspect_configured_components(
    config: object,
    *,
    resolve_tool: Callable[[str, type], object] | None = None,
    resolve_model: Callable[[str, type], type] | None = None,
) -> RuntimeInventory:
    """Resolve configured symbols and inspect them without external calls.

    Tool variables are imported because their concrete ``func``/``coroutine``
    attributes are runtime state. Model classes are imported but deliberately
    not instantiated, so provider constructors and network clients never run.
    Resolution failures are retained as unresolved dynamic boundaries.
    """
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.tools import BaseTool

    if resolve_tool is None or resolve_model is None:
        from deerflow.reflection import resolve_class, resolve_variable

        resolve_tool = resolve_tool or resolve_variable
        resolve_model = resolve_model or resolve_class

    tool_findings: list[RuntimeToolFinding] = []
    model_findings: list[RuntimeModelFinding] = []
    unresolved: list[UnresolvedComponent] = []

    for tool_config in getattr(config, "tools", ()):
        configured_name = str(getattr(tool_config, "name", "<unnamed>"))
        source = str(getattr(tool_config, "use", ""))
        try:
            tool = resolve_tool(source, BaseTool)
            tool_findings.append(
                _inspect_tool(
                    tool,
                    configured_name=configured_name,
                    source=source,
                )
            )
        except Exception as exc:
            unresolved.append(
                UnresolvedComponent(
                    component_kind="tool",
                    name=configured_name,
                    source=source,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )

    for model_config in getattr(config, "models", ()):
        model_name = str(getattr(model_config, "name", "<unnamed>"))
        source = str(getattr(model_config, "use", ""))
        try:
            model_class = resolve_model(source, BaseChatModel)
            model_findings.append(_inspect_model(model_name, model_class, source=source))
        except Exception as exc:
            unresolved.append(
                UnresolvedComponent(
                    component_kind="model",
                    name=model_name,
                    source=source,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )

    return RuntimeInventory(
        tools=tool_findings,
        models=model_findings,
        unresolved=unresolved,
    )


def _inspect_config_file(config_path: Path) -> RuntimeInventory:
    harness_path = REPO_ROOT / "backend" / "packages" / "harness"
    if str(harness_path) not in sys.path:
        sys.path.insert(0, str(harness_path))
    from deerflow.config.app_config import AppConfig

    config = AppConfig.from_file(str(config_path))
    return inspect_configured_components(config)


def build_summary(
    findings: Sequence[BoundaryFinding],
    runtime: RuntimeInventory | None = None,
) -> dict[str, object]:
    by_boundary_kind = Counter(finding.boundary_kind for finding in findings)
    by_category = Counter(finding.category for finding in findings)
    return {
        "static_findings": len(findings),
        "by_boundary_kind": {kind: by_boundary_kind.get(kind, 0) for kind in BOUNDARY_KINDS if by_boundary_kind.get(kind, 0)},
        "by_category": dict(sorted(by_category.items())),
        "runtime_tools": len(runtime.tools) if runtime else 0,
        "runtime_models": len(runtime.models) if runtime else 0,
        "runtime_unresolved": len(runtime.unresolved) if runtime else 0,
    }


def build_inventory_payload(
    findings: Sequence[BoundaryFinding],
    runtime: RuntimeInventory | None = None,
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "static_findings": [finding.to_dict() for finding in findings],
        "runtime": runtime.to_dict() if runtime is not None else None,
        "summary": build_summary(findings, runtime),
    }


def format_summary(
    findings: Sequence[BoundaryFinding],
    runtime: RuntimeInventory | None = None,
) -> str:
    summary = build_summary(findings, runtime)
    lines = [f"Thread-boundary inventory: {summary['static_findings']} static findings"]
    if runtime is not None:
        lines[0] += f", {summary['runtime_tools']} configured tools, {summary['runtime_models']} configured models, {summary['runtime_unresolved']} unresolved"
    boundary_counts = summary["by_boundary_kind"]
    if boundary_counts:
        lines.append("Execution domains:")
        for kind in BOUNDARY_KINDS:
            count = boundary_counts.get(kind)
            if count:
                lines.append(f"  {kind}: {count}")
    return "\n".join(lines)


def format_text(findings: Sequence[BoundaryFinding]) -> str:
    if not findings:
        return "No async/thread boundary findings."

    lines: list[str] = []
    for finding in findings:
        lines.append(f"{finding.severity} {finding.category} [{finding.boundary_kind}] {finding.path}:{finding.line}:{finding.column + 1} in {finding.function} async={str(finding.async_context).lower()}")
        lines.append(f"  symbol: {finding.symbol}")
        lines.append(f"  note: {finding.message}")
        if finding.code:
            lines.append(f"  code: {finding.code}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=("Inventory backend thread/executor/event-loop boundaries. Findings are evidence, not automatic bug decisions."))
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Files or directories to scan. Defaults to backend app and harness sources.",
    )
    parser.add_argument(
        "--format",
        choices=("summary", "text", "json"),
        default="summary",
        help="Console output format (default: concise summary).",
    )
    parser.add_argument(
        "--min-severity",
        choices=tuple(SEVERITY_ORDER),
        default="INFO",
        help="Only include findings at or above this severity.",
    )
    parser.add_argument(
        "--runtime-config",
        type=Path,
        help=("Inspect tools and model classes configured in this AppConfig YAML. Components are never invoked and models are never instantiated."),
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        help="Also write the complete versioned inventory JSON to this path.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    paths = args.paths or list(DEFAULT_SCAN_PATHS)
    findings = filter_findings(scan_paths(paths), args.min_severity)
    runtime = _inspect_config_file(args.runtime_config) if args.runtime_config is not None else None
    payload = build_inventory_payload(findings, runtime)

    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    if args.format == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif args.format == "text":
        print(format_text(findings))
        if runtime is not None:
            print()
            print(format_summary(findings, runtime))
    else:
        print(format_summary(findings, runtime))
    return 0
