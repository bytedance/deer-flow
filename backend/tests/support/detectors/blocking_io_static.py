"""Static inventory for likely backend event-loop blocking IO.

This detector parses backend business source with AST so untested paths are
still visible during review. Findings are prioritized static candidates, not
automatic bug decisions.

Not directly executable: import as `support.detectors.blocking_io_static` or
run via the CLI shim `scripts/detect_blocking_io_static.py`.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
from collections import Counter, defaultdict, deque
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from support.detectors.repo_root import resolve_repo_root

REPO_ROOT = resolve_repo_root(Path(__file__))
DEFAULT_SCAN_PATHS = (
    REPO_ROOT / "backend" / "app",
    REPO_ROOT / "backend" / "packages" / "harness" / "deerflow",
    REPO_ROOT / "backend" / "scripts",
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
CODE_SNIPPET_LIMIT = 200

PATH_METHOD_NAMES = {
    "exists",
    "glob",
    "hardlink_to",
    "is_dir",
    "is_file",
    "iterdir",
    "mkdir",
    "open",
    "readlink",
    "read_bytes",
    "read_text",
    "rename",
    "resolve",
    "rglob",
    "rmdir",
    "samefile",
    "stat",
    "symlink_to",
    "touch",
    "unlink",
    "write_bytes",
    "write_text",
}
AMBIGUOUS_PATH_METHOD_NAMES = {"replace"}
HTTP_METHOD_NAMES = {
    "delete",
    "get",
    "head",
    "options",
    "patch",
    "post",
    "put",
    "request",
    "stream",
}
BUILTIN_OPEN_NAMES = {"builtins.open", "io.open", "open"}
BLOCKING_SLEEP_NAMES = {"time.sleep"}
BLOCKING_OS_FILE_NAMES = {
    "os.listdir",
    "os.lstat",
    "os.makedirs",
    "os.mkdir",
    "os.remove",
    "os.rename",
    "os.replace",
    "os.rmdir",
    "os.scandir",
    "os.stat",
    "os.unlink",
    "os.walk",
    "os.path.exists",
    "os.path.getsize",
    "os.path.isdir",
    "os.path.isfile",
}
BLOCKING_SUBPROCESS_NAMES = {
    "subprocess.Popen",
    "subprocess.check_call",
    "subprocess.check_output",
    "subprocess.run",
}
BLOCKING_HTTP_NAMES = {
    "requests.delete",
    "requests.get",
    "requests.head",
    "requests.options",
    "requests.patch",
    "requests.post",
    "requests.put",
    "requests.request",
    "requests.sessions.Session.request",
    "httpx.delete",
    "httpx.get",
    "httpx.head",
    "httpx.options",
    "httpx.patch",
    "httpx.post",
    "httpx.put",
    "httpx.request",
    "httpx.stream",
    "urllib.request.urlopen",
}
SYNC_HTTP_CLIENT_FACTORIES = {
    "httpx.Client": "httpx.Client",
    "requests.Session": "requests.Session",
    "requests.sessions.Session": "requests.Session",
    "requests.session": "requests.Session",
}
BLOCKING_SHUTIL_NAMES = {
    "shutil.copy",
    "shutil.copyfile",
    "shutil.copytree",
    "shutil.move",
    "shutil.rmtree",
}
SYNC_AGENT_MIDDLEWARE_HOOKS = {
    "before_agent": "abefore_agent",
    "before_model": "abefore_model",
    "after_model": "aafter_model",
    "after_agent": "aafter_agent",
}
PATH_METHOD_OPERATIONS = {
    "exists": "FILE_METADATA",
    "glob": "FILE_ENUMERATION",
    "hardlink_to": "FILE_WRITE",
    "is_dir": "FILE_METADATA",
    "is_file": "FILE_METADATA",
    "iterdir": "FILE_ENUMERATION",
    "mkdir": "FILE_WRITE",
    "open": "FILE_OPEN",
    "readlink": "FILE_METADATA",
    "read_bytes": "FILE_READ",
    "read_text": "FILE_READ",
    "rename": "FILE_COPY_MOVE",
    "replace": "FILE_COPY_MOVE",
    "resolve": "FILE_METADATA",
    "rglob": "FILE_ENUMERATION",
    "rmdir": "FILE_DELETE",
    "samefile": "FILE_METADATA",
    "stat": "FILE_METADATA",
    "symlink_to": "FILE_WRITE",
    "touch": "FILE_WRITE",
    "unlink": "FILE_DELETE",
    "write_bytes": "FILE_WRITE",
    "write_text": "FILE_WRITE",
}
OS_FILE_OPERATIONS = {
    "os.listdir": "FILE_ENUMERATION",
    "os.lstat": "FILE_METADATA",
    "os.makedirs": "FILE_WRITE",
    "os.mkdir": "FILE_WRITE",
    "os.remove": "FILE_DELETE",
    "os.rename": "FILE_COPY_MOVE",
    "os.replace": "FILE_COPY_MOVE",
    "os.rmdir": "FILE_DELETE",
    "os.scandir": "FILE_ENUMERATION",
    "os.stat": "FILE_METADATA",
    "os.unlink": "FILE_DELETE",
    "os.walk": "FILE_ENUMERATION",
    "os.path.exists": "FILE_METADATA",
    "os.path.getsize": "FILE_METADATA",
    "os.path.isdir": "FILE_METADATA",
    "os.path.isfile": "FILE_METADATA",
}
SHUTIL_OPERATIONS = {
    "shutil.copy": "FILE_COPY_MOVE",
    "shutil.copyfile": "FILE_COPY_MOVE",
    "shutil.copytree": "FILE_TREE_COPY",
    "shutil.move": "FILE_COPY_MOVE",
    "shutil.rmtree": "FILE_TREE_DELETE",
}
OPERATION_BASE_PRIORITY = {
    "FILE_METADATA": "LOW",
    "FILE_OPEN": "MEDIUM",
    "FILE_READ": "MEDIUM",
    "FILE_WRITE": "MEDIUM",
    "FILE_ENUMERATION": "HIGH",
    "FILE_DELETE": "MEDIUM",
    "FILE_COPY_MOVE": "HIGH",
    "FILE_TREE_COPY": "HIGH",
    "FILE_TREE_DELETE": "HIGH",
    "HTTP_REQUEST": "HIGH",
    "SUBPROCESS": "HIGH",
    "SLEEP": "HIGH",
    "PARSE_ERROR": "MEDIUM",
}


@dataclass(frozen=True)
class BlockingIOStaticFinding:
    category: str
    operation: str
    priority: str
    path: str
    line: int
    column: int
    function: str
    exposure: str
    symbol: str
    code: str

    def to_dict(self) -> dict[str, object]:
        return {
            "priority": self.priority,
            "location": {
                "path": self.path,
                "line": self.line,
                "column": self.column + 1,
                "function": self.function,
            },
            "blocking_call": {
                "category": self.category,
                "operation": self.operation,
                "symbol": self.symbol,
            },
            "event_loop_exposure": self.exposure,
            "reason": _finding_reason(self.operation, self.exposure),
            "code": self.code,
        }


@dataclass(frozen=True)
class _FunctionContext:
    qualname: str
    class_name: str | None
    is_async: bool


@dataclass(frozen=True)
class _FunctionInfo:
    is_async: bool


@dataclass(frozen=True)
class _CallRef:
    name: str
    class_name: str | None
    self_method: bool


@dataclass(frozen=True)
class _PotentialFinding:
    category: str
    operation: str
    path: str
    line: int
    column: int
    function: str
    symbol: str
    code: str


@dataclass(frozen=True)
class _BlockingRule:
    category: str
    operation: str
    symbol: str


def dotted_name(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = dotted_name(node.value)
        if parent:
            return f"{parent}.{node.attr}"
        return node.attr
    if isinstance(node, ast.Call):
        return dotted_name(node.func)
    if isinstance(node, ast.Subscript):
        return dotted_name(node.value)
    return None


def relative_to_repo(path: Path, repo_root: Path = REPO_ROOT) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _source_snippet(source_lines: Sequence[str], line: int) -> str:
    if not 0 < line <= len(source_lines):
        return ""
    snippet = source_lines[line - 1].strip()
    if len(snippet) <= CODE_SNIPPET_LIMIT:
        return snippet
    return f"{snippet[:CODE_SNIPPET_LIMIT]}..."


class BlockingIOStaticVisitor(ast.NodeVisitor):
    def __init__(self, relative_path: str, source_lines: Sequence[str]) -> None:
        self.relative_path = relative_path
        self.source_lines = source_lines
        self.import_aliases: dict[str, str] = {}
        self.class_stack: list[str] = []
        self.function_stack: list[_FunctionContext] = []
        self.module_context = _FunctionContext("<module>", None, False)
        self.module_sync_http_clients: dict[str, str] = {}
        self.sync_http_client_stack: list[dict[str, str]] = []
        self.class_bases: dict[str, set[str]] = defaultdict(set)
        self.class_methods: dict[str, set[str]] = defaultdict(set)
        self.function_defs: dict[str, _FunctionInfo] = {}
        self.functions_by_name: dict[str, list[str]] = defaultdict(list)
        self.call_refs: dict[str, list[_CallRef]] = defaultdict(list)
        self.path_like_name_stack: list[set[str]] = []
        self.potential_findings: list[_PotentialFinding] = []

    @property
    def current_function(self) -> _FunctionContext | None:
        return self.function_stack[-1] if self.function_stack else None

    @property
    def current_context(self) -> _FunctionContext:
        return self.current_function or self.module_context

    @property
    def current_sync_http_clients(self) -> dict[str, str]:
        return self.sync_http_client_stack[-1] if self.sync_http_client_stack else self.module_sync_http_clients

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

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        class_name = ".".join((*self.class_stack, node.name)) if self.class_stack else node.name
        self.class_bases[class_name].update(canonical_name for base in node.bases if (canonical_name := self._canonical_name(dotted_name(base))) is not None)
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node, is_async=True)

    def visit_Assign(self, node: ast.Assign) -> None:
        self._record_sync_http_client_targets(node.value, node.targets)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._record_path_like_annotation(node.annotation, [node.target])
        if node.value is not None:
            self._record_sync_http_client_targets(node.value, [node.target])
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        temporary_clients: dict[str, str | None] = {}
        current_clients = self.current_sync_http_clients
        for item in node.items:
            self.visit(item.context_expr)
            client_base = self._sync_http_client_factory_base(item.context_expr)
            if client_base is None or not isinstance(item.optional_vars, ast.Name):
                continue
            name = item.optional_vars.id
            temporary_clients[name] = current_clients.get(name)
            current_clients[name] = client_base

        try:
            for statement in node.body:
                self.visit(statement)
        finally:
            for name, previous in temporary_clients.items():
                if previous is None:
                    current_clients.pop(name, None)
                else:
                    current_clients[name] = previous

    def visit_Call(self, node: ast.Call) -> None:
        current = self.current_context
        call_name = self._canonical_name(dotted_name(node.func))
        if call_name is not None:
            self._record_call_ref(node, call_name, current)
            self._record_blocking_candidate(node, call_name, current)
        self.generic_visit(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef, *, is_async: bool) -> None:
        qualname = ".".join((*self.class_stack, node.name)) if self.class_stack else node.name
        class_name = self.class_stack[-1] if self.class_stack else None
        context = _FunctionContext(qualname, class_name, is_async)
        self.function_defs[qualname] = _FunctionInfo(is_async)
        self.functions_by_name[node.name].append(qualname)
        if class_name is not None:
            self.class_methods[class_name].add(node.name)
        self.function_stack.append(context)
        self.sync_http_client_stack.append({})
        self.path_like_name_stack.append(set(_path_like_argument_names(node.args, self._canonical_name)))
        self.generic_visit(node)
        self.path_like_name_stack.pop()
        self.sync_http_client_stack.pop()
        self.function_stack.pop()

    def _canonical_name(self, name: str | None) -> str | None:
        if name is None:
            return None
        parts = name.split(".")
        if parts and parts[0] in self.import_aliases:
            return ".".join((self.import_aliases[parts[0]], *parts[1:]))
        return name

    def _record_call_ref(self, node: ast.Call, call_name: str, current: _FunctionContext) -> None:
        if current.qualname == "<module>":
            return
        if isinstance(node.func, ast.Name):
            self.call_refs[current.qualname].append(_CallRef(node.func.id, current.class_name, self_method=False))
            return
        if not isinstance(node.func, ast.Attribute):
            return
        receiver = dotted_name(node.func.value)
        if receiver in {"self", "cls"}:
            self.call_refs[current.qualname].append(_CallRef(node.func.attr, current.class_name, self_method=True))
            return
        # Keep same-module direct calls through canonical aliases out of the call graph.
        # External calls are handled as blocking candidates instead.
        if "." not in call_name:
            self.call_refs[current.qualname].append(_CallRef(call_name, current.class_name, self_method=False))

    def _record_blocking_candidate(self, node: ast.Call, call_name: str, current: _FunctionContext) -> None:
        rule = self._blocking_rule(node, call_name)
        if rule is None:
            return
        line = getattr(node, "lineno", 0)
        column = getattr(node, "col_offset", 0)
        code = _source_snippet(self.source_lines, line)
        self.potential_findings.append(
            _PotentialFinding(
                category=rule.category,
                operation=rule.operation,
                path=self.relative_path,
                line=line,
                column=column,
                function=current.qualname,
                symbol=rule.symbol,
                code=code,
            )
        )

    def _blocking_rule(self, node: ast.Call, call_name: str) -> _BlockingRule | None:
        sync_client_symbol = self._sync_http_client_method_symbol(call_name)
        if sync_client_symbol is not None:
            return _BlockingRule("BLOCKING_HTTP_IO", "HTTP_REQUEST", sync_client_symbol)
        chained_client_symbol = _sync_http_client_chained_method_symbol(call_name)
        if chained_client_symbol is not None:
            return _BlockingRule("BLOCKING_HTTP_IO", "HTTP_REQUEST", chained_client_symbol)
        leaf_name = call_name.rsplit(".", 1)[-1]
        if call_name in BUILTIN_OPEN_NAMES:
            return _BlockingRule("BLOCKING_FILE_IO", "FILE_OPEN", call_name)
        if leaf_name in PATH_METHOD_NAMES | AMBIGUOUS_PATH_METHOD_NAMES:
            if self._is_path_method_call(node):
                return _BlockingRule("BLOCKING_FILE_IO", _path_method_operation(leaf_name), call_name)
        if call_name in BLOCKING_OS_FILE_NAMES:
            return _BlockingRule("BLOCKING_FILE_IO", OS_FILE_OPERATIONS[call_name], call_name)
        if call_name in BLOCKING_SLEEP_NAMES:
            return _BlockingRule("BLOCKING_SLEEP", "SLEEP", call_name)
        if call_name in BLOCKING_SUBPROCESS_NAMES:
            return _BlockingRule("BLOCKING_SUBPROCESS", "SUBPROCESS", call_name)
        if call_name in BLOCKING_HTTP_NAMES:
            return _BlockingRule("BLOCKING_HTTP_IO", "HTTP_REQUEST", call_name)
        if call_name in BLOCKING_SHUTIL_NAMES:
            return _BlockingRule("BLOCKING_FILE_IO", SHUTIL_OPERATIONS[call_name], call_name)
        return None

    def _is_path_method_call(self, node: ast.Call) -> bool:
        if not isinstance(node.func, ast.Attribute):
            return False
        if node.func.attr in AMBIGUOUS_PATH_METHOD_NAMES and node.func.attr == "replace" and len(node.args) >= 2:
            return False
        receiver = node.func.value
        if _is_constructed_path(receiver):
            return True
        receiver_name = dotted_name(receiver)
        if receiver_name in self.current_path_like_names:
            return True
        if _looks_like_path_receiver_name(receiver_name):
            return True
        if node.func.attr in PATH_METHOD_NAMES and isinstance(receiver, ast.Attribute):
            return True
        return False

    @property
    def current_path_like_names(self) -> set[str]:
        return self.path_like_name_stack[-1] if self.path_like_name_stack else set()

    def _record_path_like_annotation(self, annotation: ast.AST, targets: Iterable[ast.AST]) -> None:
        if not self.path_like_name_stack or not _is_path_annotation(annotation, self._canonical_name):
            return
        self.current_path_like_names.update(name for target in targets for name in _iter_assigned_names(target))

    def _record_sync_http_client_targets(self, value: ast.AST, targets: Iterable[ast.AST]) -> None:
        client_base = self._sync_http_client_factory_base(value)
        if client_base is None:
            return
        current_clients = self.current_sync_http_clients
        for target in targets:
            for name in _iter_assigned_names(target):
                current_clients[name] = client_base

    def _sync_http_client_factory_base(self, node: ast.AST) -> str | None:
        if not isinstance(node, ast.Call):
            return None
        call_name = self._canonical_name(dotted_name(node.func))
        if call_name is None:
            return None
        return SYNC_HTTP_CLIENT_FACTORIES.get(call_name)

    def _sync_http_client_method_symbol(self, call_name: str) -> str | None:
        parts = call_name.split(".")
        if len(parts) != 2 or parts[1] not in HTTP_METHOD_NAMES:
            return None
        client_base = self.current_sync_http_clients.get(parts[0])
        if client_base is None:
            return None
        return f"{client_base}.{parts[1]}"


def _path_method_operation(method_name: str) -> str:
    return PATH_METHOD_OPERATIONS.get(method_name, "FILE_METADATA")


def _is_constructed_path(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and dotted_name(node.func) in {"Path", "pathlib.Path"}


def _looks_like_path_receiver_name(receiver_name: str | None) -> bool:
    if receiver_name is None:
        return False
    leaf = receiver_name.rsplit(".", 1)[-1].lower()
    return leaf in {"path", "file_path", "dir_path", "target", "dest", "destination", "source"} or leaf.endswith(("_path", "_dir", "_file", "_root")) or "path" in leaf


def _is_path_annotation(annotation: ast.AST | None, canonical_name: Callable[[str | None], str | None]) -> bool:
    if annotation is None:
        return False
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        return _is_path_annotation(annotation.left, canonical_name) or _is_path_annotation(annotation.right, canonical_name)
    name = dotted_name(annotation)
    canonical = canonical_name(name)
    if canonical in {"pathlib.Path", "Path"}:
        return True
    if isinstance(annotation, ast.Subscript):
        return _is_path_annotation(annotation.slice, canonical_name)
    return False


def _path_like_argument_names(arguments: ast.arguments, canonical_name: Callable[[str | None], str | None]) -> Iterable[str]:
    candidates = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
    if arguments.vararg is not None:
        candidates.append(arguments.vararg)
    if arguments.kwarg is not None:
        candidates.append(arguments.kwarg)
    for argument in candidates:
        if _is_path_annotation(argument.annotation, canonical_name):
            yield argument.arg


def _iter_assigned_names(target: ast.AST) -> Iterable[str]:
    if isinstance(target, ast.Name):
        yield target.id
        return
    if isinstance(target, (ast.Tuple, ast.List)):
        for element in target.elts:
            yield from _iter_assigned_names(element)


def _sync_http_client_chained_method_symbol(call_name: str) -> str | None:
    for factory_name, client_base in SYNC_HTTP_CLIENT_FACTORIES.items():
        prefix = f"{factory_name}."
        if not call_name.startswith(prefix):
            continue
        method_name = call_name[len(prefix) :]
        if method_name in HTTP_METHOD_NAMES:
            return f"{client_base}.{method_name}"
    return None


def _resolve_call_ref(visitor: BlockingIOStaticVisitor, ref: _CallRef) -> list[str]:
    if ref.self_method and ref.class_name is not None:
        qualname = f"{ref.class_name}.{ref.name}"
        return [qualname] if qualname in visitor.function_defs else []
    return list(visitor.functions_by_name.get(ref.name, ()))


def _reachable_functions(visitor: BlockingIOStaticVisitor, roots: Iterable[str]) -> set[str]:
    reachable = set(roots)
    queue: deque[str] = deque(reachable)
    while queue:
        qualname = queue.popleft()
        for ref in visitor.call_refs.get(qualname, ()):
            for target in _resolve_call_ref(visitor, ref):
                if target in reachable:
                    continue
                reachable.add(target)
                queue.append(target)
    return reachable


def _async_reachable_functions(visitor: BlockingIOStaticVisitor) -> set[str]:
    return _reachable_functions(
        visitor,
        (qualname for qualname, info in visitor.function_defs.items() if info.is_async),
    )


def _agent_middleware_classes(visitor: BlockingIOStaticVisitor) -> set[str]:
    middleware_classes: set[str] = set()
    changed = True
    while changed:
        changed = False
        for class_name, bases in visitor.class_bases.items():
            if class_name in middleware_classes:
                continue
            if any(_is_agent_middleware_base(base, middleware_classes) for base in bases):
                middleware_classes.add(class_name)
                changed = True
    return middleware_classes


def _is_agent_middleware_base(base: str, known_middleware_classes: set[str]) -> bool:
    leaf = base.rsplit(".", 1)[-1]
    return leaf == "AgentMiddleware" or leaf in known_middleware_classes


def _sync_only_agent_middleware_entrypoints(visitor: BlockingIOStaticVisitor) -> set[str]:
    entrypoints: set[str] = set()
    middleware_classes = _agent_middleware_classes(visitor)
    for class_name in middleware_classes:
        methods = visitor.class_methods.get(class_name, set())
        for sync_hook, async_hook in SYNC_AGENT_MIDDLEWARE_HOOKS.items():
            if sync_hook in methods and async_hook not in methods:
                qualname = f"{class_name}.{sync_hook}"
                if qualname in visitor.function_defs:
                    entrypoints.add(qualname)
    return entrypoints


def _event_loop_exposures(
    visitor: BlockingIOStaticVisitor,
    async_reachable: set[str],
    middleware_reachable: set[str],
) -> dict[str, str]:
    exposures: dict[str, str] = {}
    for qualname, info in visitor.function_defs.items():
        if info.is_async:
            exposures[qualname] = "DIRECT_ASYNC"
    for qualname in async_reachable:
        exposures.setdefault(qualname, "ASYNC_REACHABLE_SAME_FILE")
    for qualname in middleware_reachable:
        exposures.setdefault(qualname, "SYNC_AGENT_MIDDLEWARE_HOOK")
    return exposures


def _priority(operation: str) -> str:
    return OPERATION_BASE_PRIORITY[operation]


def _finding_reason(operation: str, exposure: str) -> str:
    if exposure == "DIRECT_ASYNC":
        return f"{operation} is called directly inside an async function."
    if exposure == "ASYNC_REACHABLE_SAME_FILE":
        return f"{operation} is statically reachable from an async function in the same file."
    if exposure == "SYNC_AGENT_MIDDLEWARE_HOOK":
        return f"{operation} is statically reachable from a sync AgentMiddleware hook used by the async graph."
    return "Source could not be parsed; scan coverage is incomplete for this file."


def _finalize_findings(visitor: BlockingIOStaticVisitor) -> list[BlockingIOStaticFinding]:
    reachable = _async_reachable_functions(visitor)
    middleware_reachable = _reachable_functions(visitor, _sync_only_agent_middleware_entrypoints(visitor))
    event_loop_exposures = _event_loop_exposures(visitor, reachable, middleware_reachable)
    findings: list[BlockingIOStaticFinding] = []
    for candidate in visitor.potential_findings:
        exposure = event_loop_exposures.get(candidate.function)
        if exposure is None:
            continue
        findings.append(
            BlockingIOStaticFinding(
                category=candidate.category,
                operation=candidate.operation,
                priority=_priority(candidate.operation),
                path=candidate.path,
                line=candidate.line,
                column=candidate.column,
                function=candidate.function,
                exposure=exposure,
                symbol=candidate.symbol,
                code=candidate.code,
            )
        )
    return findings


def scan_source(source: str, relative_path: str) -> list[BlockingIOStaticFinding]:
    """Scan one in-memory Python source; `relative_path` is reported verbatim in findings."""
    source_lines = source.splitlines()
    try:
        tree = ast.parse(source, filename=relative_path)
    except SyntaxError as exc:
        line = exc.lineno or 0
        code = _source_snippet(source_lines, line)
        return [
            BlockingIOStaticFinding(
                category="PARSE_ERROR",
                operation="PARSE_ERROR",
                priority="MEDIUM",
                path=relative_path,
                line=line,
                column=max((exc.offset or 1) - 1, 0),
                function="<module>",
                exposure="PARSE_INCOMPLETE",
                symbol="SyntaxError",
                code=code,
            )
        ]

    visitor = BlockingIOStaticVisitor(relative_path, source_lines)
    visitor.visit(tree)
    return sorted(_finalize_findings(visitor), key=lambda finding: (finding.path, finding.line, finding.column, finding.category))


def scan_file(path: Path, *, repo_root: Path = REPO_ROOT) -> list[BlockingIOStaticFinding]:
    return scan_source(path.read_text(encoding="utf-8"), relative_to_repo(path, repo_root))


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


def scan_paths(paths: Iterable[Path], *, repo_root: Path = REPO_ROOT) -> list[BlockingIOStaticFinding]:
    findings: list[BlockingIOStaticFinding] = []
    for path in sorted(iter_python_files(paths)):
        findings.extend(scan_file(path, repo_root=repo_root))
    return sorted(findings, key=lambda finding: (finding.path, finding.line, finding.column, finding.category))


def findings_to_json(findings: Sequence[BlockingIOStaticFinding]) -> str:
    return json.dumps([finding.to_dict() for finding in findings], indent=2) + "\n"


def write_json_report(findings: Sequence[BlockingIOStaticFinding], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(findings_to_json(findings), encoding="utf-8")


def _scan_root(path: str) -> str:
    parts = path.split("/")
    if parts[:4] == ["backend", "packages", "harness", "deerflow"]:
        return "backend/packages/harness/deerflow"
    if len(parts) >= 2 and parts[0] == "backend":
        return "/".join(parts[:2])
    return parts[0] if parts else path


def _format_counter(title: str, counter: Counter[str], *, limit: int | None = None, order: Sequence[str] | None = None) -> list[str]:
    lines = [title]
    if order is None:
        items = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    else:
        ordered = [(name, counter[name]) for name in order if counter.get(name)]
        ordered_names = {name for name, _ in ordered}
        extras = sorted((item for item in counter.items() if item[0] not in ordered_names), key=lambda item: (-item[1], item[0]))
        items = ordered + extras
    if limit is not None:
        items = items[:limit]
    width = max((len(str(count)) for _, count in items), default=1)
    lines.extend(f"  {count:>{width}}  {name}" for name, count in items)
    return lines


def format_summary(findings: Sequence[BlockingIOStaticFinding], *, output_path: Path | None = None) -> str:
    if not findings:
        lines = ["No static blocking IO event-loop risk findings in backend business code."]
    else:
        lines = [
            f"Static blocking IO event-loop risk findings: {len(findings)}",
            "",
            *_format_counter("By category:", Counter(finding.category for finding in findings)),
            "",
            *_format_counter("By priority:", Counter(finding.priority for finding in findings), order=("HIGH", "MEDIUM", "LOW")),
            "",
            *_format_counter("By operation:", Counter(finding.operation for finding in findings)),
            "",
            *_format_counter("By event-loop exposure:", Counter(finding.exposure for finding in findings)),
            "",
            *_format_counter("By scan root:", Counter(_scan_root(finding.path) for finding in findings)),
            "",
            *_format_counter("Top files:", Counter(finding.path for finding in findings), limit=10),
        ]

    if output_path is not None:
        lines.extend(["", f"Full JSON report: {relative_to_repo(output_path.resolve())}"])
    else:
        lines.extend(["", "Use --format json for full structured findings."])
    return "\n".join(lines)


def format_text(findings: Sequence[BlockingIOStaticFinding]) -> str:
    if not findings:
        return "No static blocking IO event-loop risk findings in backend business code."

    lines: list[str] = []
    for finding in findings:
        lines.append(f"{finding.priority} {finding.category}/{finding.operation} {finding.path}:{finding.line}:{finding.column + 1} in {finding.function} exposure={finding.exposure}")
        lines.append(f"  symbol: {finding.symbol}")
        lines.append(f"  reason: {_finding_reason(finding.operation, finding.exposure)}")
        if finding.code:
            lines.append(f"  code: {finding.code}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=("Statically inventory blocking IO calls that may block the backend asyncio event loop. Findings are prioritized review candidates, not automatic bug decisions."))
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
        help="Output format.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the complete finding list as JSON to this file.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    paths = args.paths or list(DEFAULT_SCAN_PATHS)
    findings = scan_paths(paths)
    output_path = args.output

    if output_path is not None:
        write_json_report(findings, output_path)

    if args.format == "summary":
        print(format_summary(findings, output_path=output_path))
    elif args.format == "json":
        print(findings_to_json(findings), end="")
    else:
        print(format_text(findings))
    return 0
