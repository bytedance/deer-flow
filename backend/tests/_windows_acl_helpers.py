"""Shared Windows ACL inspection helpers for lark-cli credential tests.

These resolvers shell out to Windows PowerShell ``Get-Acl`` and translate ACEs
to raw SIDs so tests can assert the owner-only DACL contract that the
credential-tree hardener establishes on NTFS (where POSIX modes are not
representable). They are Windows-only; callers gate them on ``os.name == "nt"``.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _windows_acl_env() -> dict[str, str]:
    """Return a PowerShell environment with a clean, ordered ``PSModulePath``.

    The Codex runtime prepends a bundled PowerShell module path that shadows the
    stock ``Microsoft.PowerShell.Security`` module, which makes ``Get-Acl`` fail
    to autoload under ``-NoProfile``. Use the stock Windows PowerShell module path
    so ACL inspection is reliable on any host.
    """
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    modules = f"{system_root}\\system32\\WindowsPowerShell\\v1.0\\Modules;{program_files}\\WindowsPowerShell\\Modules"
    return {**os.environ, "PSModulePath": modules}


def _windows_acl_sids(path: Path) -> set[str]:
    """Return the SIDs granted on *path* (Windows-only, PowerShell resolver).

    ``icacls`` displays localized account names rather than raw SIDs, so we
    translate each ACE IdentityReference back to a SID before asserting.
    """
    cmd = "(Get-Acl -LiteralPath '" + str(path) + "').Access | ForEach-Object { $_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value }"
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", cmd],
        capture_output=True,
        text=True,
        check=True,
        env=_windows_acl_env(),
    )
    return {line.strip() for line in out.stdout.splitlines() if line.strip()}


def _windows_acl_protected(path: Path) -> bool:
    """Return whether *path*'s DACL is protected from inheritance (Windows-only)."""
    cmd = "(Get-Acl -LiteralPath '" + str(path) + "').AreAccessRulesProtected"
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", cmd],
        capture_output=True,
        text=True,
        check=True,
        env=_windows_acl_env(),
    )
    return out.stdout.strip() == "True"


def _windows_acl_owner_sid(path: Path) -> str:
    """Return *path*'s object owner as a raw SID (Windows-only)."""
    cmd = "$acl = Get-Acl -LiteralPath $env:DEER_FLOW_TEST_ACL_PATH; $acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value"
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", cmd],
        capture_output=True,
        text=True,
        check=True,
        env={**_windows_acl_env(), "DEER_FLOW_TEST_ACL_PATH": str(path)},
    )
    return out.stdout.strip()
