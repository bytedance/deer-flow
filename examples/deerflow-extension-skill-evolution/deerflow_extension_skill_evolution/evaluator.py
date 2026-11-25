"""Deterministic static evaluation of proposed skill revisions.

This evaluator never executes package content. A candidate bundle is an
agent-proposed revision that has not passed the host security ``check`` yet,
so the only safe operations are structural: file presence, decoded-text
assertions, reference integrity, and ``ast.parse`` (parse only, no import,
no exec) for bundled Python scripts.

Recorded regression cases describe the defect a proposal claims to fix. The
verdict compares both sides of the proposal:

- ``justified``   — every case passes on the candidate and at least one fails
  on the baseline: the change demonstrably fixes a recorded defect.
- ``unjustified`` — every case passes on both sides: nothing recorded was
  broken, so the proposal carries no evidence-backed reason to land.
- ``failed``      — some case still fails on the candidate (or no cases were
  recorded at all): the fix does not hold, so the proposal must not commit.

The report is deterministic — same inputs, same bytes, same ``report_id`` —
which is what lets it be referenced from a commit's ``AssessmentRef`` and
re-verified later.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

EVALUATOR_NAME = "skill-evolution-example-static"
EVALUATOR_VERSION = "0.1.0"

Decision = Literal["justified", "unjustified", "failed"]

#: ``Package`` is the evaluator's view of one skill revision: POSIX-relative
#: file path → raw bytes. The host bundle (``ProposalBundle.baseline`` /
#: ``.candidate``) converts with ``{f.path: f.content for f in files}``.
Package = Mapping[str, bytes]

# Bare in-package references inside SKILL.md prose. A reference must appear as
# a standalone token: the lookbehind rejects a preceding word character, path
# separator, dot, colon or dash, so a URL such as
# ``https://example.com/scripts/run.py`` is not mistaken for an in-package file.
# Trailing sentence punctuation is trimmed after the match (see ``_references``).
# Only the two conventional skill subdirectories are scanned.
_REFERENCE_RE = re.compile(r"(?<![\w/.:-])((?:scripts|assets)/[A-Za-z0-9_./-]+)")
_CASE_ID_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_MAX_DETAIL_CHARS = 300

_CHECK_KINDS = frozenset(
    {
        "file_exists",
        "text_contains",
        "text_not_contains",
        "referenced_files_exist",
        "scripts_parse",
    }
)


def _reject_unsafe_path(value: str, field: str) -> str:
    """Validate a case-declared package path before it is ever used as a key."""
    if not value or len(value) > 1024 or "\\" in value or value.startswith("/"):
        raise ValueError(f"{field} must be a relative POSIX path: {value!r}")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError(f"{field} must not contain empty or dot segments: {value!r}")
    return value


@dataclass(frozen=True)
class Check:
    """One static assertion against a skill package."""

    kind: str
    path: str | None = None
    needle: str | None = None

    @classmethod
    def from_json(cls, raw: Any) -> Check:
        if not isinstance(raw, dict):
            raise ValueError("check must be an object")
        kind = raw.get("kind")
        if not isinstance(kind, str) or kind not in _CHECK_KINDS:
            raise ValueError(f"unknown check kind: {kind!r}")
        path = raw.get("path")
        if path is not None:
            if not isinstance(path, str):
                raise ValueError(f"{kind}: path must be a string")
            _reject_unsafe_path(path, f"{kind}: path")
        needle = raw.get("needle")
        if needle is not None and (not isinstance(needle, str) or not needle):
            raise ValueError(f"{kind}: needle must be a nonempty string")
        if kind in {"file_exists", "text_contains", "text_not_contains", "referenced_files_exist"} and path is None:
            raise ValueError(f"{kind} requires a path")
        if kind in {"text_contains", "text_not_contains"} and needle is None:
            raise ValueError(f"{kind} requires a needle")
        return cls(kind=kind, path=path, needle=needle)


@dataclass(frozen=True)
class Case:
    """A recorded regression case: all of its checks must pass on a fixed package."""

    case_id: str
    description: str
    checks: tuple[Check, ...]

    @classmethod
    def from_json(cls, raw: Any, *, origin: str) -> Case:
        if not isinstance(raw, dict):
            raise ValueError(f"{origin}: case must be an object")
        case_id = raw.get("id")
        if not isinstance(case_id, str) or not _CASE_ID_RE.fullmatch(case_id) or len(case_id) > 64:
            raise ValueError(f"{origin}: id must be kebab-case and at most 64 characters")
        description = raw.get("description")
        if not isinstance(description, str) or not description.strip():
            raise ValueError(f"{origin}: description must be a nonempty string")
        checks_raw = raw.get("checks")
        if not isinstance(checks_raw, list) or not checks_raw:
            raise ValueError(f"{origin}: checks must be a nonempty list")
        return cls(
            case_id=case_id,
            description=description.strip(),
            checks=tuple(Check.from_json(item) for item in checks_raw),
        )


def load_cases_dir(directory: str | Path) -> tuple[Case, ...]:
    """Load recorded cases from ``*.json`` files, ordered by file name.

    Malformed files raise ``ValueError`` naming the file: a broken case must
    stop the evaluation rather than silently narrow it.
    """
    root = Path(directory)
    if not root.is_dir():
        raise ValueError(f"cases directory not found: {root}")
    cases: list[Case] = []
    for file in sorted(root.glob("*.json")):
        try:
            raw = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"{file.name}: unreadable case file ({exc})") from exc
        cases.append(Case.from_json(raw, origin=file.name))
    return tuple(cases)


@dataclass(frozen=True)
class CheckOutcome:
    kind: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class CaseOutcome:
    case_id: str
    description: str
    baseline: tuple[CheckOutcome, ...]
    candidate: tuple[CheckOutcome, ...]

    @property
    def baseline_passed(self) -> bool:
        return all(outcome.passed for outcome in self.baseline)

    @property
    def candidate_passed(self) -> bool:
        return all(outcome.passed for outcome in self.candidate)


def _references(text: str) -> list[str]:
    """Extract bare in-package file references from prose.

    ``scripts/run.py.`` at the end of a sentence is the file ``scripts/run.py``,
    not a file whose name ends in a period, so trailing ``.``/``/``/``-`` are
    stripped before the token is looked up in the package.
    """
    return [token for raw in _REFERENCE_RE.findall(text) if (token := raw.rstrip("./-"))]


def _decode(package: Package, path: str) -> tuple[str | None, str]:
    content = package.get(path)
    if content is None:
        return None, f"missing {path}"
    try:
        return content.decode("utf-8"), ""
    except UnicodeDecodeError:
        return None, f"{path} is not valid UTF-8"


def _clip(detail: str) -> str:
    return detail if len(detail) <= _MAX_DETAIL_CHARS else detail[: _MAX_DETAIL_CHARS - 1] + "…"


def run_check(check: Check, package: Package) -> CheckOutcome:
    """Run one static check against one package revision. Never executes code."""
    if check.kind == "file_exists":
        assert check.path is not None
        passed = check.path in package
        return CheckOutcome(check.kind, passed, "" if passed else f"missing {check.path}")

    if check.kind == "text_contains":
        assert check.path is not None and check.needle is not None
        text, detail = _decode(package, check.path)
        if text is None:
            return CheckOutcome(check.kind, False, detail)
        passed = check.needle in text
        return CheckOutcome(check.kind, passed, "" if passed else _clip(f"{check.path} does not contain {check.needle!r}"))

    if check.kind == "text_not_contains":
        assert check.path is not None and check.needle is not None
        text, detail = _decode(package, check.path)
        if text is None:
            return CheckOutcome(check.kind, False, detail)
        passed = check.needle not in text
        return CheckOutcome(check.kind, passed, "" if passed else _clip(f"{check.path} still contains {check.needle!r}"))

    if check.kind == "referenced_files_exist":
        assert check.path is not None
        text, detail = _decode(package, check.path)
        if text is None:
            return CheckOutcome(check.kind, False, detail)
        missing = sorted({token for token in _references(text) if token not in package})
        passed = not missing
        return CheckOutcome(check.kind, passed, "" if passed else _clip(f"{check.path} references missing files: {', '.join(missing)}"))

    # scripts_parse: parse-only syntax gate over every bundled Python script.
    failures: list[str] = []
    for path in sorted(key for key in package if key.startswith("scripts/") and key.endswith(".py")):
        text, detail = _decode(package, path)
        if text is None:
            failures.append(detail)
            continue
        try:
            ast.parse(text, filename=path)
        except SyntaxError as exc:
            failures.append(f"{path}: {exc.msg} (line {exc.lineno})")
    passed = not failures
    return CheckOutcome("scripts_parse", passed, "" if passed else _clip("; ".join(failures)))


def evaluate_case(case: Case, baseline: Package, candidate: Package) -> CaseOutcome:
    return CaseOutcome(
        case_id=case.case_id,
        description=case.description,
        baseline=tuple(run_check(check, baseline) for check in case.checks),
        candidate=tuple(run_check(check, candidate) for check in case.checks),
    )


@dataclass(frozen=True)
class Evaluation:
    decision: Decision
    reasons: tuple[str, ...]
    cases: tuple[CaseOutcome, ...]

    def report(self, *, candidate_hash: str) -> dict[str, Any]:
        """Deterministic JSON-able report; identical inputs produce identical bytes."""
        return {
            "evaluator": EVALUATOR_NAME,
            "evaluator_version": EVALUATOR_VERSION,
            "decision": self.decision,
            "reasons": list(self.reasons),
            "candidate_hash": candidate_hash,
            "cases": [
                {
                    "id": outcome.case_id,
                    "description": outcome.description,
                    "baseline_passed": outcome.baseline_passed,
                    "candidate_passed": outcome.candidate_passed,
                    "baseline": [{"kind": item.kind, "passed": item.passed, "detail": item.detail} for item in outcome.baseline],
                    "candidate": [{"kind": item.kind, "passed": item.passed, "detail": item.detail} for item in outcome.candidate],
                }
                for outcome in self.cases
            ],
        }


def evaluate(cases: Sequence[Case], baseline: Package, candidate: Package) -> Evaluation:
    """Compare recorded cases across both sides of a proposal."""
    if not cases:
        return Evaluation(decision="failed", reasons=("no regression cases recorded; nothing justifies a change",), cases=())
    outcomes = tuple(evaluate_case(case, baseline, candidate) for case in cases)
    candidate_failures = [outcome.case_id for outcome in outcomes if not outcome.candidate_passed]
    baseline_failures = [outcome.case_id for outcome in outcomes if not outcome.baseline_passed]
    if candidate_failures:
        return Evaluation(
            decision="failed",
            reasons=(f"cases still failing on the candidate: {', '.join(candidate_failures)}",),
            cases=outcomes,
        )
    if not baseline_failures:
        return Evaluation(
            decision="unjustified",
            reasons=("every recorded case already passed on the baseline; the proposal fixes nothing on record",),
            cases=outcomes,
        )
    return Evaluation(
        decision="justified",
        reasons=(f"candidate fixes recorded failures: {', '.join(baseline_failures)}",),
        cases=outcomes,
    )


def report_id(report: Mapping[str, Any]) -> str:
    """Content-addressed identifier for a report, safe to store in an AssessmentRef."""
    canonical = json.dumps(dict(report), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
