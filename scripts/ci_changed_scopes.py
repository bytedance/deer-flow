#!/usr/bin/env python3
"""Decide which test scopes a pull request needs and print them as GitHub outputs.

Prints one ``<scope>=true|false`` line per scope, for ``>> "$GITHUB_OUTPUT"``.
The rules fail open: every scope runs on pushes, when CI configuration changes,
and when the changed files cannot be determined. Only the PR's own changes are
compared, as the diff between the checked-out merge commit and its first parent
(the base branch tip), so this needs ``actions/checkout`` with ``fetch-depth: 2``.

- ``backend`` runs unless every changed file is one the backend suite never
  reads. Backend tests read files across the whole repository (scripts, Compose,
  Helm, examples, contracts, root config, frontend docs), so this scope lists
  what to skip; ``test_ci_changed_scopes.py`` fails when backend code names a
  skipped frontend path.
- ``frontend`` runs when a file that frontend tests or the frontend build read
  changes. Those reads are explicit relative paths from ``frontend/``, so this
  scope lists what to include; ``test_ci_changed_scopes.py`` fails when a frontend
  file starts reading a path outside it.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Iterable

SCOPES = ("backend", "frontend")

# Any change here can alter what CI runs, so it runs everything.
RUN_ALL_PREFIXES = (".github/", "scripts/ci_changed_scopes.py")

FRONTEND_PREFIXES = (
    "frontend/",
    "contracts/",
    "examples/",
    "skills/public/",
    "backend/packages/harness/deerflow/capabilities/builtin.json",
)

# The backend suite never reads frontend sources, tests or static assets ...
BACKEND_SKIP_PREFIXES = ("frontend/src/", "frontend/tests/", "frontend/public/")
# ... except these, which backend documentation, contract and guidance tests read.
# Frontend root files (package.json, the lockfile, Makefile, next.config.js) stay
# in the backend scope because version, Compose and serve tests read them.
BACKEND_READS_UNDER_SKIPPED = (
    "frontend/src/content/",
    "frontend/src/core/api/api-client.ts",
    "frontend/src/core/extensions/bundled-documentation.json",
)
# The agent guidance tests walk every AGENTS.md and CLAUDE.md in the repository.
BACKEND_READS_BY_NAME = ("AGENTS.md", "CLAUDE.md")


def _matches(path: str, prefixes: Iterable[str]) -> bool:
    return any(path == prefix or path.startswith(prefix) for prefix in prefixes)


def _backend_reads(path: str) -> bool:
    return (
        not _matches(path, BACKEND_SKIP_PREFIXES)
        or _matches(path, BACKEND_READS_UNDER_SKIPPED)
        or path.rsplit("/", 1)[-1] in BACKEND_READS_BY_NAME
    )


def scopes_for(changed: list[str]) -> dict[str, bool]:
    """Map the changed repository paths to the scopes that must run."""
    if not changed or any(_matches(path, RUN_ALL_PREFIXES) for path in changed):
        return dict.fromkeys(SCOPES, True)
    return {
        "backend": any(_backend_reads(path) for path in changed),
        "frontend": any(_matches(path, FRONTEND_PREFIXES) for path in changed),
    }


def changed_files() -> list[str] | None:
    """Return the files the checked-out PR merge commit changes, or None if unknown."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--no-renames", "-z", "HEAD^1", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        print(
            f"ci_changed_scopes: cannot diff HEAD^1..HEAD ({exc}); running every scope",
            file=sys.stderr,
        )
        return None
    return [path for path in result.stdout.split("\0") if path]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--event", required=True, help="github.event_name of the workflow run"
    )
    args = parser.parse_args(argv)

    changed = changed_files() if args.event == "pull_request" else None
    scopes = scopes_for(changed or [])
    for scope in SCOPES:
        print(f"{scope}={'true' if scopes[scope] else 'false'}")
    reason = "pull request diff" if changed else f"{args.event} event or unknown diff"
    print(
        f"ci_changed_scopes: {scopes} from {reason} ({len(changed or [])} files)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
