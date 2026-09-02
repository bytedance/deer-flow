"""Deterministic acceptance-criteria checks (RFC #4651 PR4).

Layer 2 of the verification stack: the lead attaches ``acceptance_criteria``
to a ``task`` delegation (PR3 wired the parameter and the prompt contract);
this module checks the decidable criteria *in code* once the subagent
completes, so a self-report can never silently pass an objectively checkable
requirement.

Leaf families:

- ``file:<path> exists`` / ``file:<path> non-empty`` — read through
  ``read_current_file_content`` (the ``ReadBeforeWriteMiddleware``
  precedent), **scoped to the shared thread workspace**: the path must
  resolve under the thread's ``workspace_path``/``outputs_path`` (virtual
  ``/mnt/user-data/...`` prefixes and workspace-relative spellings are
  normalized first). The read itself uses the sandbox-native **virtual**
  form — the local read path validator accepts ``/mnt/user-data/...``
  paths, not host paths. Paths outside the shared domain return
  ``checked=False`` (UNVERIFIED) rather than assuming cross-sandbox
  reachability — if a future isolated-sandbox provider breaks sharing,
  leaves degrade to UNVERIFIED instead of misjudging. Reads are
  byte-bounded: the size is established first (``os.stat`` on the local
  host path; a metadata-only ``stat``/``realpath`` probe in a fresh
  ``env -i`` shell on remote providers — absolute-path utilities a
  poisoned persistent session cannot steer, no content opens so a FIFO
  cannot block, regular-file type required, containment canonicalized
  against the canonical mount root, matching what the provider's own
  read path resolves); above ``_FILE_CONTENT_READ_CAP_BYTES``
  the leaf answers from the size alone, at or below it the full read
  runs, and when the size cannot be established the leaf degrades to
  UNVERIFIED — never an unbounded read.
- ``file_written:<path>`` — typed claim binding: existence + read-back
  through the same workspace-scoped read.
- ``tests_passed:<command>`` — typed claim binding: the criterion must
  anchor to a *specific recorded execution* — a matching bash execution
  (harvested by the executor from the same stamped ``ToolMessage``s the
  receipt layer reads) with ``status=success`` and a test-summary shape in
  its output tail — not merely to some successful call. Matching accounts
  for shell command structure (operator-separated segments, executables,
  arguments), so an unrelated command that merely mentions the criterion
  string (e.g. inside an ``echo`` argument or a comment) cannot anchor the
  leaf. Full parent-side re-execution stays deferred to the read-only
  verifier (RFC §6).
- Anything else is undecidable in code: ``checked=False``, rendered
  ``UNVERIFIED``, never silently passed.

Vocabulary layering: the leaf booleans are ``checked``/``holds`` — never
``satisfied``/``verified``/``passed``. Strong-positive words stay exclusive
to the runtime hard gate so the model never conflates deterministic
execution evidence with task acceptance.

All functions are pure (sandbox IO only through the injected reader/prober);
the async caller offloads the whole check with ``asyncio.to_thread``.
"""

from __future__ import annotations

import os
import re
import shlex
import stat
from collections.abc import Callable, Mapping
from typing import Any, TypedDict

from deerflow.config.paths import VIRTUAL_PATH_PREFIX
from deerflow.subagents.report_contract import MAX_ACCEPTANCE_CRITERIA, MAX_CRITERION_CHARS

CHECK_SOURCE = "acceptance_checklist"
CHECK_REQUIREMENT = "delegation_acceptance_criteria"

#: Anti-automation-bias: model-visible verdict text always states its boundary
#: (same fixed line the citation layer renders).
_LIMITATION = "execution evidence only, does not validate claim correctness"

#: Bounds for untrusted evidence text folded into leaf details.
_DETAIL_MAX_CHARS = 160

#: Remote providers (E2B/OpenSandbox/BoxLite/Tenki/AIO) return an
#: ``"Error: ..."`` string from ``read_file`` instead of raising — the same
#: prefix convention ``tool_result_meta`` uses to classify tool errors. A
#: returned error string is NOT file content: treating it as such would
#: report a missing file as existing (and non-empty, and read-back-ok).
_PROVIDER_ERROR_PREFIX = "Error:"

_FILE_LEAF_RE = re.compile(r"^file:(?P<path>.+?)\s+(?P<mode>exists|non-empty)$", re.IGNORECASE)
_FILE_WRITTEN_RE = re.compile(r"^file_written:(?P<path>.+)$", re.IGNORECASE)
_TESTS_PASSED_RE = re.compile(r"^tests_passed:(?P<command>.+)$", re.IGNORECASE)

#: Byte budget for the content read behind ``file:`` leaves — the same scale
#: at which ``read_file_output_max_chars`` caps the read tool's output. A
#: larger deliverable is proven by the size probe alone instead of
#: loading ~2× its size (decoded text plus the utf-8 re-encode used for the
#: byte count) onto the worker thread, once per ``file:`` criterion.
_FILE_CONTENT_READ_CAP_BYTES = 50_000

#: Test-runner summary shapes recognized in a recorded bash output tail.
#: Pass shapes require an explicit success summary; fail shapes require an
#: explicit failure or error record. An output carrying neither is not evidence either
#: way (UNVERIFIED), and fail shapes win over pass shapes when both appear.
_TEST_PASS_SHAPE_RE = re.compile(
    r"\b[1-9]\d*\s+passed\b"  # pytest / jest: "5 passed" (zero is not a pass)
    r"|^OK$"  # unittest: bare OK line
    r"|test result: ok"  # cargo test
    r"|^ok\s+\S"  # go test: "ok  \tpkg/path"
    r"|\bBUILD SUCCESS(?:FUL)?\b"  # maven / gradle
    r"|\ball tests passed\b",
    re.IGNORECASE | re.MULTILINE,
)

#: Zero-test evidence vetoes the pass shapes the count-bearing alternatives
#: cannot see: "0 passed", go's no-test markers, unittest "Ran 0 tests".
_TEST_ZERO_SHAPE_RE = re.compile(r"\b0\s+passed\b|\[no test files\]|\[no tests to run\]|\bRan 0 tests\b", re.IGNORECASE)

_TEST_FAIL_SHAPE_RE = re.compile(
    r"\b[1-9]\d*\s+failed\b"  # pytest / jest: "1 failed"
    r"|\b[1-9]\d*\s+errors?\b"  # pytest: "1 error" — an errored collection means part of the selection never ran
    r"|^FAILED\b"  # unittest summary line
    r"|^ERROR\s+\S"  # pytest short summary: "ERROR tests/unit/test_auth.py"
    r"|test result: FAILED"  # cargo test
    r"|^FAIL\s+\S"  # go test: "FAIL\tpkg/path"
    r"|\bBUILD FAILURE\b",  # maven / gradle
    re.IGNORECASE | re.MULTILINE,
)


class AcceptanceLeaf(TypedDict):
    criterion: str  # original criterion text (bounded)
    family: str  # file_exists | file_non_empty | file_written | tests_passed | undecidable
    checked: bool  # a deterministic check ran
    holds: bool  # checked AND the condition holds; always False when unchecked
    detail: str  # short evidence note (bounded)


class AcceptanceVerdict(TypedDict):
    source: str
    requirement: str
    leaves: list[AcceptanceLeaf]
    unchecked: list[str]  # criteria with no deterministic check (PR5 judge input)
    all_hold: bool  # every leaf checked and holds


def _bound_detail(text: str) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= _DETAIL_MAX_CHARS:
        return cleaned
    return f"{cleaned[: _DETAIL_MAX_CHARS - 3]}..."


def _resolve_scoped_path(path: str, thread_data: Mapping[str, Any] | None, *, resolve_symlinks: bool = False) -> str | None:
    """Resolve a criterion path to its sandbox-native virtual form, else ``None``.

    Virtual ``/mnt/user-data/...`` prefixes map to the thread's host paths
    (``replace_virtual_path``); relative spellings resolve against
    ``workspace_path``. The normalized host result must sit under
    ``workspace_path`` or ``outputs_path`` — everything else is outside the
    shared domain and the caller marks the leaf UNVERIFIED. The returned
    path is converted back to the virtual form because the sandbox read
    path (local validation and provider mount tables alike) resolves
    virtual paths, not host paths.
    """
    if not thread_data:
        return None
    roots = [("workspace", thread_data.get("workspace_path")), ("outputs", thread_data.get("outputs_path"))]
    roots = [(kind, root) for kind, root in roots if isinstance(root, str) and root.strip()]
    if not roots:
        return None
    workspace = thread_data.get("workspace_path")
    candidate = path.strip()
    if not candidate:
        return None
    # Lazy import: sandbox.tools pulls the provider stack, and this package is
    # imported in cycles with deerflow.tools (same pattern as report_contract).
    from deerflow.sandbox.tools import replace_virtual_path

    candidate = replace_virtual_path(candidate, thread_data)  # type: ignore[arg-type]
    if not os.path.isabs(candidate):
        if not isinstance(workspace, str) or not workspace.strip():
            return None
        candidate = os.path.join(workspace, candidate)
    normalized = os.path.normpath(candidate)
    for kind, root in roots:
        root_normalized = os.path.normpath(root)
        if normalized == root_normalized or normalized.startswith(root_normalized + os.sep):
            if resolve_symlinks:
                # The lexical check is not enough on the local sandbox: a
                # symlink inside the workspace can point outside the scoped
                # roots (e.g. into uploads), and the later read would follow
                # it. Canonicalize both sides before accepting the scope.
                canonical = os.path.realpath(normalized)
                canonical_root = os.path.realpath(root_normalized)
                if canonical != canonical_root and not canonical.startswith(canonical_root + os.sep):
                    return None
            relative = normalized[len(root_normalized) :].lstrip(os.sep).replace(os.sep, "/")
            return f"{VIRTUAL_PATH_PREFIX}/{kind}" + (f"/{relative}" if relative else "")
    return None


#: Remote size-probe script (POSIX sh, positional params: ``$1`` path,
#: ``$2`` mount root). Answers a bare byte count for a regular file, or one
#: of ``NOFILE`` / ``UNREADABLE`` / ``NONREGULAR`` / ``ESCAPED``. Everything
#: runs from a fresh ``env -i`` shell with absolute-path utilities, so a
#: completed subagent's shell state cannot steer it; ``stat`` never opens
#: content, so a FIFO cannot block. Containment is canonicalized: the file's
#: ``realpath`` must stay under the mount root's ``realpath``. The canonical
#: root — not the literal spelling — is the reference because e2b and Tenki
#: realize ``/mnt/user-data`` as a symlink to the home dir by default; a
#: canonical root is also exactly what the provider's own read path
#: resolves, so the probe and the later read-back stay consistent. A
#: leaf-level symlink is rejected outright by the non-dereferencing
#: ``stat -c %F``; an intermediate dir-link escape under a sane root still
#: lands outside the canonical root (ESCAPED).
_SIZE_PROBE_INNER_SCRIPT = (
    '[ -e "$1" ] || { echo NOFILE; exit 0; }; '
    't=$(/usr/bin/stat -c %F -- "$1") || { echo UNREADABLE; exit 0; }; '
    '[ "$t" = "regular file" ] || { echo NONREGULAR; exit 0; }; '
    'r=$(/usr/bin/realpath -- "$2") || { echo UNREADABLE; exit 0; }; '
    'p=$(/usr/bin/realpath -- "$1") || { echo UNREADABLE; exit 0; }; '
    'case $p in "$r"/*) /usr/bin/stat -c %s -- "$p" ;; *) echo ESCAPED ;; esac'
)


def _probe_file_size(runtime: Any, resolved: str, thread_data: Mapping[str, Any] | None) -> int | None:
    """Bounded byte size of the resolved file, else ``None`` when it cannot be
    established without reading content.

    Local sandbox: a direct ``os.stat`` of the validated host path — the same
    filesystem access the read itself would perform, no shell, so the
    host-bash kill switch (a shell-execution policy) does not apply and the
    supported host-bash-disabled configuration keeps working. Remote
    providers: a metadata-only probe in a fresh ``env -i`` shell — utilities
    by absolute path (a poisoned persistent session's functions, aliases,
    exported functions, ``PATH``, ``IFS``, or locale cannot steer it; the
    marker env also routes AIO off its persistent shell onto a fresh
    per-call session), no content opens (``stat`` only, so a FIFO cannot
    block the parent for the provider's idle timeout), a regular-file type
    requirement, and canonicalized containment: the file's ``realpath``
    must stay under the mount root's ``realpath`` — the reference is
    canonical because e2b and Tenki realize ``/mnt/user-data`` as a symlink
    to the home dir by default, and a canonical root is exactly what the
    provider's own read path resolves, so probe and read-back stay
    consistent. A final-component symlink is rejected outright
    (``stat -c %F`` without dereference); an intermediate dir-link escape
    under a sane root lands outside the canonical root (``ESCAPED``).
    Outcomes are rendered in the probe's own words (``NOFILE`` /
    ``UNREADABLE`` / ``NONREGULAR`` / ``ESCAPED``), never parsed from
    provider error text. Only a bare integer is a size; every other outcome
    is ``None`` and the caller degrades to UNVERIFIED rather than
    performing an unbounded read. Residual: a root-privileged subagent
    (replacing the container's own binaries, or remounting the storage
    root) is only answerable by provider-side metadata APIs, which the
    sandbox contract does not expose.

    Non-regular local entries (directories, fifos) and mount-mapped virtual
    paths the parent cannot resolve to a host path yield ``None``. The size
    is a point-in-time probe: the subagent has completed, so a grow-between-
    probe-and-read race is accepted (same tradeoff as ``download_file``).

    Raises ``FileNotFoundError`` when the file is provably absent — the same
    contract ``content_reader`` has.
    """
    try:
        from deerflow.sandbox.tools import _resolve_local_read_path, ensure_sandbox_initialized, is_local_sandbox

        if is_local_sandbox(runtime):
            host_path = _resolve_local_read_path(resolved, thread_data)
            if host_path == resolved:
                # A mount-mapped virtual path: only the provider's mount
                # table resolves it, and the parent cannot stat that.
                return None
            stat_result = os.stat(host_path)
            return stat_result.st_size if stat.S_ISREG(stat_result.st_mode) else None
        sandbox = ensure_sandbox_initialized(runtime)
        root = "/".join(resolved.split("/")[:4])  # the /mnt/user-data/{workspace|outputs} mount root
        output = sandbox.execute_command(
            f"/usr/bin/env -i /bin/sh -c {shlex.quote(_SIZE_PROBE_INNER_SCRIPT)} probe {shlex.quote(resolved)} {shlex.quote(root)}",
            env={"_DEERFLOW_SIZE_PROBE": "1"},
        )
    except FileNotFoundError:
        raise
    except Exception:
        # Best-effort optimization over provider-specific failure modes; the
        # caller degrades to UNVERIFIED. Runs only inside the offloaded
        # checklist call, so this broad catch cannot mask a BlockingError on
        # the event loop (same precedent as _safe_load_agent_config).
        return None
    text = str(output or "").strip()
    if text == "NOFILE":
        raise FileNotFoundError(resolved)
    return int(text) if text.isdigit() else None


#: Remote read-probe script (POSIX sh, positional params: ``$1`` path,
#: ``$2`` mount root). Answers ``READABLE`` / ``UNREADABLE`` (or one of the
#: shared ``NOFILE`` / ``NONREGULAR`` / ``ESCAPED`` rejections). The same
#: fresh-shell, absolute-path, non-dereferencing, canonicalized-containment
#: discipline as ``_SIZE_PROBE_INNER_SCRIPT``; only then one bounded open
#: (``head -c 1``) proves the file can be opened for reading — ``stat``
#: alone cannot: a mode-000 deliverable stats fine while any open raises
#: EACCES, and metadata must not stand in for ``file_written``'s read-back
#: claim. The regular-file gate runs first, so no FIFO or device is ever
#: opened.
_READ_PROBE_INNER_SCRIPT = (
    '[ -e "$1" ] || { echo NOFILE; exit 0; }; '
    't=$(/usr/bin/stat -c %F -- "$1") || { echo UNREADABLE; exit 0; }; '
    '[ "$t" = "regular file" ] || { echo NONREGULAR; exit 0; }; '
    'r=$(/usr/bin/realpath -- "$2") || { echo UNREADABLE; exit 0; }; '
    'p=$(/usr/bin/realpath -- "$1") || { echo UNREADABLE; exit 0; }; '
    'case $p in "$r"/*) ;; *) echo ESCAPED; exit 0 ;; esac; '
    '/usr/bin/head -c 1 -- "$p" >/dev/null 2>&1 && echo READABLE || echo UNREADABLE'
)


def _probe_file_readable(runtime: Any, resolved: str, thread_data: Mapping[str, Any] | None) -> bool | None:
    """Whether the resolved file can be opened for reading — one bounded byte —
    else ``None`` when the probe itself cannot answer.

    Backs the ``file_written`` read-back claim above the content read cap:
    metadata (``stat``) proves existence and size, not readability. Local
    sandbox: a direct one-byte ``open`` of the validated host path — the
    same filesystem access the read itself would perform, no shell.
    Remote providers: one bounded open in a fresh ``env -i`` shell with
    absolute-path utilities (same discipline as the size probe; the marker
    env also routes AIO off its persistent shell), after the
    non-dereferencing regular-file gate — a FIFO is rejected before any
    open, so nothing can block — and canonicalized containment.
    ``False`` means the open provably failed (e.g. EACCES); any
    probe-level failure is ``None`` and the caller degrades to UNVERIFIED.
    """
    try:
        from deerflow.sandbox.tools import _resolve_local_read_path, ensure_sandbox_initialized, is_local_sandbox

        if is_local_sandbox(runtime):
            host_path = _resolve_local_read_path(resolved, thread_data)
            if host_path == resolved:
                # A mount-mapped virtual path: only the provider's mount
                # table resolves it, and the parent cannot open that.
                return None
            try:
                with open(host_path, "rb") as handle:
                    handle.read(1)
                return True
            except OSError:
                return False
        sandbox = ensure_sandbox_initialized(runtime)
        root = "/".join(resolved.split("/")[:4])  # the /mnt/user-data/{workspace|outputs} mount root
        output = sandbox.execute_command(
            f"/usr/bin/env -i /bin/sh -c {shlex.quote(_READ_PROBE_INNER_SCRIPT)} probe {shlex.quote(resolved)} {shlex.quote(root)}",
            env={"_DEERFLOW_SIZE_PROBE": "1"},
        )
    except Exception:
        # Same failure-isolation precedent as _probe_file_size: best-effort
        # over provider-specific failure modes; the caller degrades.
        return None
    text = str(output or "").strip()
    if text == "READABLE":
        return True
    if text == "UNREADABLE":
        return False
    return None


def _check_file_leaf(
    family: str,
    path: str,
    *,
    runtime: Any,
    thread_data: Mapping[str, Any] | None,
    content_reader: Callable[[Any, str], str],
    size_prober: Callable[[Any, str, Mapping[str, Any] | None], int | None],
    readable_prober: Callable[[Any, str, Mapping[str, Any] | None], bool | None],
) -> AcceptanceLeaf:
    criterion_path = path.strip()
    # Lazy imports: the sandbox helpers pull the provider stack, and this
    # package is imported in cycles with deerflow.tools (same pattern as
    # report_contract).
    from deerflow.sandbox.exceptions import SandboxError, SandboxFileNotFoundError
    from deerflow.sandbox.tools import is_local_sandbox

    # Symlink escapes are a local-sandbox concern (host-visible links); remote
    # providers resolve paths inside the sandbox where the parent cannot
    # canonicalize, so the check stays lexical there.
    resolved = _resolve_scoped_path(criterion_path, thread_data, resolve_symlinks=is_local_sandbox(runtime))
    base: AcceptanceLeaf = {"criterion": "", "family": family, "checked": False, "holds": False, "detail": ""}
    if resolved is None:
        base["detail"] = "path is outside the shared thread workspace" if thread_data else "shared thread workspace unavailable"
        return base
    try:
        probed_size = size_prober(runtime, resolved, thread_data)
    except (FileNotFoundError, SandboxFileNotFoundError):
        base["checked"] = True
        base["detail"] = "file does not exist"
        return base
    if probed_size is None:
        # The size could not be established by a bounded probe (unreadable or
        # non-regular file, mount-mapped path, probe unavailable). Reading the
        # content anyway could materialize an unbounded deliverable on the
        # worker — degrade to UNVERIFIED instead.
        base["detail"] = "file size could not be established by a bounded probe; content not read"
        return base
    if probed_size > _FILE_CONTENT_READ_CAP_BYTES:
        # Large deliverable: the size probe proved the file exists, is
        # regular, and is non-empty (size > cap > 0) — answering the
        # existence/non-empty leaves without loading content (and its utf-8
        # re-encode) onto the worker. Metadata is NOT read-back, though: a
        # mode-000 file stats fine while any open raises EACCES, so
        # ``file_written`` additionally requires a bounded one-byte open
        # probe; without its proof the leaf stays UNVERIFIED.
        base["checked"] = True
        base["holds"] = True
        if family == "file_non_empty":
            base["detail"] = f"{probed_size} bytes (size probe; content not loaded)"
        elif family == "file_written":
            readable = readable_prober(runtime, resolved, thread_data)
            if readable is not True:
                base["checked"] = False
                base["holds"] = False
                base["detail"] = "file cannot be opened for reading (bounded open probe failed)" if readable is False else "readability could not be established by a bounded probe; content not read"
                return base
            base["detail"] = f"read probe ok, {probed_size} bytes (content above the read cap not loaded)"
        else:  # file_exists
            base["detail"] = f"exists, {probed_size} bytes (size probe; content not loaded)"
        return base
    try:
        content = content_reader(runtime, resolved)  # resolved is the virtual read path
    except (FileNotFoundError, SandboxFileNotFoundError):
        base["checked"] = True
        base["detail"] = "file does not exist"
        return base
    except UnicodeDecodeError:
        # A binary deliverable (PDF, image, spreadsheet): undecodable bytes
        # prove the file exists and is non-empty — a valid outcome for every
        # file leaf, not an error.
        base["checked"] = True
        base["holds"] = True
        base["detail"] = "binary file (undecodable as text)"
        return base
    except (OSError, SandboxError) as exc:
        base["detail"] = _bound_detail(f"read failed: {exc}")
        return base
    if not is_local_sandbox(runtime) and content.startswith(_PROVIDER_ERROR_PREFIX):
        # A missing/inaccessible file on a REMOTE provider comes back as an
        # error string, not an exception — the check ran and the file cannot
        # be confirmed, so the leaf deterministically does not hold. The
        # local sandbox raises instead, so an ``Error:``-prefixed string from
        # it is genuine file content and must not be classified as a failure.
        base["checked"] = True
        base["detail"] = _bound_detail(f"read returned an error: {content}")
        return base
    byte_count = len(content.encode("utf-8"))
    base["checked"] = True
    if family == "file_non_empty":
        base["holds"] = byte_count > 0
        base["detail"] = f"{byte_count} bytes" if byte_count > 0 else "file is empty"
    elif family == "file_written":
        # Existence + read-back: the persisted bytes are retrievable.
        base["holds"] = True
        base["detail"] = f"read-back ok, {byte_count} bytes"
    else:  # file_exists
        base["holds"] = True
        base["detail"] = f"exists, {byte_count} bytes"
    return base


_SHELL_OPERATORS = ";&|"
#: Leading ``VAR=value`` assignments are environment setup, not the executable.
_ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _carries_summary_shape(text: str) -> bool:
    """Whether *text* carries any recognized test-summary shape (pass, fail,
    or zero-test veto). The pass shapes match as substrings, so
    subagent-chosen strings — a ``cd`` argument, a ``CDPATH`` value — must
    not be allowed to lend the recorded tail a summary shape."""
    return bool(_TEST_PASS_SHAPE_RE.search(text) or _TEST_FAIL_SHAPE_RE.search(text) or _TEST_ZERO_SHAPE_RE.search(text))


def _cd_target_in_scope(target: str, thread_data: Mapping[str, Any] | None) -> bool:
    """Whether a preceding ``cd`` target provably keeps the criterion's
    relative path-like targets resolving inside the thread's data roots.

    A relative target with no ``..`` component descends from the current
    directory without escaping it; an absolute target must sit under the
    thread's workspace/outputs/uploads paths or the virtual data prefix
    (``/mnt/user-data/...``) — the roots a subagent is expected to work in,
    so ``cd /mnt/user-data/workspace && …`` and the local auto-prefix stay
    verifiable. ``cd /tmp/fake && pytest tests/`` (a directory the subagent
    fully controls, outside any data root), ``cd ../out`` (walks out),
    ``~`` spellings (the subagent's home), and ``-`` (prints OLDPWD) are
    all out. A symlink INSIDE an allowed root pointing out is a
    filesystem-layer concern this text matcher cannot see — see the Known
    boundaries note in subagents/AGENTS.md.
    """
    if not target or target == "-" or target.startswith("~"):
        return False
    normalized = os.path.normpath(target.replace("\\", "/"))
    if normalized.startswith("/"):
        roots = [VIRTUAL_PATH_PREFIX]
        for key in ("workspace_path", "outputs_path", "uploads_path"):
            value = (thread_data or {}).get(key)
            if isinstance(value, str) and value:
                roots.append(value)
        for root in roots:
            normalized_root = os.path.normpath(root.replace("\\", "/"))
            if normalized == normalized_root or normalized.startswith(normalized_root + "/"):
                return True
        return False
    return ".." not in normalized.split("/")


def _is_silent_segment(tokens: list[str], thread_data: Mapping[str, Any] | None = None) -> bool:
    """Whether a preceding segment is provably output-free, by invocation
    form — not by executable name alone: ``pushd``/``popd`` print
    the directory stack, ``umask``/``ulimit`` print on several forms, and
    ``source``/``.`` execute arbitrary file content — a ``*/bin/activate``
    path shape says nothing about what the script emits (the subagent
    controls the filesystem and can craft one), so sourced prefixes are
    never provably silent. ``export``/``unset`` are never provably silent
    either: an invalid identifier makes bash print ``export: <arg>: not a
    valid identifier`` — subagent-chosen text that can itself carry a
    summary shape (``export 'all tests passed'; make test``) — and valid
    argument forms mutate shell state (see ``_segment_pollutes_state``).

    ``cd`` is silent only with exactly one argument that is literal and
    shape-free: with CDPATH set it prints the resolved destination —
    subagent-chosen text — so a shaped (``mkdir 'all tests passed'``) or
    runtime-expanded (``cd $D``, ``cd all*``) argument could lend the tail
    a summary shape. The target must also stay in scope
    (``_cd_target_in_scope``): the criterion's relative path-like targets
    resolve in whatever directory the wrapper sets, and an out-of-scope
    ``cd /tmp/fake`` would let a subagent-crafted directory certify them.
    Bare ``cd`` (goes HOME) and ``cd old new`` (substitution) are likewise
    unprovable. Behavior-changing assignments that feed the print
    (``CDPATH=``) are state pollution and degrade the match upstream; the
    everyday shape-free ``cd dir &&`` wrapper stays silent (bash_tool
    auto-prefixes it for every local command).
    """
    stripped = _strip_env_assignments(tokens)
    if not stripped:
        return True  # pure VAR=value assignments
    executable = os.path.basename(stripped[0])
    args = stripped[1:]
    if executable == "cd":
        if len(args) != 1:
            return False
        target = args[0]
        if _carries_summary_shape(target) or _EXPANSION_CHAR_RE.search(target) or _GLOB_CHAR_RE.search(target):
            return False
        return _cd_target_in_scope(target, thread_data)
    # pushd/popd (print the stack), umask/ulimit (print forms), export/unset
    # (see the docstring), source/. and every other executable are not
    # provably silent.
    return False


#: Runner options whose value *excludes* a target instead of running it
#: (pytest ``--ignore``/``--deselect`` and the generic skip/exclude family).
#: A criterion matching such a value would affirm tests that were explicitly
#: deselected, so negated tokens are ineligible as match evidence.
_NEGATING_OPTION_TOKENS = frozenset({"--ignore", "--ignore-glob", "--deselect", "--exclude", "--exclude-glob", "--skip", "--skip-file"})


def _negated_positions(tokens: list[str]) -> tuple[set[int], set[int]]:
    """Split *tokens* positions into (negating option tokens, their values).

    Both are accounted-for shell structure rather than free extras: the
    option names a known exclusion mechanism and the value names what did
    NOT run, so neither is eligible as match evidence and neither is
    classified as a behavior-changing *extra* flag.
    """
    options: set[int] = set()
    values: set[int] = set()
    for index, token in enumerate(tokens):
        if token in _NEGATING_OPTION_TOKENS:
            options.add(index)
            if index + 1 < len(tokens):
                values.add(index + 1)
        elif any(token.startswith(f"{option}=") for option in _NEGATING_OPTION_TOKENS):
            options.add(index)
            values.add(index)
    return options, values


def _negated_value(token: str) -> str:
    """The exclusion target a negated token names: the bare value as-is, or
    the part after ``=`` for the glued form (``--deselect=tests/x.py``)."""
    for option in _NEGATING_OPTION_TOKENS:
        if token.startswith(f"{option}="):
            return token.split("=", 1)[1]
    return token


def _negation_overlaps(criterion_token: str, negated_value: str) -> bool:
    """Whether a negated value overlaps a matched criterion target: equal, or
    one nested under the other at a path boundary (``tests`` vs
    ``tests/unit/test_auth.py``) or a pytest nodeid boundary (``tests/x.py``
    vs ``tests/x.py::test_y``). Overlap means part of the criterion's
    selection never ran, so the passing summary may not cover it; unrelated
    exclusions (``--ignore tests/slow`` against ``pytest tests/unit``) do not
    overlap and keep matching."""
    a = criterion_token.replace("\\", "/").removeprefix("./").rstrip("/")
    b = negated_value.replace("\\", "/").removeprefix("./").rstrip("/")
    if not a or not b:
        return False
    return a == b or a.startswith((b + "/", b + "::")) or b.startswith((a + "/", a + "::"))


def _normalize_command(command: str) -> str:
    return " ".join(command.split())


def _shell_parse_line(line: str) -> tuple[str | None, list[list[str]], list[str]] | None:
    """Tokenize one physical line into segments plus the operators joining them.

    Returns ``(leading_op, segments, ops)``: ``ops[i]`` is the operator
    between segment ``i`` and segment ``i+1`` (``;``, ``&&``, ``||``, ``|``,
    ``&``, or a rarer punctuation run), and ``leading_op`` is an operator
    the line STARTS with (``cmd1\\n|| cmd2``) — real control flow the caller
    must join with, never drop: a continuation ``||`` after a successful
    first line SKIPS the line's commands while exiting 0, so parsing it as
    ``;`` would overstate what provably ran. Comments are stripped (a
    ``# pytest ...`` remark executes nothing) and quotes are honored, so an
    operator inside an argument cannot split a segment. Returns ``None`` on
    malformed shell (unbalanced quotes).
    """
    lexer = shlex.shlex(line, posix=True, punctuation_chars=_SHELL_OPERATORS)
    lexer.whitespace_split = True
    lexer.commenters = "#"
    try:
        tokens = list(lexer)
    except ValueError:
        return None
    segments: list[list[str]] = []
    ops: list[str] = []
    current: list[str] = []
    leading_op: str | None = None
    for token in tokens:
        if token and all(char in _SHELL_OPERATORS for char in token):
            if current:
                segments.append(current)
                current = []
                ops.append(token)
            elif not segments and leading_op is None:
                leading_op = token
            # A doubled operator (``cmd ;; esac`` style) attaches no
            # following segment; it can never make evidence more provable,
            # so it is simply not recorded.
        else:
            current.append(token)
    if current:
        segments.append(current)
    # ops[i] is the operator following segment i; a trailing operator (e.g.
    # ``make test &``) leaves ops as long as segments and must stay visible —
    # backgrounding makes the execution unprovable.
    return leading_op, segments, ops


def _shell_parse(command: str) -> tuple[list[list[str]], list[str]] | None:
    """Tokenize a shell command into segments plus the operators joining them.

    Physical newlines are command separators with ``;`` semantics — bash
    executes ``pytest tests/\\nseq 1 90000\\necho '3 passed'`` as three
    sequential commands whose overall exit status is the LAST one's. shlex
    treats ``\\n`` as ordinary whitespace, so parsing the raw string would
    merge the lines into one segment: the trailing ``echo`` would pass for an
    extra positional, its exit status for the run's, and its text for the
    test summary while bulk output (``seq``) pushes the real one out of the
    bounded tail. Each line is parsed on its own and joined with a ``;`` op —
    with the previous line's trailing operator when it ends on one
    (``cmd &``), or with the continuation operator the next line opens with
    (``cmd1\\n&& cmd2`` parses as ``&&``, and ``cmd1\\n|| cmd2`` as ``||`` —
    a continuation ``||`` after a successful first command skips the rest
    while exiting 0, which ``;`` would overstate). A newline inside an open
    quote breaks that line's parse and falls back to exact-equality matching
    — fail closed.
    """
    segments: list[list[str]] = []
    ops: list[str] = []
    for line in command.split("\n"):
        parsed = _shell_parse_line(line)
        if parsed is None:
            return None
        leading_op, line_segments, line_ops = parsed
        if not line_segments:
            continue  # blank line: no command, no separator effect
        if segments and len(ops) < len(segments):
            # The previous line ended without an operator: the newline
            # itself separates the two commands — with the continuation
            # operator this line opens with (``cmd1\\n&& cmd2``), not a
            # hardcoded ``;``.
            ops.append(leading_op or ";")
        segments.extend(line_segments)
        ops.extend(line_ops)
    return segments, ops


def _strip_env_assignments(tokens: list[str]) -> list[str]:
    index = 0
    while index < len(tokens) and _ENV_ASSIGNMENT_RE.match(tokens[index]):
        index += 1
    return tokens[index:]


def _leading_assignment_tokens(tokens: list[str]) -> list[str]:
    """The leading ``NAME=value`` assignment tokens (the env-setup prefix)."""
    assignments: list[str] = []
    for token in tokens:
        if not _ENV_ASSIGNMENT_RE.match(token):
            break
        assignments.append(token)
    return assignments


def _effective_env_assignments(tokens: list[str]) -> dict[str, str]:
    """The effective leading environment as a name → final-value mapping.

    A set of raw tokens is only order-insensitive when names are distinct:
    shell assignments may repeat a name and the LAST value wins, so
    ``CI=0 CI=1`` and ``CI=1 CI=0`` are the same token set but different
    environments (effective ``CI`` of 1 vs 0).
    """
    effective: dict[str, str] = {}
    for token in _leading_assignment_tokens(tokens):
        name, _, value = token.partition("=")
        effective[name] = value
    return effective


def _segment_pollutes_state(tokens: list[str]) -> bool:
    """Whether a preceding segment mutates shell state the matcher cannot
    see: ANY assignment (prefix or pure-assignment segment) or any
    ``export``/``unset`` with arguments. No variable is provably inert across
    repositories — ``CI``/``DEBUG``/``VERBOSE`` are routinely read by tests
    and can change or skip execution, and PATH/LD_PRELOAD/PYTHONPATH/
    PYTEST_ADDOPTS/MAKEFILES/BASH_ENV change what runs outright."""
    if _leading_assignment_tokens(tokens):
        return True
    stripped = _strip_env_assignments(tokens)
    if not stripped:
        return False
    if os.path.basename(stripped[0]) in ("export", "unset"):
        # ``export NAME`` marks the inherited value for later children,
        # ``export NAME=…`` sets it, ``unset NAME`` removes it — all mutate
        # the state the matched run executes in. (An argument-less
        # ``export`` prints the environment; the silence check rejects it.)
        return bool(stripped[1:])
    return False


#: Tokens whose runtime expansion the matcher cannot see: command/parameter
#: substitution (``$(cat args)``, ``$TARGET``, backticks). In the matched
#: span a substitution can inject selection-changing flags or an unknown
#: exclusion; anywhere it makes the run's arguments unknowable.
_EXPANSION_CHAR_RE = re.compile(r"[$`]")
#: Glob metacharacters in an *extra* executed token: the expanded file set
#: is unknowable — and crafted option-looking filenames (``-k``/``smoke``)
#: turn a widening glob into an invisible narrowing. Criterion tokens are
#: matched literally, so a criterion-side glob stays self-consistent.
_GLOB_CHAR_RE = re.compile(r"[*?[]")


#: Options that consume the NEXT token as their value (separate form), so
#: that token is not a positional target: the negating family (the value
#: names what did NOT run), selection flags, and the output/config family.
#: Glued forms (``--opt=value``) need no entry — the whole token is an
#: option either way.
_VALUE_TAKING_OPTION_TOKENS = frozenset(
    {
        "-k",
        "-m",
        "-c",
        "-p",
        "-n",
        "-r",
        "--maxfail",
        "--junitxml",
        "--basetemp",
        "--cov",
        "--cov-report",
        "--durations-min",
        "--capture",
        "--tb",
        "--color",
        "--dist",
        "--ignore",
        "--ignore-glob",
        "--deselect",
        "--exclude",
        "--exclude-glob",
        "--skip",
        "--skip-file",
    }
)

#: A criterion argument scopes the run's selection only when it is path-like
#: (``tests/security``, ``tests/test_auth.py``); dotted module names, make
#: targets, and bare runner invocations leave the runner default in charge,
#: so extra positionals after them narrow rather than widen.
_CRITERION_PATHLIKE_ARG_RE = re.compile(r"[/\\]|\.(?:py|jsx?|tsx?|go|rs|java|rb|php)$")


def _criterion_positional_args(expected: list[str]) -> list[str] | None:
    """Criterion tokens that are positional arguments — the tokens that can
    name a test selection. Options and their values are skipped by arity,
    so a path embedded in an option (``--basetemp=/tmp/p``,
    ``--junitxml=/tmp/r.xml``) is never mistaken for a selection target.

    Returns ``None`` when the positional set is unknowable: an option whose
    arity is NOT known (absent from the value-taking table, no glued
    ``=``) immediately followed by a path-like token — that token may be
    the option's separate value (``--rootdir /tmp/project``) rather than a
    selection target, and the table stays incomplete across runners and
    plugins by construction, so the unknown case must fail closed rather
    than lend the criterion a scoped-selection proof it does not have."""
    args: list[str] = []
    tokens = expected[1:]
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.startswith("-"):
            if token in _VALUE_TAKING_OPTION_TOKENS:
                index += 2
                continue
            if "=" not in token:
                following = tokens[index + 1] if index + 1 < len(tokens) else None
                if following is not None and not following.startswith("-") and _CRITERION_PATHLIKE_ARG_RE.search(following):
                    return None
            index += 1
            continue
        args.append(token)
        index += 1
    return args


def _criterion_scopes_selection(expected: list[str]) -> bool:
    positionals = _criterion_positional_args(expected)
    # Unknown arity (None) fails closed: no scoped-selection proof.
    return positionals is not None and any(_CRITERION_PATHLIKE_ARG_RE.search(token) for token in positionals)


#: Extra flags that provably do not change *which* tests run: verbosity,
#: output formatting, parallelism, coverage, exit-on-failure. Anything else
#: (``-k``/``-m`` selection, ``--lf``, ``--collect-only``, ``-c`` config,
#: ``-p`` plugins, …) makes the recorded run a *different* test selection
#: than the criterion's and must not anchor it.
_EXTRA_TOKEN_SAFE_RE = re.compile(
    r"^(-[vqxsl]+|-r\S*|-n\d*"
    r"|--verbose|--quiet|--capture=\S+|--tb=\S+|--color=\S+"
    r"|--durations(=\S+)?|--durations-min=\S+|--disable-warnings"
    r"|--junitxml=\S+|--basetemp=\S+|--dist=\S+"
    r"|--cov(=\S*)?|--cov-report=\S+"
    r"|--strict-markers|--strict-config|--exitfirst|--showlocals|--maxfail=\d+"
    r"|--no-header|--no-summary)$"
)


def _normalize_executable(token: str) -> str:
    """Canonical spelling of an executable token: forward slashes, no ``.`` or
    duplicate-separator noise — ``./venv/bin/pytest`` and ``venv/bin/pytest``
    are the same invocation. Lexical only: callers must reject ``..``
    components BEFORE comparing (normpath collapses them textually, but the
    OS resolves them after following symlinks)."""
    return os.path.normpath(token.replace("\\", "/"))


def _segment_matches(expected: list[str], actual: list[str]) -> str:
    """Match one segment against the criterion's, classifying extra flags.

    Returns ``"match"`` when the executable agrees — directional: a bare
    criterion executable (``pytest``) accepts any path spelling of the same
    name, while an explicitly path-spelled criterion
    (``/opt/project/.venv/bin/pytest``, and also ``./pytest`` — spelling is
    judged on the raw token because normpath collapses ``./``) requires a
    path-spelled execution of the same normalized path, and a ``..``
    component on either side is unprovable outright (``link/../pytest``
    normalizes to ``pytest`` textually, but the OS follows ``link`` first —
    it may be a different binary) —
    the criterion's arguments appear in order among the executed ones
    (tokens consumed by a negating option — ``--ignore tests/security`` —
    are ineligible evidence, they name what did NOT run), and every extra
    executed token is provably selection-preserving. Extra *positional*
    targets are safe only when the criterion itself scopes the selection
    with a path-like argument (``pytest tests/security``): they widen it,
    so the criterion's tests still ran and the overall result covers them.
    After a bare criterion the same extra positional NARROWS the runner's
    default selection (``python -m unittest pkg.OneTest``). Returns
    ``"unprovable"`` when the textual match carries a behavior-changing
    extra (``pytest -k smoke tests/security``), a negating option excludes
    the matched target or a sub-path of it (``--deselect
    tests/unit/test_auth.py`` against ``pytest tests``), the env-assignment
    prefix differs at all (extra, missing, or different value — no variable
    is provably inert across repositories), or any span token carries a
    runtime expansion (``$VAR``/``$( )``/backticks — expanded arguments are
    unknowable) or an extra token carries glob metacharacters
    (option-looking filenames can narrow invisibly), ``"no_match"``
    otherwise.
    """
    if _effective_env_assignments(expected) != _effective_env_assignments(actual):
        # The environment is part of the invocation: an assignment the
        # criterion does not make, or makes with a different value, can
        # change or skip execution — no variable is provably inert across
        # repositories, so only an exactly equal environment matches. The
        # comparison is the effective name → final-value mapping, not the
        # raw token set: distinct-name order is insignificant, but a
        # repeated name is last-wins — ``CI=0 CI=1`` vs ``CI=1 CI=0`` are
        # equal sets with opposite effective ``CI`` values.
        return "unprovable"
    expected = _strip_env_assignments(expected)
    actual = _strip_env_assignments(actual)
    if not expected or not actual:
        return "no_match"
    if any(_EXPANSION_CHAR_RE.search(token) for token in (*expected, *actual)):
        # A substitution expands at runtime to arguments the matcher cannot
        # see — hidden flags (``pytest tests/security $(cat args)``) or
        # unknown targets (``pytest $T``).
        return "unprovable"
    if expected[0] != actual[0]:
        # A ``..`` component makes the executable's identity lexically
        # unprovable: ``os.path.normpath`` collapses ``link/../pytest`` to
        # ``pytest`` TEXTUALLY, but the OS resolves ``..`` AFTER following
        # symlinks — with ``link`` → ``/tmp/attacker/subdir`` the executed
        # binary is ``/tmp/attacker/pytest``, not the project-local
        # ``./pytest`` the normalized form claims. Two tokens that normalize
        # alike can name different binaries, so any parent-traversal
        # component on either side fails closed. (An identical token on
        # both sides skips this branch entirely — the criterion and the
        # execution then name the same odd path, which is fine.)
        if ".." in expected[0].replace("\\", "/").split("/") or ".." in actual[0].replace("\\", "/").split("/"):
            return "unprovable"
        # Path-spelling is judged on the RAW token, not the normalized form:
        # ``./pytest`` names the project-local file, but normpath collapses
        # it to bare ``pytest`` — deciding on the normalized form would let a
        # PATH lookup or ``/tmp/fake/pytest`` stand in for the explicit
        # local executable the criterion asked for.
        if "/" in expected[0] or "\\" in expected[0]:
            # An explicitly path-spelled criterion names THAT executable: a
            # same-basename binary at a different path (or a bare PATH lookup
            # resolving who-knows-where) may select a different environment —
            # only a path-spelled execution of the same normalized path is
            # evidence for it (``venv/bin/pytest`` ≡ ``./venv/bin/pytest``).
            if "/" not in actual[0] and "\\" not in actual[0]:
                return "no_match"
            if _normalize_executable(expected[0]) != _normalize_executable(actual[0]):
                return "no_match"
        elif os.path.basename(expected[0]) != os.path.basename(actual[0]):
            # A bare criterion deliberately leaves the runner to PATH, so any
            # path spelling of the same executable name is evidence for it.
            return "no_match"
    option_positions, negated = _negated_positions(actual)
    consumed: set[int] = {0}
    index = 1
    for token in expected[1:]:
        found = False
        while index < len(actual):
            candidate = actual[index]
            eligible = index not in negated
            if candidate == token and eligible:
                consumed.add(index)
                index += 1
                found = True
                break
            index += 1
        if not found:
            return "no_match"
    if negated and not _criterion_scopes_selection(expected):
        # A criterion with no positional selection target (bare ``pytest``,
        # ``make test``) stands for the runner's DEFAULT selection: any
        # negating option narrows it, and there is no consumed criterion
        # token for the overlap check below to catch it with —
        # ``pytest --ignore tests/security`` never ran the selection the
        # criterion means.
        return "unprovable"
    # An expected target negated elsewhere in the same command was excluded
    # even though a positional occurrence matched — the passing summary comes
    # from the remaining targets. The overlap check is by path/nodeid
    # prefix, not exact token equality: excluding a SUB-PATH of the
    # criterion's target (``pytest tests --deselect tests/unit/test_auth.py``)
    # means the excluded tests never ran, so the summary does not cover the
    # criterion's selection; excluding a PARENT (``pytest tests/unit
    # --ignore tests``) excludes the target itself. Unrelated exclusions
    # (``--ignore tests/slow`` against ``pytest tests/unit``) keep matching.
    negated_values = [_negated_value(actual[position]) for position in negated]
    if any(_EXPANSION_CHAR_RE.search(value) or _GLOB_CHAR_RE.search(value) or ".." in value.replace("\\", "/").split("/") for value in negated_values):
        # An unknown, glob, or parent-traversal exclusion (``--ignore $X``,
        # ``--ignore tests/slow*``, ``--ignore link/../tests/security``):
        # the overlap check cannot reason about what did not run — the
        # ``..`` form because lexical prefixes lie (the OS follows ``link``
        # before resolving ``..``, so a textually unrelated value can name
        # the criterion's target).
        return "unprovable"
    if any(_negation_overlaps(actual[position], value) for position in consumed if position != 0 for value in negated_values):
        return "unprovable"
    for position, token in enumerate(actual):
        if position in consumed or position in negated or position in option_positions:
            continue
        if _EXPANSION_CHAR_RE.search(token) or _GLOB_CHAR_RE.search(token):
            # An extra token whose expansion or glob result is unknowable —
            # it may inject flags (``$(cat args)``) or option-looking
            # filenames that narrow the run invisibly.
            return "unprovable"
        if token.startswith("-"):
            if not _EXTRA_TOKEN_SAFE_RE.fullmatch(token):
                return "unprovable"
        elif not _criterion_scopes_selection(expected):
            # A bare criterion (``python -m unittest``, bare ``pytest``) means
            # the runner's default selection; an extra positional NARROWS it
            # to specific targets (``pkg.OneTest``), so the recorded run is a
            # different selection than the criterion's — unprovable.
            return "unprovable"
    return "match"


def _span_attributable(ops_before: list[str], ops_within: list[str], ops_after: list[str], executed_success: bool) -> bool:
    """Whether the matching span provably ran with the recorded exit status.

    The whole-command exit status belongs to the *last executed* segment, so
    the span must end at the last segment (checked by the caller) and every
    operator around it must keep execution provable:

    - ``;`` is unconditional; ``|`` before the span is unconditional too
      (pipeline stages all run), but ``|`` *within* the span breaks exit
      attribution (the pipeline's status is its last stage's, not the test's).
    - ``&&`` makes the next segment conditional on success — provable only
      when the recorded status is success.
    - ``||`` makes the next segment conditional on failure — provable only
      when the recorded status is failure.
    - ``&`` (background) and exotic punctuation runs are never provable.
    """
    if any(op != ";" for op in ops_after):
        # A trailing ``&`` (backgrounding) or dangling conditional means the
        # recorded status is not the matched command's own outcome. A
        # trailing ``;`` is everyday shell punctuation and harmless.
        return False
    for op in ops_within:
        if op == ";":
            continue
        if op == "&&" and executed_success:
            continue
        return False
    for op in ops_before:
        if op in (";", "|", "|&"):
            continue
        if op == "&&" and executed_success:
            continue
        if op == "||" and not executed_success:
            continue
        return False
    return True


def _criterion_connectors_preserved(expected_ops: list[str], executed_within_ops: list[str], executed_success: bool) -> bool:
    """Whether the executed span keeps the criterion's control-flow connectors.

    Criterion operators carry semantics the match must preserve: an expected
    ``&&`` makes the next segment conditional on the previous segment's
    success, so executing it as ``;`` (``cd missing; pytest
    tests/test_auth.py`` against criterion ``cd missing && pytest
    tests/test_auth.py``) lets a failed preceding step be bypassed while the
    run still succeeds from the wrong state. The reverse substitution is
    sound: an unconditional criterion connector (``;``) executed as ``&&``
    is the stricter run — with a recorded success the final segment provably
    ran (a recorded failure already fails span attribution on its own). A
    trailing criterion operator other than ``;`` (``make test &``) has no
    executed counterpart — the span must end at the last executed segment —
    so it is never preserved.
    """
    trailing = expected_ops[len(executed_within_ops) :]
    if any(op != ";" for op in trailing):
        return False
    # Trailing criterion ``;`` operators are validated above; the pairwise
    # comparison covers only the connector prefix between the span's
    # segments, or a criterion spelled ``make test;`` (one more operator
    # than connectors) would raise on the strict zip — and the task tool
    # discards the whole verdict on an exception.
    for expected_op, executed_op in zip(expected_ops[: len(executed_within_ops)], executed_within_ops, strict=True):
        if expected_op == executed_op:
            continue
        if expected_op == ";" and executed_op == "&&" and executed_success:
            continue
        return False
    return True


def _commands_match(criterion_command: str, executed_command: str, *, executed_success: bool) -> str:
    """Shell-structure match with control-flow attribution.

    Returns ``"match"`` when the criterion's segment sequence appears as
    consecutive executed segments ending at the last segment AND the span
    provably ran with the recorded status; ``"unprovable"`` when a span
    matches textually but control flow (``false && pytest x; echo done``,
    backgrounding, pipelines inside the span) means it cannot be proven to
    have executed; ``"no_match"`` otherwise. Containment of raw strings is
    deliberately not enough — ``echo '12 passed'; # pytest x.py`` must not
    anchor ``tests_passed:pytest x.py``.
    """
    expected_parsed = _shell_parse(criterion_command)
    actual_parsed = _shell_parse(executed_command)
    if expected_parsed is None or actual_parsed is None:
        # Malformed shell: only exact normalized equality survives.
        expected_norm = _normalize_command(criterion_command)
        return "match" if expected_norm and expected_norm == _normalize_command(executed_command) else "no_match"
    expected, expected_ops = expected_parsed
    actual, ops = actual_parsed
    if not expected or not actual or len(expected) > len(actual):
        return "no_match"
    span = len(expected)
    saw_unprovable = False
    for start in range(len(actual) - span + 1):
        if any(_segment_pollutes_state(segment) for segment in actual[:start]):
            # A preceding segment mutated shell state the matcher cannot see
            # (PATH/exports): nothing later is provable.
            saw_unprovable = True
            continue
        outcomes = [_segment_matches(expected[i], actual[start + i]) for i in range(span)]
        if any(outcome == "no_match" for outcome in outcomes):
            continue
        if any(outcome == "unprovable" for outcome in outcomes):
            saw_unprovable = True
            continue
        # The exit status is attributable only to the command's last segment.
        if start + span != len(actual):
            saw_unprovable = True
            continue
        if not _criterion_connectors_preserved(expected_ops, ops[start : start + span - 1], executed_success):
            # Textually equal segments wired with weaker control flow than the
            # criterion's (an expected ``&&`` executed as ``;``) — a failed
            # preceding step may have been bypassed.
            saw_unprovable = True
            continue
        if _span_attributable(ops[:start], ops[start : start + span - 1], ops[start + span - 1 :], executed_success):
            return "match"
        saw_unprovable = True
    return "unprovable" if saw_unprovable else "no_match"


#: ``<``/``>`` are ordinary word characters to the parser (only ``;&|`` are
#: punctuation), so a redirection in the matched final segment is invisible
#: to the matcher: ``pytest tests/ > /dev/null`` still matches, while the
#: runner's real summary went to the redirection target and the recorded
#: tail carries whatever remains — text any preceding segment (or nothing)
#: produced. Any token carrying a redirection char makes the tail
#: non-attributable. (``&>``/``2>&1`` already degrade upstream: the bare
#: ``&`` parses as an operator and breaks span/exit attribution.)
_REDIRECTION_CHAR_RE = re.compile(r"[<>]")


def _output_attribution(executed_command: str, thread_data: Mapping[str, Any] | None = None) -> str | None:
    """Why the recorded output tail cannot be attributed to the matched
    final segment, or ``None`` when it can.

    The matched segment is always the command's last (the matcher requires
    the span to end there). Two channels break attribution:

    - A redirection token in that final segment (``pytest tests/ > log``):
      the real summary may have gone to the target while the recorded tail
      carries text from anywhere, so neither a pass nor a fail shape in it
      is test evidence.
    - A preceding segment that is not provably silent by invocation form
      (``echo '12 passed'; make test``, a ``pushd``/``export -p`` that
      prints): it could have emitted the very summary the shape check reads.
    """
    parsed = _shell_parse(executed_command)
    if parsed is None:
        return None  # unparseable commands already fell back to exact equality
    segments, _ops = parsed
    if any(_REDIRECTION_CHAR_RE.search(token) for token in segments[-1]):
        return "matched segment redirects its output; the recorded tail is not test evidence"
    if not all(_is_silent_segment(segment, thread_data) for segment in segments[:-1]):
        return "recorded output is not attributable to the matched segment"
    return None


def _check_tests_passed_leaf(command: str, bash_executions: list[dict[str, Any]] | None, thread_data: Mapping[str, Any] | None = None) -> AcceptanceLeaf:
    base: AcceptanceLeaf = {"criterion": "", "family": "tests_passed", "checked": False, "holds": False, "detail": ""}
    matches: list[tuple[str, dict[str, Any]]] = []
    for execution in bash_executions or []:
        status = str(execution.get("status") or "")
        outcome = _commands_match(command, str(execution.get("command") or ""), executed_success=status == "success")
        if outcome == "match" and execution.get("command_truncated"):
            # The recorded command lost its suffix to the evidence cap; a
            # selection-changing tail (``-k smoke``) may have been cut away.
            outcome = "unprovable"
        if outcome != "no_match":
            matches.append((outcome, execution))
    if not matches:
        base["detail"] = "no matching bash execution recorded"
        return base
    # The latest matching run is decisive: earlier failing attempts superseded
    # by a later pass must not fail the leaf.
    latest_outcome, latest = matches[-1]
    if latest_outcome == "unprovable":
        base["detail"] = "recorded command is truncated; the match cannot be proven" if latest.get("command_truncated") else "matching segment cannot be proven to have executed"
        return base
    shell_persistent = latest.get("shell_persistent")
    if shell_persistent is not False:
        # Provenance comes from the harvest stamp (``_harvest_bash_executions``
        # resolves ``Sandbox.persistent_shell_sessions`` against the sandbox
        # recorded in the state that CARRIED the evidence — the subagent's own
        # graph state — never the parent task runtime, which has no
        # ``sandbox`` key when the parent delegated before touching one).
        # True: the matched run shared one persistent shell with every earlier
        # call — any of them (including one since capped away or compacted
        # out) could have exported PATH or redefined the runner. None: the
        # producing sandbox could not be identified OR never declared its
        # session semantics (a custom provider's silence is not fresh-shell
        # proof) — fail closed either way. Re-execution belongs to the
        # read-only verifier (RFC §6).
        if shell_persistent is True:
            base["detail"] = "recorded bash evidence comes from a persistent shell session; earlier calls' state cannot be proven clean"
        else:
            base["detail"] = "the producing sandbox does not declare one-shot shell sessions (or could not be identified); shell state cannot be proven clean"
        return base
    status = str(latest.get("status") or "")
    if status != "success":
        base["checked"] = True
        marker = latest.get("status_marker")
        if isinstance(marker, str) and marker.strip():
            # The recorded failure comes from a trailing exit marker, which
            # the harness cannot distinguish from the command's own output
            # ending in the same shape — report what was actually seen.
            base["detail"] = f"recorded output carries an exit marker ({_bound_detail(marker)}); the harness cannot tell it from the command's own text"
        else:
            base["detail"] = f"latest matching run recorded status={status or 'unknown'}"
        return base
    output_tail = str(latest.get("output_tail") or "")
    unattributable = _output_attribution(str(latest.get("command") or ""), thread_data)
    if unattributable is not None:
        # Neither a pass nor a fail shape here can be trusted either way.
        base["detail"] = unattributable
        return base
    if _TEST_FAIL_SHAPE_RE.search(output_tail):
        base["checked"] = True
        base["detail"] = "recorded output carries a failing test summary"
        return base
    if _TEST_PASS_SHAPE_RE.search(output_tail) and not _TEST_ZERO_SHAPE_RE.search(output_tail):
        base["checked"] = True
        base["holds"] = True
        base["detail"] = "recorded output carries a passing test summary"
        return base
    base["detail"] = "matching run recorded no test-summary shape"
    return base


def check_acceptance_criteria(
    acceptance_criteria: list[str] | None,
    *,
    runtime: Any = None,
    thread_data: Mapping[str, Any] | None = None,
    bash_executions: list[dict[str, Any]] | None = None,
    content_reader: Callable[[Any, str], str] | None = None,
    size_prober: Callable[[Any, str, Mapping[str, Any] | None], int | None] | None = None,
    readable_prober: Callable[[Any, str, Mapping[str, Any] | None], bool | None] | None = None,
) -> AcceptanceVerdict | None:
    """Check each decidable criterion against recorded execution evidence.

    Returns ``None`` when no usable criterion exists (caller stamps nothing).
    Synchronous: the async call site offloads via ``asyncio.to_thread`` —
    ``content_reader`` performs sandbox IO. Criteria hygiene mirrors
    ``report_contract.render_acceptance_criteria_block`` (strip, drop empties,
    cap count/length) so the checked list matches the delegated list.
    """
    if not acceptance_criteria:
        return None
    # Lazy import: the sanitizer lives in agents.middlewares, and this package
    # is imported in cycles with deerflow.agents (same pattern as
    # report_contract). Criterion text is model-supplied untrusted data; it
    # must be neutralized here exactly as render_acceptance_criteria_block
    # does, or a blocked tag in a criterion would be reintroduced into the
    # lead-visible result text by render_acceptance_section.
    from deerflow.agents.middlewares.input_sanitization_middleware import neutralize_untrusted_tags

    criteria: list[str] = []
    for criterion in acceptance_criteria:
        if not isinstance(criterion, str):
            continue
        cleaned = criterion.strip()[:MAX_CRITERION_CHARS].strip()
        if cleaned:
            criteria.append(neutralize_untrusted_tags(cleaned))
        if len(criteria) >= MAX_ACCEPTANCE_CRITERIA:
            break
    if not criteria:
        return None

    if content_reader is None:
        # Lazy import: sandbox.tools pulls the provider stack (see
        # _resolve_scoped_path).
        from deerflow.sandbox.tools import read_current_file_content

        content_reader = read_current_file_content
    if size_prober is None:
        size_prober = _probe_file_size
    if readable_prober is None:
        readable_prober = _probe_file_readable
    leaves: list[AcceptanceLeaf] = []
    for criterion in criteria:
        file_match = _FILE_LEAF_RE.match(criterion)
        written_match = _FILE_WRITTEN_RE.match(criterion)
        tests_match = _TESTS_PASSED_RE.match(criterion)
        if file_match is not None:
            mode = file_match.group("mode").lower()
            family = "file_exists" if mode == "exists" else "file_non_empty"
            leaf = _check_file_leaf(family, file_match.group("path"), runtime=runtime, thread_data=thread_data, content_reader=content_reader, size_prober=size_prober, readable_prober=readable_prober)
        elif written_match is not None:
            leaf = _check_file_leaf("file_written", written_match.group("path"), runtime=runtime, thread_data=thread_data, content_reader=content_reader, size_prober=size_prober, readable_prober=readable_prober)
        elif tests_match is not None:
            leaf = _check_tests_passed_leaf(tests_match.group("command"), bash_executions, thread_data)
        else:
            leaf = AcceptanceLeaf(criterion="", family="undecidable", checked=False, holds=False, detail="not deterministically checkable")
        leaf["criterion"] = criterion
        leaf["detail"] = _bound_detail(leaf["detail"])
        leaves.append(leaf)

    return AcceptanceVerdict(
        source=CHECK_SOURCE,
        requirement=CHECK_REQUIREMENT,
        leaves=leaves,
        unchecked=[leaf["criterion"] for leaf in leaves if not leaf["checked"]],
        all_hold=all(leaf["checked"] and leaf["holds"] for leaf in leaves),
    )


def validate_acceptance_verdict(value: object) -> AcceptanceVerdict | None:
    """Structural check for a persisted verdict (read side trusts nothing)."""
    if not isinstance(value, dict):
        return None
    source = value.get("source")
    requirement = value.get("requirement")
    all_hold = value.get("all_hold")
    if not isinstance(source, str) or not isinstance(requirement, str):
        return None
    if not isinstance(all_hold, bool):
        return None
    raw_leaves = value.get("leaves")
    raw_unchecked = value.get("unchecked")
    if not isinstance(raw_leaves, list) or len(raw_leaves) > MAX_ACCEPTANCE_CRITERIA:
        return None
    if not isinstance(raw_unchecked, list) or any(not isinstance(item, str) for item in raw_unchecked):
        return None
    leaves: list[AcceptanceLeaf] = []
    for entry in raw_leaves:
        if not isinstance(entry, dict):
            return None
        criterion = entry.get("criterion")
        family = entry.get("family")
        checked = entry.get("checked")
        holds = entry.get("holds")
        detail = entry.get("detail")
        if not all(isinstance(field, str) for field in (criterion, family, detail)):
            return None
        if not isinstance(checked, bool) or not isinstance(holds, bool):
            return None
        leaves.append(AcceptanceLeaf(criterion=criterion, family=family, checked=checked, holds=holds, detail=detail))
    return AcceptanceVerdict(
        source=source,
        requirement=requirement,
        leaves=leaves,
        unchecked=list(raw_unchecked),
        all_hold=all_hold,
    )


def render_acceptance_section(verdict: AcceptanceVerdict) -> str:
    """Render the per-criterion checklist section for the result text.

    One leaf is exactly one line: the criterion is model-supplied untrusted
    text (tag-neutralized, but newlines are not tags), so it is rendered
    whitespace-collapsed — a multi-line criterion would otherwise inject a
    forged ``- [holds] …`` line into the checklist the lead reads. The
    stored verdict keeps the verbatim criterion; only the display collapses.
    """
    lines = [f"Acceptance checklist (deterministic checks; {_LIMITATION}):"]
    for leaf in verdict["leaves"]:
        if not leaf["checked"]:
            marker = "UNVERIFIED"
        elif leaf["holds"]:
            marker = "holds"
        else:
            marker = "does not hold"
        lines.append(f"- [{marker}] {' '.join(leaf['criterion'].split())} — {leaf['detail']}")
    return "\n".join(lines)


def render_acceptance_segment(verdict: AcceptanceVerdict) -> str:
    """Render the compact delegation-ledger segment (counts only)."""
    holds = sum(1 for leaf in verdict["leaves"] if leaf["checked"] and leaf["holds"])
    does_not_hold = sum(1 for leaf in verdict["leaves"] if leaf["checked"] and not leaf["holds"])
    unverified = sum(1 for leaf in verdict["leaves"] if not leaf["checked"])
    parts: list[str] = []
    if holds:
        parts.append(f"{holds} hold")
    if does_not_hold:
        parts.append(f"{does_not_hold} does not hold")
    if unverified:
        parts.append(f"{unverified} UNVERIFIED")
    if not parts:
        return ""
    return f"acceptance: {', '.join(parts)} — {_LIMITATION}"
