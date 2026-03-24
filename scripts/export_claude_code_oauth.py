#!/usr/bin/env python3
"""Export Claude Code OAuth credentials from macOS Keychain on purpose.

This helper is intentionally manual. DeerFlow runtime does not probe Keychain.
Use this script when you want to bridge an existing Claude Code login into an
environment variable or an exported credentials file for DeerFlow.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shlex
import subprocess
import sys
import tempfile
from hashlib import sha256
from pathlib import Path
from typing import Any


def claude_code_oauth_file_suffix() -> str:
    if os.getenv("CLAUDE_CODE_CUSTOM_OAUTH_URL"):
        return "-custom-oauth"
    if os.getenv("USE_LOCAL_OAUTH") or os.getenv("LOCAL_BRIDGE"):
        return "-local-oauth"
    if os.getenv("USE_STAGING_OAUTH"):
        return "-staging-oauth"
    return ""


def default_service_name() -> str:
    service = f"Claude Code{claude_code_oauth_file_suffix()}-credentials"
    config_dir = os.getenv("CLAUDE_CONFIG_DIR")
    if config_dir:
        config_hash = sha256(str(Path(config_dir).expanduser()).encode()).hexdigest()[:8]
        service = f"{service}-{config_hash}"
    return service


def default_account_name() -> str:
    return os.getenv("USER") or "claude-code-user"


def load_keychain_container(service: str, account: str) -> dict[str, Any]:
    if platform.system() != "Darwin":
        raise RuntimeError("Claude Code Keychain export is only supported on macOS.")

    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-a", account, "-w", "-s", service],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise RuntimeError(f"Failed to invoke macOS security tool: {exc}") from exc

    if result.returncode != 0:
        stderr = (result.stderr or "").strip() or "unknown Keychain error"
        raise RuntimeError(f"Keychain lookup failed for service={service!r} account={account!r}: {stderr}")

    secret = (result.stdout or "").strip()
    if not secret:
        raise RuntimeError("Keychain item was empty.")

    try:
        data = json.loads(secret)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Claude Code Keychain item did not contain valid JSON.") from exc

    access_token = data.get("claudeAiOauth", {}).get("accessToken", "")
    if not access_token:
        raise RuntimeError("Claude Code Keychain item did not contain claudeAiOauth.accessToken.")

    return data


def write_credentials_file(output_path: Path, data: dict[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f"{output_path.name}.", suffix=".tmp", dir=output_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(data, indent=2) + "\n")
        Path(tmp_name).replace(output_path)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Manually export Claude Code OAuth credentials from macOS Keychain for DeerFlow.",
    )
    parser.add_argument(
        "--service",
        default=default_service_name(),
        help="Override the Keychain service name. Defaults to Claude Code's computed service name.",
    )
    parser.add_argument(
        "--account",
        default=default_account_name(),
        help="Override the Keychain account name. Defaults to the current user.",
    )
    parser.add_argument(
        "--show-target",
        action="store_true",
        help="Print the resolved Keychain service/account without reading Keychain.",
    )
    parser.add_argument(
        "--print-token",
        action="store_true",
        help="Print only the OAuth access token to stdout.",
    )
    parser.add_argument(
        "--print-export",
        action="store_true",
        help="Print a shell export command for CLAUDE_CODE_OAUTH_TOKEN.",
    )
    parser.add_argument(
        "--write-credentials",
        type=Path,
        help="Write the full Claude credentials container to this file with 0600 permissions.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.show_target:
        print(f"service={args.service}")
        print(f"account={args.account}")

    if not any([args.print_token, args.print_export, args.write_credentials]):
        if not args.show_target:
            print("No export action selected. Use --show-target, --print-export, --print-token, or --write-credentials.", file=sys.stderr)
            return 2
        return 0

    try:
        data = load_keychain_container(service=args.service, account=args.account)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    access_token = data["claudeAiOauth"]["accessToken"]

    if args.print_token:
        print(access_token)

    if args.print_export:
        print(f"export CLAUDE_CODE_OAUTH_TOKEN={shlex.quote(access_token)}")

    if args.write_credentials:
        output_path = args.write_credentials.expanduser()
        write_credentials_file(output_path, data)
        print(f"Wrote Claude Code credentials to {output_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
