#!/usr/bin/env python3
"""Run the frontend's pinned pnpm version directly or through Corepack."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
COREPACK_NOTICE = "Using pnpm via Corepack."
PACKAGE_JSON_PATH = FRONTEND_DIR / "package.json"


def find_corepack_command() -> list[str] | None:
    corepack_names = ("corepack.cmd", "corepack") if os.name == "nt" else ("corepack", "corepack.cmd")
    for name in corepack_names:
        if corepack_path := shutil.which(name):
            return [str(Path(corepack_path)), "pnpm"]
    return None


def find_pnpm_command() -> list[str] | None:
    """Return the preferred pnpm-compatible command for this machine."""
    pnpm_names = ("pnpm.cmd", "pnpm") if os.name == "nt" else ("pnpm", "pnpm.cmd")
    for name in pnpm_names:
        if pnpm_path := shutil.which(name):
            return [str(Path(pnpm_path))]

    return find_corepack_command()


def run_pnpm(arguments: Sequence[str]) -> int:
    """Run pnpm with the supplied arguments and propagate its exit status."""
    command = find_pnpm_command()
    if command is None:
        print(
            "Error: Neither pnpm nor Corepack is available on PATH.",
            file=sys.stderr,
        )
        print(
            "Install pnpm, or install Corepack and ensure 'corepack' is on PATH.",
            file=sys.stderr,
        )
        return 127

    if Path(command[0]).stem.lower() == "pnpm":
        try:
            package_manager = json.loads(PACKAGE_JSON_PATH.read_text(encoding="utf-8"))["packageManager"]
            if not isinstance(package_manager, str) or not package_manager.startswith("pnpm@"):
                raise ValueError("packageManager must name a pinned pnpm version")
            pinned_version = package_manager.removeprefix("pnpm@")
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            print(f"Error: Cannot read pinned pnpm version from frontend/package.json: {exc}", file=sys.stderr)
            return 127
        try:
            probe = subprocess.run(
                [command[0], "--version"],
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                check=False,
                shell=False,
                cwd=FRONTEND_DIR,
            )
        except OSError as exc:
            print(f"Error: Failed to check pnpm version via {command[0]}: {exc}", file=sys.stderr)
            return 126
        installed_version = probe.stdout.strip()
        if probe.returncode == 0 and re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", installed_version):
            if installed_version != pinned_version:
                corepack_command = find_corepack_command()
                if corepack_command is None:
                    print(
                        f"Error: pnpm {installed_version} is on PATH, but frontend/package.json pins {pinned_version}. Install that version or make Corepack available.",
                        file=sys.stderr,
                    )
                    return 127
                command = corepack_command
        else:
            print("Warning: could not determine pnpm version; proceeding without pin check.", file=sys.stderr)

    if Path(command[0]).stem.lower() == "corepack":
        print(COREPACK_NOTICE, file=sys.stderr)

    try:
        result = subprocess.run(
            [*command, *arguments],
            check=False,
            shell=False,
            cwd=FRONTEND_DIR,
        )
    except OSError as exc:
        print(f"Error: Failed to run pnpm via {command[0]}: {exc}", file=sys.stderr)
        return 126

    exit_code = 128 - result.returncode if result.returncode < 0 else result.returncode
    if exit_code != 0:
        print(
            f"Error: pnpm command failed with exit status {exit_code}.",
            file=sys.stderr,
        )
    return exit_code


def main(argv: Sequence[str] | None = None) -> int:
    return run_pnpm(sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    sys.exit(main())
