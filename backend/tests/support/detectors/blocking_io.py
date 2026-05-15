"""Test helper for detecting blocking calls on an asyncio event loop.

The detector is intentionally test-only. It monkeypatches a small set of
well-known blocking entry points and their already-loaded module-level aliases,
then records calls only when they happen on a thread that is currently running
an asyncio event loop. Aliases captured in closures or default arguments remain
out of scope.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
import traceback
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from types import TracebackType
from typing import Any

BlockingCallable = Callable[..., Any]


@dataclass(frozen=True)
class BlockingCallSpec:
    """Describes one blocking callable to wrap during a detector run."""

    name: str
    target: str
    record_on_iteration: bool = False


@dataclass(frozen=True)
class BlockingCall:
    """One blocking call observed on an asyncio event loop thread."""

    name: str
    target: str
    stack: tuple[traceback.FrameSummary, ...]


DEFAULT_BLOCKING_CALL_SPECS: tuple[BlockingCallSpec, ...] = (
    BlockingCallSpec("time.sleep", "time:sleep"),
    BlockingCallSpec("requests.Session.request", "requests.sessions:Session.request"),
    BlockingCallSpec("httpx.Client.request", "httpx:Client.request"),
    BlockingCallSpec("os.walk", "os:walk", record_on_iteration=True),
    BlockingCallSpec("pathlib.Path.resolve", "pathlib:Path.resolve"),
    BlockingCallSpec("pathlib.Path.read_text", "pathlib:Path.read_text"),
    BlockingCallSpec("pathlib.Path.write_text", "pathlib:Path.write_text"),
)


def _is_event_loop_thread() -> bool:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False
    return loop.is_running()


def _resolve_target(target: str) -> tuple[object, str, BlockingCallable]:
    module_name, attr_path = target.split(":", maxsplit=1)
    owner: object = importlib.import_module(module_name)
    parts = attr_path.split(".")
    for part in parts[:-1]:
        owner = getattr(owner, part)

    attr_name = parts[-1]
    original = getattr(owner, attr_name)
    return owner, attr_name, original


def _trim_detector_frames(stack: Iterable[traceback.FrameSummary]) -> tuple[traceback.FrameSummary, ...]:
    return tuple(frame for frame in stack if frame.filename != __file__)


class BlockingIODetector(AbstractContextManager["BlockingIODetector"]):
    """Record blocking calls made from async runtime code.

    By default the detector reports violations but does not fail on context
    exit. Tests can set ``fail_on_exit=True`` or call
    ``assert_no_blocking_calls()`` explicitly.
    """

    def __init__(
        self,
        specs: Iterable[BlockingCallSpec] = DEFAULT_BLOCKING_CALL_SPECS,
        *,
        fail_on_exit: bool = False,
        patch_loaded_aliases: bool = True,
        stack_limit: int = 12,
    ) -> None:
        self._specs = tuple(specs)
        self._fail_on_exit = fail_on_exit
        self._patch_loaded_aliases_enabled = patch_loaded_aliases
        self._stack_limit = stack_limit
        self._patches: list[tuple[object, str, BlockingCallable]] = []
        self._patch_keys: set[tuple[int, str]] = set()
        self.violations: list[BlockingCall] = []
        self._active = False

    def __enter__(self) -> BlockingIODetector:
        try:
            self._active = True
            alias_replacements: dict[int, BlockingCallable] = {}
            for spec in self._specs:
                owner, attr_name, original = _resolve_target(spec.target)
                wrapper = self._wrap(spec, original)
                self._patch_attribute(owner, attr_name, original, wrapper)
                alias_replacements[id(original)] = wrapper

            if self._patch_loaded_aliases_enabled:
                self._patch_loaded_module_aliases(alias_replacements)
        except Exception:
            self._restore()
            self._active = False
            raise
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback_value: TracebackType | None,
    ) -> bool | None:
        self._restore()
        self._active = False
        if exc_type is None and self._fail_on_exit:
            self.assert_no_blocking_calls()
        return None

    def _restore(self) -> None:
        for owner, attr_name, original in reversed(self._patches):
            setattr(owner, attr_name, original)
        self._patches.clear()
        self._patch_keys.clear()

    def _patch_attribute(self, owner: object, attr_name: str, original: BlockingCallable, replacement: BlockingCallable) -> None:
        key = (id(owner), attr_name)
        if key in self._patch_keys:
            return
        setattr(owner, attr_name, replacement)
        self._patches.append((owner, attr_name, original))
        self._patch_keys.add(key)

    def _patch_loaded_module_aliases(self, replacements_by_id: dict[int, BlockingCallable]) -> None:
        for module in tuple(sys.modules.values()):
            namespace = getattr(module, "__dict__", None)
            if not isinstance(namespace, dict):
                continue

            for attr_name, value in tuple(namespace.items()):
                replacement = replacements_by_id.get(id(value))
                if replacement is not None:
                    self._patch_attribute(module, attr_name, value, replacement)

    def _wrap(self, spec: BlockingCallSpec, original: BlockingCallable) -> BlockingCallable:
        @wraps(original)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if spec.record_on_iteration:
                result = original(*args, **kwargs)
                return self._wrap_iteration(spec, result)
            self._record_if_blocking(spec)
            return original(*args, **kwargs)

        return wrapper

    def _wrap_iteration(self, spec: BlockingCallSpec, iterable: Iterable[Any]) -> Iterator[Any]:
        iterator = iter(iterable)
        reported = False

        while True:
            if not reported:
                reported = self._record_if_blocking(spec)
            try:
                yield next(iterator)
            except StopIteration:
                return

    def _record_if_blocking(self, spec: BlockingCallSpec) -> bool:
        if self._active and _is_event_loop_thread():
            stack = _trim_detector_frames(traceback.extract_stack(limit=self._stack_limit))
            self.violations.append(BlockingCall(spec.name, spec.target, stack))
            return True
        return False

    def assert_no_blocking_calls(self) -> None:
        if self.violations:
            raise AssertionError(format_blocking_calls(self.violations))


class BlockingIOProbe:
    """Collect detector output across tests and format a compact summary."""

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root.resolve()
        self._observed: list[tuple[str, BlockingCall]] = []

    @property
    def violation_count(self) -> int:
        return len(self._observed)

    @property
    def test_count(self) -> int:
        return len({nodeid for nodeid, _violation in self._observed})

    def clear(self) -> None:
        self._observed.clear()

    def record(self, nodeid: str, violations: Iterable[BlockingCall]) -> None:
        for violation in violations:
            self._observed.append((nodeid, violation))

    def format_summary(self, *, limit: int = 30) -> str:
        if not self._observed:
            return "blocking io probe: no violations"

        call_sites: Counter[tuple[str, str, int, str, str]] = Counter()
        for _nodeid, violation in self._observed:
            frame = self._local_call_site(violation.stack)
            if frame is None:
                call_sites[(violation.name, "<unknown>", 0, "<unknown>", "")] += 1
                continue

            call_sites[
                (
                    violation.name,
                    self._relative(frame.filename),
                    frame.lineno,
                    frame.name,
                    (frame.line or "").strip(),
                )
            ] += 1

        lines = [f"blocking io probe: {self.violation_count} violations across {self.test_count} tests", "Top call sites:"]
        for (name, filename, lineno, function, line), count in call_sites.most_common(limit):
            lines.append(f"{count:4d} {name} {filename}:{lineno} {function} | {line}")
        return "\n".join(lines)

    def _relative(self, filename: str) -> str:
        try:
            return str(Path(filename).resolve().relative_to(self._project_root))
        except ValueError:
            return filename

    def _local_call_site(self, stack: tuple[traceback.FrameSummary, ...]) -> traceback.FrameSummary | None:
        local_frames = [frame for frame in stack if str(self._project_root) in frame.filename and "/.venv/" not in frame.filename and not self._relative(frame.filename).startswith("tests/")]
        if local_frames:
            return local_frames[-1]

        test_frames = [frame for frame in stack if str(self._project_root) in frame.filename and "/.venv/" not in frame.filename]
        return test_frames[-1] if test_frames else None


def detect_blocking_io(
    specs: Iterable[BlockingCallSpec] = DEFAULT_BLOCKING_CALL_SPECS,
    *,
    fail_on_exit: bool = False,
    patch_loaded_aliases: bool = True,
    stack_limit: int = 12,
) -> BlockingIODetector:
    """Create a detector context manager for a focused test scope."""

    return BlockingIODetector(specs, fail_on_exit=fail_on_exit, patch_loaded_aliases=patch_loaded_aliases, stack_limit=stack_limit)


def format_blocking_calls(violations: Iterable[BlockingCall]) -> str:
    """Format detector output with enough stack context to locate call sites."""

    lines = ["Blocking calls were executed on an asyncio event loop thread:"]
    for index, violation in enumerate(violations, start=1):
        lines.append(f"{index}. {violation.name} ({violation.target})")
        lines.extend(_format_stack(violation.stack))
    return "\n".join(lines)


def _format_stack(stack: Iterable[traceback.FrameSummary]) -> Iterator[str]:
    for frame in stack:
        location = f"{frame.filename}:{frame.lineno}"
        lines = [f"   at {frame.name} ({location})"]
        if frame.line:
            lines.append(f"      {frame.line.strip()}")
        yield from lines
