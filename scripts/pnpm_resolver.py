#!/usr/bin/env python3
"""Shared pnpm command resolver for all host-side entry points.

Why this exists
---------------
``make check`` historically resolved pnpm through ``find_pnpm_command`` in
``scripts/check.py`` (with a Corepack fallback), while ``make install``,
``make dev`` and ``scripts/serve.sh`` all invoked a bare ``pnpm``. In a
Corepack-only environment (Corepack shipped with Node, but
``corepack enable`` never run so no ``pnpm`` shim exists on ``PATH``),
``make check`` passed while every execution entry point failed with
``pnpm: command not found``. See issue #4404.

This module is the single source of truth. Every host-side consumer —
``scripts/check.py``, ``scripts/doctor.py``, ``scripts/support_bundle.py``,
the ``Makefile`` and ``scripts/serve.sh`` — resolves pnpm through it so the
check path and the execution path can never drift again.

CLI usage (Makefile + shell scripts):

    $ python3 scripts/pnpm_resolver.py
    pnpm                       # when ``pnpm``/``pnpm.cmd`` is on PATH
    /opt/homebrew/bin/pnpm     # absolute paths are returned verbatim
    corepack pnpm              # fallback when only Corepack is available

    Exit code 1 + a stderr message when neither pnpm nor Corepack is on PATH.

Module usage (check.py / doctor.py / support_bundle.py):

    from pnpm_resolver import find_pnpm_command
    cmd = find_pnpm_command()  # list[str] | None
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from shlex import join as _shlex_join


def find_pnpm_command() -> list[str] | None:
    """Return a pnpm-compatible command argv, or ``None`` if none is available.

    Resolution order — every host-side entry point must honour this same order
    so install/check/start agree:

    1. ``pnpm`` on ``PATH`` (preferred — what users typically have).
    2. ``pnpm.cmd`` on ``PATH`` (Windows).
    3. ``corepack`` (or ``corepack.cmd``) on ``PATH`` → invoke as
       ``corepack pnpm`` so a Corepack-only machine still works without
       ``corepack enable``.
    """
    for candidate in ("pnpm", "pnpm.cmd"):
        path = shutil.which(candidate)
        if path:
            return [str(Path(path))]

    for candidate in ("corepack", "corepack.cmd"):
        path = shutil.which(candidate)
        if path:
            return [str(Path(path)), "pnpm"]

    return None


def shell_string(argv: list[str]) -> str:
    """Render an argv as a shell string ready for ``$(...)`` substitution.

    ``shlex.join`` keeps each token separate and shell-safe; consumers
    (``Makefile``'s ``$(PNPM)``, ``serve.sh``'s ``$PNPM_CMD``) word-split it
    back into the original argv, so ``["corepack", "pnpm"]`` round-trips as
    ``corepack pnpm`` rather than a single ``'corepack pnpm'`` token.
    """
    return _shlex_join(argv)


def main() -> int:
    command = find_pnpm_command()
    if not command:
        print(
            "pnpm: not found. Install pnpm (npm install -g pnpm) or enable "
            "Corepack (corepack enable); see https://pnpm.io/installation",
            file=sys.stderr,
        )
        return 1
    print(shell_string(command))
    return 0


if __name__ == "__main__":
    sys.exit(main())
