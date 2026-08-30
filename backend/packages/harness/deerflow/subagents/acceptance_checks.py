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
  leaves degrade to UNVERIFIED instead of misjudging.
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

All functions are pure (file IO only through the injected reader); the async
caller offloads the whole check with ``asyncio.to_thread``.
"""

from __future__ import annotations

import os
import re
import shlex
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

#: Test-runner summary shapes recognized in a recorded bash output tail.
#: Pass shapes require an explicit success summary; fail shapes require an
#: explicit failure record. An output carrying neither is not evidence either
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
    r"|^FAILED\b"  # unittest summary line
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


def _check_file_leaf(family: str, path: str, *, runtime: Any, thread_data: Mapping[str, Any] | None, content_reader: Callable[[Any, str], str]) -> AcceptanceLeaf:
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


def _is_silent_segment(tokens: list[str]) -> bool:
    """Whether a preceding segment is provably output-free, by invocation
    form — not by executable name alone: ``pushd``/``popd`` print the
    directory stack, ``export -p`` prints variables, ``umask``/``ulimit``
    print on several forms, and ``source`` runs whatever the file prints.

    ``cd`` stays classified silent: it only prints via CDPATH (a bare path,
    never a test-summary shape) and the workspace ``cd dir &&`` wrapper is
    the norm — bash_tool auto-prefixes it for every local command.
    """
    stripped = _strip_env_assignments(tokens)
    if not stripped:
        return True  # pure VAR=value assignments
    executable = os.path.basename(stripped[0])
    args = stripped[1:]
    if executable == "cd":
        return True
    if executable == "export":
        # ``export A=1`` / ``export NAME`` print nothing; bare ``export``
        # and ``export -p`` print the environment.
        return bool(args) and "-p" not in args
    if executable in {"source", "."}:
        # Only the conventional (quiet) venv activation script is accepted.
        return bool(args) and args[-1].endswith("activate")
    if executable == "unset":
        return bool(args)
    # pushd/popd (print the stack), umask/ulimit (print forms), and every
    # other executable are not provably silent.
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


def _normalize_command(command: str) -> str:
    return " ".join(command.split())


def _shell_parse(command: str) -> tuple[list[list[str]], list[str]] | None:
    """Tokenize a shell command into segments plus the operators joining them.

    ``ops[i]`` is the operator between segment ``i`` and segment ``i+1``
    (``;``, ``&&``, ``||``, ``|``, ``&``, or a rarer punctuation run).
    Comments are stripped (a ``# pytest ...`` remark executes nothing) and
    quotes are honored, so an operator inside an argument cannot split a
    segment. Returns ``None`` on malformed shell (unbalanced quotes).
    """
    lexer = shlex.shlex(command, posix=True, punctuation_chars=_SHELL_OPERATORS)
    lexer.whitespace_split = True
    lexer.commenters = "#"
    try:
        tokens = list(lexer)
    except ValueError:
        return None
    segments: list[list[str]] = []
    ops: list[str] = []
    current: list[str] = []
    for token in tokens:
        if token and all(char in _SHELL_OPERATORS for char in token):
            if current:
                segments.append(current)
                current = []
                ops.append(token)
            # A leading or doubled operator (``cmd ;; esac`` style) attaches
            # no following segment; it can never make evidence more provable,
            # so it is simply not recorded.
        else:
            current.append(token)
    if current:
        segments.append(current)
    # ops[i] is the operator following segment i; a trailing operator (e.g.
    # ``make test &``) leaves ops as long as segments and must stay visible —
    # backgrounding makes the execution unprovable.
    return segments, ops


def _strip_env_assignments(tokens: list[str]) -> list[str]:
    index = 0
    while index < len(tokens) and _ENV_ASSIGNMENT_RE.match(tokens[index]):
        index += 1
    return tokens[index:]


#: A criterion argument scopes the run's selection only when it is path-like
#: (``tests/security``, ``tests/test_auth.py``); dotted module names, make
#: targets, and bare runner invocations leave the runner default in charge,
#: so extra positionals after them narrow rather than widen.
_CRITERION_PATHLIKE_ARG_RE = re.compile(r"[/\\]|\.(?:py|jsx?|tsx?|go|rs|java|rb|php)$")


def _criterion_scopes_selection(expected: list[str]) -> bool:
    return any(_CRITERION_PATHLIKE_ARG_RE.search(token) for token in expected[1:])


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


def _segment_matches(expected: list[str], actual: list[str]) -> str:
    """Match one segment against the criterion's, classifying extra flags.

    Returns ``"match"`` when the executable agrees (path spellings allowed),
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
    extra (``pytest -k smoke tests/security``), ``"no_match"`` otherwise.
    """
    expected = _strip_env_assignments(expected)
    actual = _strip_env_assignments(actual)
    if not expected or not actual:
        return "no_match"
    if expected[0] != actual[0] and os.path.basename(expected[0]) != os.path.basename(actual[0]):
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
    # An expected target that is ALSO negated elsewhere in the same command
    # (``pytest tests/security tests/unit --ignore tests/security``) was
    # excluded even though a positional occurrence matched — the passing
    # summary comes from the remaining targets.
    if {actual[position] for position in consumed if position != 0} & {actual[position] for position in negated}:
        return "unprovable"
    for position, token in enumerate(actual):
        if position in consumed or position in negated or position in option_positions:
            continue
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
    expected, _ = expected_parsed
    actual, ops = actual_parsed
    if not expected or not actual or len(expected) > len(actual):
        return "no_match"
    span = len(expected)
    saw_unprovable = False
    for start in range(len(actual) - span + 1):
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
        if _span_attributable(ops[:start], ops[start : start + span - 1], ops[start + span - 1 :], executed_success):
            return "match"
        saw_unprovable = True
    return "unprovable" if saw_unprovable else "no_match"


def _output_attributable(executed_command: str) -> bool:
    """Whether the recorded output is attributable to the matched final
    segment: every preceding segment must be provably silent by invocation
    form. Anything else — ``echo '12 passed'; make test``, or a
    ``pushd``/``export -p`` that prints — could have emitted the very
    summary the shape check would read."""
    parsed = _shell_parse(executed_command)
    if parsed is None:
        return True  # unparseable commands already fell back to exact equality
    segments, _ops = parsed
    return all(_is_silent_segment(segment) for segment in segments[:-1])


def _check_tests_passed_leaf(command: str, bash_executions: list[dict[str, Any]] | None) -> AcceptanceLeaf:
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
    status = str(latest.get("status") or "")
    if status != "success":
        base["checked"] = True
        base["detail"] = f"latest matching run recorded status={status or 'unknown'}"
        return base
    output_tail = str(latest.get("output_tail") or "")
    if not _output_attributable(str(latest.get("command") or "")):
        # A preceding segment may have printed the summary — neither a pass
        # nor a fail shape here can be trusted either way.
        base["detail"] = "recorded output is not attributable to the matched segment"
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

    leaves: list[AcceptanceLeaf] = []
    for criterion in criteria:
        file_match = _FILE_LEAF_RE.match(criterion)
        written_match = _FILE_WRITTEN_RE.match(criterion)
        tests_match = _TESTS_PASSED_RE.match(criterion)
        if file_match is not None:
            mode = file_match.group("mode").lower()
            family = "file_exists" if mode == "exists" else "file_non_empty"
            leaf = _check_file_leaf(family, file_match.group("path"), runtime=runtime, thread_data=thread_data, content_reader=content_reader)
        elif written_match is not None:
            leaf = _check_file_leaf("file_written", written_match.group("path"), runtime=runtime, thread_data=thread_data, content_reader=content_reader)
        elif tests_match is not None:
            leaf = _check_tests_passed_leaf(tests_match.group("command"), bash_executions)
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
    """Render the per-criterion checklist section for the result text."""
    lines = [f"Acceptance checklist (deterministic checks; {_LIMITATION}):"]
    for leaf in verdict["leaves"]:
        if not leaf["checked"]:
            marker = "UNVERIFIED"
        elif leaf["holds"]:
            marker = "holds"
        else:
            marker = "does not hold"
        lines.append(f"- [{marker}] {leaf['criterion']} — {leaf['detail']}")
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
