"""Write initial admin credentials to a restricted file instead of logs.

Logging secrets to stdout/stderr is a well-known CodeQL finding
(py/clear-text-logging-sensitive-data) — in production those logs
get collected into ELK/Splunk/etc and become a secret sprawl
source. This helper writes the credential to a 0600 file that only
the process user can read, and returns the path so the caller can
log **the path** (not the password) for the operator to pick up.
"""

from __future__ import annotations

import os
from pathlib import Path

from deerflow.config.paths import get_paths

_CREDENTIAL_FILENAME = "admin_initial_credentials.txt"


def write_initial_credentials(email: str, password: str, *, label: str = "initial") -> Path:
    """Write the admin email + password to ``{base_dir}/admin_initial_credentials.txt``.

    The file is created **atomically** with mode 0600 via ``os.open``
    so the password is never world-readable, even for the single syscall
    window between ``write_text`` and ``chmod``.

    ``label`` distinguishes "initial" (fresh creation) from "reset"
    (password reset) in the file header so an operator picking up the
    file after a restart can tell which event produced it.

    Returns the absolute :class:`Path` to the file.
    """
    target = get_paths().base_dir / _CREDENTIAL_FILENAME
    target.parent.mkdir(parents=True, exist_ok=True)

    content = (
        f"# DeerFlow admin {label} credentials\n# This file is generated on first boot or password reset.\n# Change the password after login via Settings -> Account,\n# then delete this file.\n#\nemail: {email}\npassword: {password}\n"
    )

    # Atomic 0600 create-or-truncate. O_TRUNC (not O_EXCL) so the
    # reset-password path can rewrite an existing file without a
    # separate unlink-then-create dance.
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(content)

    return target.resolve()
