#!/usr/bin/env python3
"""Cross-platform dependency checker for DeerFlow."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

PNPM_SCRIPT_PATH = Path(__file__).resolve().with_name("pnpm.py")
FRONTEND_DIR = PNPM_SCRIPT_PATH.parent.parent / "frontend"
COREPACK_NOTICE = "Using pnpm via Corepack."


def configure_stdio() -> None:
    """Prefer UTF-8 output so Unicode status markers render on Windows."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                continue


def run_command(command: list[str]) -> str | None:
    """Run a command and return trimmed stdout, or None on failure."""
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, check=True, shell=False
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or result.stderr.strip()


def run_pnpm_version() -> tuple[str | None, bool, str | None]:
    """Return the pnpm version, resolution source, and failure message."""
    try:
        result = subprocess.run(
            [sys.executable, str(PNPM_SCRIPT_PATH), "-v"],
            capture_output=True,
            text=True,
            check=False,
            shell=False,
            cwd=FRONTEND_DIR,
        )
    except OSError as exc:
        return None, False, f"Unable to launch the pnpm runner: {exc}"

    stdout = result.stdout.strip()
    stderr_lines = result.stderr.splitlines()
    via_corepack = COREPACK_NOTICE in stderr_lines
    stderr = "\n".join(line for line in stderr_lines if line != COREPACK_NOTICE).strip()
    if result.returncode == 0 and (stdout or stderr):
        return stdout or stderr, via_corepack, None

    diagnostics = "\n".join(part for part in (stderr, stdout) if part)
    if diagnostics:
        return None, via_corepack, diagnostics
    return (
        None,
        via_corepack,
        f"The pnpm runner exited with status {result.returncode} without output.",
    )


def parse_node_major(version_text: str) -> int | None:
    version = version_text.strip()
    if version.startswith("v"):
        version = version[1:]
    major_str = version.split(".", 1)[0]
    if not major_str.isdigit():
        return None
    return int(major_str)


def main() -> int:
    configure_stdio()
    print("==========================================")
    print("  Checking Required Dependencies")
    print("==========================================")
    print()

    failed = False

    print("Checking Node.js...")
    node_path = shutil.which("node")
    if node_path:
        node_version = run_command(["node", "-v"])
        if node_version:
            major = parse_node_major(node_version)
            if major is not None and major >= 22:
                print(f"  OK Node.js {node_version.lstrip('v')} (>= 22 required)")
            else:
                print(
                    f"  FAIL Node.js {node_version.lstrip('v')} found, but version 22+ is required"
                )
                print("    Install from: https://nodejs.org/")
                failed = True
        else:
            print("  INFO Unable to determine Node.js version")
            print("    Install from: https://nodejs.org/")
            failed = True
    else:
        print("  FAIL Node.js not found (version 22+ required)")
        print("    Install from: https://nodejs.org/")
        failed = True

    print()
    print("Checking pnpm...")
    pnpm_version, pnpm_via_corepack, pnpm_error = run_pnpm_version()
    if pnpm_version:
        resolution_hint = " (via Corepack)" if pnpm_via_corepack else ""
        print(f"  OK pnpm {pnpm_version}{resolution_hint}")
    else:
        print("  FAIL pnpm is unavailable or failed to run")
        if pnpm_error:
            for line in pnpm_error.splitlines():
                print(f"    {line}")
        failed = True

    print()
    print("Checking uv...")
    if shutil.which("uv"):
        uv_version_text = run_command(["uv", "--version"])
        if uv_version_text:
            uv_version_parts = uv_version_text.split()
            uv_version = (
                uv_version_parts[1] if len(uv_version_parts) > 1 else uv_version_text
            )
            print(f"  OK uv {uv_version}")
        else:
            print("  INFO Unable to determine uv version")
            failed = True
    else:
        print("  FAIL uv not found")
        print("    Visit the official installation guide for your platform:")
        print("    https://docs.astral.sh/uv/getting-started/installation/")
        failed = True

    print()
    print("Checking nginx...")
    if shutil.which("nginx"):
        nginx_version_text = run_command(["nginx", "-v"])
        if nginx_version_text and "/" in nginx_version_text:
            nginx_version = nginx_version_text.split("/", 1)[1]
            print(f"  OK nginx {nginx_version}")
        else:
            print("  INFO nginx (version unknown)")
    else:
        print("  FAIL nginx not found")
        print("    macOS:   brew install nginx")
        print("    Ubuntu:  sudo apt install nginx")
        print("    Windows: use WSL for local mode or use Docker mode")
        print("    Or visit: https://nginx.org/en/download.html")
        failed = True

    print()
    if not failed:
        print("==========================================")
        print("  OK All dependencies are installed!")
        print("==========================================")
        print()
        print("You can now run:")
        print("  make install  - Install project dependencies")
        print("  make setup    - Create a minimal working config (recommended)")
        print("  make config   - Copy the full config template (manual setup)")
        print("  make doctor   - Verify config and dependency health")
        print("  make dev      - Start development server")
        print("  make start    - Start production server")
        return 0

    print("==========================================")
    print("  FAIL Some dependencies are missing")
    print("==========================================")
    print()
    print("Please install the missing tools and run 'make check' again.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
