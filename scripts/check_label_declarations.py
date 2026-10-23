#!/usr/bin/env python3
"""Check that every label the triage workflow applies is declared in labels.yml.

``.github/labels.yml`` is the declarative source of truth for repository labels,
and ``.github/workflows/triage.yml`` applies labels by name at runtime. GitHub
rejects an ``addLabels`` call with **422** when *any* requested label does not
exist, and drops the whole batch -- so a label added to the workflow but
forgotten here makes labelling stop working silently instead of failing loudly.

This is the static guard for that pair: it extracts the label literals the
triage workflow can apply and asserts each one is declared in labels.yml.

Standard library only -- the check has to stay cheap enough to run on every PR.

Usage:
    python scripts/check_label_declarations.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LABELS_FILE = REPO_ROOT / ".github" / "labels.yml"
TRIAGE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "triage.yml"

#: A label literal the triage workflow may hand to ``addLabels``. Deliberately
#: narrower than "any quoted string" so unrelated literals (event names, user
#: types, the bare ``'area:'`` prefix used by ``startsWith``) are not counted.
LABEL_LITERAL = re.compile(
    r"^("
    r"area:[a-z]+"
    r"|size/(?:XS|S|M|L|XL)"
    r"|risk:(?:low|medium|high)"
    r"|needs-[a-z-]+"
    r"|skip-validation"
    r"|reviewing"
    r"|first-time-contributor"
    r")$"
)

#: ``- name: bug`` / ``- name: "area:frontend"`` -- the only shape this file uses.
DECLARED_NAME = re.compile(r"^\s*-\s+name:\s*(?P<value>.+?)\s*$")
QUOTED = re.compile(r"""['"]([^'"\n]+)['"]""")


def declared_labels(path: Path) -> set[str]:
    names: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        match = DECLARED_NAME.match(line)
        if match:
            names.add(match.group("value").strip().strip("'\""))
    return names


def applied_labels(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    return {token for token in QUOTED.findall(text) if LABEL_LITERAL.match(token)}


def main() -> int:
    if not LABELS_FILE.is_file():
        sys.exit(f"Missing {LABELS_FILE}")
    if not TRIAGE_WORKFLOW.is_file():
        sys.exit(f"Missing {TRIAGE_WORKFLOW}")

    declared = declared_labels(LABELS_FILE)
    applied = applied_labels(TRIAGE_WORKFLOW)

    # Guard the guards: a change that makes either extraction match nothing would
    # otherwise turn this check into a no-op that always passes.
    if len(declared) < 20:
        sys.exit(f"Only {len(declared)} labels parsed from {LABELS_FILE} -- the extraction is broken.")
    if not applied:
        sys.exit(f"No label literals found in {TRIAGE_WORKFLOW} -- the extraction is broken.")

    missing = sorted(applied - declared)
    if missing:
        print(
            f"{len(missing)} label(s) applied by {TRIAGE_WORKFLOW.name} are not declared "
            f"in {LABELS_FILE.name}:",
            file=sys.stderr,
        )
        for name in missing:
            print(f"  - {name}", file=sys.stderr)
        print(
            "\nGitHub drops the whole addLabels batch with 422 when a label is missing, "
            "so add these under the matching section of labels.yml.",
            file=sys.stderr,
        )
        return 1

    print(f"OK -- {len(applied)} labels applied by {TRIAGE_WORKFLOW.name} are all declared.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
